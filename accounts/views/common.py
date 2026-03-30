"""Shared accounts view helpers and dependencies."""

from calendar import monthrange

from collections import defaultdict

import csv

from datetime import date, timedelta

from decimal import Decimal, InvalidOperation

from functools import wraps

from pathlib import Path

import uuid

from django.conf import settings

from django.contrib import messages

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash

from django.contrib.auth.decorators import login_required

from django.core.files.images import get_image_dimensions

from django.db import IntegrityError, transaction

from django.db.models import (
    Avg,
    BooleanField,
    Case,
    CharField,
    Count,
    DateTimeField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    TextField,
    Value,
    When,
)

from django.http import HttpResponse, JsonResponse

from django.shortcuts import get_object_or_404, redirect, render

from django.urls import reverse

from django.utils.http import url_has_allowed_host_and_scheme

from django.utils import timezone

from django.utils.timesince import timesince

from django.views.decorators.cache import never_cache

from django.views.decorators.csrf import csrf_protect

from django.views.decorators.http import require_POST

from core.models import (
    Booking,
    Package,
    SpecialOffer,
    Review,
    PackageImage,
    SupportConversation,
    SupportMessage,
    Transaction,
    Wishlist,
)

from core.payments import (
    EsewaError,
    StripeError,
    create_checkout_session_for_item,
    get_esewa_payment_url,
    retrieve_checkout_session,
    verify_esewa_payment,
)

from ..models import (
    AdminProfile,
    FeatureSlot,
    Notification,
    Badge,
    UserBadge,
    TravelerProfile,
    User,
    VendorFeature,
    VendorProfile,
    VendorSubscription,
    VendorSubscriptionPlan,
)

from ..forms import PackageForm, VendorProfileForm

from ..notifications import (
    create_notification,
    notify_admins,
    notification_link,
    serialize_notification,
)

from ..utils import create_otp, verify_otp as verify_otp_util

from ..achievements import (
    add_points,
    sync_badges_for_user,
    total_points_for_user,
    badge_progress_for_user,
)

TRAVELER_CATEGORY_LABELS = {
    'adventure': 'Adventure',
    'cultural': 'Cultural',
    'trekking': 'Trekking',
}

TRAVELER_CATEGORY_SLUGS = tuple(TRAVELER_CATEGORY_LABELS.keys())

def _get_vendor_profile(user):
    try:
        return user.vendor_profile
    except VendorProfile.DoesNotExist:
        return None


def _get_admin_profile(user):
    try:
        return user.admin_profile
    except AdminProfile.DoesNotExist:
        return None


def _get_traveler_profile(user):
    try:
        return user.traveler_profile
    except TravelerProfile.DoesNotExist:
        return None


def _get_active_subscription(vendor):
    return VendorSubscription.active_for_vendor(vendor)


def _sync_active_special_offers_for_user(user):
    if not user or not user.is_active:
        return 0

    today = timezone.localdate()
    offers = SpecialOffer.objects.filter(is_active=True).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    )

    created_count = 0
    for offer in offers:
        message_text = f'Special offer available: {offer.title}'
        exists = Notification.objects.filter(
            user=user,
            type=Notification.TYPE_PROMOTION,
            message=message_text,
            related_object_id=offer.id,
        ).exists()
        if not exists:
            create_notification(
                user,
                message_text,
                Notification.TYPE_PROMOTION,
                related_object_id=offer.id,
            )
            created_count += 1
    return created_count


def _notify_opted_in_travelers_for_limited_package_offer(package):
    if package is None:
        return 0

    travelers = User.objects.filter(
        user_type='traveler',
        is_active=True,
        wants_promotions=True,
    )
    notified = 0
    for traveler in travelers:
        create_notification(
            traveler,
            f'Limited-time package offer: {package.title}',
            Notification.TYPE_PROMOTION,
            related_object_id=package.id,
        )
        notified += 1
    return notified


def _delete_stored_file(instance, field_name, file_name):
    if not file_name:
        return
    storage = instance._meta.get_field(field_name).storage
    if storage.exists(file_name):
        storage.delete(file_name)


def _is_valid_uploaded_image(uploaded_file):
    if uploaded_file is None:
        return False
    try:
        get_image_dimensions(uploaded_file)
        uploaded_file.seek(0)
    except Exception:
        return False
    return True


def _ensure_vendor(request):
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile and not vendor_profile.is_approved:
        messages.error(request, 'Your account is pending admin approval.')
        return False
    return True


def _ensure_vendor_account(request):
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    return True


def _ensure_traveler(request):
    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return False
    return True


def _safe_next_url(request, fallback_name):
    candidate = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(fallback_name)


def _subscription_esewa_payload(*, amount, pid, success_url, failure_url):
    merchant_code = getattr(settings, 'ESEWA_MERCHANT_CODE', '')
    if not merchant_code:
        raise EsewaError('eSewa is not configured. Add ESEWA_MERCHANT_CODE to your .env file or environment.')

    amount_str = format(Decimal(str(amount)).quantize(Decimal('0.01')), 'f')
    return {
        'amt': amount_str,
        'pdc': '0',
        'psc': '0',
        'txAmt': '0',
        'tAmt': amount_str,
        'pid': pid,
        'scd': merchant_code,
        'su': success_url,
        'fu': failure_url,
    }


def _subscription_payment_session_key(vendor_id):
    return f'subscription_payment_{vendor_id}'


def _feature_slot_payment_session_key(vendor_id):
    return f'feature_slot_payment_{vendor_id}'


def _record_subscription_transaction(*, vendor, subscription, amount, payment_status, payment_method):
    return Transaction.objects.create(
        transaction_type=Transaction.TYPE_SUBSCRIPTION,
        booking=None,
        vendor_subscription=subscription,
        traveler=None,
        vendor=vendor,
        total_amount=Decimal(str(amount)).quantize(Decimal('0.01')),
        payment_method=payment_method,
        payment_status=payment_status,
    )


def _record_feature_slot_transaction(*, vendor, vendor_feature, amount, payment_status, payment_method):
    return Transaction.objects.create(
        transaction_type=Transaction.TYPE_FEATURE_SLOT,
        booking=None,
        vendor_subscription=None,
        vendor_feature=vendor_feature,
        traveler=None,
        vendor=vendor,
        total_amount=Decimal(str(amount)).quantize(Decimal('0.01')),
        payment_method=payment_method,
        payment_status=payment_status,
    )


def _total_active_feature_slots_for_vendor(vendor):
    return VendorFeature.total_slots_for_vendor(vendor)


def _total_featured_packages_for_vendor(vendor):
    return Package.objects.filter(vendor=vendor, is_featured=True).count()


def _total_homepage_feature_capacity():
    return FeatureSlot.active_total_capacity()


def _total_homepage_featured_count():
    return Package.objects.filter(is_active=True, is_featured=True).count()


def _activate_feature_slots_after_verified_payment(*, vendor, slot, purchased_slots, amount, payment_method):
    today = timezone.localdate()
    end_date = today + timedelta(days=29)
    with transaction.atomic():
        vendor_feature = VendorFeature.objects.create(
            vendor=vendor,
            slot=slot,
            package=None,
            purchased_slots=max(int(purchased_slots or 0), 1),
            start_date=today,
            end_date=end_date,
            is_active=True,
        )
        _record_feature_slot_transaction(
            vendor=vendor,
            vendor_feature=vendor_feature,
            amount=amount,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            payment_method=payment_method,
        )
    return vendor_feature


def _activate_subscription_after_verified_payment(*, vendor, plan, amount, payment_method):
    with transaction.atomic():
        VendorSubscription.expire_overdue(vendor=vendor)
        active_subscription = VendorSubscription.active_for_vendor(vendor)
        today = timezone.localdate()

        if active_subscription and active_subscription.status == VendorSubscription.STATUS_ACTIVE:
            base_end = active_subscription.end_date if active_subscription.end_date >= today else today - timedelta(days=1)
            active_subscription.plan = plan
            active_subscription.plan_name = plan.name
            active_subscription.price = plan.price
            active_subscription.duration_days = plan.duration_days
            active_subscription.max_featured_packages = plan.max_featured_packages
            active_subscription.start_date = min(active_subscription.start_date, today)
            active_subscription.end_date = base_end + timedelta(days=max(plan.duration_days, 1))
            active_subscription.status = VendorSubscription.STATUS_ACTIVE
            active_subscription.save(
                update_fields=[
                    'plan',
                    'plan_name',
                    'price',
                    'duration_days',
                    'max_featured_packages',
                    'start_date',
                    'end_date',
                    'status',
                ]
            )
            subscription = active_subscription
        else:
            VendorSubscription.objects.filter(
                vendor=vendor,
                status=VendorSubscription.STATUS_ACTIVE,
            ).update(status=VendorSubscription.STATUS_EXPIRED)

            start_date = today
            end_date = start_date + timedelta(days=max(plan.duration_days - 1, 0))
            subscription = VendorSubscription.objects.create(
                vendor=vendor,
                plan=plan,
                plan_name=plan.name,
                price=plan.price,
                duration_days=plan.duration_days,
                max_featured_packages=plan.max_featured_packages,
                start_date=start_date,
                end_date=end_date,
                status=VendorSubscription.STATUS_ACTIVE,
            )

        _record_subscription_transaction(
            vendor=vendor,
            subscription=subscription,
            amount=amount,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            payment_method=payment_method,
        )

        if subscription.max_featured_packages is not None:
            featured_packages = Package.objects.filter(vendor=vendor, is_featured=True).order_by('-created_at')
            allowed_ids = list(
                featured_packages.values_list('id', flat=True)[:subscription.max_featured_packages]
            )
            if allowed_ids:
                Package.objects.filter(vendor=vendor, is_featured=True).exclude(id__in=allowed_ids).update(is_featured=False)
            else:
                featured_packages.update(is_featured=False)

    return subscription


def _parse_filter_date(raw_value):
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def _apply_transaction_filters(queryset, request, *, allow_vendor=False):
    date_from_raw = (request.GET.get('date_from') or '').strip()
    date_to_raw = (request.GET.get('date_to') or '').strip()
    status = (request.GET.get('status') or '').strip().lower()
    vendor_raw = (request.GET.get('vendor') or '').strip()

    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    allowed_statuses = {
        Booking.PAYMENT_STATUS_PENDING,
        Booking.PAYMENT_STATUS_COMPLETED,
        Booking.PAYMENT_STATUS_FAILED,
    }
    if status in allowed_statuses:
        queryset = queryset.filter(payment_status=status)
    else:
        status = ''

    selected_vendor = ''
    if allow_vendor:
        try:
            selected_vendor = str(int(vendor_raw))
        except (TypeError, ValueError):
            selected_vendor = ''
        if selected_vendor:
            queryset = queryset.filter(vendor_id=selected_vendor)

    return queryset, {
        'date_from': date_from_raw,
        'date_to': date_to_raw,
        'status': status,
        'vendor': selected_vendor,
    }


def _transaction_csv_response(rows, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([
        'Transaction ID',
        'Date',
        'Traveler',
        'Vendor',
        'Package',
        'Total Amount',
        'Platform Fee',
        'Vendor Earnings',
        'Payment Method',
        'Payment Status',
    ])
    for row in rows:
        booking = row.booking
        package_title = booking.package.title if booking and booking.package_id else ''
        traveler_email = row.traveler.email if row.traveler else ''
        vendor_email = row.vendor.email if row.vendor else ''
        writer.writerow([
            row.transaction_id,
            timezone.localtime(row.created_at).strftime('%Y-%m-%d %H:%M'),
            traveler_email,
            vendor_email,
            package_title,
            row.total_amount,
            row.platform_fee,
            row.vendor_earnings,
            row.get_payment_method_display(),
            row.get_payment_status_display(),
        ])
    return response


def _dashboard_route_name(user):
    user_type = getattr(user, 'user_type', '')
    if user_type == 'traveler':
        return 'traveler_home'
    if user_type == 'vendor':
        vendor_profile = _get_vendor_profile(user)
        if vendor_profile and not vendor_profile.is_approved:
            return 'vendor_profile'
        return 'vendor_dashboard'
    if user_type == 'admin':
        return 'admin_dashboard'
    return 'home'


def _traveler_category_expression():
    trekking_match = (
        Q(title__icontains='trek')
        | Q(description__icontains='trek')
        | Q(itinerary__icontains='trek')
        | Q(title__icontains='base camp')
        | Q(description__icontains='base camp')
        | Q(title__icontains='hike')
        | Q(description__icontains='hike')
    )
    cultural_match = (
        Q(title__icontains='cultural')
        | Q(description__icontains='cultural')
        | Q(itinerary__icontains='cultural')
        | Q(title__icontains='heritage')
        | Q(description__icontains='heritage')
        | Q(title__icontains='temple')
        | Q(description__icontains='temple')
        | Q(title__icontains='monastery')
        | Q(description__icontains='monastery')
    )
    return Case(
        When(trekking_match, then=Value('trekking')),
        When(cultural_match, then=Value('cultural')),
        default=Value('adventure'),
        output_field=CharField(),
    )


def _traveler_package_queryset():
    return (
        Package.objects.filter(is_active=True)
        .select_related('vendor')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
            booking_count=Count(
                'bookings',
                filter=Q(bookings__status='confirmed'),
                distinct=True,
            ),
            category_slug=_traveler_category_expression(),
        )
    )


def _add_category_labels(packages):
    for package in packages:
        package.category_label = TRAVELER_CATEGORY_LABELS.get(
            getattr(package, 'category_slug', 'adventure'),
            'Adventure',
        )


def _append_package_images(package, uploaded_images):
    if not uploaded_images:
        return

    max_order = package.images.aggregate(max_order=Max('order'))['max_order'] or 0
    for offset, image in enumerate(uploaded_images, start=1):
        PackageImage.objects.create(
            package=package,
            image=image,
            order=max_order + offset,
        )


def _reorder_package_images(package, post_data):
    remaining_images = list(package.images.all())
    if not remaining_images:
        return

    sortable = []
    for image in remaining_images:
        raw_order = post_data.get(f'image_order_{image.id}', '').strip()
        try:
            desired_order = int(raw_order)
        except (TypeError, ValueError):
            desired_order = image.order
        sortable.append((max(desired_order, 0), image.created_at, image.id, image))

    sortable.sort(key=lambda item: (item[0], item[1], item[2]))
    for index, (_, _, _, image) in enumerate(sortable, start=1):
        image.order = index
    PackageImage.objects.bulk_update([item[3] for item in sortable], ['order'])


def _sync_package_images(package, post_data, files_data):
    delete_ids = []
    for raw_id in post_data.getlist('delete_images'):
        try:
            delete_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if delete_ids:
        package.images.filter(id__in=delete_ids).delete()

    _reorder_package_images(package, post_data)
    _append_package_images(package, files_data.getlist('images'))


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('admin_login')
        if getattr(request.user, 'user_type', '') != 'admin' or not request.user.is_staff:
            messages.error(request, 'Admin access only.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return never_cache(_wrapped)


def _get_latest_support_conversation(user):
    return SupportConversation.objects.filter(user=user).order_by('-created_at').first()


def _get_or_create_support_conversation(user):
    conversation = _get_latest_support_conversation(user)
    if conversation is None:
        conversation = SupportConversation.objects.create(user=user)
    return conversation


def _serialize_support_message(message):
    sender = message.sender
    sender_label = 'You'
    if message.is_system_generated:
        sender_label = 'Auto Message'
    elif message.is_admin_reply:
        sender_label = 'Admin'
    elif sender and sender.user_type == 'vendor':
        sender_label = sender.get_full_name().strip() or sender.username or sender.email

    return {
        'id': message.id,
        'message': message.message,
        'is_admin_reply': message.is_admin_reply,
        'is_system_generated': message.is_system_generated,
        'sender_label': sender_label,
        'related_booking_id': message.related_booking_id,
        'created_at': timezone.localtime(message.created_at).strftime('%b %d, %Y %H:%M'),
    }


def _admin_analytics_year_options():
    current_year = timezone.localdate().year
    return [current_year - 2, current_year - 1, current_year]


def _parse_admin_analytics_year(raw_year, year_options):
    try:
        parsed = int(raw_year)
    except (TypeError, ValueError):
        return year_options[-1]
    if parsed not in year_options:
        return year_options[-1]
    return parsed


def _month_labels():
    return [date(2000, month, 1).strftime('%b') for month in range(1, 13)]


def _month_range_dates(year, month):
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def _monthly_sum_for_bookings(bookings_queryset, year, field_name, *, confirmed_only=False):
    values = []
    for month in range(1, 13):
        start, end = _month_range_dates(year, month)
        month_qs = bookings_queryset.filter(created_at__date__range=(start, end))
        if confirmed_only:
            month_qs = month_qs.filter(status=Booking.STATUS_CONFIRMED)
        total = month_qs.aggregate(total=Sum(field_name))['total'] or 0
        values.append(float(total))
    return values


def _monthly_count_for_queryset(queryset, year, date_field):
    values = []
    for month in range(1, 13):
        start, end = _month_range_dates(year, month)
        filter_kwargs = {
            f'{date_field}__date__range': (start, end),
        }
        values.append(queryset.filter(**filter_kwargs).count())
    return values


def _monthly_growth(values, year):
    if not values:
        return {
            'percent': None,
            'current': 0.0,
            'previous': 0.0,
            'current_month': '',
            'previous_month': '',
        }

    now = timezone.localdate()
    current_month = now.month if year == now.year else 12
    current_idx = max(current_month - 1, 0)
    previous_idx = current_idx - 1
    current_value = float(values[current_idx])
    previous_value = float(values[previous_idx]) if previous_idx >= 0 else 0.0

    if previous_idx < 0:
        percent = None
        previous_month_label = ''
    elif previous_value == 0:
        percent = None if current_value > 0 else 0.0
        previous_month_label = date(year, previous_idx + 1, 1).strftime('%b')
    else:
        percent = round(((current_value - previous_value) / previous_value) * 100, 1)
        previous_month_label = date(year, previous_idx + 1, 1).strftime('%b')

    return {
        'percent': percent,
        'current': current_value,
        'previous': previous_value,
        'current_month': date(year, current_idx + 1, 1).strftime('%b'),
        'previous_month': previous_month_label,
    }


def _is_cultural_package(package):
    keywords = (
        'cultural',
        'culture',
        'heritage',
        'temple',
        'monastery',
        'pilgrimage',
        'museum',
    )
    searchable_text = ' '.join([
        package.title or '',
        package.description or '',
        package.itinerary or '',
        package.location_name or '',
        package.location or '',
    ]).lower()
    return any(keyword in searchable_text for keyword in keywords)


def _package_category_breakdown_for_year(year):
    packages = Package.objects.filter(created_at__year=year)
    trek_count = 0
    tour_count = 0
    cultural_count = 0

    for package in packages:
        if _is_cultural_package(package):
            cultural_count += 1
        elif package.category == Package.CATEGORY_TREK:
            trek_count += 1
        else:
            tour_count += 1

    return {
        'labels': ['Treks', 'Tours', 'Cultural'],
        'values': [trek_count, tour_count, cultural_count],
    }


def _vendor_display_label(vendor_user):
    profile = _get_vendor_profile(vendor_user)
    if profile and profile.business_name:
        return profile.business_name
    full_name = vendor_user.get_full_name().strip()
    if full_name:
        return full_name
    return vendor_user.email or vendor_user.username or f'Vendor #{vendor_user.id}'


def _top_vendor_earnings_for_year(year, limit=8):
    bookings = Booking.objects.filter(
        status=Booking.STATUS_CONFIRMED,
        created_at__year=year,
    ).select_related(
        'vendor',
        'vendor__vendor_profile',
        'package__vendor',
        'package__vendor__vendor_profile',
    )

    earnings_by_vendor = defaultdict(float)
    vendor_labels = {}

    for booking in bookings:
        vendor_user = booking.vendor or (booking.package.vendor if booking.package_id else None)
        if not vendor_user:
            continue
        earnings_by_vendor[vendor_user.id] += float(booking.vendor_amount or 0)
        if vendor_user.id not in vendor_labels:
            vendor_labels[vendor_user.id] = _vendor_display_label(vendor_user)

    ranked = sorted(
        earnings_by_vendor.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]
    return [
        {
            'name': vendor_labels[vendor_id],
            'earnings': round(total, 2),
        }
        for vendor_id, total in ranked
    ]

__all__ = [
    'monthrange',
    'defaultdict',
    'csv',
    'date',
    'timedelta',
    'Decimal',
    'InvalidOperation',
    'wraps',
    'Path',
    'uuid',
    'settings',
    'messages',
    'authenticate',
    'login',
    'logout',
    'update_session_auth_hash',
    'login_required',
    'get_image_dimensions',
    'IntegrityError',
    'transaction',
    'Avg',
    'BooleanField',
    'Case',
    'CharField',
    'Count',
    'DateTimeField',
    'Max',
    'OuterRef',
    'Q',
    'Subquery',
    'Sum',
    'TextField',
    'Value',
    'When',
    'HttpResponse',
    'JsonResponse',
    'get_object_or_404',
    'redirect',
    'render',
    'reverse',
    'url_has_allowed_host_and_scheme',
    'timezone',
    'timesince',
    'never_cache',
    'csrf_protect',
    'require_POST',
    'Booking',
    'Package',
    'SpecialOffer',
    'Review',
    'PackageImage',
    'SupportConversation',
    'SupportMessage',
    'Transaction',
    'Wishlist',
    'EsewaError',
    'StripeError',
    'create_checkout_session_for_item',
    'get_esewa_payment_url',
    'retrieve_checkout_session',
    'verify_esewa_payment',
    'AdminProfile',
    'FeatureSlot',
    'Notification',
    'Badge',
    'UserBadge',
    'TravelerProfile',
    'User',
    'VendorFeature',
    'VendorProfile',
    'VendorSubscription',
    'VendorSubscriptionPlan',
    'PackageForm',
    'VendorProfileForm',
    'create_notification',
    'notify_admins',
    'notification_link',
    'serialize_notification',
    'create_otp',
    'verify_otp_util',
    'add_points',
    'sync_badges_for_user',
    'total_points_for_user',
    'badge_progress_for_user',
    'TRAVELER_CATEGORY_LABELS',
    'TRAVELER_CATEGORY_SLUGS',
    '_get_vendor_profile',
    '_get_admin_profile',
    '_get_traveler_profile',
    '_get_active_subscription',
    '_sync_active_special_offers_for_user',
    '_notify_opted_in_travelers_for_limited_package_offer',
    '_delete_stored_file',
    '_is_valid_uploaded_image',
    '_ensure_vendor',
    '_ensure_vendor_account',
    '_ensure_traveler',
    '_safe_next_url',
    '_subscription_esewa_payload',
    '_subscription_payment_session_key',
    '_feature_slot_payment_session_key',
    '_record_subscription_transaction',
    '_record_feature_slot_transaction',
    '_total_active_feature_slots_for_vendor',
    '_total_featured_packages_for_vendor',
    '_total_homepage_feature_capacity',
    '_total_homepage_featured_count',
    '_activate_feature_slots_after_verified_payment',
    '_activate_subscription_after_verified_payment',
    '_parse_filter_date',
    '_apply_transaction_filters',
    '_transaction_csv_response',
    '_dashboard_route_name',
    '_traveler_category_expression',
    '_traveler_package_queryset',
    '_add_category_labels',
    '_append_package_images',
    '_reorder_package_images',
    '_sync_package_images',
    'admin_required',
    '_get_latest_support_conversation',
    '_get_or_create_support_conversation',
    '_serialize_support_message',
    '_admin_analytics_year_options',
    '_parse_admin_analytics_year',
    '_month_labels',
    '_month_range_dates',
    '_monthly_sum_for_bookings',
    '_monthly_count_for_queryset',
    '_monthly_growth',
    '_is_cultural_package',
    '_package_category_breakdown_for_year',
    '_vendor_display_label',
    '_top_vendor_earnings_for_year',
]
