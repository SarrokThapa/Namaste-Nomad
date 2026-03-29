from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from core.models import Booking, Discount, Post, Review, Wishlist
from .models import Badge, Notification, RewardPoint, UserBadge
from .notifications import create_notification


def add_points(user, action_type, points):
    if not getattr(user, 'is_authenticated', False):
        return None
    if getattr(user, 'user_type', '') != 'traveler':
        return None
    return RewardPoint.objects.create(
        user=user,
        points=points,
        action_type=action_type,
    )


def _confirmed_booking_count(user):
    return Booking.objects.filter(
        traveler=user,
        status=Booking.STATUS_CONFIRMED,
    ).count()


def _confirmed_trek_booking_count(user):
    return Booking.objects.filter(
        traveler=user,
        status=Booking.STATUS_CONFIRMED,
        package__category='TREK',
    ).count()


def _post_like_total(user):
    return (
        Post.objects.filter(user=user)
        .aggregate(total=Count('likes'))
        .get('total')
        or 0
    )


def _collect_badge_stats(user):
    return {
        Badge.CONDITION_FIRST_POST: Post.objects.filter(user=user).count(),
        Badge.CONDITION_FIRST_WISHLIST: Wishlist.objects.filter(traveler=user).count(),
        Badge.CONDITION_FIRST_BOOKING_CONFIRMED: _confirmed_booking_count(user),
        Badge.CONDITION_POST_LIKES: _post_like_total(user),
        Badge.CONDITION_FIRST_REVIEW: Review.objects.filter(traveler=user).count(),
        Badge.CONDITION_TREK_BOOKINGS_CONFIRMED: _confirmed_trek_booking_count(user),
    }


def sync_badges_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return []
    if getattr(user, 'user_type', '') != 'traveler':
        return []

    stats = _collect_badge_stats(user)

    earned_ids = set(
        UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)
    )
    newly_awarded = []
    for badge in Badge.objects.all():
        if badge.id in earned_ids:
            continue
        current_value = stats.get(badge.condition_type, 0)
        if current_value >= badge.condition_value:
            UserBadge.objects.create(user=user, badge=badge)
            newly_awarded.append(badge)

    if newly_awarded:
        expires_at = timezone.now() + timedelta(days=7)
        for _badge in newly_awarded:
            Discount.objects.create(
                user=user,
                percentage=10,
                fixed_amount=None,
                max_discount_cap=2000,
                expires_at=expires_at,
                source=Discount.SOURCE_ACHIEVEMENT,
            )
        create_notification(
            user,
            'You unlocked a discount!',
            Notification.TYPE_BOOKING,
        )
    return newly_awarded


def total_points_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return 0
    if getattr(user, 'user_type', '') != 'traveler':
        return 0
    return (
        RewardPoint.objects.filter(user=user)
        .aggregate(total=Sum('points'))
        .get('total')
        or 0
    )


def discount_for_points(points):
    if points >= 500:
        return 15, None
    if points >= 200:
        return 10, 500
    if points >= 100:
        return 5, 200
    return 0, 100


def badge_progress_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return [], {}, None
    if getattr(user, 'user_type', '') != 'traveler':
        return [], {}, None

    stats = _collect_badge_stats(user)
    earned_map = {
        entry.badge_id: entry
        for entry in UserBadge.objects.filter(user=user).select_related('badge')
    }
    badges = list(Badge.objects.all())

    def progress_label(badge, current):
        mapping = {
            Badge.CONDITION_FIRST_POST: 'Community posts',
            Badge.CONDITION_FIRST_WISHLIST: 'Wishlist saves',
            Badge.CONDITION_FIRST_BOOKING_CONFIRMED: 'Confirmed bookings',
            Badge.CONDITION_POST_LIKES: 'Likes received',
            Badge.CONDITION_FIRST_REVIEW: 'Reviews written',
            Badge.CONDITION_TREK_BOOKINGS_CONFIRMED: 'Confirmed treks',
        }
        label = mapping.get(badge.condition_type, 'Progress')
        return f"{label}: {current} / {badge.condition_value}"

    next_badge = None
    best_progress = -1
    for badge in badges:
        current = stats.get(badge.condition_type, 0)
        earned_entry = earned_map.get(badge.id)
        badge.earned = earned_entry is not None
        badge.earned_at = earned_entry.earned_at if earned_entry else None
        badge.progress_current = current
        badge.progress_total = badge.condition_value
        badge.progress_pct = min(int((current / badge.condition_value) * 100), 100) if badge.condition_value else 0
        badge.progress_label = progress_label(badge, min(current, badge.condition_value))
        if not badge.earned:
            if badge.progress_pct > best_progress:
                best_progress = badge.progress_pct
                next_badge = badge
    summary = {
        'earned_count': len(earned_map),
        'total_badges': len(badges),
    }
    return badges, summary, next_badge
