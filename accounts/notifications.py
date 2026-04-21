"""Notification creation, deep-linking, and websocket fan-out helpers.

Owns the small utility layer that:
- maps a Notification record to its in-app deep link (``notification_link``),
- serializes a Notification for the JSON dropdown / websocket payload,
- creates a Notification and immediately broadcasts it via Channels,
- fans out a single message to every admin user (``notify_admins``).
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Notification, User

logger = logging.getLogger(__name__)


def notification_link(notification):
    """Return the in-app URL the notification dropdown / list should link to."""
    notif_type = notification.type
    related_id = notification.related_object_id
    user_type = notification.user.user_type

    if notif_type in {'community_post', 'like', 'comment'}:
        if related_id:
            return f"{reverse('community_feed')}#post-{related_id}"
        return reverse('community_feed')

    if notif_type == 'booking':
        if user_type == 'vendor':
            return reverse('vendor_bookings')
        if user_type == 'traveler':
            return reverse('traveler_bookings')
        return f"{reverse('admin_dashboard')}#bookings"

    if notif_type == 'vendor_approval':
        return reverse('vendor_dashboard')

    if notif_type == 'package_approved':
        return reverse('vendor_packages')

    if notif_type == 'admin_message':
        return reverse('support_chat')

    if notif_type == 'support_message':
        if related_id:
            return reverse('admin_support_chat', kwargs={'conversation_id': related_id})
        return reverse('admin_support_inbox')

    if notif_type == 'package_submission':
        return f"{reverse('admin_dashboard')}#packages"

    if notif_type == 'user_registration':
        return f"{reverse('admin_dashboard')}#users"

    if notif_type == 'subscription':
        if user_type == 'vendor':
            return reverse('vendor_settings')
        return reverse('admin_subscriptions')

    return reverse('home')


def serialize_notification(notification):
    """Render a Notification as a JSON-friendly dict for the dropdown / websocket payload."""
    return {
        'id': notification.id,
        'message': notification.message,
        'type': notification.type,
        'is_read': notification.is_read,
        'created_at': notification.created_at.strftime('%b %d, %Y %H:%M'),
        'link': notification_link(notification),
    }


def create_notification(user, message, notif_type, related_object_id=None):
    """Persist a Notification and immediately fan it out over the websocket."""
    notification = Notification.objects.create(
        user=user,
        message=message,
        type=notif_type,
        related_object_id=related_object_id,
    )
    send_notification(notification)
    return notification


def notify_admins(message, notif_type, related_object_id=None):
    """Send a notification to every staff admin user."""
    admins = User.objects.filter(user_type='admin', is_staff=True)
    for admin in admins:
        create_notification(admin, message, notif_type, related_object_id=related_object_id)


def send_notification(notification):
    """Push a notification payload to the user's Channels group; logs and swallows errors."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    payload = serialize_notification(notification)
    try:
        async_to_sync(channel_layer.group_send)(
            f'notifications_{notification.user_id}',
            {
                'type': 'notification.message',
                'payload': payload,
            }
        )
    except Exception as exc:
        logger.warning(
            "Notification delivery failed for user %s: %s",
            notification.user_id,
            exc,
        )
