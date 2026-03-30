"""Vendor booking and review views."""

from ..common import *

@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def vendor_bookings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    bookings = Booking.objects.filter(package__vendor=request.user).select_related(
        'package',
        'traveler',
    ).order_by('-created_at')
    return render(request, 'accounts/vendor_bookings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'bookings',
        'bookings': bookings,
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect

def vendor_booking_status_update(request, booking_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    next_url = request.POST.get('next') or reverse('vendor_bookings')
    if request.method != 'POST':
        return redirect(next_url)

    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        package__vendor=request.user,
    )
    requested_status = (request.POST.get('status') or '').strip().lower()

    if requested_status not in {'confirmed', 'cancelled'}:
        messages.error(request, 'Invalid booking action.')
        return redirect(next_url)

    if booking.status == requested_status:
        return redirect(next_url)

    if (
        requested_status == Booking.STATUS_CONFIRMED
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        messages.error(request, 'Only paid bookings can be confirmed.')
        return redirect(next_url)

    package = booking.package

    if requested_status == Booking.STATUS_CANCELLED and booking.status != Booking.STATUS_CANCELLED:
        package.available_slots += booking.number_of_people
        package.save(update_fields=['available_slots'])

    if requested_status == Booking.STATUS_CONFIRMED and booking.status == Booking.STATUS_CANCELLED:
        if booking.number_of_people > package.available_slots:
            messages.error(
                request,
                f'Cannot confirm booking. Only {package.available_slots} slot(s) are currently available.',
            )
            return redirect(next_url)
        package.available_slots -= booking.number_of_people
        package.save(update_fields=['available_slots'])

    booking.status = requested_status
    booking.save(update_fields=['status'])
    if requested_status == Booking.STATUS_CONFIRMED and booking.traveler:
        add_points(booking.traveler, 'booking_confirmed', 50)
        sync_badges_for_user(booking.traveler)
    if booking.traveler:
        status_label = 'confirmed' if requested_status == Booking.STATUS_CONFIRMED else 'cancelled'
        create_notification(
            booking.traveler,
            f'Your booking for {booking.package.title} was {status_label}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    messages.success(request, f'Booking marked as {requested_status}.')
    return redirect(next_url)


@never_cache
@login_required(login_url='vendor_login')

def vendor_reviews(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    reviews = Review.objects.filter(package__vendor=request.user).order_by('-created_at')
    return render(request, 'accounts/vendor_reviews.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'reviews',
        'reviews': reviews,
    })

