"""Notification and support-message service helpers.

Bundles the booking-related notification side-effects (vendor + admin
pings on booking creation and payment, plus the auto-generated vendor
"thank you" support message). Re-exports its names through ``__all__``
so payment_views.py can pull the whole bundle.
"""

from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import create_notification, notify_admins

from ..models import Booking, SupportConversation, SupportMessage


def _notify_booking_created(booking):
    """Ping the vendor and the admin team that a new booking has been created."""
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
    """Ping the vendor and the admin team that a booking has been paid for."""
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
    """Return the user's most recent OPEN support conversation, creating one if missing."""
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
    """Return a friendly display name for the vendor used in the auto-generated message."""
    if vendor is None:
        return 'Vendor Team'
    full_name = vendor.get_full_name().strip()
    if full_name:
        return full_name
    return vendor.username or vendor.email or 'Vendor Team'


def _send_post_booking_vendor_message(booking):
    """Auto-post a vendor "thank you" support message to the traveler after a paid booking."""
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

__all__ = [
    'timezone',
    'Notification',
    'create_notification',
    'notify_admins',
    'Booking',
    'SupportConversation',
    'SupportMessage',
    '_notify_booking_created',
    '_notify_booking_paid',
    '_get_or_create_open_support_conversation_for_user',
    '_vendor_display_for_auto_message',
    '_send_post_booking_vendor_message',
]
