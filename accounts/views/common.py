"""Shared accounts view helpers and dependencies.

This is a "hub" module: every view file in ``accounts/views/`` (and the
admin views in ``core/views/admin/``) imports the names it needs from
here instead of pulling them straight from Django, the models, the
forms, or the services. The benefits are:

* one place to update an import path when something is renamed,
* sibling view files stay short and focused,
* small cross-cutting helpers (role guards, profile lookups, transaction
  filters, admin analytics, etc.) live here so they are not duplicated.

The bottom of the file exposes everything via ``__all__`` so the imports
in sibling files keep working. Do not flatten this hub: 17 files import
from it.
"""

# NOTE: file > 300 lines — split deferred. This is a hub re-export module
# consumed by 17 sibling view files; splitting would force edits across
# every one of them and is forbidden by the project's safety rules.

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

from django.core.exceptions import PermissionDenied

from django.core.files.images import get_image_dimensions

from django.db import IntegrityError, transaction

from django.db.models import (
    Avg,
    BooleanField,
    Count,
    DateTimeField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    TextField,
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

# --- Cross-app model re-exports ---------------------------------------------
# Pulled from the core app so accounts views can refer to bookings,
# packages, reviews, support chat, etc., without importing core directly.
from core.models import (
    Booking,
    Package,
    Review,
    PackageImage,
    SupportConversation,
    SupportMessage,
    Transaction,
    Wishlist,
)

# --- Payment gateway re-exports ---------------------------------------------
# Stripe wrapper used for international card payments and feature plans.
from core.payments import (
    StripeError,
    create_checkout_session_for_item,
    retrieve_checkout_session,
)
# eSewa V2 (HMAC-SHA256, NPR) used for Nepal-side payments.
from core.services.esewa_service import (
    EsewaError,
    get_esewa_payment_url,
    build_payment_payload as build_esewa_v2_payload,
    process_success_callback as esewa_process_success_callback,
)

# --- Accounts app re-exports ------------------------------------------------
# Models, forms, notification helpers, selectors, and reward/badge logic
# used by the accounts views.
from ..models import (
    AdminProfile,
    FeaturedPackage,
    FeaturePlan,
    Notification,
    Badge,
    UserBadge,
    TravelerProfile,
    User,
    VendorFeatureSubscription,
    VendorProfile,
)

from ..forms import PackageForm, VendorProfileForm

from ..notifications import (
    create_notification,
    notify_admins,
    notification_link,
    serialize_notification,
)
from ..selectors import (
    get_active_subscription,
    get_admin_profile,
    get_traveler_profile,
    get_vendor_profile,
)

from ..achievements import (
    add_points,
    sync_badges_for_user,
    total_points_for_user,
    badge_progress_for_user,
)

# --- Profile lookup helpers -------------------------------------------------
# Thin wrappers around the selector layer. Kept under their old underscore
# names so existing view code does not need to change.

def _get_vendor_profile(user):
    """Return the VendorProfile attached to ``user``, or ``None``."""
    return get_vendor_profile(user)


def _get_admin_profile(user):
    """Return the AdminProfile attached to ``user``, or ``None``."""
    return get_admin_profile(user)


def _get_traveler_profile(user):
    """Return the TravelerProfile attached to ``user``, or ``None``."""
    return get_traveler_profile(user)


def _get_active_subscription(vendor):
    """Return the vendor's currently active feature subscription, if any."""
    return get_active_subscription(vendor)


def _delete_stored_file(instance, field_name, file_name):
    """Remove a previously-stored file from the model field's storage backend."""
    if not file_name:
        return
    storage = instance._meta.get_field(field_name).storage
    if storage.exists(file_name):
        storage.delete(file_name)


def _is_valid_uploaded_image(uploaded_file):
    """Return True if Django can read image dimensions from ``uploaded_file``."""
    if uploaded_file is None:
        return False
    try:
        get_image_dimensions(uploaded_file)
        uploaded_file.seek(0)
    except Exception:
        return False
    return True


# --- Role guards ------------------------------------------------------------
# Lightweight checks used at the top of view functions. They flash an error
# message and return False so the caller can early-redirect.

def _ensure_vendor(request):
    """Vendor-only AND must be admin-approved."""
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile and not vendor_profile.is_approved:
        messages.error(request, 'Your account is pending admin approval.')
        return False
    return True


def _ensure_vendor_account(request):
    """Vendor-only check that does NOT require approval (registration flow)."""
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    return True


def _ensure_traveler(request):
    """Traveler-only access guard."""
    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return False
    return True


def traveler_required(view_func=None, *, login_url='traveler_login'):
    """Decorator: authenticated travelers only."""

    def decorator(func):
        @login_required(login_url=login_url)
        @wraps(func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, 'user_type', '') != 'traveler':
                raise PermissionDenied('Traveler access only.')
            return func(request, *args, **kwargs)

        return _wrapped

    if view_func is None:
        return decorator
    return decorator(view_func)


def vendor_required(view_func=None, *, login_url='vendor_login', require_approved=True):
    """Decorator: authenticated vendors only.

    ``require_approved=True`` additionally blocks vendors whose profile has not
    yet been approved by an admin.
    """

    def decorator(func):
        @login_required(login_url=login_url)
        @wraps(func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, 'user_type', '') != 'vendor':
                raise PermissionDenied('Vendor access only.')

            if require_approved:
                vendor_profile = _get_vendor_profile(request.user)
                if vendor_profile and not vendor_profile.is_approved:
                    messages.error(request, 'Your account is pending admin approval.')
                    return redirect('vendor_login')

            return func(request, *args, **kwargs)

        return _wrapped

    if view_func is None:
        return decorator
    return decorator(view_func)


def vendor_account_required(view_func=None, *, login_url='vendor_login'):
    """Decorator: authenticated vendor-only check without approval requirement."""

    def decorator(func):
        return vendor_required(
            func,
            login_url=login_url,
            require_approved=False,
        )

    if view_func is None:
        return decorator
    return decorator(view_func)


def _safe_next_url(request, fallback_name):
    """Validate a ``?next=`` parameter against open-redirect attacks."""
    candidate = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(fallback_name)


def _plan_esewa_payload(*, amount, pid, success_url, failure_url):
    """Build eSewa V2 payment payload for feature plan purchases."""
    return build_esewa_v2_payload(
        amount=amount,
        transaction_uuid=pid,
        success_url=success_url,
        failure_url=failure_url,
    )


def _plan_payment_session_key(vendor_id):
    """Session key under which an in-flight feature-plan checkout is stored."""
    return f'feature_plan_payment_{vendor_id}'


# --- Transaction filtering helpers ------------------------------------------
# Shared by the admin transactions screen and the vendor transactions screen.

def _parse_filter_date(raw_value):
    """Safely parse an ISO date string from a query parameter."""
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def _apply_transaction_filters(queryset, request, *, allow_vendor=False, allow_status=True):
    """Apply ``date_from``/``date_to``/``status``/``vendor`` GET filters.

    Returns the filtered queryset and an echo dict so the template can
    repopulate the filter form. ``allow_vendor=True`` is used by the
    admin view, which can scope to a single vendor.
    """
    date_from_raw = (request.GET.get('date_from') or '').strip()
    date_to_raw = (request.GET.get('date_to') or '').strip()
    status = (request.GET.get('status') or '').strip().lower()
    vendor_raw = (request.GET.get('vendor') or '').strip()

    date_from = _parse_filter_date(date_from_raw)
    date_to = _parse_filter_date(date_to_raw)
    date_error = ''
    today = timezone.localdate()

    if date_from_raw and not date_from:
        date_error = 'Please enter a valid From date.'
    elif date_to_raw and not date_to:
        date_error = 'Please enter a valid To date.'
    elif date_from and date_from > today:
        date_error = 'From date cannot be in the future.'
    elif date_from and date_to and date_from > date_to:
        date_error = 'From date cannot be later than To date.'

    if date_error:
        messages.error(request, date_error)
    else:
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

    if allow_status:
        allowed_statuses = {
            Booking.PAYMENT_STATUS_PENDING,
            Booking.PAYMENT_STATUS_COMPLETED,
            Booking.PAYMENT_STATUS_FAILED,
        }
        if status in allowed_statuses:
            queryset = queryset.filter(payment_status=status)
        else:
            status = ''
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
        'date_error': date_error,
        'status': status,
        'vendor': selected_vendor,
    }


def _transaction_csv_response(rows, filename):
    """Stream a list of Transaction rows back to the user as a CSV download."""
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
    """Pick the post-login landing page based on user_type and approval state."""
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


def _traveler_package_queryset():
    """Active packages annotated with traveler-facing ranking metrics."""
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
        )
    )


# --- Package image management -----------------------------------------------
# Used by vendor_package create/edit views to manage the per-package gallery.

def _append_package_images(package, uploaded_images):
    """Append newly uploaded images at the end of the existing gallery order."""
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
    """Re-number existing images using the ``image_order_<id>`` POST fields."""
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
    """Apply delete/reorder/append in one call from a single form submission."""
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
    """Decorator: only authenticated admin/staff users may call ``view_func``."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('admin_login')
        if getattr(request.user, 'user_type', '') != 'admin' or not request.user.is_staff:
            raise PermissionDenied('Admin access only.')
        return view_func(request, *args, **kwargs)
    return never_cache(_wrapped)


# --- Support chat helpers ---------------------------------------------------
# Used by the admin support inbox and the in-page chat widget.

def _get_latest_support_conversation(user):
    """Most recent support thread for ``user`` (any status), or ``None``."""
    return SupportConversation.objects.filter(user=user).order_by('-created_at').first()


def _get_or_create_support_conversation(user):
    """Reuse the latest thread or open a new one."""
    conversation = _get_latest_support_conversation(user)
    if conversation is None:
        conversation = SupportConversation.objects.create(user=user)
    return conversation


def _serialize_support_message(message):
    """Convert a SupportMessage to the JSON shape consumed by the chat widget."""
    sender = message.sender
    sender_label = 'You'
    if message.is_system_generated:
        sender_label = 'Auto Message'
    elif message.is_admin_reply:
        sender_label = 'Admin'
    elif sender and sender.user_type == 'vendor':
        sender_label = _vendor_display_label(sender)

    return {
        'id': message.id,
        'message': message.message,
        'is_admin_reply': message.is_admin_reply,
        'is_system_generated': message.is_system_generated,
        'sender_label': sender_label,
        'related_booking_id': message.related_booking_id,
        'created_at': timezone.localtime(message.created_at).strftime('%b %d, %Y %H:%M'),
    }


# --- Admin analytics helpers ------------------------------------------------
# Powers the dashboard charts: revenue trend, signups, package mix, top
# vendors. Kept here so admin_views.py and the analytics JSON API share
# the same math.

def _admin_analytics_year_options():
    """Three-year window (current and two previous) shown in the year picker."""
    current_year = timezone.localdate().year
    return [current_year - 2, current_year - 1, current_year]


def _parse_admin_analytics_year(raw_year, year_options):
    """Validate the ``?year=`` query parameter; fall back to the latest year."""
    try:
        parsed = int(raw_year)
    except (TypeError, ValueError):
        return year_options[-1]
    if parsed not in year_options:
        return year_options[-1]
    return parsed


def _month_labels():
    """Twelve short month labels (Jan..Dec) for chart x-axes."""
    return [date(2000, month, 1).strftime('%b') for month in range(1, 13)]


def _month_range_dates(year, month):
    """Inclusive (first_day, last_day) tuple for the given calendar month."""
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def _monthly_sum_for_bookings(bookings_queryset, year, field_name, *, confirmed_only=False):
    """Sum ``field_name`` per month for the year; optionally only CONFIRMED bookings."""
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
    """Count rows per month for the given year (e.g. signups, new packages)."""
    values = []
    for month in range(1, 13):
        start, end = _month_range_dates(year, month)
        filter_kwargs = {
            f'{date_field}__date__range': (start, end),
        }
        values.append(queryset.filter(**filter_kwargs).count())
    return values


def _monthly_growth(values, year):
    """Compute month-over-month % growth from a 12-element series.

    Returns a dict with current/previous values, their month labels, and a
    percent change. ``percent`` is ``None`` when there is no comparable
    previous month or when the previous month was zero and current is too.
    """
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


def _package_category_breakdown_for_year(year):
    """Return ``{labels, values}`` for the Trek vs Tour donut chart."""
    packages = Package.objects.filter(created_at__year=year)
    trek_count = 0
    tour_count = 0

    for package in packages:
        if package.category == Package.CATEGORY_TREK:
            trek_count += 1
        else:
            tour_count += 1

    return {
        'labels': ['Treks', 'Tours'],
        'values': [trek_count, tour_count],
    }


def _vendor_display_label(vendor_user):
    """Pick a display name for a vendor: business → full name → email → fallback."""
    profile = _get_vendor_profile(vendor_user)
    if profile and profile.business_name:
        return profile.business_name
    full_name = vendor_user.get_full_name().strip()
    if full_name:
        return full_name
    return vendor_user.email or vendor_user.username or f'Vendor #{vendor_user.id}'


def _top_vendor_earnings_for_year(year, limit=8):
    """Return up to ``limit`` highest-earning vendors (by vendor share) for ``year``.

    Earnings are summed from CONFIRMED bookings using ``Booking.vendor_amount``.
    """
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
    'Count',
    'DateTimeField',
    'Max',
    'OuterRef',
    'Q',
    'Subquery',
    'Sum',
    'TextField',
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
    'build_esewa_v2_payload',
    'esewa_process_success_callback',
    'AdminProfile',
    'FeaturedPackage',
    'FeaturePlan',
    'Notification',
    'Badge',
    'UserBadge',
    'TravelerProfile',
    'User',
    'VendorFeatureSubscription',
    'VendorProfile',
    'PackageForm',
    'VendorProfileForm',
    'create_notification',
    'notify_admins',
    'notification_link',
    'serialize_notification',
    'add_points',
    'sync_badges_for_user',
    'total_points_for_user',
    'badge_progress_for_user',
    '_get_vendor_profile',
    '_get_admin_profile',
    '_get_traveler_profile',
    '_get_active_subscription',
    '_delete_stored_file',
    '_is_valid_uploaded_image',
    '_ensure_vendor',
    '_ensure_vendor_account',
    '_ensure_traveler',
    'traveler_required',
    'vendor_required',
    'vendor_account_required',
    '_safe_next_url',
    '_plan_esewa_payload',
    '_plan_payment_session_key',
    '_parse_filter_date',
    '_apply_transaction_filters',
    '_transaction_csv_response',
    '_dashboard_route_name',
    '_traveler_package_queryset',
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
    '_package_category_breakdown_for_year',
    '_vendor_display_label',
    '_top_vendor_earnings_for_year',
]
