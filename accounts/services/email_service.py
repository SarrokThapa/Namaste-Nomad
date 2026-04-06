"""Email sending service for Namaste Nomad platform."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _base_context():
    """Return context variables shared by all email templates."""
    return {
        'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
    }


def _send_html_email(subject, template_name, context, recipient_email):
    """Send an HTML email with a plain-text fallback."""
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        logger.error('Email not sent to %s: SMTP credentials missing.', recipient_email)
        return False

    full_context = {**_base_context(), **context}

    try:
        html_message = render_to_string(template_name, full_context)
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Email sending failed for %s (subject: %s)', recipient_email, subject)
        return False


def send_otp_email(email, otp_code):
    """Send OTP verification email."""
    return _send_html_email(
        subject='Namaste Nomad - Your Verification Code',
        template_name='emails/otp_email.html',
        context={'otp_code': otp_code, 'expiry_minutes': 5},
        recipient_email=email,
    )


def send_traveler_welcome(user):
    """Send welcome email to a newly registered traveler."""
    return _send_html_email(
        subject='Welcome to Namaste Nomad! Your Adventure Begins',
        template_name='emails/traveler_welcome.html',
        context={'user': user},
        recipient_email=user.email,
    )


def send_vendor_under_review(user):
    """Send account-under-review email to a newly registered vendor."""
    return _send_html_email(
        subject='Namaste Nomad - Account Under Review',
        template_name='emails/vendor_under_review.html',
        context={'user': user},
        recipient_email=user.email,
    )


def send_vendor_approved(user):
    """Send approval congratulations email to a vendor."""
    return _send_html_email(
        subject='Namaste Nomad - Your Vendor Account is Approved!',
        template_name='emails/vendor_approved.html',
        context={'user': user},
        recipient_email=user.email,
    )


def send_vendor_rejected(user):
    """Send polite rejection email to a vendor."""
    return _send_html_email(
        subject='Namaste Nomad - Vendor Application Update',
        template_name='emails/vendor_rejected.html',
        context={'user': user},
        recipient_email=user.email,
    )


def send_password_reset_otp(email, otp_code):
    """Send a password reset OTP email."""
    return _send_html_email(
        subject='Namaste Nomad - Password Reset Code',
        template_name='emails/password_reset_code.html',
        context={'otp_code': otp_code, 'expiry_minutes': 10},
        recipient_email=email,
    )


def send_password_changed_confirmation(user):
    """Send a confirmation email after a successful password reset."""
    from django.utils import timezone
    changed_at = timezone.localtime(timezone.now()).strftime('%B %d, %Y at %I:%M %p')
    return _send_html_email(
        subject='Namaste Nomad - Password Changed Successfully',
        template_name='emails/password_changed.html',
        context={'user': user, 'changed_at': changed_at},
        recipient_email=user.email,
    )
