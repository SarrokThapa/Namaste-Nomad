"""OTP generation, session storage, and verification for registration flow."""

import random
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

OTP_EXPIRY_MINUTES = 5

_SESSION_OTP_CODE = '_reg_otp_code'
_SESSION_OTP_EXPIRES = '_reg_otp_expires'
_SESSION_REG_DATA = '_registration_data'


def generate_otp():
    """Generate a random 6-digit OTP code."""
    return str(random.randint(100000, 999999))


def store_otp(request, otp_code):
    """Store OTP code and expiry timestamp in the session."""
    expires = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    request.session[_SESSION_OTP_CODE] = otp_code
    request.session[_SESSION_OTP_EXPIRES] = expires.isoformat()
    request.session.modified = True


def verify_otp(request, submitted_code):
    """Verify submitted OTP against session-stored OTP.

    Returns:
        'valid'   - code matches and is within expiry window.
        'expired' - code was correct but has expired.
        'invalid' - code is wrong or no OTP is stored.
    """
    stored_code = request.session.get(_SESSION_OTP_CODE)
    stored_expires = request.session.get(_SESSION_OTP_EXPIRES)

    if not stored_code or not stored_expires:
        return 'invalid'

    expires_at = parse_datetime(stored_expires)
    if expires_at is None:
        return 'invalid'

    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at)

    submitted_code = (submitted_code or '').strip()

    # Check code match first to differentiate expired vs invalid
    if submitted_code != stored_code:
        return 'invalid'

    if timezone.now() > expires_at:
        return 'expired'

    # Valid - clear OTP from session (single use)
    request.session.pop(_SESSION_OTP_CODE, None)
    request.session.pop(_SESSION_OTP_EXPIRES, None)
    request.session.modified = True
    return 'valid'


def store_registration_data(request, data):
    """Store registration form data in session."""
    request.session[_SESSION_REG_DATA] = data
    request.session.modified = True


def get_registration_data(request):
    """Retrieve stored registration data from session."""
    return request.session.get(_SESSION_REG_DATA)


def clear_registration_session(request):
    """Remove all registration-related data from session."""
    request.session.pop(_SESSION_OTP_CODE, None)
    request.session.pop(_SESSION_OTP_EXPIRES, None)
    request.session.pop(_SESSION_REG_DATA, None)
    request.session.pop('user_id', None)  # legacy key
    request.session.modified = True
