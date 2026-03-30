"""Admin views and analytics endpoints."""

from .common import *

@admin_required
def admin_support_inbox(request):
    admin_profile = _get_admin_profile(request.user)
    last_message_qs = SupportMessage.objects.filter(
        conversation=OuterRef('pk'),
    ).order_by('-created_at', '-id')
    conversations = SupportConversation.objects.select_related('user').annotate(
        last_message_text=Subquery(
            last_message_qs.values('message')[:1],
            output_field=TextField(),
        ),
        last_message_at=Subquery(
            last_message_qs.values('created_at')[:1],
            output_field=DateTimeField(),
        ),
        last_message_is_admin=Subquery(
            last_message_qs.values('is_admin_reply')[:1],
            output_field=BooleanField(),
        ),
    ).order_by('-last_message_at', '-created_at')

    role_labels = dict(User.USER_TYPE_CHOICES)
    unread_count = 0
    for conversation in conversations:
        user = conversation.user
        conversation.user_display = user.get_full_name().strip() or user.username or user.email
        conversation.user_role = role_labels.get(user.user_type, user.user_type.title())
        conversation.last_message_text = conversation.last_message_text or ''
        conversation.unread_by_admin = conversation.last_message_is_admin is False
        if conversation.unread_by_admin:
            unread_count += 1

    return render(request, 'accounts/admin_support_inbox.html', {
        'admin_profile': admin_profile,
        'conversations': conversations,
        'active_page': 'support',
        'support_inbox_unread_count': unread_count,
    })


@admin_required
@csrf_protect
def admin_support_chat(request, conversation_id):
    admin_profile = _get_admin_profile(request.user)
    conversation = get_object_or_404(
        SupportConversation.objects.select_related('user'),
        id=conversation_id,
    )
    if request.method == 'POST':
        action = (request.POST.get('action') or '').lower()
        if action == 'close':
            if conversation.status != SupportConversation.STATUS_CLOSED:
                conversation.status = SupportConversation.STATUS_CLOSED
                conversation.save(update_fields=['status'])
                messages.success(request, 'Conversation closed.')
            return redirect('admin_support_chat', conversation_id=conversation.id)

        message_text = (request.POST.get('message') or '').strip()
        if not message_text:
            messages.error(request, 'Please enter a message before sending.')
        elif conversation.status != SupportConversation.STATUS_OPEN:
            messages.error(request, 'This support conversation is closed.')
        else:
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=True,
            )
            create_notification(
                conversation.user,
                'Admin replied to your support message.',
                Notification.TYPE_ADMIN_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('admin_support_chat', conversation_id=conversation.id)

    role_labels = dict(User.USER_TYPE_CHOICES)
    user = conversation.user
    conversation.user_display = user.get_full_name().strip() or user.username or user.email
    conversation.user_role = role_labels.get(user.user_type, user.user_type.title())
    support_messages = (
        SupportMessage.objects.filter(conversation=conversation)
        .select_related('sender', 'related_booking')
        .order_by('created_at')
    )

    return render(request, 'accounts/admin_support_chat.html', {
        'admin_profile': admin_profile,
        'conversation': conversation,
        'support_messages': support_messages,
        'active_page': 'support',
    })


@never_cache
@admin_required
def admin_dashboard(request):
    VendorSubscription.expire_overdue()
    VendorFeature.expire_overdue()
    admin_profile = _get_admin_profile(request.user)
    vendors = User.objects.filter(user_type='vendor').select_related('vendor_profile').annotate(
        package_count=Count('vendor_packages', distinct=True),
    ).order_by('-date_joined')
    pending_vendors = vendors.filter(
        vendor_profile__is_approved=False,
        is_active=True,
    )
    travelers = User.objects.filter(user_type='traveler').order_by('-date_joined')
    packages = Package.objects.select_related('vendor').order_by('-created_at')
    bookings = Booking.objects.select_related(
        'package',
        'traveler',
        'vendor',
        'package__vendor',
    ).order_by('-created_at')
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')
    subscription_plans = VendorSubscriptionPlan.objects.order_by('price', 'duration_days')
    vendor_subscriptions = VendorSubscription.objects.select_related('vendor').order_by('-created_at')
    feature_slots = FeatureSlot.objects.order_by('-created_at')
    vendor_features = VendorFeature.objects.select_related('vendor', 'slot', 'package').order_by('-created_at')
    subscription_revenue = vendor_subscriptions.aggregate(total=Sum('price'))['total'] or 0
    featured_packages = Package.objects.filter(is_featured=True).select_related('vendor').order_by('-created_at')

    platform_earnings = bookings.filter(status='confirmed').aggregate(
        total=Sum('platform_fee')
    )['total'] or 0
    vendor_earnings = bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    total_bookings = bookings.count()
    active_vendors = vendors.filter(is_active=True, vendor_profile__is_approved=True).count()
    total_users = vendors.count() + travelers.count()
    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    activity_items = []
    for booking in bookings[:3]:
        actor = booking.traveler.get_full_name() if booking.traveler else 'Traveler'
        activity_items.append({
            'action': 'New Booking',
            'actor': actor or 'Traveler',
            'date': booking.created_at,
            'details': booking.package.title,
        })
    for vendor in vendors[:2]:
        vendor_profile = _get_vendor_profile(vendor)
        activity_items.append({
            'action': 'Vendor Registration',
            'actor': vendor_profile.business_name if vendor_profile else vendor.email,
            'date': vendor.date_joined,
            'details': 'Pending approval' if vendor_profile and not vendor_profile.is_approved else 'Approved',
        })
    for package in packages[:2]:
        activity_items.append({
            'action': 'Package Created',
            'actor': package.vendor.get_full_name() or package.vendor.email,
            'date': package.created_at,
            'details': package.title,
        })
    for review in reviews[:2]:
        activity_items.append({
            'action': 'Review Posted',
            'actor': review.traveler.get_full_name() if review.traveler else 'Traveler',
            'date': review.created_at,
            'details': f'{review.rating}-star rating',
        })
    activity_items.sort(key=lambda item: item['date'], reverse=True)
    activity_items = activity_items[:6]

    stats = {
        'total_vendors': vendors.count(),
        'pending_vendors': pending_vendors.count(),
        'total_travelers': travelers.count(),
        'total_packages': packages.count(),
        'active_packages': packages.filter(is_active=True).count(),
        'total_users': total_users,
        'active_vendors': active_vendors,
        'total_bookings': total_bookings,
        'platform_earnings': float(platform_earnings),
        'vendor_earnings': float(vendor_earnings),
        'subscription_revenue': float(subscription_revenue),
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating or 0, 1),
        'forum_posts': 0,
        'feature_slot_capacity': _total_homepage_feature_capacity(),
        'feature_slot_used': _total_homepage_featured_count(),
    }
    current_year = timezone.localdate().year
    analytics_years = [current_year - 2, current_year - 1, current_year]

    return render(request, 'accounts/admin_dashboard.html', {
        'admin_profile': admin_profile,
        'vendors': vendors,
        'pending_vendors': pending_vendors,
        'travelers': travelers,
        'packages': packages,
        'bookings': bookings,
        'subscription_plans': subscription_plans,
        'vendor_subscriptions': vendor_subscriptions,
        'feature_slots': feature_slots,
        'vendor_features': vendor_features,
        'featured_packages': featured_packages,
        'stats': stats,
        'activity_items': activity_items,
        'analytics_years': analytics_years,
        'selected_analytics_year': current_year,
        'active_page': 'dashboard',
    })


@admin_required
def admin_analytics_api(request):
    year_options = _admin_analytics_year_options()
    selected_year = _parse_admin_analytics_year(
        request.GET.get('year'),
        year_options,
    )

    bookings_for_year = Booking.objects.filter(created_at__year=selected_year)
    confirmed_bookings_for_year = bookings_for_year.filter(status=Booking.STATUS_CONFIRMED)
    subscriptions_for_year = VendorSubscription.objects.filter(created_at__year=selected_year)
    users_for_year = User.objects.filter(date_joined__year=selected_year)
    active_vendors_for_year = User.objects.filter(
        user_type='vendor',
        is_active=True,
        vendor_profile__is_approved=True,
        date_joined__year=selected_year,
    )

    monthly_platform_revenue = _monthly_sum_for_bookings(
        bookings_for_year,
        selected_year,
        'platform_fee',
        confirmed_only=True,
    )
    monthly_vendor_earnings = _monthly_sum_for_bookings(
        bookings_for_year,
        selected_year,
        'vendor_amount',
        confirmed_only=True,
    )
    monthly_bookings = _monthly_count_for_queryset(
        bookings_for_year,
        selected_year,
        'created_at',
    )
    monthly_subscription_revenue = []
    for month in range(1, 13):
        start, end = _month_range_dates(selected_year, month)
        total = subscriptions_for_year.filter(
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('price'))['total'] or 0
        monthly_subscription_revenue.append(float(total))
    monthly_new_users = _monthly_count_for_queryset(
        users_for_year,
        selected_year,
        'date_joined',
    )
    monthly_new_active_vendors = _monthly_count_for_queryset(
        active_vendors_for_year,
        selected_year,
        'date_joined',
    )

    category_data = _package_category_breakdown_for_year(selected_year)
    top_vendors = _top_vendor_earnings_for_year(selected_year)

    summary = {
        'platform_earnings': float(
            confirmed_bookings_for_year.aggregate(total=Sum('platform_fee'))['total'] or 0
        ),
        'vendor_earnings': float(
            confirmed_bookings_for_year.aggregate(total=Sum('vendor_amount'))['total'] or 0
        ),
        'subscription_revenue': float(
            subscriptions_for_year.aggregate(total=Sum('price'))['total'] or 0
        ),
        'total_users': users_for_year.count(),
        'active_vendors': active_vendors_for_year.count(),
        'total_bookings': bookings_for_year.count(),
    }

    payload = {
        'year': selected_year,
        'years': year_options,
        'months': _month_labels(),
        'summary': summary,
        'revenue': {
            'values': monthly_platform_revenue,
            'growth': _monthly_growth(monthly_platform_revenue, selected_year),
        },
        'vendor_earnings': {
            'values': monthly_vendor_earnings,
            'growth': _monthly_growth(monthly_vendor_earnings, selected_year),
        },
        'bookings': {
            'values': monthly_bookings,
            'growth': _monthly_growth(monthly_bookings, selected_year),
        },
        'subscriptions': {
            'values': monthly_subscription_revenue,
            'growth': _monthly_growth(monthly_subscription_revenue, selected_year),
        },
        'users': {
            'values': monthly_new_users,
            'growth': _monthly_growth(monthly_new_users, selected_year),
        },
        'active_vendors': {
            'values': monthly_new_active_vendors,
            'growth': _monthly_growth(monthly_new_active_vendors, selected_year),
        },
        'top_vendors': top_vendors,
        'categories': category_data,
    }
    return JsonResponse(payload)


@admin_required
@csrf_protect
def admin_profile(request):
    profile = _get_admin_profile(request.user)
    if profile is None:
        profile = AdminProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('admin_profile')

        current_password = request.POST.get('current_password') or ''
        new_password = request.POST.get('new_password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('admin_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.save()

        profile.bio = bio
        uploading_new_avatar = bool(avatar)
        if remove_avatar:
            profile.avatar = None
        elif avatar:
            profile.avatar = avatar

        profile.save()
        if remove_avatar or uploading_new_avatar:
            current_avatar_name = profile.avatar.name if profile.avatar else ''
            if old_avatar_name and old_avatar_name != current_avatar_name:
                _delete_stored_file(profile, 'avatar', old_avatar_name)

        if current_password or new_password or confirm_password:
            if not request.user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('admin_profile')
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return redirect('admin_profile')
            if len(new_password) < 6:
                messages.error(request, 'New password must be at least 6 characters long.')
                return redirect('admin_profile')
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password updated successfully.')
        else:
            messages.success(request, 'Profile updated successfully.')

        return redirect('admin_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    pending_vendors = User.objects.filter(
        user_type='vendor',
        vendor_profile__is_approved=False,
        is_active=True,
    ).select_related('vendor_profile').order_by('-date_joined')

    return render(request, 'accounts/admin_profile.html', {
        'profile': profile,
        'full_name': full_name,
        'pending_vendors': pending_vendors,
        'active_page': 'profile',
    })


@admin_required
@csrf_protect
def admin_vendor_action(request, vendor_id):
    next_url = (request.POST.get('next') or '').strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('admin_dashboard')

    if request.method != 'POST':
        return redirect(next_url)

    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    action = request.POST.get('action')

    if profile is None:
        messages.error(request, 'Vendor profile not found.')
        return redirect(next_url)

    if action == 'approve':
        profile.is_approved = True
        vendor.is_active = True
        create_notification(
            vendor,
            'Your vendor account was approved by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} approved.')
    elif action == 'reject':
        profile.is_approved = False
        vendor.is_active = False
        create_notification(
            vendor,
            'Your vendor account was rejected by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} rejected.')
    elif action == 'suspend':
        vendor.is_active = False
        create_notification(
            vendor,
            'Your vendor account was suspended by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} suspended.')
    elif action == 'activate':
        vendor.is_active = True
        create_notification(
            vendor,
            'Your vendor account was activated by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} activated.')
    elif action == 'verify':
        profile.is_verified = True
        create_notification(
            vendor,
            'Your vendor profile is now verified by Namaste Nomad.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} marked as verified.')
    elif action == 'unverify':
        profile.is_verified = False
        create_notification(
            vendor,
            'Your vendor verification badge was removed by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} marked as unverified.')
    else:
        messages.error(request, 'Invalid action.')
        return redirect(next_url)

    vendor.save()
    profile.save()
    return redirect(next_url)


@admin_required
@csrf_protect
def admin_package_toggle(request, package_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    package.is_active = not package.is_active
    package.save()

    if package.vendor:
        if package.is_active:
            message = f'Your package "{package.title}" was approved by admin.'
        else:
            message = f'Your package "{package.title}" was hidden by admin.'
        create_notification(
            package.vendor,
            message,
            Notification.TYPE_PACKAGE_APPROVED,
            related_object_id=package.id,
        )

    status_label = 'activated' if package.is_active else 'deactivated'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_feature_toggle(request, package_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    if not package.is_featured:
        VendorFeature.expire_overdue(vendor=package.vendor)
        purchased_slots = _total_active_feature_slots_for_vendor(package.vendor)
        featured_count = Package.objects.filter(
            vendor=package.vendor,
            is_featured=True,
        ).count()
        if purchased_slots <= featured_count:
            messages.error(request, 'Upgrade subscription to feature more packages')
            return redirect('admin_dashboard')
        global_capacity = _total_homepage_feature_capacity()
        global_used = _total_homepage_featured_count()
        if global_used >= global_capacity:
            messages.error(request, 'No homepage feature slots available right now.')
            return redirect('admin_dashboard')

    package.is_featured = not package.is_featured
    package.save(update_fields=['is_featured'])

    status_label = 'featured' if package.is_featured else 'unfeatured'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_subscription_plan_create(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    name = (request.POST.get('name') or '').strip()
    price_raw = (request.POST.get('price') or '').strip()
    duration_raw = (request.POST.get('duration_days') or '').strip()
    limit_raw = (request.POST.get('max_featured_packages') or '').strip()

    if not name or not price_raw or not duration_raw:
        messages.error(request, 'Plan name, price, and duration are required.')
        return redirect('admin_dashboard')

    try:
        price = Decimal(price_raw)
        duration_days = int(duration_raw)
        max_featured_packages = int(limit_raw) if limit_raw else None
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, 'Invalid subscription plan values.')
        return redirect('admin_dashboard')

    if duration_days < 1:
        messages.error(request, 'Duration must be at least 1 day.')
        return redirect('admin_dashboard')
    if price < 0:
        messages.error(request, 'Price must be a positive value.')
        return redirect('admin_dashboard')
    if max_featured_packages is not None and max_featured_packages < 1:
        messages.error(request, 'Featured limit must be at least 1.')
        return redirect('admin_dashboard')

    try:
        VendorSubscriptionPlan.objects.create(
            name=name,
            price=price,
            duration_days=max(duration_days, 1),
            max_featured_packages=max_featured_packages,
            is_active=True,
        )
    except IntegrityError:
        messages.error(request, 'A plan with that name already exists.')
    else:
        messages.success(request, 'Subscription plan created.')
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_feature_slot_create(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    name = (request.POST.get('name') or '').strip()
    max_slots_raw = (request.POST.get('max_slots') or '').strip()
    price_raw = (request.POST.get('price_per_slot') or '').strip()

    if not name or not max_slots_raw or not price_raw:
        messages.error(request, 'Feature slot name, max slots, and price are required.')
        return redirect('admin_dashboard')

    try:
        max_slots = int(max_slots_raw)
        price_per_slot = Decimal(price_raw)
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, 'Invalid feature slot values.')
        return redirect('admin_dashboard')

    if max_slots < 1:
        messages.error(request, 'Max slots must be at least 1.')
        return redirect('admin_dashboard')
    if price_per_slot < 0:
        messages.error(request, 'Price per slot must be a positive value.')
        return redirect('admin_dashboard')

    FeatureSlot.objects.create(
        name=name,
        max_slots=max_slots,
        price_per_slot=price_per_slot,
        is_active=True,
    )
    messages.success(request, 'Feature slot created.')
    return redirect('admin_dashboard')


@admin_required
def admin_vendor_detail(request, vendor_id):
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    admin_profile = _get_admin_profile(request.user)
    packages = Package.objects.filter(vendor=vendor).order_by('-created_at')

    return render(request, 'accounts/admin_vendor_detail.html', {
        'admin_profile': admin_profile,
        'vendor': vendor,
        'vendor_profile': profile,
        'packages': packages,
        'active_page': 'vendors',
    })


@never_cache
@admin_required
def admin_transactions(request):
    admin_profile = _get_admin_profile(request.user)
    transactions = Transaction.objects.select_related(
        'booking',
        'booking__package',
        'traveler',
        'vendor',
    )
    transactions, filters = _apply_transaction_filters(transactions, request, allow_vendor=True)
    transactions = transactions.order_by('-created_at')
    vendor_choices = User.objects.filter(user_type='vendor').order_by('email')

    if request.GET.get('export') == 'csv':
        return _transaction_csv_response(transactions, 'admin-transactions.csv')

    return render(request, 'accounts/admin_transactions.html', {
        'admin_profile': admin_profile,
        'transactions': transactions,
        'filters': filters,
        'vendor_choices': vendor_choices,
        'active_page': 'transactions',
    })
