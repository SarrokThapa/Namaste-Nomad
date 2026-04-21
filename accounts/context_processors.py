from django.core.exceptions import ObjectDoesNotExist
from django.db.models import BooleanField, OuterRef, Subquery
from django.urls import reverse

from core.models import SupportConversation, SupportMessage, Wishlist
from .models import Notification


def _safe_related(instance, relation_name):
    try:
        return getattr(instance, relation_name)
    except ObjectDoesNotExist:
        return None


def _display_name(user, user_type):
    if user_type == 'vendor':
        profile = _safe_related(user, 'vendor_profile')
        business_name = (getattr(profile, 'business_name', '') or '').strip()
        if business_name:
            return business_name

        owner_name = (getattr(profile, 'owner_name', '') or '').strip()
        if owner_name:
            return owner_name

    full_name = user.get_full_name().strip()
    if full_name:
        return full_name

    username = (getattr(user, 'username', '') or '').strip()
    if username and '@' not in username:
        return username

    if user_type == 'vendor':
        return 'Vendor'

    return user.email or 'Account'


def _avatar_url(user, user_type):
    if user_type == 'traveler':
        profile = _safe_related(user, 'traveler_profile')
        if profile and profile.avatar:
            return profile.avatar.url
    elif user_type == 'vendor':
        profile = _safe_related(user, 'vendor_profile')
        if profile and profile.logo:
            return profile.logo.url
    elif user_type == 'admin':
        profile = _safe_related(user, 'admin_profile')
        if profile and profile.avatar:
            return profile.avatar.url
    return ''


def _dashboard_url(user_type):
    if user_type == 'traveler':
        return reverse('traveler_home')
    if user_type == 'vendor':
        return reverse('vendor_dashboard')
    if user_type == 'admin':
        return reverse('admin_dashboard')
    return reverse('home')


def _profile_url(user_type):
    if user_type == 'traveler':
        return reverse('traveler_profile')
    if user_type == 'vendor':
        return reverse('vendor_profile')
    if user_type == 'admin':
        return reverse('admin_profile')
    return reverse('home')


def _settings_url(user_type):
    if user_type == 'traveler':
        return reverse('traveler_profile')
    if user_type == 'vendor':
        return reverse('vendor_settings')
    if user_type == 'admin':
        return reverse('admin_profile')
    return reverse('home')


def _navbar_context(user):
    user_type = getattr(user, 'user_type', '')
    return {
        'nav_user_type': user_type,
        'nav_display_name': _display_name(user, user_type),
        'nav_avatar_url': _avatar_url(user, user_type),
        'nav_dashboard_url': _dashboard_url(user_type),
        'nav_profile_url': _profile_url(user_type),
        'nav_settings_url': _settings_url(user_type),
    }


def support_context(request):
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return {}

    payload = _navbar_context(user)
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
            payload.update({
                'support_unread_count': 0,
                'notifications_unread_count': notification_count,
            })
            if user_type == 'traveler':
                payload['wishlist_count'] = wishlist_count
            return payload
        last_message = conversation.messages.order_by('-created_at', '-id').first()
        unread = 1 if last_message and last_message.is_admin_reply else 0
        payload.update({
            'support_unread_count': unread,
            'notifications_unread_count': notification_count,
        })
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
        payload.update({
            'support_inbox_unread_count': unread_count,
            'notifications_unread_count': notification_count,
        })
        return payload

    payload.update({
        'notifications_unread_count': notification_count,
        'wishlist_count': wishlist_count,
    })
    return payload
