import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class StripeError(Exception):
    pass


class EsewaError(Exception):
    pass


def _amount_to_minor_units(amount):
    decimal_amount = Decimal(amount)
    return int((decimal_amount * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _amount_to_major_units(amount):
    decimal_amount = Decimal(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return format(decimal_amount, 'f')


def _stripe_request(method, path, payload=None):
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


def retrieve_checkout_session(session_id):
    safe_session_id = quote(session_id, safe='')
    return _stripe_request('GET', f'/checkout/sessions/{safe_session_id}')


def expire_checkout_session(session_id):
    safe_session_id = quote(session_id, safe='')
    return _stripe_request('POST', f'/checkout/sessions/{safe_session_id}/expire', [])


def get_esewa_payment_url():
    payment_url = getattr(settings, 'ESEWA_PAYMENT_URL', '')
    if not payment_url:
        raise EsewaError('eSewa is not configured. Add ESEWA_PAYMENT_URL to your .env file or environment.')
    return payment_url


def build_esewa_payment_payload(*, booking, success_url, failure_url):
    merchant_code = getattr(settings, 'ESEWA_MERCHANT_CODE', '')
    if not merchant_code:
        raise EsewaError('eSewa is not configured. Add ESEWA_MERCHANT_CODE to your .env file or environment.')

    total_amount = _amount_to_major_units(booking.total_price)
    return {
        'amt': total_amount,
        'pdc': '0',
        'psc': '0',
        'txAmt': '0',
        'tAmt': total_amount,
        'pid': str(booking.id),
        'scd': merchant_code,
        'su': success_url,
        'fu': failure_url,
    }


def _is_esewa_verification_success(payload_text):
    normalized = (payload_text or '').strip().lower()
    if normalized == 'success':
        return True
    if '<response_code>success</response_code>' in normalized:
        return True
    if '<responsecode>success</responsecode>' in normalized:
        return True
    return False


def verify_esewa_payment(*, amount, transaction_id, product_id):
    verify_url = getattr(settings, 'ESEWA_VERIFY_URL', '')
    merchant_code = getattr(settings, 'ESEWA_MERCHANT_CODE', '')
    if not verify_url or not merchant_code:
        raise EsewaError(
            'eSewa verification is not configured. Add ESEWA_VERIFY_URL and ESEWA_MERCHANT_CODE to your .env file.'
        )
    if not transaction_id:
        raise EsewaError('Missing eSewa transaction id for verification.')

    payload = [
        ('amt', _amount_to_major_units(amount)),
        ('rid', str(transaction_id)),
        ('pid', str(product_id)),
        ('scd', merchant_code),
    ]
    body = urlencode(payload).encode('utf-8')
    request = Request(
        url=verify_url,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )

    try:
        with urlopen(request, timeout=15) as response:
            response_text = response.read().decode('utf-8', errors='replace')
    except HTTPError as exc:
        response_text = exc.read().decode('utf-8', errors='replace')
        if _is_esewa_verification_success(response_text):
            return True
        raise EsewaError('eSewa verification request failed.') from exc
    except URLError as exc:
        raise EsewaError('Unable to reach eSewa right now. Please try again.') from exc

    return _is_esewa_verification_success(response_text)
