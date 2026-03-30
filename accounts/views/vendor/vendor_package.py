"""Vendor package management views."""

from ..common import *

@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def vendor_packages(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    packages = Package.objects.filter(vendor=request.user).annotate(
        booking_count=Count('bookings'),
    ).order_by('-created_at')
    active_subscription = _get_active_subscription(request.user)
    VendorFeature.expire_overdue(vendor=request.user)
    featured_count = packages.filter(is_featured=True).count()
    featured_limit = _total_active_feature_slots_for_vendor(request.user)
    return render(request, 'accounts/vendor_packages.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'packages': packages,
        'active_subscription': active_subscription,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
        'featured_remaining': max(featured_limit - featured_count, 0),
    })


@never_cache
@login_required(login_url='vendor_login')

def vendor_feature_toggle(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')
    if request.method != 'POST':
        return redirect('vendor_packages')

    next_url = request.POST.get('next') or reverse('vendor_packages')
    VendorFeature.expire_overdue(vendor=request.user)
    package = get_object_or_404(Package, id=package_id, vendor=request.user)
    if not package.is_featured:
        purchased_slots = _total_active_feature_slots_for_vendor(request.user)
        featured_count = Package.objects.filter(vendor=request.user, is_featured=True).count()
        if purchased_slots <= featured_count:
            messages.error(request, 'Upgrade subscription to feature more packages')
            return redirect(next_url)
        global_capacity = _total_homepage_feature_capacity()
        global_used = _total_homepage_featured_count()
        if global_used >= global_capacity:
            messages.error(request, 'No homepage feature slots available right now.')
            return redirect(next_url)

    package.is_featured = not package.is_featured
    package.save(update_fields=['is_featured'])
    status_label = 'featured' if package.is_featured else 'unfeatured'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect(next_url)


@never_cache
@login_required(login_url='vendor_login')

def vendor_package_create(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)

    if request.method == 'POST':
        form = PackageForm(request.POST, vendor=request.user)
        if form.is_valid():
            limited_time_offer = bool(form.cleaned_data.get('limited_time_offer'))
            package = form.save(commit=False)
            package.vendor = request.user
            package.save()
            _append_package_images(package, request.FILES.getlist('images'))
            notify_admins(
                f'Vendor submitted new package: {package.title}',
                Notification.TYPE_PACKAGE_SUBMISSION,
                related_object_id=package.id,
            )
            if limited_time_offer:
                notified_count = _notify_opted_in_travelers_for_limited_package_offer(package)
                if notified_count:
                    messages.info(
                        request,
                        f'Limited-time offer notifications sent to {notified_count} opted-in traveler(s).',
                    )
            messages.success(request, 'Package created successfully.')
            return redirect('vendor_packages')
    else:
        form = PackageForm(vendor=request.user)

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': False,
        'existing_images': [],
        'active_subscription': _get_active_subscription(request.user),
    })


@never_cache
@login_required(login_url='vendor_login')

def vendor_package_edit(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    package = get_object_or_404(
        Package.objects.prefetch_related('images'),
        id=package_id,
        vendor=request.user,
    )

    if request.method == 'POST':
        form = PackageForm(request.POST, instance=package, vendor=request.user)
        if form.is_valid():
            package = form.save()
            _sync_package_images(package, request.POST, request.FILES)
            messages.success(request, 'Package updated successfully.')
            return redirect('vendor_package_edit', package_id=package.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PackageForm(instance=package, vendor=request.user)

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': True,
        'package': package,
        'existing_images': package.images.all(),
        'active_subscription': _get_active_subscription(request.user),
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect

def vendor_package_delete(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    next_url = request.POST.get('next') or reverse('vendor_packages')
    if request.method != 'POST':
        return redirect(next_url)

    package = get_object_or_404(
        Package.objects.annotate(booking_count=Count('bookings')),
        id=package_id,
        vendor=request.user,
    )
    if package.booking_count:
        messages.error(
            request,
            'Cannot delete a package with existing bookings. Please set it inactive instead.',
        )
        return redirect(next_url)

    package.delete()
    messages.success(request, 'Package deleted successfully.')
    return redirect(next_url)

