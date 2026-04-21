"""Vendor dashboard and support/notification views.

Owns the vendor analytics dashboard, the vendor settings page, the
vendor transactions list, and the shared traveler+vendor support chat
and notifications endpoints (both full-page and AJAX widget variants).
"""

# NOTE: file > 300 lines — split deferred. Support, notifications and
# vendor dashboard share the same `from ..common import (...)` bundle
# and are tightly coupled to vendor session/role checks; splitting
# would duplicate the import bundle in 3 separate files.

from ..common import (
    Avg,
    Booking,
    Count,
    Decimal,
    JsonResponse,
    Notification,
    Package,
    Q,
    Review,
    Sum,
    SupportConversation,
    SupportMessage,
    Transaction,
    TravelerProfile,
    _apply_transaction_filters,
    _get_admin_profile,
    _get_or_create_support_conversation,
    _get_traveler_profile,
    _get_vendor_profile,
    _serialize_support_message,
    _transaction_csv_response,
    csrf_protect,
    csv,
    date,
    login_required,
    messages,
    monthrange,
    never_cache,
    notification_link,
    notify_admins,
    redirect,
    render,
    reverse,
    serialize_notification,
    settings,
    timedelta,
    timezone,
    vendor_required,
)
from core.services.subscription_service import (
    expire_overdue_subscriptions,
    get_active_subscription as get_active_sub,
    get_available_plans,
    get_featured_packages_for_vendor,
)

@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def support_chat(request):
    """Full-page support chat for travelers and vendors; posts a new message."""
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        messages.error(request, 'Traveler or Vendor access only.')
        return redirect('home')

    conversation = _get_or_create_support_conversation(request.user)

    if request.method == 'POST':
        message_text = (request.POST.get('message') or '').strip()
        if not message_text:
            messages.error(request, 'Please enter a message before sending.')
        elif conversation.status != SupportConversation.STATUS_OPEN:
            conversation = SupportConversation.objects.create(user=request.user)
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=False,
            )
            notify_admins(
                f'New support message from {request.user.email}',
                Notification.TYPE_SUPPORT_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('support_chat')
        else:
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=False,
            )
            notify_admins(
                f'New support message from {request.user.email}',
                Notification.TYPE_SUPPORT_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('support_chat')

    support_messages = (
        SupportMessage.objects.filter(conversation=conversation)
        .select_related('sender', 'sender__vendor_profile')
        .order_by('created_at')
    )
    base_template = (
        'accounts/vendor_base.html'
        if request.user.user_type == 'vendor'
        else 'accounts/traveler_base.html'
    )
    context = {
        'base_template': base_template,
        'conversation': conversation,
        'support_messages': support_messages,
        'active_page': 'support',
    }
    if request.user.user_type == 'vendor':
        context['vendor_profile'] = _get_vendor_profile(request.user)
    else:
        traveler_profile = _get_traveler_profile(request.user)
        if traveler_profile is None:
            traveler_profile = TravelerProfile.objects.create(user=request.user)
        context['traveler_profile'] = traveler_profile
    return render(request, 'accounts/support_chat.html', context)


@never_cache
@login_required(login_url='account_login_choice')

def support_widget_data(request):
    """JSON feed of the user's open support conversation for the floating widget."""
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    conversation = _get_or_create_support_conversation(request.user)
    support_messages = SupportMessage.objects.filter(
        conversation=conversation,
    ).select_related('sender', 'sender__vendor_profile').order_by('created_at')

    return JsonResponse({
        'conversation_id': conversation.id,
        'status': conversation.status,
        'messages': [_serialize_support_message(message) for message in support_messages],
    })


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def support_widget_send(request):
    """AJAX endpoint to post a new support message from the floating widget."""
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    message_text = (request.POST.get('message') or '').strip()
    if not message_text:
        return JsonResponse({'error': 'Message is required.'}, status=400)

    conversation = _get_or_create_support_conversation(request.user)
    if conversation.status != SupportConversation.STATUS_OPEN:
        conversation = SupportConversation.objects.create(user=request.user)

    new_message = SupportMessage.objects.create(
        conversation=conversation,
        sender=request.user,
        message=message_text,
        is_admin_reply=False,
    )
    notify_admins(
        f'New support message from {request.user.email}',
        Notification.TYPE_SUPPORT_MESSAGE,
        related_object_id=conversation.id,
    )

    return JsonResponse({
        'message': _serialize_support_message(new_message),
    })


@never_cache
@login_required(login_url='account_login_choice')

def notifications_data(request):
    """JSON feed of the 20 most recent notifications for the bell-icon dropdown."""
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:20]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({
        'unread_count': unread_count,
        'notifications': [serialize_notification(notification) for notification in notifications],
    })


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def notifications_mark_read(request):
    """Mark a single notification (or all notifications) as read."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    notification_id = (request.POST.get('notification_id') or '').strip().lower()
    queryset = Notification.objects.filter(user=request.user)
    if notification_id in {'all', '*'} or request.POST.get('mark_all') == '1':
        queryset.update(is_read=True)
    else:
        try:
            target_id = int(notification_id)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid notification id'}, status=400)
        queryset.filter(id=target_id).update(is_read=True)

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    if not is_ajax:
        return redirect('notifications_list')
    return JsonResponse({'unread_count': unread_count})


@never_cache
@login_required(login_url='account_login_choice')

def notifications_list(request):
    """Full-page list of the user's 50 most recent notifications, role-aware template."""
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    for notification in notifications:
        notification.link = notification_link(notification)

    if getattr(request.user, 'user_type', '') == 'admin':
        admin_profile = _get_admin_profile(request.user)
        return render(request, 'accounts/admin_notifications.html', {
            'admin_profile': admin_profile,
            'notifications': notifications,
            'unread_count': unread_count,
            'active_page': 'notifications',
        })

    base_template = (
        'accounts/vendor_base.html'
        if request.user.user_type == 'vendor'
        else 'accounts/traveler_base.html'
    )
    context = {
        'base_template': base_template,
        'notifications': notifications,
        'unread_count': unread_count,
        'active_page': 'notifications',
    }
    if request.user.user_type == 'vendor':
        context['vendor_profile'] = _get_vendor_profile(request.user)
    else:
        traveler_profile = _get_traveler_profile(request.user)
        if traveler_profile is None:
            traveler_profile = TravelerProfile.objects.create(user=request.user)
        context['traveler_profile'] = traveler_profile
    return render(request, 'accounts/notifications.html', context)


@never_cache
@vendor_required(login_url='vendor_login')

def vendor_dashboard(request):
    """Main vendor dashboard: KPIs, revenue, monthly trends, recent bookings, featured slots."""
    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(
        package__vendor=request.user,
        traveler__isnull=False,
    )
    completed_vendor_bookings = vendor_bookings.filter(
        payment_status=Booking.PAYMENT_STATUS_COMPLETED,
    )
    subscription = get_active_sub(request.user)
    featured_entries = get_featured_packages_for_vendor(request.user)
    featured_count = featured_entries.count()
    featured_limit = subscription.slots_total if subscription else 0
    featured_remaining = max(featured_limit - featured_count, 0)
    feature_plans = get_available_plans()

    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    active_packages = vendor_packages.filter(is_active=True).count()
    total_bookings = vendor_bookings.count()
    pending_bookings = vendor_bookings.filter(status='pending').count()
    average_rating = Review.objects.filter(
        package__vendor=request.user,
        traveler__isnull=False,
    ).aggregate(
        avg=Avg('rating')
    )['avg'] or 0

    today = timezone.localdate()

    month_cursor = today.replace(day=1)
    month_periods = []
    for _ in range(6):
        last_day = monthrange(month_cursor.year, month_cursor.month)[1]
        start = month_cursor
        end = date(month_cursor.year, month_cursor.month, last_day)
        month_periods.append((start, end, start.strftime('%b')))
        if month_cursor.month == 1:
            month_cursor = date(month_cursor.year - 1, 12, 1)
        else:
            month_cursor = date(month_cursor.year, month_cursor.month - 1, 1)
    month_periods.reverse()

    monthly_earnings = []
    monthly_bookings = []
    for start, end, label in month_periods:
        vendor_share = completed_vendor_bookings.filter(
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('vendor_amount'))['total'] or Decimal('0')
        booking_count = completed_vendor_bookings.filter(created_at__date__range=(start, end)).count()
        monthly_earnings.append({
            'label': label,
            'value': float(vendor_share),
        })
        monthly_bookings.append({
            'label': label,
            'value': booking_count,
        })

    package_performance_chart = list(
        vendor_packages.annotate(
            completed_booking_count=Count(
                'bookings',
                filter=Q(bookings__payment_status=Booking.PAYMENT_STATUS_COMPLETED),
            ),
        )
        .order_by('-completed_booking_count', '-views_count')[:5]
    )

    vendor_trek_count = vendor_packages.filter(category=Package.CATEGORY_TREK).count()
    vendor_tour_count = vendor_packages.filter(category=Package.CATEGORY_TOUR).count()
    vendor_other_count = vendor_packages.exclude(
        category__in=[Package.CATEGORY_TREK, Package.CATEGORY_TOUR],
    ).count()

    earnings_chart = {
        'labels': [entry['label'] for entry in monthly_earnings],
        'values': [round(entry['value'], 2) for entry in monthly_earnings],
    }
    bookings_chart = {
        'labels': [entry['label'] for entry in monthly_bookings],
        'values': [entry['value'] for entry in monthly_bookings],
    }
    packages_chart = {
        'labels': [package.title for package in package_performance_chart],
        'values': [package.completed_booking_count for package in package_performance_chart],
    }
    category_chart = {
        'labels': ['Treks', 'Tours', 'Others'],
        'values': [vendor_trek_count, vendor_tour_count, vendor_other_count],
        'colors': ['#1d4ed8', '#1e3a8a', '#60a5fa'],
    }

    def _growth_text(values):
        if len(values) < 2 or values[-2] == 0:
            return 'No baseline from last month'
        change = ((values[-1] - values[-2]) / values[-2]) * 100
        sign = '+' if change >= 0 else ''
        return f'{sign}{change:.0f}% from last month'

    chart_insights = {
        'earnings': _growth_text(earnings_chart['values']),
        'bookings': _growth_text(bookings_chart['values']),
        'packages': _growth_text(packages_chart['values']),
        'categories': 'Distribution based on your packages',
    }

    upcoming_bookings = vendor_bookings.filter(
        travel_date__gte=today,
        travel_date__lte=today + timedelta(days=14),
    ).exclude(status='cancelled').order_by('travel_date')[:3]

    package_performance = vendor_packages.annotate(
        booking_count=Count('bookings'),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-booking_count', '-views_count')[:3]

    return render(request, 'accounts/vendor_dashboard.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'dashboard',
        'stats': {
            'total_revenue': float(total_revenue),
            'active_packages': active_packages,
            'total_bookings': total_bookings,
            'pending_bookings': pending_bookings,
            'average_rating': round(average_rating or 0, 1),
        },
        'active_subscription': subscription,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
        'featured_remaining': featured_remaining,
        'feature_plans': feature_plans,
        'earnings_chart': earnings_chart,
        'bookings_chart': bookings_chart,
        'packages_chart': packages_chart,
        'category_chart': category_chart,
        'chart_insights': chart_insights,
        'upcoming_bookings': upcoming_bookings,
        'package_performance': package_performance,
    })


@never_cache
@vendor_required(login_url='vendor_login')

def vendor_settings(request):
    """Vendor settings page: subscription, feature plans, and featured-package slot UI."""
    vendor_profile = _get_vendor_profile(request.user)
    subscription = get_active_sub(request.user)
    feature_plans = get_available_plans()
    featured_entries = get_featured_packages_for_vendor(request.user)
    featured_count = featured_entries.count()
    slots_total = subscription.slots_total if subscription else 0

    # Get vendor's packages for the "assign to slot" UI
    vendor_packages = Package.objects.filter(
        vendor=request.user, is_active=True,
    ).order_by('-created_at')
    featured_package_ids = set(featured_entries.values_list('package_id', flat=True))

    return render(request, 'accounts/vendor_settings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'settings',
        'active_subscription': subscription,
        'feature_plans': feature_plans,
        'featured_entries': featured_entries,
        'featured_count': featured_count,
        'slots_total': slots_total,
        'slots_remaining': max(slots_total - featured_count, 0),
        'vendor_packages': vendor_packages,
        'featured_package_ids': featured_package_ids,
    })


@never_cache
@vendor_required(login_url='vendor_login')
@csrf_protect

def vendor_transactions(request):
    """List the vendor's payment transactions with filters and CSV export."""
    vendor_profile = _get_vendor_profile(request.user)
    transactions = Transaction.objects.filter(vendor=request.user).select_related(
        'booking',
        'booking__package',
        'traveler',
    )
    transactions, filters = _apply_transaction_filters(transactions, request, allow_status=False)
    transactions = transactions.order_by('-created_at')

    if request.GET.get('export') == 'csv' and not filters.get('date_error'):
        return _transaction_csv_response(transactions, 'vendor-transactions.csv')

    return render(request, 'accounts/vendor_transactions.html', {
        'vendor_profile': vendor_profile,
        'transactions': transactions,
        'filters': filters,
        'active_page': 'transactions',
    })

