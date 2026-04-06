from django.shortcuts import render

from accounts.views.common import _get_admin_profile, admin_required
from core.models import Booking


@admin_required
def admin_bookings(request):
    status = (request.GET.get('status') or '').strip().lower()
    payment_status = (request.GET.get('payment_status') or '').strip().lower()

    bookings = Booking.objects.select_related('package', 'traveler', 'vendor', 'package__vendor').order_by('-created_at')

    if status in {
        Booking.STATUS_PENDING,
        Booking.STATUS_CONFIRMED,
        Booking.STATUS_CANCELLED,
    }:
        bookings = bookings.filter(status=status)

    if payment_status in {
        Booking.PAYMENT_STATUS_PENDING,
        Booking.PAYMENT_STATUS_COMPLETED,
        Booking.PAYMENT_STATUS_FAILED,
    }:
        bookings = bookings.filter(payment_status=payment_status)

    return render(request, 'admin/bookings.html', {
        'admin_profile': _get_admin_profile(request.user),
        'bookings': bookings,
        'selected_status': status,
        'selected_payment_status': payment_status,
        'active_page': 'bookings',
        'breadcrumb': 'Bookings',
    })
