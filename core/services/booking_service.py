"""Booking lifecycle service helpers."""

from decimal import Decimal

from django.db.models import F
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import create_notification

from ..models import Booking, Discount, Package, Transaction
from .notification_service import _send_post_booking_vendor_message


def _expire_stale_pending_bookings(package_id=None):
    stale_bookings = Booking.objects.select_for_update().filter(
        status=Booking.STATUS_PENDING,
        payment_status__in=[
            Booking.PAYMENT_STATUS_PENDING,
            Booking.PAYMENT_STATUS_FAILED,
        ],
        payment_expires_at__isnull=False,
        payment_expires_at__lt=timezone.now(),
    )
    if package_id is not None:
        stale_bookings = stale_bookings.filter(package_id=package_id)

    for stale_booking in stale_bookings:
        Package.objects.filter(id=stale_booking.package_id).update(
            available_slots=F('available_slots') + stale_booking.number_of_people,
        )
        stale_booking.status = Booking.STATUS_CANCELLED
        stale_booking.payment_status = Booking.PAYMENT_STATUS_FAILED
        stale_booking.payment_expires_at = None
        stale_booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _cancel_unpaid_booking(booking, payment_status):
    if (
        booking.status == Booking.STATUS_PENDING
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        Package.objects.filter(id=booking.package_id).update(
            available_slots=F('available_slots') + booking.number_of_people,
        )
    booking.status = Booking.STATUS_CANCELLED
    booking.payment_status = payment_status
    booking.payment_expires_at = None
    booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _complete_paid_booking(
    booking,
    *,
    payment_reference='',
    stripe_checkout_session_id='',
    esewa_transaction_id='',
    paid_amount=None,
):
    booking.status = Booking.STATUS_CONFIRMED
    booking.payment_status = Booking.PAYMENT_STATUS_COMPLETED
    if payment_reference:
        booking.payment_reference = payment_reference
    if stripe_checkout_session_id:
        booking.stripe_checkout_session_id = stripe_checkout_session_id
    if esewa_transaction_id:
        booking.esewa_transaction_id = esewa_transaction_id
    if paid_amount is not None:
        booking.paid_amount = paid_amount
    elif booking.paid_amount is None:
        booking.paid_amount = booking.total_price
    if not booking.paid_at:
        booking.paid_at = timezone.now()
    booking.payment_expires_at = None
    discount_used = None
    discount_used_amount = Decimal('0.00')
    if booking.discount_id:
        discount = (
            Discount.objects.select_for_update()
            .filter(id=booking.discount_id, user_id=booking.traveler_id)
            .first()
        )
        if discount and discount.is_valid():
            discount.is_used = True
            discount.used_at = timezone.now()
            discount.save(update_fields=['is_used', 'used_at'])
            discount_used = discount
            discount_used_amount = booking.discount_amount or Decimal('0.00')

    booking.save(
        update_fields=[
            'status',
            'payment_status',
            'payment_reference',
            'stripe_checkout_session_id',
            'esewa_transaction_id',
            'paid_amount',
            'paid_at',
            'payment_expires_at',
        ]
    )
    Transaction.objects.update_or_create(
        booking=booking,
        defaults={
            'transaction_type': Transaction.TYPE_BOOKING,
            'vendor_subscription': None,
            'traveler': booking.traveler,
            'vendor': booking.vendor,
            'total_amount': booking.paid_amount or booking.total_price,
            'payment_method': booking.payment_method,
            'payment_status': booking.payment_status,
        },
    )

    if discount_used and booking.traveler:
        create_notification(
            booking.traveler,
            f'Your discount of Rs {discount_used_amount:.0f} was applied to booking #{booking.id}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    if discount_used and booking.vendor:
        create_notification(
            booking.vendor,
            'A booking used discount on your package.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    _send_post_booking_vendor_message(booking)

__all__ = [
    'Decimal',
    'F',
    'timezone',
    'Notification',
    'create_notification',
    'Booking',
    'Discount',
    'Package',
    'Transaction',
    '_send_post_booking_vendor_message',
    '_expire_stale_pending_bookings',
    '_cancel_unpaid_booking',
    '_complete_paid_booking',
]
