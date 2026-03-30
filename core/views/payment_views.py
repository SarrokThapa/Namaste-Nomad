"""Payment helper and gateway views (Stripe/eSewa)."""

from ..services.booking_service import *
from ..services.discount_service import *
from ..services.notification_service import *
from ..services.payment_service import *
from ..utils.helpers import *






def _stripe_checkout_ttl_minutes():
    try:
        minutes = int(getattr(settings, 'STRIPE_CHECKOUT_TTL_MINUTES', 30))
    except (TypeError, ValueError):
        minutes = 30
    return max(minutes, 30)


def _booking_payment_expires_at():
    return timezone.now() + timedelta(minutes=_stripe_checkout_ttl_minutes())


def _expire_stale_pending_bookings(package_id=None):
    stale_bookings = Booking.objects.select_for_update().filter(
        status=Booking.STATUS_PENDING,
        payment_status__in=[
            Booking.PAYMENT_STATUS_PENDING,
            Booking.PAYMENT_STATUS_FAILED,
        ],
        payment_expires_at__isnull=False,
        payment_expires_at__lt=timezone.now(),
    )
    if package_id is not None:
        stale_bookings = stale_bookings.filter(package_id=package_id)

    for stale_booking in stale_bookings:
        Package.objects.filter(id=stale_booking.package_id).update(
            available_slots=F('available_slots') + stale_booking.number_of_people,
        )
        stale_booking.status = Booking.STATUS_CANCELLED
        stale_booking.payment_status = Booking.PAYMENT_STATUS_FAILED
        stale_booking.payment_expires_at = None
        stale_booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _cancel_unpaid_booking(booking, payment_status):
    if (
        booking.status == Booking.STATUS_PENDING
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        Package.objects.filter(id=booking.package_id).update(
            available_slots=F('available_slots') + booking.number_of_people,
        )
    booking.status = Booking.STATUS_CANCELLED
    booking.payment_status = payment_status
    booking.payment_expires_at = None
    booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _complete_paid_booking(
    booking,
    *,
    payment_reference='',
    stripe_checkout_session_id='',
    esewa_transaction_id='',
    paid_amount=None,
):
    booking.status = Booking.STATUS_CONFIRMED
    booking.payment_status = Booking.PAYMENT_STATUS_COMPLETED
    if payment_reference:
        booking.payment_reference = payment_reference
    if stripe_checkout_session_id:
        booking.stripe_checkout_session_id = stripe_checkout_session_id
    if esewa_transaction_id:
        booking.esewa_transaction_id = esewa_transaction_id
    if paid_amount is not None:
        booking.paid_amount = paid_amount
    elif booking.paid_amount is None:
        booking.paid_amount = booking.total_price
    if not booking.paid_at:
        booking.paid_at = timezone.now()
    booking.payment_expires_at = None
    discount_used = None
    discount_used_amount = Decimal('0.00')
    if booking.discount_id:
        discount = (
            Discount.objects.select_for_update()
            .filter(id=booking.discount_id, user_id=booking.traveler_id)
            .first()
        )
        if discount and discount.is_valid():
            discount.is_used = True
            discount.used_at = timezone.now()
            discount.save(update_fields=['is_used', 'used_at'])
            discount_used = discount
            discount_used_amount = booking.discount_amount or Decimal('0.00')

    booking.save(
        update_fields=[
            'status',
            'payment_status',
            'payment_reference',
            'stripe_checkout_session_id',
            'esewa_transaction_id',
            'paid_amount',
            'paid_at',
            'payment_expires_at',
        ]
    )
    Transaction.objects.update_or_create(
        booking=booking,
        defaults={
            'transaction_type': Transaction.TYPE_BOOKING,
            'vendor_subscription': None,
            'traveler': booking.traveler,
            'vendor': booking.vendor,
            'total_amount': booking.paid_amount or booking.total_price,
            'payment_method': booking.payment_method,
            'payment_status': booking.payment_status,
        },
    )

    if discount_used and booking.traveler:
        create_notification(
            booking.traveler,
            f'Your discount of Rs {discount_used_amount:.0f} was applied to booking #{booking.id}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    if discount_used and booking.vendor:
        create_notification(
            booking.vendor,
            'A booking used discount on your package.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    _send_post_booking_vendor_message(booking)


def _mark_payment_failed(booking):
    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return
    booking.payment_status = Booking.PAYMENT_STATUS_FAILED
    booking.save(update_fields=['payment_status'])


def _as_money_decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _best_available_discount_for_user(user, original_total):
    if not user.is_authenticated or getattr(user, 'user_type', '') != 'traveler':
        return None, Decimal('0.00')

    now = timezone.now()
    candidates = Discount.objects.filter(
        user=user,
        source=Discount.SOURCE_ACHIEVEMENT,
        is_used=False,
        expires_at__gt=now,
    )

    best_discount = None
    best_amount = Decimal('0.00')
    for candidate in candidates:
        amount = candidate.calculate_discount_amount(original_total)
        if amount > best_amount:
            best_discount = candidate
            best_amount = amount
    return best_discount, best_amount


def _notify_booking_created(booking):
    if booking.vendor:
        create_notification(
            booking.vendor,
            f'New booking request for {booking.package.title}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    notify_admins(
        f'New booking created for {booking.package.title}.',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _notify_booking_paid(booking):
    if booking.vendor:
        create_notification(
            booking.vendor,
            f'Payment completed for booking #{booking.id} ({booking.package.title}).',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    notify_admins(
        f'Payment completed for booking #{booking.id} ({booking.package.title}).',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _get_or_create_open_support_conversation_for_user(user):
    conversation = (
        SupportConversation.objects.filter(
            user=user,
            status=SupportConversation.STATUS_OPEN,
        )
        .order_by('-created_at', '-id')
        .first()
    )
    if conversation is not None:
        return conversation
    return SupportConversation.objects.create(user=user)


def _vendor_display_for_auto_message(vendor):
    if vendor is None:
        return 'Vendor Team'
    full_name = vendor.get_full_name().strip()
    if full_name:
        return full_name
    return vendor.username or vendor.email or 'Vendor Team'


def _send_post_booking_vendor_message(booking):
    traveler = booking.traveler
    vendor = booking.vendor or booking.package.vendor
    if traveler is None or vendor is None:
        return

    existing_message = SupportMessage.objects.filter(
        related_booking=booking,
        is_system_generated=True,
        sender=vendor,
    ).exists()
    if existing_message:
        return

    conversation = _get_or_create_open_support_conversation_for_user(traveler)
    traveler_name = traveler.get_full_name().strip() or traveler.username or 'Traveler'
    vendor_name = _vendor_display_for_auto_message(vendor)
    travel_date_label = booking.travel_date.strftime('%b %d, %Y')
    vendor_phone = (getattr(vendor, 'phone', '') or '').strip() or 'N/A'
    vendor_email = (getattr(vendor, 'email', '') or '').strip() or 'N/A'

    message_body = (
        f'Hello {traveler_name},\n\n'
        'Thank you for booking with us!\n\n'
        f'Package: {booking.package.title}\n'
        f'Travel Date: {travel_date_label}\n'
        f'People: {booking.number_of_people}\n\n'
        'For further details, feel free to contact us:\n'
        f'Phone: {vendor_phone}\n'
        f'Email: {vendor_email}\n\n'
        'We will also reach out to you shortly.\n\n'
        'Thank you for choosing our service!\n\n'
        f'- {vendor_name}'
    )

    SupportMessage.objects.create(
        conversation=conversation,
        sender=vendor,
        related_booking=booking,
        message=message_body,
        is_admin_reply=True,
        is_system_generated=True,
    )

    create_notification(
        traveler,
        'You received a message from vendor',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )
    create_notification(
        vendor,
        'Booking confirmed successfully',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _render_esewa_checkout(request, booking):
    success_url = request.build_absolute_uri(
        reverse('booking_esewa_success', kwargs={'booking_id': booking.id}),
    )
    failure_url = request.build_absolute_uri(
        reverse('booking_esewa_failure', kwargs={'booking_id': booking.id}),
    )
    payload = build_esewa_payment_payload(
        booking=booking,
        success_url=success_url,
        failure_url=failure_url,
    )
    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': booking,
            'esewa_payment_url': get_esewa_payment_url(),
            'esewa_payload': payload,
        },
    )


@login_required(login_url='account_login_choice')
def booking_stripe_checkout(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.status != Booking.STATUS_PENDING:
        messages.error(request, 'This booking is no longer awaiting payment.')
        return redirect('booking_confirmation', booking_id=booking.id)

    success_url = (
        request.build_absolute_uri(
            reverse('booking_confirmation', kwargs={'booking_id': booking.id}),
        )
        + '?session_id={CHECKOUT_SESSION_ID}'
    )
    cancel_url = request.build_absolute_uri(
        reverse('booking_checkout_cancel', kwargs={'booking_id': booking.id}),
    )

    try:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            if locked_booking.status != Booking.STATUS_PENDING:
                messages.error(request, 'This booking is no longer awaiting payment.')
                return redirect('booking_confirmation', booking_id=locked_booking.id)

            locked_booking.payment_method = Booking.PAYMENT_METHOD_STRIPE
            locked_booking.payment_status = Booking.PAYMENT_STATUS_PENDING
            locked_booking.payment_expires_at = _booking_payment_expires_at()
            locked_booking.esewa_transaction_id = ''

            session_data = create_checkout_session(
                booking=locked_booking,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            checkout_url = session_data.get('url')
            if not checkout_url:
                raise StripeError('Stripe did not return a checkout URL.')

            locked_booking.stripe_checkout_session_id = session_data.get('id', '')
            locked_booking.payment_reference = (
                session_data.get('payment_intent')
                or session_data.get('id', '')
            )
            locked_booking.save(
                update_fields=[
                    'payment_method',
                    'payment_status',
                    'payment_expires_at',
                    'esewa_transaction_id',
                    'stripe_checkout_session_id',
                    'payment_reference',
                ]
            )
    except StripeError as exc:
        messages.error(request, str(exc))
        return redirect('booking_confirmation', booking_id=booking.id)

    return redirect(checkout_url)


@login_required(login_url='account_login_choice')
def booking_esewa_checkout(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.status != Booking.STATUS_PENDING:
        messages.error(request, 'This booking is no longer awaiting payment.')
        return redirect('booking_confirmation', booking_id=booking.id)

    try:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            if locked_booking.status != Booking.STATUS_PENDING:
                messages.error(request, 'This booking is no longer awaiting payment.')
                return redirect('booking_confirmation', booking_id=locked_booking.id)

            locked_booking.payment_method = Booking.PAYMENT_METHOD_ESEWA
            locked_booking.payment_status = Booking.PAYMENT_STATUS_PENDING
            locked_booking.payment_expires_at = _booking_payment_expires_at()
            locked_booking.stripe_checkout_session_id = ''
            locked_booking.payment_reference = ''
            locked_booking.save(
                update_fields=[
                    'payment_method',
                    'payment_status',
                    'payment_expires_at',
                    'stripe_checkout_session_id',
                    'payment_reference',
                ]
            )
        return _render_esewa_checkout(request, locked_booking)
    except EsewaError as exc:
        messages.error(request, str(exc))
        return redirect('booking_confirmation', booking_id=booking.id)


@login_required(login_url='account_login_choice')
def booking_esewa_success(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_method != Booking.PAYMENT_METHOD_ESEWA:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        messages.success(request, 'Payment already confirmed for this booking.')
        return redirect('booking_confirmation', booking_id=booking.id)

    transaction_id = (
        (request.GET.get('refId') or '')
        or (request.GET.get('rid') or '')
    ).strip()
    callback_pid = (
        (request.GET.get('pid') or '')
        or (request.GET.get('oid') or '')
    ).strip()
    callback_amount_raw = (
        (request.GET.get('amt') or '')
        or (request.GET.get('tAmt') or '')
    ).strip()
    expected_pid = str(booking.id)
    expected_amount = _as_money_decimal(booking.total_price)
    callback_amount = _as_money_decimal(callback_amount_raw) if callback_amount_raw else expected_amount

    if not transaction_id:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Missing eSewa transaction id.')
        return redirect('booking_confirmation', booking_id=booking.id)

    if callback_pid and callback_pid != expected_pid:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Product ID mismatch.')
        return redirect('booking_confirmation', booking_id=booking.id)

    if expected_amount is None or callback_amount != expected_amount:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Amount mismatch.')
        return redirect('booking_confirmation', booking_id=booking.id)

    try:
        is_verified = verify_esewa_payment(
            amount=expected_amount,
            transaction_id=transaction_id,
            product_id=expected_pid,
        )
    except EsewaError as exc:
        messages.warning(request, f'eSewa verification is pending: {exc}')
        return redirect('booking_confirmation', booking_id=booking.id)

    if not is_verified:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment Failed. Try again.')
        return redirect('booking_confirmation', booking_id=booking.id)

    with transaction.atomic():
        locked_booking = get_object_or_404(
            Booking.objects.select_for_update().select_related('package', 'traveler'),
            id=booking_id,
            traveler=request.user,
        )
        if (
            locked_booking.status == Booking.STATUS_PENDING
            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
        ):
            _complete_paid_booking(
                locked_booking,
                payment_reference=transaction_id,
                esewa_transaction_id=transaction_id,
                paid_amount=expected_amount,
            )
            _notify_booking_paid(locked_booking)
        booking = locked_booking

    messages.success(request, 'Payment Successful. Your booking is confirmed.')
    return redirect('booking_confirmation', booking_id=booking.id)


@login_required(login_url='account_login_choice')
def booking_esewa_failure(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_method != Booking.PAYMENT_METHOD_ESEWA:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)

    messages.error(request, 'Payment Failed. Try again.')
    return redirect('booking_confirmation', booking_id=booking.id)

__all__ = [
    '_stripe_checkout_ttl_minutes',
    '_booking_payment_expires_at',
    '_expire_stale_pending_bookings',
    '_cancel_unpaid_booking',
    '_complete_paid_booking',
    '_mark_payment_failed',
    '_as_money_decimal',
    '_best_available_discount_for_user',
    '_notify_booking_created',
    '_notify_booking_paid',
    '_get_or_create_open_support_conversation_for_user',
    '_vendor_display_for_auto_message',
    '_send_post_booking_vendor_message',
    '_render_esewa_checkout',
    'booking_stripe_checkout',
    'booking_esewa_checkout',
    'booking_esewa_success',
    'booking_esewa_failure',
]
