"""Vendor package management views."""

from ..common import (
    Count,
    FeaturedPackage,
    Notification,
    Package,
    PackageForm,
    _append_package_images,
    _get_active_subscription,
    _get_vendor_profile,
    _sync_package_images,
    csrf_protect,
    get_object_or_404,
    messages,
    never_cache,
    notify_admins,
    redirect,
    render,
    reverse,
    vendor_required,
)
from core.services.subscription_service import (
    expire_overdue_subscriptions,
    feature_package,
    get_active_subscription,
    get_featured_packages_for_vendor,
    unfeature_package,
)


@never_cache
@vendor_required(login_url='account_login_choice')
@csrf_protect
def vendor_packages(request):
    """List the vendor's own packages with featured-slot status."""
    vendor_profile = _get_vendor_profile(request.user)
    packages = Package.objects.filter(vendor=request.user).annotate(
        booking_count=Count('bookings'),
    ).order_by('-created_at')
    subscription = get_active_subscription(request.user)
    featured_entries = get_featured_packages_for_vendor(request.user)
    featured_package_ids = set(featured_entries.values_list('package_id', flat=True))
    featured_count = len(featured_package_ids)
    featured_limit = subscription.slots_total if subscription else 0
    return render(request, 'accounts/vendor_packages.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'packages': packages,
        'active_subscription': subscription,
        'featured_package_ids': featured_package_ids,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
        'featured_remaining': max(featured_limit - featured_count, 0),
    })


@never_cache
@vendor_required(login_url='vendor_login')
def vendor_feature_toggle(request, package_id):
    """Toggle a package's featured-slot status under the vendor's active subscription."""
    if request.method != 'POST':
        return redirect('vendor_packages')

    next_url = request.POST.get('next') or reverse('vendor_packages')
    package = get_object_or_404(Package, id=package_id, vendor=request.user)
    subscription = get_active_subscription(request.user)

    if not subscription:
        messages.error(request, 'You need an active feature plan to feature packages.')
        return redirect(next_url)

    # Check if package is currently featured
    is_currently_featured = FeaturedPackage.objects.filter(
        subscription=subscription,
        package=package,
        is_active=True,
    ).exists()

    if is_currently_featured:
        unfeature_package(subscription, package)
        messages.success(request, f'{package.title} removed from featured.')
    else:
        fp, error = feature_package(subscription, package)
        if error:
            messages.error(request, error)
        else:
            messages.success(request, f'{package.title} is now featured!')

    return redirect(next_url)


@never_cache
@vendor_required(login_url='vendor_login')

def vendor_package_create(request):
    """Create a new package owned by the vendor; notifies admins and limited-offer subscribers."""
    vendor_profile = _get_vendor_profile(request.user)

    if request.method == 'POST':
        form = PackageForm(request.POST, vendor=request.user)
        if form.is_valid():
            package = form.save(commit=False)
            package.vendor = request.user
            package.save()
            _append_package_images(package, request.FILES.getlist('images'))
            notify_admins(
                f'Vendor submitted new package: {package.title}',
                Notification.TYPE_PACKAGE_SUBMISSION,
                related_object_id=package.id,
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
@vendor_required(login_url='vendor_login')

def vendor_package_edit(request, package_id):
    """Edit one of the vendor's packages and reorder/replace its image set."""
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
@vendor_required(login_url='vendor_login')
@csrf_protect

def vendor_package_delete(request, package_id):
    """Delete a package, but only if it has zero existing bookings."""
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

