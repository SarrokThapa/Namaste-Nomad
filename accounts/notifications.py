import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Notification, User

logger = logging.getLogger(__name__)


def notification_link(notification):
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

    return reverse('home')


def serialize_notification(notification):
    return {
        'id': notification.id,
        'message': notification.message,
        'type': notification.type,
        'is_read': notification.is_read,
        'created_at': notification.created_at.strftime('%b %d, %Y %H:%M'),
        'link': notification_link(notification),
    }


def create_notification(user, message, notif_type, related_object_id=None):
    notification = Notification.objects.create(
        user=user,
        message=message,
        type=notif_type,
        related_object_id=related_object_id,
    )
    send_notification(notification)
    return notification


def notify_admins(message, notif_type, related_object_id=None):
    admins = User.objects.filter(user_type='admin', is_staff=True)
    for admin in admins:
        create_notification(admin, message, notif_type, related_object_id=related_object_id)


def send_notification(notification):
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
