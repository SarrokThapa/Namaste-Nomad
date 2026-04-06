from django.shortcuts import render

from accounts.views.common import _get_admin_profile, admin_required
from core.models import Review


@admin_required
def admin_reviews(request):
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')

    return render(request, 'admin/reviews.html', {
        'admin_profile': _get_admin_profile(request.user),
        'reviews': reviews,
        'active_page': 'reviews',
        'breadcrumb': 'Reviews',
    })
