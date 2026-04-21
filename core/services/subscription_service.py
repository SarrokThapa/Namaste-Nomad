"""Business logic for the vendor feature subscription system."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import (
    FeaturedPackage,
    FeaturePlan,
    VendorFeatureSubscription,
)
from core.models import Package, Transaction


def expire_overdue_subscriptions(vendor=None):
    """Expire subscriptions past their end_date and deactivate their featured packages."""
    return VendorFeatureSubscription.expire_overdue(vendor=vendor)


def get_active_subscription(vendor):
    """Return the active paid subscription for this vendor, or None."""
    return VendorFeatureSubscription.active_for_vendor(vendor)


def get_available_plans():
    """Return all active feature plans ordered by price."""
    return FeaturePlan.objects.filter(is_active=True).order_by('price', 'slots_count')


def activate_subscription(*, vendor, plan, payment_method, transaction_id=''):
    """
    Activate a feature subscription after verified payment.

    If the vendor already has an active subscription, upgrade it:
    - Replace the plan details (name, slots, price)
    - Extend end_date from now + new plan duration
    - If new plan has fewer slots than currently used, trim excess featured packages
    """
    today = timezone.localdate()

    with transaction.atomic():
        expire_overdue_subscriptions(vendor=vendor)
        existing = get_active_subscription(vendor)

        if existing:
            # Upgrade: update plan details, extend from today
            existing.plan = plan
            existing.plan_name = plan.name
            existing.slots_total = plan.slots_count
            existing.price = plan.price
            existing.start_date = today
            existing.end_date = today + timedelta(days=max(plan.duration_days - 1, 0))
            existing.payment_status = VendorFeatureSubscription.PAYMENT_STATUS_PAID
            existing.payment_method = payment_method
            existing.transaction_id = transaction_id
            existing.is_active = True
            existing.save(update_fields=[
                'plan', 'plan_name', 'slots_total', 'price',
                'start_date', 'end_date',
                'payment_status', 'payment_method', 'transaction_id',
                'is_active',
            ])
            subscription = existing

            # Trim excess featured packages if downgrading slots
            _trim_featured_packages(subscription)
        else:
            subscription = VendorFeatureSubscription.objects.create(
                vendor=vendor,
                plan=plan,
                plan_name=plan.name,
                slots_total=plan.slots_count,
                price=plan.price,
                start_date=today,
                end_date=today + timedelta(days=max(plan.duration_days - 1, 0)),
                payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
                payment_method=payment_method,
                transaction_id=transaction_id,
                is_active=True,
            )

        _record_transaction(
            vendor=vendor,
            subscription=subscription,
            amount=plan.price,
            payment_method=payment_method,
            payment_status='completed',
        )

    return subscription


def _record_transaction(*, vendor, subscription, amount, payment_method, payment_status):
    """Record a transaction for a feature subscription payment."""
    return Transaction.objects.create(
        transaction_type=Transaction.TYPE_FEATURE_SUBSCRIPTION,
        booking=None,
        feature_subscription=subscription,
        traveler=None,
        vendor=vendor,
        total_amount=Decimal(str(amount)).quantize(Decimal('0.01')),
        payment_method=payment_method,
        payment_status=payment_status,
    )


def record_failed_transaction(*, vendor, amount, payment_method):
    """Record a failed payment attempt."""
    from core.models import Booking
    return Transaction.objects.create(
        transaction_type=Transaction.TYPE_FEATURE_SUBSCRIPTION,
        booking=None,
        feature_subscription=None,
        traveler=None,
        vendor=vendor,
        total_amount=Decimal(str(amount)).quantize(Decimal('0.01')),
        payment_method=payment_method,
        payment_status=Booking.PAYMENT_STATUS_FAILED,
    )


def feature_package(subscription, package):
    """
    Add a package to the vendor's featured slots.
    Returns (featured_package, error_message).
    """
    if package.vendor_id != subscription.vendor_id:
        return None, 'You can only feature your own packages.'

    if subscription.slots_remaining <= 0:
        return None, f'All {subscription.slots_total} featured slots are in use. Remove a package first.'

    existing = FeaturedPackage.objects.filter(
        subscription=subscription,
        package=package,
        is_active=True,
    ).first()
    if existing:
        return None, 'This package is already featured.'

    # Reactivate if previously unfeatured under same subscription
    inactive = FeaturedPackage.objects.filter(
        subscription=subscription,
        package=package,
        is_active=False,
    ).first()
    if inactive:
        inactive.is_active = True
        inactive.featured_date = timezone.now()
        inactive.save(update_fields=['is_active', 'featured_date'])
        return inactive, None

    fp = FeaturedPackage.objects.create(
        subscription=subscription,
        package=package,
        is_active=True,
    )
    return fp, None


def unfeature_package(subscription, package):
    """Remove a package from featured slots."""
    updated = FeaturedPackage.objects.filter(
        subscription=subscription,
        package=package,
        is_active=True,
    ).update(is_active=False)
    return updated > 0


def get_featured_packages_for_vendor(vendor):
    """Return active featured packages for this vendor's active subscription."""
    subscription = get_active_subscription(vendor)
    if not subscription:
        return FeaturedPackage.objects.none()
    return FeaturedPackage.objects.filter(
        subscription=subscription,
        is_active=True,
    ).select_related('package')


def get_all_featured_packages():
    """
    Return all packages that are currently featured by any vendor
    with an active subscription. Used by the homepage.
    """
    today = timezone.localdate()
    VendorFeatureSubscription.expire_overdue()
    return Package.objects.filter(
        is_active=True,
        featured_entries__is_active=True,
        featured_entries__subscription__is_active=True,
        featured_entries__subscription__payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
        featured_entries__subscription__start_date__lte=today,
        featured_entries__subscription__end_date__gte=today,
    ).distinct()


def _trim_featured_packages(subscription):
    """If slots_total < currently featured, deactivate the oldest excess."""
    active_featured = FeaturedPackage.objects.filter(
        subscription=subscription,
        is_active=True,
    ).order_by('-featured_date')

    count = active_featured.count()
    if count <= subscription.slots_total:
        return

    keep_ids = list(active_featured.values_list('id', flat=True)[:subscription.slots_total])
    FeaturedPackage.objects.filter(
        subscription=subscription,
        is_active=True,
    ).exclude(id__in=keep_ids).update(is_active=False)


def deactivate_subscription(subscription):
    """Admin manually deactivates a vendor's subscription."""
    FeaturedPackage.objects.filter(
        subscription=subscription,
        is_active=True,
    ).update(is_active=False)
    subscription.is_active = False
    subscription.save(update_fields=['is_active'])


def reactivate_subscription(subscription):
    """Admin reactivates an eligible vendor subscription."""
    today = timezone.localdate()

    if subscription.payment_status != VendorFeatureSubscription.PAYMENT_STATUS_PAID:
        return False, 'Only paid subscriptions can be activated.'

    if subscription.end_date < today:
        return False, 'This subscription is expired and cannot be activated.'

    if subscription.is_active:
        return False, 'Subscription is already active.'

    subscription.is_active = True
    subscription.save(update_fields=['is_active'])
    return True, ''
