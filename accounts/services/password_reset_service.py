"""Password reset OTP service — DB-backed for cross-session security."""

import random
from datetime import timedelta

from django.contrib.auth.hashers import check_password as django_check_password, make_password
from django.utils import timezone
from django.utils.dateparse import parse_datetime

PR_OTP_EXPIRY_MINUTES = 10
PR_MAX_ATTEMPTS = 5
PR_BLOCK_MINUTES = 15
PR_RATE_LIMIT_PER_HOUR = 3
PR_RESEND_COOLDOWN_SECONDS = 60

# Session keys
PR_SESSION_EMAIL = '_pw_reset_email'
PR_SESSION_OTP_ID = '_pw_reset_otp_id'
PR_SESSION_VERIFIED = '_pw_reset_verified'
PR_SESSION_RESEND_AT = '_pw_reset_resend_at'


def _get_model():
    from ..models import PasswordResetOTP
    return PasswordResetOTP


def is_rate_limited(email: str) -> bool:
    """Return True if this email has hit the hourly request cap."""
    PasswordResetOTP = _get_model()
    one_hour_ago = timezone.now() - timedelta(hours=1)
    return (
        PasswordResetOTP.objects.filter(email=email, created_at__gte=one_hour_ago).count()
        >= PR_RATE_LIMIT_PER_HOUR
    )


def create_reset_otp(email: str):
    """Create and persist a new password reset OTP for the given email.

    Invalidates any previous unused OTPs for this email first.
    Returns (PasswordResetOTP instance, plain otp_code string).
    """
    PasswordResetOTP = _get_model()
    PasswordResetOTP.objects.filter(email=email, is_used=False).update(is_used=True)

    otp_code = str(random.randint(100000, 999999))
    otp_hash = make_password(otp_code)
    expires_at = timezone.now() + timedelta(minutes=PR_OTP_EXPIRY_MINUTES)

    otp = PasswordResetOTP.objects.create(
        email=email,
        otp_hash=otp_hash,
        expires_at=expires_at,
    )
    return otp, otp_code


def store_reset_session(request, email: str, otp_id: int):
    """Store password reset state in session with resend cooldown."""
    resend_at = (timezone.now() + timedelta(seconds=PR_RESEND_COOLDOWN_SECONDS)).isoformat()
    request.session[PR_SESSION_EMAIL] = email
    request.session[PR_SESSION_OTP_ID] = otp_id
    request.session[PR_SESSION_VERIFIED] = False
    request.session[PR_SESSION_RESEND_AT] = resend_at
    request.session.modified = True


def store_email_only_session(request, email: str):
    """Store email in session for the non-existent-email security flow (no OTP)."""
    request.session[PR_SESSION_EMAIL] = email
    request.session[PR_SESSION_VERIFIED] = False
    request.session.modified = True


def get_reset_email(request):
    return request.session.get(PR_SESSION_EMAIL)


def get_reset_otp_id(request):
    return request.session.get(PR_SESSION_OTP_ID)


def is_reset_verified(request) -> bool:
    return bool(request.session.get(PR_SESSION_VERIFIED))


def seconds_until_resend(request) -> int:
    """Return seconds remaining until resend is available (0 means can resend now)."""
    raw = request.session.get(PR_SESSION_RESEND_AT)
    if not raw:
        return 0
    dt = parse_datetime(raw)
    if dt is None:
        return 0
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    delta = (dt - timezone.now()).total_seconds()
    return max(0, int(delta))


def verify_reset_otp(request, submitted_code: str) -> str:
    """Verify a submitted OTP code against the DB record.

    Returns one of:
        'valid'   — correct and not expired
        'expired' — correct but expired
        'invalid' — wrong code
        'blocked' — too many attempts, temporarily locked
        'error'   — no OTP record found in session or DB
    """
    PasswordResetOTP = _get_model()
    otp_id = get_reset_otp_id(request)
    if not otp_id:
        return 'error'

    try:
        otp = PasswordResetOTP.objects.get(id=otp_id, is_used=False)
    except PasswordResetOTP.DoesNotExist:
        return 'error'

    # Check block first
    if otp.blocked_until and timezone.now() < otp.blocked_until:
        return 'blocked'

    # Check expiry
    if timezone.now() > otp.expires_at:
        return 'expired'

    # Check code
    if not django_check_password((submitted_code or '').strip(), otp.otp_hash):
        otp.attempts += 1
        if otp.attempts >= PR_MAX_ATTEMPTS:
            otp.blocked_until = timezone.now() + timedelta(minutes=PR_BLOCK_MINUTES)
        otp.save(update_fields=['attempts', 'blocked_until'])
        return 'invalid'

    # Valid — mark verified (OTP stays active until password is actually changed)
    otp.verified = True
    otp.save(update_fields=['verified'])
    request.session[PR_SESSION_VERIFIED] = True
    request.session.modified = True
    return 'valid'


def refresh_resend_cooldown(request, otp_id: int):
    """Update session after a resend — new otp_id and fresh cooldown."""
    resend_at = (timezone.now() + timedelta(seconds=PR_RESEND_COOLDOWN_SECONDS)).isoformat()
    request.session[PR_SESSION_OTP_ID] = otp_id
    request.session[PR_SESSION_VERIFIED] = False
    request.session[PR_SESSION_RESEND_AT] = resend_at
    request.session.modified = True


def consume_reset_otp(request):
    """Mark OTP as used after password change. Returns email on success, None on failure."""
    PasswordResetOTP = _get_model()
    otp_id = get_reset_otp_id(request)
    if not otp_id:
        return None
    try:
        otp = PasswordResetOTP.objects.get(id=otp_id, is_used=False, verified=True)
        email = otp.email
        otp.is_used = True
        otp.save(update_fields=['is_used'])
        return email
    except PasswordResetOTP.DoesNotExist:
        return None


def clear_reset_session(request):
    """Remove all password reset state from session."""
    for key in (PR_SESSION_EMAIL, PR_SESSION_OTP_ID, PR_SESSION_VERIFIED, PR_SESSION_RESEND_AT):
        request.session.pop(key, None)
    request.session.modified = True


def mask_email(email: str) -> str:
    """Return a masked email, e.g. john@gmail.com → j***@gmail.com."""
    try:
        local, domain = email.rsplit('@', 1)
        if len(local) <= 1:
            masked_local = '*'
        elif len(local) == 2:
            masked_local = local[0] + '*'
        else:
            masked_local = local[0] + '***'
        return f'{masked_local}@{domain}'
    except ValueError:
        return email
