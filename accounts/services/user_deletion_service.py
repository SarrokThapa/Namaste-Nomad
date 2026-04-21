"""Safe permanent user-deletion helpers."""

from django.db import transaction
from django.db.models import Q
from social_django.models import UserSocialAuth

from core.models import Booking, ContactMessage, Review, Transaction, Wishlist


def delete_user_permanently(user):
    """Delete a user and all user-owned records that should not survive.

    We explicitly remove records tied to nullable user FKs (SET_NULL) so
    package/admin templates do not render orphan rows after user deletion.
    """
    with transaction.atomic():
        # remove oauth links first so social auth never points to a deleted user
        UserSocialAuth.objects.filter(user=user).delete()

        # remove user-owned traveler/vendor content instead of leaving null owners
        Wishlist.objects.filter(traveler=user).delete()
        Review.objects.filter(traveler=user).delete()
        Booking.objects.filter(Q(traveler=user) | Q(vendor=user)).delete()
        Transaction.objects.filter(Q(traveler=user) | Q(vendor=user)).delete()
        ContactMessage.objects.filter(user=user).delete()

        # profiles and CASCADE-linked records are removed naturally from user.delete()
        user.delete()
