"""Admin: list vendor feature plans and active subscriptions."""

from django.shortcuts import render

from accounts.models import FeaturePlan, VendorFeatureSubscription
from accounts.views.common import _get_admin_profile, admin_required


@admin_required
def admin_subscriptions(request):
    """Admin subscriptions page with all plans and active vendor subscriptions."""
    subscriptions = VendorFeatureSubscription.objects.select_related('vendor', 'plan').order_by('-created_at')
    feature_plans = FeaturePlan.objects.order_by('price', 'slots_count')
    active_subscriptions = subscriptions.filter(
        is_active=True,
        payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
    )

    return render(request, 'admin/subscriptions.html', {
        'admin_profile': _get_admin_profile(request.user),
        'feature_plans': feature_plans,
        'active_subscriptions': active_subscriptions,
        'subscriptions': subscriptions,
        'active_page': 'subscriptions',
        'breadcrumb': 'Subscriptions',
    })
