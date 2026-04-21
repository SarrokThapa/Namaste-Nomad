"""Admin: list and filter all packages on the platform."""

from django.shortcuts import render

from accounts.views.common import _get_admin_profile, admin_required
from core.models import Package


@admin_required
def admin_packages(request):
    """Admin package list filtered by active/hidden status."""
    status = (request.GET.get('status') or '').strip().lower()

    packages = Package.objects.select_related('vendor').order_by('-created_at')
    if status == 'active':
        packages = packages.filter(is_active=True)
    elif status == 'hidden':
        packages = packages.filter(is_active=False)

    return render(request, 'admin/packages.html', {
        'admin_profile': _get_admin_profile(request.user),
        'packages': packages,
        'selected_status': status,
        'active_page': 'packages',
        'breadcrumb': 'Packages',
    })
