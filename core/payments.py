"""Stripe Checkout integration plus eSewa V2 re-exports.

Owns the Stripe Checkout REST calls (create / retrieve / expire) used
by the booking and feature-plan flows. eSewa logic lives in
``core/services/esewa_service.py``; the re-exports at the top of this
file preserve the legacy ``from core.payments import EsewaError`` etc.
import paths so older callers keep working.
"""

import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings

# eSewa V2 service — all eSewa logic lives there; re-export key names
# so existing ``from core.payments import EsewaError`` still works.
from .services.esewa_service import (  # noqa: F401
    EsewaError,
    get_esewa_payment_url,
    build_booking_payment_payload as build_esewa_payment_payload,
    build_payment_payload as build_esewa_generic_payload,
    process_success_callback as esewa_process_success_callback,
    decode_success_response as esewa_decode_success_response,
    verify_payment as esewa_verify_payment,
)


class StripeError(Exception):
    """Raised when a Stripe API call fails or Stripe is not configured."""


def _amount_to_minor_units(amount):
    """Convert a major-unit amount (e.g. dollars) to Stripe's expected minor units (e.g. cents)."""
    decimal_amount = Decimal(amount)
    return int((decimal_amount * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))



def _stripe_request(method, path, payload=None):
    """Low-level Stripe REST helper that raises StripeError on any failure."""
    if not settings.STRIPE_SECRET_KEY:
        raise StripeError('Stripe is not configured. Add STRIPE_SECRET_KEY to your .env file or environment.')

    body = None
    headers = {
        'Authorization': f'Bearer {settings.STRIPE_SECRET_KEY}',
    }
    if payload is not None:
        body = urlencode(payload).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

    request = Request(
        url=f'https://api.stripe.com/v1{path}',
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        payload = exc.read().decode('utf-8', errors='replace')
        try:
            error_payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise StripeError('Stripe request failed.') from error
        raise StripeError(error_payload.get('error', {}).get('message') or 'Stripe request failed.') from exc
    except URLError as exc:
        raise StripeError('Unable to reach Stripe right now. Please try again.') from exc


def create_checkout_session(*, booking, success_url, cancel_url):
    """Create a Stripe Checkout session for a Booking and return the JSON response."""
    description = (
        f'{booking.number_of_people} traveler(s) · '
        f'{booking.travel_date:%b %d, %Y} · '
        f'{booking.package.location or "Nepal"}'
    )
    payload = [
        ('mode', 'payment'),
        ('success_url', success_url),
        ('cancel_url', cancel_url),
        ('payment_method_types[0]', 'card'),
        ('client_reference_id', str(booking.id)),
        ('metadata[booking_id]', str(booking.id)),
        ('metadata[package_id]', str(booking.package_id)),
        ('line_items[0][quantity]', str(booking.number_of_people)),
        ('line_items[0][price_data][currency]', settings.STRIPE_CURRENCY),
        ('line_items[0][price_data][unit_amount]', str(_amount_to_minor_units(booking.package.price))),
        ('line_items[0][price_data][product_data][name]', booking.package.title),
        ('line_items[0][price_data][product_data][description]', description),
    ]

    if booking.payment_expires_at:
        payload.append(('expires_at', str(int(booking.payment_expires_at.timestamp()))))

    if booking.traveler and booking.traveler.email:
        payload.append(('customer_email', booking.traveler.email))

    return _stripe_request('POST', '/checkout/sessions', payload)


def create_checkout_session_for_item(
    *,
    amount,
    name,
    description,
    success_url,
    cancel_url,
    client_reference_id,
    metadata=None,
    customer_email=None,
):
    """Generic Stripe Checkout session for non-booking items (e.g. vendor feature plans)."""
    payload = [
        ('mode', 'payment'),
        ('success_url', success_url),
        ('cancel_url', cancel_url),
        ('payment_method_types[0]', 'card'),
        ('client_reference_id', str(client_reference_id)),
        ('line_items[0][quantity]', '1'),
        ('line_items[0][price_data][currency]', settings.STRIPE_CURRENCY),
        ('line_items[0][price_data][unit_amount]', str(_amount_to_minor_units(amount))),
        ('line_items[0][price_data][product_data][name]', str(name)),
        ('line_items[0][price_data][product_data][description]', str(description)),
    ]

    if metadata:
        for key, value in metadata.items():
            payload.append((f'metadata[{key}]', str(value)))

    if customer_email:
        payload.append(('customer_email', customer_email))

    return _stripe_request('POST', '/checkout/sessions', payload)


def retrieve_checkout_session(session_id):
    """Fetch a Stripe Checkout session by id (used by success-callback verification)."""
    safe_session_id = quote(session_id, safe='')
    return _stripe_request('GET', f'/checkout/sessions/{safe_session_id}')


def expire_checkout_session(session_id):
    """Tell Stripe to expire an outstanding Checkout session (used when cancelling unpaid bookings)."""
    safe_session_id = quote(session_id, safe='')
    return _stripe_request('POST', f'/checkout/sessions/{safe_session_id}/expire', [])



# Legacy eSewa V1 functions have been removed.
# All eSewa logic now lives in core.services.esewa_service.
# The re-exports at the top of this file keep existing import paths working.
