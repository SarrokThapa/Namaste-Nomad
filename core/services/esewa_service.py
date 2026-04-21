"""eSewa ePay V2 integration service.

All eSewa payment logic lives here. Views should call these functions
and never contain payment logic directly.

API Reference: https://developer.esewa.com.np/pages/Epay#integration

V2 endpoints:
    Test payment:      https://rc-epay.esewa.com.np/api/epay/main/v2/form
    Prod payment:      https://epay.esewa.com.np/api/epay/main/v2/form
    Test verification:  https://rc.esewa.com.np/api/epay/transaction/status/
    Prod verification:  https://esewa.com.np/api/epay/transaction/status/
"""

# NOTE: file > 300 lines — split deferred. eSewa payload building, HMAC
# signing, response decoding and server-side verification are all part
# of the same V2 protocol flow and share the secret-key/merchant-code
# helpers; splitting would make the verification chain harder to follow.

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


class EsewaError(Exception):
    """Raised when an eSewa operation fails."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _is_test_mode():
    """Return True if ESEWA_TEST_MODE is enabled (default: True for safety)."""
    return getattr(settings, 'ESEWA_TEST_MODE', True)


def _get_secret_key():
    """Return the configured eSewa HMAC secret key, raising EsewaError if missing."""
    key = getattr(settings, 'ESEWA_SECRET_KEY', '')
    if not key:
        raise EsewaError('eSewa is not configured. Add ESEWA_SECRET_KEY to your .env file.')
    return key


def _get_merchant_code():
    """Return the configured eSewa merchant code (product_code), raising EsewaError if missing."""
    code = getattr(settings, 'ESEWA_MERCHANT_CODE', '')
    if not code:
        raise EsewaError('eSewa is not configured. Add ESEWA_MERCHANT_CODE to your .env file.')
    return code


def get_esewa_payment_url():
    """Return the V2 payment form URL based on test/production mode."""
    if _is_test_mode():
        return 'https://rc-epay.esewa.com.np/api/epay/main/v2/form'
    return 'https://epay.esewa.com.np/api/epay/main/v2/form'


def _get_verification_url():
    """Return the V2 server-to-server transaction status URL based on test/production mode."""
    if _is_test_mode():
        return 'https://rc.esewa.com.np/api/epay/transaction/status/'
    return 'https://esewa.com.np/api/epay/transaction/status/'


# ---------------------------------------------------------------------------
# HMAC-SHA256 signature
# ---------------------------------------------------------------------------

def _generate_signature(message):
    """Generate HMAC-SHA256 signature (base64-encoded) for *message*."""
    secret = _get_secret_key()
    digest = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode('utf-8')


def _build_signature_message(total_amount, transaction_uuid, product_code):
    """Build the canonical comma-joined signing message used by the eSewa V2 HMAC scheme."""
    return f'total_amount={total_amount},transaction_uuid={transaction_uuid},product_code={product_code}'


# ---------------------------------------------------------------------------
# Amount formatting
# ---------------------------------------------------------------------------

def _format_amount(amount):
    """Format *amount* for eSewa payload/signature fields.

    eSewa examples use whole numbers without a trailing ``.00`` in signed
    fields (for example ``110`` instead of ``110.00``). We keep 2-decimal
    precision internally, but trim only a terminal ``.00`` for transport.
    """
    value = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    text = format(value, 'f')
    if text.endswith('.00'):
        return text[:-3]
    return text


# ---------------------------------------------------------------------------
# Payment payload builders
# ---------------------------------------------------------------------------

def build_payment_payload(
    *,
    amount,
    transaction_uuid,
    success_url,
    failure_url,
    tax_amount='0',
    product_service_charge='0',
    product_delivery_charge='0',
):
    """Build the V2 eSewa payment form payload (dict of hidden-field values).

    The caller should POST this as a form to :func:`get_esewa_payment_url`.
    """
    product_code = _get_merchant_code()

    amt = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    tax = Decimal(str(tax_amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    psc = Decimal(str(product_service_charge)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    pdc = Decimal(str(product_delivery_charge)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = amt + tax + psc + pdc

    total_amount_str = _format_amount(total)
    uuid_str = str(transaction_uuid)

    signed_field_names = 'total_amount,transaction_uuid,product_code'
    message = _build_signature_message(total_amount_str, uuid_str, product_code)
    signature = _generate_signature(message)

    logger.info(
        'eSewa V2 payload built: transaction_uuid=%s total_amount=%s product_code=%s',
        uuid_str, total_amount_str, product_code,
    )

    return {
        'amount': _format_amount(amt),
        'tax_amount': _format_amount(tax),
        'product_service_charge': _format_amount(psc),
        'product_delivery_charge': _format_amount(pdc),
        'total_amount': total_amount_str,
        'transaction_uuid': uuid_str,
        'product_code': product_code,
        'success_url': success_url,
        'failure_url': failure_url,
        'signed_field_names': signed_field_names,
        'signature': signature,
    }


def _generate_transaction_uuid(booking_id):
    """Generate a unique transaction UUID for eSewa: ``{booking_id}-{timestamp}``.

    eSewa rejects duplicate UUIDs, so every payment attempt must have a
    fresh one — even retries for the same booking.
    """
    import time
    return f'{booking_id}-{int(time.time())}'


def build_booking_payment_payload(*, booking, success_url, failure_url):
    """Convenience wrapper for booking payments.

    Generates a unique ``transaction_uuid`` per attempt.  The caller
    **must** persist this UUID on the booking (e.g. in
    ``payment_reference``) so the success handler can verify it.
    """
    txn_uuid = _generate_transaction_uuid(booking.id)
    return build_payment_payload(
        amount=booking.total_price,
        transaction_uuid=txn_uuid,
        success_url=success_url,
        failure_url=failure_url,
    )


# ---------------------------------------------------------------------------
# Success response decoding & signature verification
# ---------------------------------------------------------------------------

def decode_success_response(encoded_data):
    """Decode the base64-encoded ``data`` query-param from the success redirect.

    Returns the decoded dict **only** if the HMAC signature is valid.
    Raises :class:`EsewaError` otherwise.
    """
    if not encoded_data:
        raise EsewaError('Missing eSewa response data.')

    try:
        decoded_bytes = base64.b64decode(encoded_data)
        response_data = json.loads(decoded_bytes.decode('utf-8'))
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error('Failed to decode eSewa success response: %s', exc)
        raise EsewaError('Invalid eSewa response data.') from exc

    logger.info('eSewa success response decoded: %s', response_data)

    # Rebuild the expected signature from the signed fields
    signed_field_names = response_data.get('signed_field_names', '')
    response_signature = response_data.get('signature', '')

    if not signed_field_names or not response_signature:
        raise EsewaError('eSewa response missing signature fields.')

    parts = [
        f'{field}={response_data.get(field, "")}'
        for field in signed_field_names.split(',')
    ]
    expected_signature = _generate_signature(','.join(parts))

    if not hmac.compare_digest(response_signature, expected_signature):
        logger.warning(
            'eSewa signature mismatch: expected=%s got=%s',
            expected_signature, response_signature,
        )
        raise EsewaError('eSewa response signature verification failed.')

    return response_data


# ---------------------------------------------------------------------------
# Server-to-server transaction verification
# ---------------------------------------------------------------------------

def verify_payment(*, total_amount, transaction_uuid, product_code=None):
    """Call eSewa's transaction status API (GET, JSON response).

    Returns the parsed JSON dict.  Raises :class:`EsewaError` on failure.
    """
    if product_code is None:
        product_code = _get_merchant_code()

    verify_url = _get_verification_url()
    total_amount_str = _format_amount(total_amount)

    params = urlencode({
        'product_code': product_code,
        'total_amount': total_amount_str,
        'transaction_uuid': str(transaction_uuid),
    })
    full_url = f'{verify_url}?{params}'

    logger.info(
        'eSewa verification request: transaction_uuid=%s total_amount=%s',
        transaction_uuid, total_amount_str,
    )

    request = Request(url=full_url, method='GET')

    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode('utf-8', errors='replace')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        logger.error('eSewa verification HTTP %s: %s', exc.code, body)
        raise EsewaError('eSewa verification request failed.') from exc
    except URLError as exc:
        logger.error('eSewa verification network error: %s', exc)
        raise EsewaError('Unable to reach eSewa right now. Please try again.') from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error('eSewa verification response not JSON: %s', body)
        raise EsewaError('Invalid response from eSewa verification.') from exc

    logger.info('eSewa verification result: %s', result)
    return result


def is_payment_complete(verification_result):
    """Return ``True`` if the verification JSON says ``COMPLETE``."""
    return (verification_result or {}).get('status') == 'COMPLETE'


# ---------------------------------------------------------------------------
# High-level: full success-callback processing
# ---------------------------------------------------------------------------

def process_success_callback(encoded_data, *, expected_total_amount, expected_transaction_uuid):
    """Decode, verify signature, validate amounts, and server-verify.

    Returns ``(response_data, verification_result)`` on success.
    Raises :class:`EsewaError` on any failure.
    """
    # 1. Decode base64 + verify HMAC signature
    response_data = decode_success_response(encoded_data)

    # 2. Check eSewa-reported status
    status = response_data.get('status', '')
    if status != 'COMPLETE':
        raise EsewaError(f'eSewa payment status is "{status}", expected COMPLETE.')

    # 3. Validate transaction_uuid
    response_uuid = str(response_data.get('transaction_uuid', ''))
    expected_uuid = str(expected_transaction_uuid)
    if response_uuid != expected_uuid:
        raise EsewaError(
            f'Transaction UUID mismatch: expected {expected_uuid}, got {response_uuid}.',
        )

    # 4. Validate total amount
    response_amount = Decimal(str(response_data.get('total_amount', '0'))).quantize(Decimal('0.01'))
    expected_amount = Decimal(str(expected_total_amount)).quantize(Decimal('0.01'))
    if response_amount != expected_amount:
        raise EsewaError(
            f'Amount mismatch: expected {expected_amount}, got {response_amount}.',
        )

    # 5. Server-to-server verification
    verification_result = verify_payment(
        total_amount=expected_amount,
        transaction_uuid=expected_uuid,
    )

    if not is_payment_complete(verification_result):
        raise EsewaError(
            f'eSewa server verification status: {verification_result.get("status", "UNKNOWN")}.',
        )

    transaction_code = response_data.get('transaction_code', '')
    ref_id = verification_result.get('ref_id', '')
    logger.info(
        'eSewa payment fully verified: uuid=%s code=%s ref_id=%s',
        expected_uuid, transaction_code, ref_id,
    )

    return response_data, verification_result
