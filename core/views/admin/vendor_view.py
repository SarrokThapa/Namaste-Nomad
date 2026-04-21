"""Admin: list vendor users with pending/approved approval-status filter."""

from django.db.models import Count
from django.shortcuts import render

from accounts.models import User
from accounts.views.common import _get_admin_profile, admin_required


@admin_required
def admin_vendors(request):
    """Admin vendors list filtered by approval status."""
    status = (request.GET.get('status') or '').strip().lower()

    vendors = User.objects.filter(user_type='vendor').select_related('vendor_profile').annotate(
        package_count=Count('vendor_packages', distinct=True),
    ).order_by('-date_joined')

    if status == 'pending':
        vendors = vendors.filter(vendor_profile__is_approved=False)
    elif status == 'approved':
        vendors = vendors.filter(vendor_profile__is_approved=True)

    return render(request, 'admin/vendors.html', {
        'admin_profile': _get_admin_profile(request.user),
        'vendors': vendors,
        'selected_status': status,
        'active_page': 'vendors',
        'breadcrumb': 'Vendors',
    })
