from django.db.models import BooleanField, OuterRef, Subquery

from core.models import SupportConversation, SupportMessage, Wishlist
from .models import Notification


def support_context(request):
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return {}

    user_type = getattr(user, 'user_type', '')
    notification_count = Notification.objects.filter(user=user, is_read=False).count()
    wishlist_count = 0
    if user_type == 'traveler':
        wishlist_count = Wishlist.objects.filter(traveler=user).count()
    if user_type in {'traveler', 'vendor'}:
        conversation = SupportConversation.objects.filter(
            user=user,
        ).order_by('-created_at').first()
        if not conversation:
            payload = {
                'support_unread_count': 0,
                'notifications_unread_count': notification_count,
            }
            if user_type == 'traveler':
                payload['wishlist_count'] = wishlist_count
            return payload
        last_message = conversation.messages.order_by('-created_at', '-id').first()
        unread = 1 if last_message and last_message.is_admin_reply else 0
        payload = {
            'support_unread_count': unread,
            'notifications_unread_count': notification_count,
        }
        if user_type == 'traveler':
            payload['wishlist_count'] = wishlist_count
        return payload

    if user_type == 'admin' and getattr(user, 'is_staff', False):
        last_message_qs = SupportMessage.objects.filter(
            conversation=OuterRef('pk'),
        ).order_by('-created_at', '-id')
        conversations = SupportConversation.objects.filter(
            status=SupportConversation.STATUS_OPEN,
        ).annotate(
            last_message_is_admin=Subquery(
                last_message_qs.values('is_admin_reply')[:1],
                output_field=BooleanField(),
            )
        )
        unread_count = conversations.filter(last_message_is_admin=False).count()
        return {
            'support_inbox_unread_count': unread_count,
            'notifications_unread_count': notification_count,
        }

    return {
        'notifications_unread_count': notification_count,
        'wishlist_count': wishlist_count,
    }
