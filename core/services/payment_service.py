"""Payment utility service helpers."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from ..models import Booking
from .esewa_service import (
    build_booking_payment_payload,
    get_esewa_payment_url,
)


def _stripe_checkout_ttl_minutes():
    try:
        minutes = int(getattr(settings, 'STRIPE_CHECKOUT_TTL_MINUTES', 30))
    except (TypeError, ValueError):
        minutes = 30
    return max(minutes, 30)


def _booking_payment_expires_at():
    return timezone.now() + timedelta(minutes=_stripe_checkout_ttl_minutes())


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


def _render_esewa_checkout(request, booking):
    success_url = request.build_absolute_uri(
        reverse('booking_esewa_success', kwargs={'booking_id': booking.id}),
    )
    failure_url = request.build_absolute_uri(
        reverse('booking_esewa_failure', kwargs={'booking_id': booking.id}),
    )
    payload = build_booking_payment_payload(
        booking=booking,
        success_url=success_url,
        failure_url=failure_url,
    )
    # Persist the generated transaction_uuid so the success handler can
    # verify it against eSewa's callback.
    booking.payment_reference = payload['transaction_uuid']
    booking.save(update_fields=['payment_reference'])

    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': booking,
            'esewa_payment_url': get_esewa_payment_url(),
            'esewa_payload': payload,
        },
    )

__all__ = [
    'timedelta',
    'Decimal',
    'InvalidOperation',
    'settings',
    'render',
    'reverse',
    'timezone',
    'Booking',
    'build_booking_payment_payload',
    'get_esewa_payment_url',
    '_stripe_checkout_ttl_minutes',
    '_booking_payment_expires_at',
    '_mark_payment_failed',
    '_as_money_decimal',
    '_render_esewa_checkout',
]
