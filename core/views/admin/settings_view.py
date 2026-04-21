"""Admin: edit the singleton SiteSetting row (commission, contact email, feature flags)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect

from accounts.views.common import _get_admin_profile, admin_required
from core.forms import SiteSettingForm
from core.services.site_settings import get_site_settings


@admin_required
@csrf_protect
def admin_settings(request):
    """Admin site-settings editor (POST persists, GET renders the form)."""
    site_settings = get_site_settings()

    if request.method == 'POST':
        form = SiteSettingForm(request.POST, instance=site_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Site settings updated successfully.')
            return redirect('admin_settings')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SiteSettingForm(instance=site_settings)

    return render(request, 'admin/settings.html', {
        'form': form,
        'admin_profile': _get_admin_profile(request.user),
        'active_page': 'settings',
        'breadcrumb': 'Settings',
    })
