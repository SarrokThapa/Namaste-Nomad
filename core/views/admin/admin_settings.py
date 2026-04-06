from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect

from accounts.views.common import _get_admin_profile, admin_required

from ...forms import SiteSettingForm
from ...services.site_settings import get_site_settings


@admin_required
@csrf_protect
def admin_settings(request):
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
