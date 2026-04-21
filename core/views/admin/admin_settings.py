"""Admin: edit the SiteSetting singleton.

NOTE: this file duplicates ``settings_view.py`` and is not re-exported
from ``core/views/admin/__init__.py``. Kept here only because removing
it is out of scope for the current "comments only" pass.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect

from accounts.views.common import _get_admin_profile, admin_required

from ...forms import SiteSettingForm
from ...services.site_settings import get_site_settings


@admin_required
@csrf_protect
def admin_settings(request):
    """Admin site-settings editor (duplicate of settings_view.admin_settings)."""
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

    return render(
        request,
        'admin/settings.html',
        {
            'form': form,
            'admin_profile': _get_admin_profile(request.user),
            'active_page': 'settings',
        },
    )
