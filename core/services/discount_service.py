"""Discount-related service helpers."""

from decimal import Decimal

from django.utils import timezone

from ..models import Discount


def _best_available_discount_for_user(user, original_total):
    """Pick the unused achievement discount that yields the largest reduction on *original_total*."""
    if not user.is_authenticated or getattr(user, 'user_type', '') != 'traveler':
        return None, Decimal('0.00')

    now = timezone.now()
    candidates = Discount.objects.filter(
        user=user,
        source=Discount.SOURCE_ACHIEVEMENT,
        is_used=False,
        expires_at__gt=now,
    )

    best_discount = None
    best_amount = Decimal('0.00')
    for candidate in candidates:
        amount = candidate.calculate_discount_amount(original_total)
        if amount > best_amount:
            best_discount = candidate
            best_amount = amount
    return best_discount, best_amount

__all__ = [
    'Decimal',
    'timezone',
    'Discount',
    '_best_available_discount_for_user',
]
