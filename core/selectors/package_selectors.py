from django.db.models import Avg, Count

from core.models import Package, Wishlist


def public_package_queryset():
    # get public packages with rating and booking summary fields
    return (
        Package.objects.filter(is_active=True)
        .select_related('vendor', 'vendor__vendor_profile')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
            booking_count=Count('bookings', distinct=True),
        )
        .order_by('-created_at')
    )


def wishlist_ids_for_user(user):
    # get package ids already saved by logged-in traveler
    if not getattr(user, 'is_authenticated', False):
        return set()
    if getattr(user, 'user_type', '') != 'traveler':
        return set()
    return set(Wishlist.objects.filter(traveler=user).values_list('package_id', flat=True))
