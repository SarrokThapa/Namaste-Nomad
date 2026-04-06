from django.db.models import Count
from django.shortcuts import render

from accounts.models import User
from accounts.views.common import _get_admin_profile, admin_required


@admin_required
def admin_users(request):
    role = (request.GET.get('role') or '').strip().lower()

    users = User.objects.filter(user_type__in=['traveler', 'vendor']).select_related('vendor_profile').annotate(
        booking_count=Count('traveler_bookings', distinct=True),
    ).order_by('-date_joined')

    if role in {'traveler', 'vendor'}:
        users = users.filter(user_type=role)

    return render(request, 'admin/users.html', {
        'admin_profile': _get_admin_profile(request.user),
        'users': users,
        'selected_role': role,
        'active_page': 'users',
        'breadcrumb': 'Users',
    })
