"""Vendor dashboard and support/notification views."""

from ..common import *

@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def support_chat(request):
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
        .select_related('sender')
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
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    conversation = _get_or_create_support_conversation(request.user)
    support_messages = SupportMessage.objects.filter(
        conversation=conversation,
    ).select_related('sender').order_by('created_at')

    return JsonResponse({
        'conversation_id': conversation.id,
        'status': conversation.status,
        'messages': [_serialize_support_message(message) for message in support_messages],
    })


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def support_widget_send(request):
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
@login_required(login_url='vendor_login')

def vendor_dashboard(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)
    completed_vendor_bookings = vendor_bookings.filter(
        payment_status=Booking.PAYMENT_STATUS_COMPLETED,
    )
    active_subscription = _get_active_subscription(request.user)
    VendorFeature.expire_overdue(vendor=request.user)
    active_feature_purchases = VendorFeature.active_for_vendor(request.user).select_related('slot')
    featured_count = vendor_packages.filter(is_featured=True).count()
    featured_limit = _total_active_feature_slots_for_vendor(request.user)
    featured_remaining = max(featured_limit - featured_count, 0)
    active_feature_slots = FeatureSlot.objects.filter(is_active=True).order_by('-created_at')
    subscription_plans = VendorSubscriptionPlan.objects.filter(is_active=True).order_by('price', 'duration_days')

    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    active_packages = vendor_packages.filter(is_active=True).count()
    total_bookings = vendor_bookings.count()
    pending_bookings = vendor_bookings.filter(status='pending').count()
    average_rating = Review.objects.filter(package__vendor=request.user).aggregate(
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
        month_total = completed_vendor_bookings.filter(
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        vendor_share = (Decimal(month_total) * Booking.COMMISSION_VENDOR_RATE).quantize(Decimal('0.01'))
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
        'active_subscription': active_subscription,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
        'featured_remaining': featured_remaining,
        'active_feature_slots': active_feature_slots,
        'active_feature_purchases': active_feature_purchases,
        'subscription_plans': subscription_plans,
        'earnings_chart': earnings_chart,
        'bookings_chart': bookings_chart,
        'packages_chart': packages_chart,
        'category_chart': category_chart,
        'chart_insights': chart_insights,
        'upcoming_bookings': upcoming_bookings,
        'package_performance': package_performance,
    })


@never_cache
@login_required(login_url='vendor_login')

def vendor_analytics(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)
    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0

    analytics = {
        'packages': vendor_packages.count(),
        'bookings': vendor_bookings.count(),
        'revenue': float(total_revenue),
        'reviews': Review.objects.filter(package__vendor=request.user).count(),
        'avg_rating': Review.objects.filter(package__vendor=request.user).aggregate(
            avg=Avg('rating')
        )['avg'] or 0,
    }

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

    monthly_revenue = []
    max_monthly_revenue = 0
    for start, end, label in month_periods:
        value = vendor_bookings.filter(
            status='confirmed',
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('vendor_amount'))['total'] or 0
        value = float(value)
        max_monthly_revenue = max(max_monthly_revenue, value)
        monthly_revenue.append({
            'label': label,
            'value': value,
        })

    for entry in monthly_revenue:
        if max_monthly_revenue <= 0:
            entry['percent'] = 0
        else:
            entry['percent'] = int((entry['value'] / max_monthly_revenue) * 100)

    line_values = [entry['value'] for entry in monthly_revenue]
    chart_width = 420
    chart_height = 170
    chart_padding_x = 12
    chart_padding_y = 22
    chart_step = (chart_width - chart_padding_x * 2) / max(len(line_values) - 1, 1)
    max_line_value = max(line_values) if line_values else 0
    min_line_value = min(line_values) if line_values else 0
    monthly_line_points = []
    for idx, value in enumerate(line_values):
        x = chart_padding_x + idx * chart_step
        if max_line_value == min_line_value:
            y = chart_height / 2
        else:
            ratio = (value - min_line_value) / (max_line_value - min_line_value)
            y = chart_height - chart_padding_y - ratio * (chart_height - chart_padding_y * 2)
        monthly_line_points.append(f"{x:.0f},{y:.0f}")

    payment_method_counts = {}
    for method_key, _label in Booking.PAYMENT_METHOD_CHOICES:
        payment_method_counts[method_key] = 0
    for row in vendor_bookings.values('payment_method').annotate(count=Count('id')):
        payment_method_counts[row['payment_method']] = row['count']

    method_labels = dict(Booking.PAYMENT_METHOD_CHOICES)
    method_colors = {
        Booking.PAYMENT_METHOD_ESEWA: '#0f766e',
        Booking.PAYMENT_METHOD_STRIPE: '#2563eb',
        Booking.PAYMENT_METHOD_KHALTI: '#7c3aed',
    }
    method_order = [
        Booking.PAYMENT_METHOD_ESEWA,
        Booking.PAYMENT_METHOD_STRIPE,
        Booking.PAYMENT_METHOD_KHALTI,
    ]

    total_method_count = sum(payment_method_counts.values())
    payment_method_breakdown = []
    method_segments = []
    current_percent = 0
    for method in method_order:
        count = payment_method_counts.get(method, 0)
        percent = (count / total_method_count * 100) if total_method_count else 0
        payment_method_breakdown.append({
            'key': method,
            'label': method_labels.get(method, method.title()),
            'count': count,
            'percent': round(percent),
            'color': method_colors[method],
        })
        if percent > 0:
            next_percent = current_percent + percent
            method_segments.append(
                f"{method_colors[method]} {current_percent:.1f}% {next_percent:.1f}%"
            )
            current_percent = next_percent

    if not method_segments:
        payment_method_gradient = "conic-gradient(#e5e7eb 0 100%)"
    else:
        if current_percent < 100:
            method_segments.append(f"#e5e7eb {current_percent:.1f}% 100%")
        payment_method_gradient = f"conic-gradient({', '.join(method_segments)})"

    return render(request, 'accounts/vendor_analytics.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'analytics',
        'analytics': analytics,
        'monthly_revenue': monthly_revenue,
        'monthly_line_points': " ".join(monthly_line_points),
        'payment_method_breakdown': payment_method_breakdown,
        'payment_method_gradient': payment_method_gradient,
    })


@never_cache
@login_required(login_url='vendor_login')

def vendor_settings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    active_subscription = _get_active_subscription(request.user)
    subscription_plans = VendorSubscriptionPlan.objects.filter(is_active=True).order_by('price', 'duration_days')
    VendorFeature.expire_overdue(vendor=request.user)
    active_feature_slots = FeatureSlot.objects.filter(is_active=True).order_by('-created_at')
    active_feature_purchases = VendorFeature.active_for_vendor(request.user).select_related('slot').order_by('-created_at')
    used_slots = _total_featured_packages_for_vendor(request.user)
    purchased_slots = _total_active_feature_slots_for_vendor(request.user)
    return render(request, 'accounts/vendor_settings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'settings',
        'active_subscription': active_subscription,
        'subscription_plans': subscription_plans,
        'active_feature_slots': active_feature_slots,
        'active_feature_purchases': active_feature_purchases,
        'feature_slots_purchased': purchased_slots,
        'feature_slots_used': used_slots,
        'feature_slots_remaining': max(purchased_slots - used_slots, 0),
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect

def vendor_transactions(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    transactions = Transaction.objects.filter(vendor=request.user).select_related(
        'booking',
        'booking__package',
        'traveler',
    )
    transactions, filters = _apply_transaction_filters(transactions, request)
    transactions = transactions.order_by('-created_at')

    if request.GET.get('export') == 'csv':
        return _transaction_csv_response(transactions, 'vendor-transactions.csv')

    return render(request, 'accounts/vendor_transactions.html', {
        'vendor_profile': vendor_profile,
        'transactions': transactions,
        'filters': filters,
        'active_page': 'transactions',
    })

