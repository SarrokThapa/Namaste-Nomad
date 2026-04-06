"""Booking lifecycle service helpers."""

import re
from decimal import Decimal

from django.db.models import F
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import create_notification

from ..models import Booking, BookingTraveler, Discount, Package, Transaction
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

def _parse_traveler_post_data(post, number_of_people):
    """
    Parse traveler detail fields from POST data.
    Returns (travelers_data: list[dict], errors: dict[int, dict[str, str]]).
    """
    _email_re = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    travelers_data = []
    errors = {}

    for i in range(number_of_people):
        prefix = f't_{i}_'
        is_primary = (i == 0)

        full_name = (post.get(f'{prefix}full_name') or '').strip()
        age_str = (post.get(f'{prefix}age') or '').strip()
        gender = (post.get(f'{prefix}gender') or '').strip()
        phone_number = (post.get(f'{prefix}phone_number') or '').strip()
        email = (post.get(f'{prefix}email') or '').strip()
        nationality = (post.get(f'{prefix}nationality') or 'Nepali').strip()
        id_type = (post.get(f'{prefix}id_type') or '').strip()
        id_number = (post.get(f'{prefix}id_number') or '').strip()
        medical_notes = (post.get(f'{prefix}medical_notes') or '').strip()
        emergency_contact_name = (post.get(f'{prefix}emergency_contact_name') or '').strip()
        emergency_contact_phone = (post.get(f'{prefix}emergency_contact_phone') or '').strip()

        traveler_errors = {}

        if not full_name:
            traveler_errors['full_name'] = 'Full name is required.'

        age = None
        if not age_str:
            traveler_errors['age'] = 'Age is required.'
        else:
            try:
                age = int(age_str)
                if age < 1 or age > 120:
                    traveler_errors['age'] = 'Please enter a valid age (1–120).'
            except (TypeError, ValueError):
                traveler_errors['age'] = 'Age must be a whole number.'

        if not id_number:
            traveler_errors['id_number'] = 'ID number is required.'

        if is_primary:
            if not phone_number:
                traveler_errors['phone_number'] = 'Phone number is required for the primary traveler.'
            if not email:
                traveler_errors['email'] = 'Email is required for the primary traveler.'
            elif not _email_re.match(email):
                traveler_errors['email'] = 'Please enter a valid email address.'
            if not emergency_contact_name:
                traveler_errors['emergency_contact_name'] = 'Emergency contact name is required.'
            if not emergency_contact_phone:
                traveler_errors['emergency_contact_phone'] = 'Emergency contact phone is required.'
        elif email and not _email_re.match(email):
            traveler_errors['email'] = 'Please enter a valid email address.'

        if traveler_errors:
            errors[i] = traveler_errors

        travelers_data.append({
            'full_name': full_name,
            'age': age if age is not None else 0,
            'gender': gender,
            'phone_number': phone_number,
            'email': email,
            'nationality': nationality,
            'id_type': id_type,
            'id_number': id_number,
            'medical_notes': medical_notes,
            'emergency_contact_name': emergency_contact_name,
            'emergency_contact_phone': emergency_contact_phone,
        })

    return travelers_data, errors


def save_booking_travelers(booking, travelers_data):
    """
    Atomically replace all BookingTraveler records for this booking.
    travelers_data: list of dicts (index 0 = primary traveler).
    """
    BookingTraveler.objects.filter(booking=booking).delete()
    for i, data in enumerate(travelers_data):
        BookingTraveler.objects.create(
            booking=booking,
            traveler_index=i,
            full_name=data.get('full_name', ''),
            age=data.get('age') or 0,
            gender=data.get('gender', ''),
            phone_number=data.get('phone_number', ''),
            email=data.get('email', ''),
            nationality=data.get('nationality') or 'Nepali',
            id_type=data.get('id_type', ''),
            id_number=data.get('id_number', ''),
            medical_notes=data.get('medical_notes', ''),
            emergency_contact_name=data.get('emergency_contact_name', ''),
            emergency_contact_phone=data.get('emergency_contact_phone', ''),
        )


__all__ = [
    're',
    'Decimal',
    'F',
    'timezone',
    'Notification',
    'create_notification',
    'Booking',
    'BookingTraveler',
    'Discount',
    'Package',
    'Transaction',
    '_send_post_booking_vendor_message',
    '_expire_stale_pending_bookings',
    '_cancel_unpaid_booking',
    '_complete_paid_booking',
    '_parse_traveler_post_data',
    'save_booking_travelers',
]
