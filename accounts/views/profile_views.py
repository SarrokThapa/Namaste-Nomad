"""Traveler and profile-related views.

Owns the traveler home dashboard, the per-user wishlist, the bookings
list, the achievements/badges page, the personal transactions list,
the traveler profile editor, the vendor profile editor, and the
public-facing vendor profile page.
"""

# NOTE: file > 300 lines — split deferred. The traveler home + profile
# screens share a large bundle of imports from accounts/views/common.py
# and a single common context-prep flow; splitting would duplicate that
# bundle in multiple files.

from .common import (
    Avg,
    Booking,
    Count,
    IntegrityError,
    JsonResponse,
    Package,
    Q,
    Review,
    Transaction,
    TravelerProfile,
    User,
    UserBadge,
    VendorProfile,
    VendorProfileForm,
    Wishlist,
    _apply_transaction_filters,
    _delete_stored_file,
    _get_traveler_profile,
    _get_vendor_profile,
    _is_valid_uploaded_image,
    _transaction_csv_response,
    _traveler_package_queryset,
    add_points,
    badge_progress_for_user,
    csv,
    get_object_or_404,
    login_required,
    messages,
    never_cache,
    redirect,
    render,
    require_POST,
    sync_badges_for_user,
    traveler_required,
    timesince,
    total_points_for_user,
    vendor_account_required,
)

@never_cache
@vendor_account_required(login_url='vendor_login')
def vendor_profile(request):
    """Show / update the logged-in vendor's profile, logo, contact details, and password."""
    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile is None:
        vendor_profile = VendorProfile.objects.create(
            user=request.user,
            business_name=request.user.get_full_name() or request.user.username,
            owner_name=request.user.get_full_name() or request.user.username,
        )

    if request.method == 'POST':
        old_logo_name = vendor_profile.logo.name if vendor_profile.logo else ''
        form = VendorProfileForm(request.POST, request.FILES, instance=vendor_profile)
        phone = (request.POST.get('phone') or '').strip()
        remove_logo = request.POST.get('remove_logo') == '1'

        request.user.phone = phone
        request.user.save()

        if form.is_valid():
            uploading_new_logo = bool(request.FILES.get('logo'))
            profile_instance = form.save(commit=False)

            if remove_logo:
                profile_instance.logo = None

            profile_instance.save()
            if remove_logo or uploading_new_logo:
                current_logo_name = profile_instance.logo.name if profile_instance.logo else ''
                if old_logo_name and old_logo_name != current_logo_name:
                    _delete_stored_file(profile_instance, 'logo', old_logo_name)
            messages.success(request, 'Profile updated successfully.')
            return redirect('vendor_profile')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = VendorProfileForm(instance=vendor_profile)

    packages = Package.objects.filter(vendor=request.user).prefetch_related('images').order_by('-created_at')[:6]

    return render(request, 'accounts/vendor_profile.html', {
        'vendor_profile': vendor_profile,
        'form': form,
        'packages': packages,
        'active_page': 'profile',
    })


def vendor_public_profile(request, vendor_id):
    """Public-facing vendor profile page listing their active packages."""
    vendor = get_object_or_404(
        User.objects.select_related('vendor_profile'),
        id=vendor_id,
        user_type='vendor',
    )
    profile = _get_vendor_profile(vendor)
    packages = (
        Package.objects.filter(vendor=vendor, is_active=True).select_related('vendor', 'vendor__vendor_profile')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
        )
        .order_by('-created_at')
    )

    return render(request, 'accounts/vendor_public_profile.html', {
        'vendor': vendor,
        'vendor_profile': profile,
        'packages': packages,
    })


@require_POST
@login_required(login_url='account_login_choice')
def wishlist_toggle(request):
    """Add or remove a package from the current traveler's wishlist (AJAX)."""
    if getattr(request.user, 'user_type', '') != 'traveler':
        return JsonResponse(
            {'error': 'forbidden', 'message': 'Traveler access only.'},
            status=403,
        )

    package_id = request.POST.get('package_id')
    if not package_id:
        return JsonResponse({'error': 'missing_package'}, status=400)
    try:
        package_id = int(package_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_package'}, status=400)

    existing = Wishlist.objects.filter(traveler=request.user, package_id=package_id).first()
    if existing:
        existing.delete()
        status = 'removed'
        is_wishlisted = False
    else:
        package = get_object_or_404(Package, id=package_id, is_active=True)
        try:
            Wishlist.objects.create(traveler=request.user, package=package)
        except IntegrityError:
            pass
        status = 'added'
        is_wishlisted = True
        add_points(request.user, 'wishlist', 5)
        sync_badges_for_user(request.user)

    count = Wishlist.objects.filter(traveler=request.user).count()
    return JsonResponse({
        'status': status,
        'is_wishlisted': is_wishlisted,
        'count': count,
        'package_id': package_id,
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_home(request):
    """Traveler explore dashboard with search and curated package lists."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    wishlist_ids = set(
        Wishlist.objects.filter(traveler=request.user).values_list('package_id', flat=True)
    )

    search_query = (request.GET.get('q') or '').strip()
    filtered_packages = _traveler_package_queryset()

    if search_query:
        filtered_packages = filtered_packages.filter(
            Q(title__icontains=search_query)
            | Q(location__icontains=search_query)
            | Q(location_name__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    featured_packages = list(
        filtered_packages.order_by(
            '-avg_rating',
            '-review_count',
            '-views_count',
            '-created_at',
        )[:4]
    )
    result_count = filtered_packages.count()

    recent_reviews = Review.objects.filter(
        package__is_active=True,
        traveler__isnull=False,
    ).select_related(
        'traveler',
        'package',
    ).order_by('-created_at')[:6]

    return render(request, 'accounts/traveler_home.html', {
        'traveler_profile': profile,
        'active_page': 'explore',
        'search_query': search_query,
        'featured_packages': featured_packages,
        'recent_reviews': recent_reviews,
        'result_count': result_count,
        'can_clear_filters': bool(search_query),
        'wishlist_ids': wishlist_ids,
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_wishlist(request):
    """List the traveler's saved packages."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    wishlist_items = (
        Wishlist.objects.filter(traveler=request.user)
        .select_related('package', 'package__vendor')
        .prefetch_related('package__images')
        .order_by('-created_at')
    )
    wishlist_ids = set(wishlist_items.values_list('package_id', flat=True))

    return render(request, 'accounts/traveler_wishlist.html', {
        'traveler_profile': profile,
        'wishlist_items': wishlist_items,
        'wishlist_ids': wishlist_ids,
        'active_page': 'wishlist',
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_achievements(request):
    """Show the traveler's badges, points, and progress toward the next badge."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    sync_badges_for_user(request.user)
    badges, summary, next_badge = badge_progress_for_user(request.user)
    total_points = total_points_for_user(request.user)

    earned_badges = [
        entry.badge
        for entry in UserBadge.objects.filter(user=request.user)
        .select_related('badge')
        .order_by('-earned_at')
    ]

    return render(request, 'accounts/traveler_achievements.html', {
        'traveler_profile': profile,
        'badges': badges,
        'earned_badges': earned_badges,
        'total_points': total_points,
        'earned_badge_count': summary.get('earned_count', 0),
        'total_badges': summary.get('total_badges', 0),
        'next_badge': next_badge,
        'active_page': 'achievements',
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_bookings(request):
    """List all bookings made by the current traveler, newest first."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    bookings = Booking.objects.filter(traveler=request.user).select_related(
        'package',
    ).order_by('-created_at')

    return render(request, 'accounts/traveler_bookings.html', {
        'traveler_profile': profile,
        'bookings': bookings,
        'active_page': 'bookings',
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_transactions(request):
    """List the traveler's payment transactions with optional filters and CSV export."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    transactions = Transaction.objects.filter(
        traveler=request.user,
        payment_status=Booking.PAYMENT_STATUS_COMPLETED,
    ).select_related(
        'booking',
        'booking__package',
        'vendor',
    )
    transactions, filters = _apply_transaction_filters(
        transactions,
        request,
        allow_status=False,
    )
    transactions = transactions.order_by('-created_at')

    if request.GET.get('export') == 'csv' and not filters.get('date_error'):
        return _transaction_csv_response(transactions, 'traveler-transactions.csv')

    return render(request, 'accounts/traveler_transactions.html', {
        'traveler_profile': profile,
        'transactions': transactions,
        'filters': filters,
        'active_page': 'transactions',
    })


@never_cache
@traveler_required(login_url='traveler_login')
def traveler_profile(request):
    """Show / update the logged-in traveler's profile, avatar, and personal info."""
    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender') or ''
        nationality = (request.POST.get('nationality') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('traveler_profile')

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        request.user.phone = phone
        request.user.save()

        profile.gender = gender
        profile.nationality = nationality
        profile.bio = bio
        profile.date_of_birth = date_of_birth or None
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

        messages.success(request, 'Profile updated successfully.')
        return redirect('traveler_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    sync_badges_for_user(request.user)
    traveler_reviews = Review.objects.filter(traveler=request.user).select_related('package').order_by('-created_at')[:6]
    review_packages = Package.objects.filter(is_active=True).order_by('title')
    activity = [
        {
            'title': f'Left a review for {review.package.title}',
            'time': f'{timesince(review.created_at)} ago',
            'variant': 'review',
        }
        for review in traveler_reviews[:3]
    ]

    return render(request, 'accounts/traveler_profile.html', {
        'traveler_profile': profile,
        'profile': profile,
        'full_name': full_name,
        'traveler_reviews': traveler_reviews,
        'review_packages': review_packages,
        'activity': activity,
        'active_page': 'profile',
    })
