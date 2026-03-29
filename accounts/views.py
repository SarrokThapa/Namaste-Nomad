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
from .models import (
    AdminProfile,
    Notification,
    Badge,
    UserBadge,
    TravelerProfile,
    User,
    VendorProfile,
    VendorSubscription,
    VendorSubscriptionPlan,
)
from .forms import PackageForm, VendorProfileForm
from .notifications import (
    create_notification,
    notify_admins,
    notification_link,
    serialize_notification,
)
from .utils import create_otp, verify_otp as verify_otp_util
from .achievements import (
    add_points,
    sync_badges_for_user,
    total_points_for_user,
    badge_progress_for_user,
)


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


TRAVELER_CATEGORY_LABELS = {
    'adventure': 'Adventure',
    'cultural': 'Cultural',
    'trekking': 'Trekking',
}
TRAVELER_CATEGORY_SLUGS = tuple(TRAVELER_CATEGORY_LABELS.keys())


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


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect
def support_chat(request):
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        messages.error(request, 'Traveler or Vendor access only.')
        return redirect('home')

    conversation = _get_or_create_support_conversation(request.user)

    if request.method == 'POST':
        message_text = (request.POST.get('message') or '').strip()
        if not message_text:
            messages.error(request, 'Please enter a message before sending.')
        elif conversation.status != SupportConversation.STATUS_OPEN:
            conversation = SupportConversation.objects.create(user=request.user)
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=False,
            )
            notify_admins(
                f'New support message from {request.user.email}',
                Notification.TYPE_SUPPORT_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('support_chat')
        else:
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=False,
            )
            notify_admins(
                f'New support message from {request.user.email}',
                Notification.TYPE_SUPPORT_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('support_chat')

    support_messages = (
        SupportMessage.objects.filter(conversation=conversation)
        .select_related('sender')
        .order_by('created_at')
    )
    base_template = (
        'accounts/vendor_base.html'
        if request.user.user_type == 'vendor'
        else 'accounts/traveler_base.html'
    )
    context = {
        'base_template': base_template,
        'conversation': conversation,
        'support_messages': support_messages,
        'active_page': 'support',
    }
    if request.user.user_type == 'vendor':
        context['vendor_profile'] = _get_vendor_profile(request.user)
    else:
        traveler_profile = _get_traveler_profile(request.user)
        if traveler_profile is None:
            traveler_profile = TravelerProfile.objects.create(user=request.user)
        context['traveler_profile'] = traveler_profile
    return render(request, 'accounts/support_chat.html', context)


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


@never_cache
@login_required(login_url='account_login_choice')
def support_widget_data(request):
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    conversation = _get_or_create_support_conversation(request.user)
    support_messages = SupportMessage.objects.filter(
        conversation=conversation,
    ).select_related('sender').order_by('created_at')

    return JsonResponse({
        'conversation_id': conversation.id,
        'status': conversation.status,
        'messages': [_serialize_support_message(message) for message in support_messages],
    })


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect
def support_widget_send(request):
    if getattr(request.user, 'user_type', '') not in {'traveler', 'vendor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    message_text = (request.POST.get('message') or '').strip()
    if not message_text:
        return JsonResponse({'error': 'Message is required.'}, status=400)

    conversation = _get_or_create_support_conversation(request.user)
    if conversation.status != SupportConversation.STATUS_OPEN:
        conversation = SupportConversation.objects.create(user=request.user)

    new_message = SupportMessage.objects.create(
        conversation=conversation,
        sender=request.user,
        message=message_text,
        is_admin_reply=False,
    )
    notify_admins(
        f'New support message from {request.user.email}',
        Notification.TYPE_SUPPORT_MESSAGE,
        related_object_id=conversation.id,
    )

    return JsonResponse({
        'message': _serialize_support_message(new_message),
    })


@never_cache
@login_required(login_url='account_login_choice')
def notifications_data(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:20]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({
        'unread_count': unread_count,
        'notifications': [serialize_notification(notification) for notification in notifications],
    })


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect
def notifications_mark_read(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    notification_id = (request.POST.get('notification_id') or '').strip().lower()
    queryset = Notification.objects.filter(user=request.user)
    if notification_id in {'all', '*'} or request.POST.get('mark_all') == '1':
        queryset.update(is_read=True)
    else:
        try:
            target_id = int(notification_id)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid notification id'}, status=400)
        queryset.filter(id=target_id).update(is_read=True)

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    if not is_ajax:
        return redirect('notifications_list')
    return JsonResponse({'unread_count': unread_count})


@never_cache
@login_required(login_url='account_login_choice')
def notifications_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    for notification in notifications:
        notification.link = notification_link(notification)

    if getattr(request.user, 'user_type', '') == 'admin':
        admin_profile = _get_admin_profile(request.user)
        return render(request, 'accounts/admin_notifications.html', {
            'admin_profile': admin_profile,
            'notifications': notifications,
            'unread_count': unread_count,
            'active_page': 'notifications',
        })

    base_template = (
        'accounts/vendor_base.html'
        if request.user.user_type == 'vendor'
        else 'accounts/traveler_base.html'
    )
    context = {
        'base_template': base_template,
        'notifications': notifications,
        'unread_count': unread_count,
        'active_page': 'notifications',
    }
    if request.user.user_type == 'vendor':
        context['vendor_profile'] = _get_vendor_profile(request.user)
    else:
        traveler_profile = _get_traveler_profile(request.user)
        if traveler_profile is None:
            traveler_profile = TravelerProfile.objects.create(user=request.user)
        context['traveler_profile'] = traveler_profile
    return render(request, 'accounts/notifications.html', context)


@admin_required
def admin_support_inbox(request):
    admin_profile = _get_admin_profile(request.user)
    last_message_qs = SupportMessage.objects.filter(
        conversation=OuterRef('pk'),
    ).order_by('-created_at', '-id')
    conversations = SupportConversation.objects.select_related('user').annotate(
        last_message_text=Subquery(
            last_message_qs.values('message')[:1],
            output_field=TextField(),
        ),
        last_message_at=Subquery(
            last_message_qs.values('created_at')[:1],
            output_field=DateTimeField(),
        ),
        last_message_is_admin=Subquery(
            last_message_qs.values('is_admin_reply')[:1],
            output_field=BooleanField(),
        ),
    ).order_by('-last_message_at', '-created_at')

    role_labels = dict(User.USER_TYPE_CHOICES)
    unread_count = 0
    for conversation in conversations:
        user = conversation.user
        conversation.user_display = user.get_full_name().strip() or user.username or user.email
        conversation.user_role = role_labels.get(user.user_type, user.user_type.title())
        conversation.last_message_text = conversation.last_message_text or ''
        conversation.unread_by_admin = conversation.last_message_is_admin is False
        if conversation.unread_by_admin:
            unread_count += 1

    return render(request, 'accounts/admin_support_inbox.html', {
        'admin_profile': admin_profile,
        'conversations': conversations,
        'active_page': 'support',
        'support_inbox_unread_count': unread_count,
    })


@admin_required
@csrf_protect
def admin_support_chat(request, conversation_id):
    admin_profile = _get_admin_profile(request.user)
    conversation = get_object_or_404(
        SupportConversation.objects.select_related('user'),
        id=conversation_id,
    )
    if request.method == 'POST':
        action = (request.POST.get('action') or '').lower()
        if action == 'close':
            if conversation.status != SupportConversation.STATUS_CLOSED:
                conversation.status = SupportConversation.STATUS_CLOSED
                conversation.save(update_fields=['status'])
                messages.success(request, 'Conversation closed.')
            return redirect('admin_support_chat', conversation_id=conversation.id)

        message_text = (request.POST.get('message') or '').strip()
        if not message_text:
            messages.error(request, 'Please enter a message before sending.')
        elif conversation.status != SupportConversation.STATUS_OPEN:
            messages.error(request, 'This support conversation is closed.')
        else:
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message_text,
                is_admin_reply=True,
            )
            create_notification(
                conversation.user,
                'Admin replied to your support message.',
                Notification.TYPE_ADMIN_MESSAGE,
                related_object_id=conversation.id,
            )
            return redirect('admin_support_chat', conversation_id=conversation.id)

    role_labels = dict(User.USER_TYPE_CHOICES)
    user = conversation.user
    conversation.user_display = user.get_full_name().strip() or user.username or user.email
    conversation.user_role = role_labels.get(user.user_type, user.user_type.title())
    support_messages = (
        SupportMessage.objects.filter(conversation=conversation)
        .select_related('sender', 'related_booking')
        .order_by('created_at')
    )

    return render(request, 'accounts/admin_support_chat.html', {
        'admin_profile': admin_profile,
        'conversation': conversation,
        'support_messages': support_messages,
        'active_page': 'support',
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_dashboard(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)
    completed_vendor_bookings = vendor_bookings.filter(
        payment_status=Booking.PAYMENT_STATUS_COMPLETED,
    )
    active_subscription = _get_active_subscription(request.user)
    featured_count = vendor_packages.filter(is_featured=True).count()
    featured_limit = active_subscription.max_featured_packages if active_subscription else None
    subscription_plans = VendorSubscriptionPlan.objects.filter(is_active=True).order_by('price', 'duration_days')

    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    active_packages = vendor_packages.filter(is_active=True).count()
    total_bookings = vendor_bookings.count()
    pending_bookings = vendor_bookings.filter(status='pending').count()
    average_rating = Review.objects.filter(package__vendor=request.user).aggregate(
        avg=Avg('rating')
    )['avg'] or 0

    today = timezone.localdate()

    month_cursor = today.replace(day=1)
    month_periods = []
    for _ in range(6):
        last_day = monthrange(month_cursor.year, month_cursor.month)[1]
        start = month_cursor
        end = date(month_cursor.year, month_cursor.month, last_day)
        month_periods.append((start, end, start.strftime('%b')))
        if month_cursor.month == 1:
            month_cursor = date(month_cursor.year - 1, 12, 1)
        else:
            month_cursor = date(month_cursor.year, month_cursor.month - 1, 1)
    month_periods.reverse()

    monthly_earnings = []
    monthly_bookings = []
    for start, end, label in month_periods:
        month_total = completed_vendor_bookings.filter(
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        vendor_share = (Decimal(month_total) * Booking.COMMISSION_VENDOR_RATE).quantize(Decimal('0.01'))
        booking_count = completed_vendor_bookings.filter(created_at__date__range=(start, end)).count()
        monthly_earnings.append({
            'label': label,
            'value': float(vendor_share),
        })
        monthly_bookings.append({
            'label': label,
            'value': booking_count,
        })

    package_performance_chart = list(
        vendor_packages.annotate(
            completed_booking_count=Count(
                'bookings',
                filter=Q(bookings__payment_status=Booking.PAYMENT_STATUS_COMPLETED),
            ),
        )
        .order_by('-completed_booking_count', '-views_count')[:5]
    )

    vendor_trek_count = vendor_packages.filter(category=Package.CATEGORY_TREK).count()
    vendor_tour_count = vendor_packages.filter(category=Package.CATEGORY_TOUR).count()
    vendor_other_count = vendor_packages.exclude(
        category__in=[Package.CATEGORY_TREK, Package.CATEGORY_TOUR],
    ).count()

    earnings_chart = {
        'labels': [entry['label'] for entry in monthly_earnings],
        'values': [round(entry['value'], 2) for entry in monthly_earnings],
    }
    bookings_chart = {
        'labels': [entry['label'] for entry in monthly_bookings],
        'values': [entry['value'] for entry in monthly_bookings],
    }
    packages_chart = {
        'labels': [package.title for package in package_performance_chart],
        'values': [package.completed_booking_count for package in package_performance_chart],
    }
    category_chart = {
        'labels': ['Treks', 'Tours', 'Others'],
        'values': [vendor_trek_count, vendor_tour_count, vendor_other_count],
        'colors': ['#1d4ed8', '#1e3a8a', '#60a5fa'],
    }

    def _growth_text(values):
        if len(values) < 2 or values[-2] == 0:
            return 'No baseline from last month'
        change = ((values[-1] - values[-2]) / values[-2]) * 100
        sign = '+' if change >= 0 else ''
        return f'{sign}{change:.0f}% from last month'

    chart_insights = {
        'earnings': _growth_text(earnings_chart['values']),
        'bookings': _growth_text(bookings_chart['values']),
        'packages': _growth_text(packages_chart['values']),
        'categories': 'Distribution based on your packages',
    }

    upcoming_bookings = vendor_bookings.filter(
        travel_date__gte=today,
        travel_date__lte=today + timedelta(days=14),
    ).exclude(status='cancelled').order_by('travel_date')[:3]

    package_performance = vendor_packages.annotate(
        booking_count=Count('bookings'),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-booking_count', '-views_count')[:3]

    return render(request, 'accounts/vendor_dashboard.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'dashboard',
        'stats': {
            'total_revenue': float(total_revenue),
            'active_packages': active_packages,
            'total_bookings': total_bookings,
            'pending_bookings': pending_bookings,
            'average_rating': round(average_rating or 0, 1),
        },
        'active_subscription': active_subscription,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
        'subscription_plans': subscription_plans,
        'earnings_chart': earnings_chart,
        'bookings_chart': bookings_chart,
        'packages_chart': packages_chart,
        'category_chart': category_chart,
        'chart_insights': chart_insights,
        'upcoming_bookings': upcoming_bookings,
        'package_performance': package_performance,
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_packages(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    packages = Package.objects.filter(vendor=request.user).annotate(
        booking_count=Count('bookings'),
    ).order_by('-created_at')
    active_subscription = _get_active_subscription(request.user)
    featured_count = packages.filter(is_featured=True).count()
    featured_limit = active_subscription.max_featured_packages if active_subscription else None
    return render(request, 'accounts/vendor_packages.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'packages': packages,
        'active_subscription': active_subscription,
        'featured_count': featured_count,
        'featured_limit': featured_limit,
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_bookings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    bookings = Booking.objects.filter(package__vendor=request.user).select_related(
        'package',
        'traveler',
    ).order_by('-created_at')
    return render(request, 'accounts/vendor_bookings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'bookings',
        'bookings': bookings,
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect
def vendor_booking_status_update(request, booking_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    next_url = request.POST.get('next') or reverse('vendor_bookings')
    if request.method != 'POST':
        return redirect(next_url)

    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        package__vendor=request.user,
    )
    requested_status = (request.POST.get('status') or '').strip().lower()

    if requested_status not in {'confirmed', 'cancelled'}:
        messages.error(request, 'Invalid booking action.')
        return redirect(next_url)

    if booking.status == requested_status:
        return redirect(next_url)

    if (
        requested_status == Booking.STATUS_CONFIRMED
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        messages.error(request, 'Only paid bookings can be confirmed.')
        return redirect(next_url)

    package = booking.package

    if requested_status == Booking.STATUS_CANCELLED and booking.status != Booking.STATUS_CANCELLED:
        package.available_slots += booking.number_of_people
        package.save(update_fields=['available_slots'])

    if requested_status == Booking.STATUS_CONFIRMED and booking.status == Booking.STATUS_CANCELLED:
        if booking.number_of_people > package.available_slots:
            messages.error(
                request,
                f'Cannot confirm booking. Only {package.available_slots} slot(s) are currently available.',
            )
            return redirect(next_url)
        package.available_slots -= booking.number_of_people
        package.save(update_fields=['available_slots'])

    booking.status = requested_status
    booking.save(update_fields=['status'])
    if requested_status == Booking.STATUS_CONFIRMED and booking.traveler:
        add_points(booking.traveler, 'booking_confirmed', 50)
        sync_badges_for_user(booking.traveler)
    if booking.traveler:
        status_label = 'confirmed' if requested_status == Booking.STATUS_CONFIRMED else 'cancelled'
        create_notification(
            booking.traveler,
            f'Your booking for {booking.package.title} was {status_label}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    messages.success(request, f'Booking marked as {requested_status}.')
    return redirect(next_url)


@never_cache
@login_required(login_url='vendor_login')
def vendor_reviews(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    reviews = Review.objects.filter(package__vendor=request.user).order_by('-created_at')
    return render(request, 'accounts/vendor_reviews.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'reviews',
        'reviews': reviews,
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_analytics(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)
    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0

    analytics = {
        'packages': vendor_packages.count(),
        'bookings': vendor_bookings.count(),
        'revenue': float(total_revenue),
        'reviews': Review.objects.filter(package__vendor=request.user).count(),
        'avg_rating': Review.objects.filter(package__vendor=request.user).aggregate(
            avg=Avg('rating')
        )['avg'] or 0,
    }

    today = timezone.localdate()

    month_cursor = today.replace(day=1)
    month_periods = []
    for _ in range(6):
        last_day = monthrange(month_cursor.year, month_cursor.month)[1]
        start = month_cursor
        end = date(month_cursor.year, month_cursor.month, last_day)
        month_periods.append((start, end, start.strftime('%b')))

        if month_cursor.month == 1:
            month_cursor = date(month_cursor.year - 1, 12, 1)
        else:
            month_cursor = date(month_cursor.year, month_cursor.month - 1, 1)
    month_periods.reverse()

    monthly_revenue = []
    max_monthly_revenue = 0
    for start, end, label in month_periods:
        value = vendor_bookings.filter(
            status='confirmed',
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('vendor_amount'))['total'] or 0
        value = float(value)
        max_monthly_revenue = max(max_monthly_revenue, value)
        monthly_revenue.append({
            'label': label,
            'value': value,
        })

    for entry in monthly_revenue:
        if max_monthly_revenue <= 0:
            entry['percent'] = 0
        else:
            entry['percent'] = int((entry['value'] / max_monthly_revenue) * 100)

    line_values = [entry['value'] for entry in monthly_revenue]
    chart_width = 420
    chart_height = 170
    chart_padding_x = 12
    chart_padding_y = 22
    chart_step = (chart_width - chart_padding_x * 2) / max(len(line_values) - 1, 1)
    max_line_value = max(line_values) if line_values else 0
    min_line_value = min(line_values) if line_values else 0
    monthly_line_points = []
    for idx, value in enumerate(line_values):
        x = chart_padding_x + idx * chart_step
        if max_line_value == min_line_value:
            y = chart_height / 2
        else:
            ratio = (value - min_line_value) / (max_line_value - min_line_value)
            y = chart_height - chart_padding_y - ratio * (chart_height - chart_padding_y * 2)
        monthly_line_points.append(f"{x:.0f},{y:.0f}")

    payment_method_counts = {}
    for method_key, _label in Booking.PAYMENT_METHOD_CHOICES:
        payment_method_counts[method_key] = 0
    for row in vendor_bookings.values('payment_method').annotate(count=Count('id')):
        payment_method_counts[row['payment_method']] = row['count']

    method_labels = dict(Booking.PAYMENT_METHOD_CHOICES)
    method_colors = {
        Booking.PAYMENT_METHOD_ESEWA: '#0f766e',
        Booking.PAYMENT_METHOD_STRIPE: '#2563eb',
        Booking.PAYMENT_METHOD_KHALTI: '#7c3aed',
    }
    method_order = [
        Booking.PAYMENT_METHOD_ESEWA,
        Booking.PAYMENT_METHOD_STRIPE,
        Booking.PAYMENT_METHOD_KHALTI,
    ]

    total_method_count = sum(payment_method_counts.values())
    payment_method_breakdown = []
    method_segments = []
    current_percent = 0
    for method in method_order:
        count = payment_method_counts.get(method, 0)
        percent = (count / total_method_count * 100) if total_method_count else 0
        payment_method_breakdown.append({
            'key': method,
            'label': method_labels.get(method, method.title()),
            'count': count,
            'percent': round(percent),
            'color': method_colors[method],
        })
        if percent > 0:
            next_percent = current_percent + percent
            method_segments.append(
                f"{method_colors[method]} {current_percent:.1f}% {next_percent:.1f}%"
            )
            current_percent = next_percent

    if not method_segments:
        payment_method_gradient = "conic-gradient(#e5e7eb 0 100%)"
    else:
        if current_percent < 100:
            method_segments.append(f"#e5e7eb {current_percent:.1f}% 100%")
        payment_method_gradient = f"conic-gradient({', '.join(method_segments)})"

    return render(request, 'accounts/vendor_analytics.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'analytics',
        'analytics': analytics,
        'monthly_revenue': monthly_revenue,
        'monthly_line_points': " ".join(monthly_line_points),
        'payment_method_breakdown': payment_method_breakdown,
        'payment_method_gradient': payment_method_gradient,
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_settings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    active_subscription = _get_active_subscription(request.user)
    subscription_plans = VendorSubscriptionPlan.objects.filter(is_active=True).order_by('price', 'duration_days')
    return render(request, 'accounts/vendor_settings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'settings',
        'active_subscription': active_subscription,
        'subscription_plans': subscription_plans,
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect
def vendor_subscription_purchase(request, plan_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')
    if request.method != 'POST':
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=plan_id, is_active=True)
    payment_method = (request.POST.get('payment_method') or Booking.PAYMENT_METHOD_ESEWA).strip().lower()
    if payment_method not in {Booking.PAYMENT_METHOD_ESEWA, Booking.PAYMENT_METHOD_STRIPE}:
        payment_method = Booking.PAYMENT_METHOD_ESEWA

    payment_pid = f'SUB-{request.user.id}-{plan.id}-{uuid.uuid4().hex[:8].upper()}'
    payment_session = {
        'pid': payment_pid,
        'plan_id': plan.id,
        'payment_method': payment_method,
        'amount': format(plan.price, 'f'),
        'created_at': timezone.now().isoformat(),
    }
    request.session[_subscription_payment_session_key(request.user.id)] = payment_session
    request.session.modified = True

    if payment_method == Booking.PAYMENT_METHOD_STRIPE:
        success_url = (
            request.build_absolute_uri(reverse('vendor_subscription_stripe_success'))
            + '?session_id={CHECKOUT_SESSION_ID}'
        )
        cancel_url = request.build_absolute_uri(reverse('vendor_subscription_stripe_cancel'))

        try:
            session_data = create_checkout_session_for_item(
                amount=plan.price,
                name=f'{plan.name} Subscription',
                description=f'{plan.duration_days} days subscription plan',
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=payment_pid,
                metadata={
                    'type': 'subscription',
                    'pid': payment_pid,
                    'plan_id': plan.id,
                    'vendor_id': request.user.id,
                },
                customer_email=request.user.email or None,
            )
            checkout_url = session_data.get('url')
            if not checkout_url:
                raise StripeError('Stripe did not return a checkout URL.')
            payment_session['stripe_session_id'] = session_data.get('id', '')
            request.session[_subscription_payment_session_key(request.user.id)] = payment_session
            request.session.modified = True
            return redirect(checkout_url)
        except StripeError as exc:
            messages.error(request, str(exc))
            return redirect('vendor_settings')

    success_url = request.build_absolute_uri(reverse('vendor_subscription_esewa_success'))
    failure_url = request.build_absolute_uri(reverse('vendor_subscription_esewa_failure'))

    try:
        payload = _subscription_esewa_payload(
            amount=plan.price,
            pid=payment_pid,
            success_url=success_url,
            failure_url=failure_url,
        )
        payment_url = get_esewa_payment_url()
    except EsewaError as exc:
        messages.error(request, str(exc))
        return redirect('vendor_settings')

    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': None,
            'esewa_payment_url': payment_url,
            'esewa_payload': payload,
        },
    )


@never_cache
@login_required(login_url='vendor_login')
def vendor_subscription_esewa_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Subscription payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
        messages.error(request, 'Invalid payment callback for this subscription session.')
        return redirect('vendor_settings')

    transaction_id = ((request.GET.get('refId') or '') or (request.GET.get('rid') or '')).strip()
    callback_pid = ((request.GET.get('pid') or '') or (request.GET.get('oid') or '')).strip()

    expected_pid = payment_session.get('pid', '')
    if callback_pid and callback_pid != expected_pid:
        messages.error(request, 'Subscription payment verification failed: Product ID mismatch.')
        return redirect('vendor_settings')

    if not transaction_id:
        messages.error(request, 'Subscription payment verification failed: Missing transaction id.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Subscription payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    try:
        is_verified = verify_esewa_payment(
            amount=expected_amount,
            transaction_id=transaction_id,
            product_id=expected_pid,
        )
    except EsewaError as exc:
        messages.warning(request, f'eSewa verification is pending: {exc}')
        return redirect('vendor_settings')

    if not is_verified:
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        messages.error(request, 'Subscription payment failed verification. Please retry.')
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=payment_session.get('plan_id'))
    subscription = _activate_subscription_after_verified_payment(
        vendor=request.user,
        plan=plan,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_ESEWA,
    )

    request.session.pop(session_key, None)
    messages.success(request, f'{subscription.plan_name} subscription activated until {subscription.end_date:%b %d, %Y}.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')
def vendor_subscription_esewa_failure(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session:
        if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
            messages.error(request, 'Invalid payment callback for this subscription session.')
            return redirect('vendor_settings')
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        request.session.pop(session_key, None)

    messages.error(request, 'Subscription payment failed. Please try again.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')
def vendor_subscription_stripe_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Subscription payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_STRIPE:
        messages.error(request, 'Invalid payment callback for this subscription session.')
        return redirect('vendor_settings')

    stripe_session_id = (request.GET.get('session_id') or '').strip()
    if not stripe_session_id:
        messages.error(request, 'Missing Stripe checkout session id.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Subscription payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    try:
        session_data = retrieve_checkout_session(stripe_session_id)
    except StripeError as exc:
        messages.warning(request, f'Stripe verification is pending: {exc}')
        return redirect('vendor_settings')

    metadata = session_data.get('metadata') or {}
    expected_pid = payment_session.get('pid')
    is_paid = (
        session_data.get('status') == 'complete'
        and session_data.get('payment_status') == 'paid'
        and str(session_data.get('client_reference_id') or '') == str(expected_pid)
        and str(metadata.get('pid') or '') == str(expected_pid)
    )

    if not is_paid:
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        messages.error(request, 'Stripe payment was not marked as paid. Please retry.')
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=payment_session.get('plan_id'))
    subscription = _activate_subscription_after_verified_payment(
        vendor=request.user,
        plan=plan,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_STRIPE,
    )

    request.session.pop(session_key, None)
    messages.success(request, f'{subscription.plan_name} subscription activated until {subscription.end_date:%b %d, %Y}.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')
def vendor_subscription_stripe_cancel(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session and payment_session.get('payment_method') == Booking.PAYMENT_METHOD_STRIPE:
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        request.session.pop(session_key, None)

    messages.warning(request, 'Stripe checkout was canceled. You can try again anytime.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect
def vendor_feature_toggle(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')
    if request.method != 'POST':
        return redirect('vendor_packages')

    next_url = request.POST.get('next') or reverse('vendor_packages')
    package = get_object_or_404(Package, id=package_id, vendor=request.user)
    subscription = _get_active_subscription(request.user)

    if subscription is None:
        messages.error(request, 'Activate a subscription to feature packages.')
        return redirect(next_url)

    if not package.is_featured and subscription.max_featured_packages is not None:
        featured_count = Package.objects.filter(vendor=request.user, is_featured=True).count()
        if featured_count >= subscription.max_featured_packages:
            messages.error(
                request,
                f'Your plan allows up to {subscription.max_featured_packages} featured package(s).',
            )
            return redirect(next_url)

    package.is_featured = not package.is_featured
    package.save(update_fields=['is_featured'])
    status_label = 'featured' if package.is_featured else 'unfeatured'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect(next_url)


@never_cache
@login_required(login_url='vendor_login')
def vendor_profile(request):
    if not _ensure_vendor_account(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile is None:
        vendor_profile = VendorProfile.objects.create(
            user=request.user,
            business_name=request.user.get_full_name() or request.user.username,
            owner_name=request.user.get_full_name() or request.user.username,
        )

    if request.method == 'POST':
        had_promotions_enabled = bool(request.user.wants_promotions)
        old_logo_name = vendor_profile.logo.name if vendor_profile.logo else ''
        form = VendorProfileForm(request.POST, request.FILES, instance=vendor_profile)
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        wants_promotions = request.POST.get('wants_promotions') == 'on'
        remove_logo = request.POST.get('remove_logo') == '1'

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('vendor_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.wants_promotions = wants_promotions
        request.user.save()

        if form.is_valid():
            uploading_new_logo = bool(request.FILES.get('logo'))
            profile_instance = form.save(commit=False)

            if remove_logo:
                profile_instance.logo = None

            profile_instance.save()
            if remove_logo or uploading_new_logo:
                current_logo_name = profile_instance.logo.name if profile_instance.logo else ''
                if old_logo_name and old_logo_name != current_logo_name:
                    _delete_stored_file(profile_instance, 'logo', old_logo_name)

            if wants_promotions and not had_promotions_enabled:
                offers_count = _sync_active_special_offers_for_user(request.user)
                if offers_count:
                    messages.info(
                        request,
                        f'Limited-time special offers enabled. {offers_count} active offer notification(s) were added.',
                    )
            messages.success(request, 'Profile updated successfully.')
            return redirect('vendor_profile')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = VendorProfileForm(instance=vendor_profile)

    packages = Package.objects.filter(vendor=request.user).prefetch_related('images').order_by('-created_at')[:6]

    return render(request, 'accounts/vendor_profile.html', {
        'vendor_profile': vendor_profile,
        'form': form,
        'packages': packages,
        'active_page': 'profile',
    })


@never_cache
@admin_required
def admin_dashboard(request):
    VendorSubscription.expire_overdue()
    admin_profile = _get_admin_profile(request.user)
    vendors = User.objects.filter(user_type='vendor').select_related('vendor_profile').annotate(
        package_count=Count('vendor_packages', distinct=True),
    ).order_by('-date_joined')
    pending_vendors = vendors.filter(
        vendor_profile__is_approved=False,
        is_active=True,
    )
    travelers = User.objects.filter(user_type='traveler').order_by('-date_joined')
    packages = Package.objects.select_related('vendor').order_by('-created_at')
    bookings = Booking.objects.select_related(
        'package',
        'traveler',
        'vendor',
        'package__vendor',
    ).order_by('-created_at')
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')
    subscription_plans = VendorSubscriptionPlan.objects.order_by('price', 'duration_days')
    vendor_subscriptions = VendorSubscription.objects.select_related('vendor').order_by('-created_at')
    subscription_revenue = vendor_subscriptions.aggregate(total=Sum('price'))['total'] or 0
    featured_packages = Package.objects.filter(is_featured=True).select_related('vendor').order_by('-created_at')

    platform_earnings = bookings.filter(status='confirmed').aggregate(
        total=Sum('platform_fee')
    )['total'] or 0
    vendor_earnings = bookings.filter(status='confirmed').aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    total_bookings = bookings.count()
    active_vendors = vendors.filter(is_active=True, vendor_profile__is_approved=True).count()
    total_users = vendors.count() + travelers.count()
    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    activity_items = []
    for booking in bookings[:3]:
        actor = booking.traveler.get_full_name() if booking.traveler else 'Traveler'
        activity_items.append({
            'action': 'New Booking',
            'actor': actor or 'Traveler',
            'date': booking.created_at,
            'details': booking.package.title,
        })
    for vendor in vendors[:2]:
        vendor_profile = _get_vendor_profile(vendor)
        activity_items.append({
            'action': 'Vendor Registration',
            'actor': vendor_profile.business_name if vendor_profile else vendor.email,
            'date': vendor.date_joined,
            'details': 'Pending approval' if vendor_profile and not vendor_profile.is_approved else 'Approved',
        })
    for package in packages[:2]:
        activity_items.append({
            'action': 'Package Created',
            'actor': package.vendor.get_full_name() or package.vendor.email,
            'date': package.created_at,
            'details': package.title,
        })
    for review in reviews[:2]:
        activity_items.append({
            'action': 'Review Posted',
            'actor': review.traveler.get_full_name() if review.traveler else 'Traveler',
            'date': review.created_at,
            'details': f'{review.rating}-star rating',
        })
    activity_items.sort(key=lambda item: item['date'], reverse=True)
    activity_items = activity_items[:6]

    stats = {
        'total_vendors': vendors.count(),
        'pending_vendors': pending_vendors.count(),
        'total_travelers': travelers.count(),
        'total_packages': packages.count(),
        'active_packages': packages.filter(is_active=True).count(),
        'total_users': total_users,
        'active_vendors': active_vendors,
        'total_bookings': total_bookings,
        'platform_earnings': float(platform_earnings),
        'vendor_earnings': float(vendor_earnings),
        'subscription_revenue': float(subscription_revenue),
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating or 0, 1),
        'forum_posts': 0,
    }
    current_year = timezone.localdate().year
    analytics_years = [current_year - 2, current_year - 1, current_year]

    return render(request, 'accounts/admin_dashboard.html', {
        'admin_profile': admin_profile,
        'vendors': vendors,
        'pending_vendors': pending_vendors,
        'travelers': travelers,
        'packages': packages,
        'bookings': bookings,
        'subscription_plans': subscription_plans,
        'vendor_subscriptions': vendor_subscriptions,
        'featured_packages': featured_packages,
        'stats': stats,
        'activity_items': activity_items,
        'analytics_years': analytics_years,
        'selected_analytics_year': current_year,
        'active_page': 'dashboard',
    })


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


@admin_required
def admin_analytics_api(request):
    year_options = _admin_analytics_year_options()
    selected_year = _parse_admin_analytics_year(
        request.GET.get('year'),
        year_options,
    )

    bookings_for_year = Booking.objects.filter(created_at__year=selected_year)
    confirmed_bookings_for_year = bookings_for_year.filter(status=Booking.STATUS_CONFIRMED)
    subscriptions_for_year = VendorSubscription.objects.filter(created_at__year=selected_year)
    users_for_year = User.objects.filter(date_joined__year=selected_year)
    active_vendors_for_year = User.objects.filter(
        user_type='vendor',
        is_active=True,
        vendor_profile__is_approved=True,
        date_joined__year=selected_year,
    )

    monthly_platform_revenue = _monthly_sum_for_bookings(
        bookings_for_year,
        selected_year,
        'platform_fee',
        confirmed_only=True,
    )
    monthly_vendor_earnings = _monthly_sum_for_bookings(
        bookings_for_year,
        selected_year,
        'vendor_amount',
        confirmed_only=True,
    )
    monthly_bookings = _monthly_count_for_queryset(
        bookings_for_year,
        selected_year,
        'created_at',
    )
    monthly_subscription_revenue = []
    for month in range(1, 13):
        start, end = _month_range_dates(selected_year, month)
        total = subscriptions_for_year.filter(
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('price'))['total'] or 0
        monthly_subscription_revenue.append(float(total))
    monthly_new_users = _monthly_count_for_queryset(
        users_for_year,
        selected_year,
        'date_joined',
    )
    monthly_new_active_vendors = _monthly_count_for_queryset(
        active_vendors_for_year,
        selected_year,
        'date_joined',
    )

    category_data = _package_category_breakdown_for_year(selected_year)
    top_vendors = _top_vendor_earnings_for_year(selected_year)

    summary = {
        'platform_earnings': float(
            confirmed_bookings_for_year.aggregate(total=Sum('platform_fee'))['total'] or 0
        ),
        'vendor_earnings': float(
            confirmed_bookings_for_year.aggregate(total=Sum('vendor_amount'))['total'] or 0
        ),
        'subscription_revenue': float(
            subscriptions_for_year.aggregate(total=Sum('price'))['total'] or 0
        ),
        'total_users': users_for_year.count(),
        'active_vendors': active_vendors_for_year.count(),
        'total_bookings': bookings_for_year.count(),
    }

    payload = {
        'year': selected_year,
        'years': year_options,
        'months': _month_labels(),
        'summary': summary,
        'revenue': {
            'values': monthly_platform_revenue,
            'growth': _monthly_growth(monthly_platform_revenue, selected_year),
        },
        'vendor_earnings': {
            'values': monthly_vendor_earnings,
            'growth': _monthly_growth(monthly_vendor_earnings, selected_year),
        },
        'bookings': {
            'values': monthly_bookings,
            'growth': _monthly_growth(monthly_bookings, selected_year),
        },
        'subscriptions': {
            'values': monthly_subscription_revenue,
            'growth': _monthly_growth(monthly_subscription_revenue, selected_year),
        },
        'users': {
            'values': monthly_new_users,
            'growth': _monthly_growth(monthly_new_users, selected_year),
        },
        'active_vendors': {
            'values': monthly_new_active_vendors,
            'growth': _monthly_growth(monthly_new_active_vendors, selected_year),
        },
        'top_vendors': top_vendors,
        'categories': category_data,
    }
    return JsonResponse(payload)


@admin_required
@csrf_protect
def admin_profile(request):
    profile = _get_admin_profile(request.user)
    if profile is None:
        profile = AdminProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('admin_profile')

        current_password = request.POST.get('current_password') or ''
        new_password = request.POST.get('new_password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('admin_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.save()

        profile.bio = bio
        uploading_new_avatar = bool(avatar)
        if remove_avatar:
            profile.avatar = None
        elif avatar:
            profile.avatar = avatar

        profile.save()
        if remove_avatar or uploading_new_avatar:
            current_avatar_name = profile.avatar.name if profile.avatar else ''
            if old_avatar_name and old_avatar_name != current_avatar_name:
                _delete_stored_file(profile, 'avatar', old_avatar_name)

        if current_password or new_password or confirm_password:
            if not request.user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('admin_profile')
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return redirect('admin_profile')
            if len(new_password) < 6:
                messages.error(request, 'New password must be at least 6 characters long.')
                return redirect('admin_profile')
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password updated successfully.')
        else:
            messages.success(request, 'Profile updated successfully.')

        return redirect('admin_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    pending_vendors = User.objects.filter(
        user_type='vendor',
        vendor_profile__is_approved=False,
        is_active=True,
    ).select_related('vendor_profile').order_by('-date_joined')

    return render(request, 'accounts/admin_profile.html', {
        'profile': profile,
        'full_name': full_name,
        'pending_vendors': pending_vendors,
        'active_page': 'profile',
    })


@admin_required
@csrf_protect
def admin_vendor_action(request, vendor_id):
    next_url = (request.POST.get('next') or '').strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('admin_dashboard')

    if request.method != 'POST':
        return redirect(next_url)

    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    action = request.POST.get('action')

    if profile is None:
        messages.error(request, 'Vendor profile not found.')
        return redirect(next_url)

    if action == 'approve':
        profile.is_approved = True
        vendor.is_active = True
        create_notification(
            vendor,
            'Your vendor account was approved by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} approved.')
    elif action == 'reject':
        profile.is_approved = False
        vendor.is_active = False
        create_notification(
            vendor,
            'Your vendor account was rejected by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} rejected.')
    elif action == 'suspend':
        vendor.is_active = False
        create_notification(
            vendor,
            'Your vendor account was suspended by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} suspended.')
    elif action == 'activate':
        vendor.is_active = True
        create_notification(
            vendor,
            'Your vendor account was activated by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} activated.')
    elif action == 'verify':
        profile.is_verified = True
        create_notification(
            vendor,
            'Your vendor profile is now verified by Namaste Nomad.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} marked as verified.')
    elif action == 'unverify':
        profile.is_verified = False
        create_notification(
            vendor,
            'Your vendor verification badge was removed by admin.',
            Notification.TYPE_VENDOR_APPROVAL,
            related_object_id=vendor.id,
        )
        messages.success(request, f'{vendor.email} marked as unverified.')
    else:
        messages.error(request, 'Invalid action.')
        return redirect(next_url)

    vendor.save()
    profile.save()
    return redirect(next_url)


@admin_required
@csrf_protect
def admin_package_toggle(request, package_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    package.is_active = not package.is_active
    package.save()

    if package.vendor:
        if package.is_active:
            message = f'Your package "{package.title}" was approved by admin.'
        else:
            message = f'Your package "{package.title}" was hidden by admin.'
        create_notification(
            package.vendor,
            message,
            Notification.TYPE_PACKAGE_APPROVED,
            related_object_id=package.id,
        )

    status_label = 'activated' if package.is_active else 'deactivated'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_feature_toggle(request, package_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    if not package.is_featured:
        subscription = VendorSubscription.active_for_vendor(package.vendor)
        if subscription is None:
            messages.error(request, 'Vendor has no active subscription for featuring.')
            return redirect('admin_dashboard')
        if subscription.max_featured_packages is not None:
            featured_count = Package.objects.filter(
                vendor=package.vendor,
                is_featured=True,
            ).count()
            if featured_count >= subscription.max_featured_packages:
                messages.error(
                    request,
                    f'{package.vendor.email} has reached the featured package limit.',
                )
                return redirect('admin_dashboard')

    package.is_featured = not package.is_featured
    package.save(update_fields=['is_featured'])

    status_label = 'featured' if package.is_featured else 'unfeatured'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_subscription_plan_create(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    name = (request.POST.get('name') or '').strip()
    price_raw = (request.POST.get('price') or '').strip()
    duration_raw = (request.POST.get('duration_days') or '').strip()
    limit_raw = (request.POST.get('max_featured_packages') or '').strip()

    if not name or not price_raw or not duration_raw:
        messages.error(request, 'Plan name, price, and duration are required.')
        return redirect('admin_dashboard')

    try:
        price = Decimal(price_raw)
        duration_days = int(duration_raw)
        max_featured_packages = int(limit_raw) if limit_raw else None
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, 'Invalid subscription plan values.')
        return redirect('admin_dashboard')

    if duration_days < 1:
        messages.error(request, 'Duration must be at least 1 day.')
        return redirect('admin_dashboard')
    if price < 0:
        messages.error(request, 'Price must be a positive value.')
        return redirect('admin_dashboard')
    if max_featured_packages is not None and max_featured_packages < 1:
        messages.error(request, 'Featured limit must be at least 1.')
        return redirect('admin_dashboard')

    try:
        VendorSubscriptionPlan.objects.create(
            name=name,
            price=price,
            duration_days=max(duration_days, 1),
            max_featured_packages=max_featured_packages,
            is_active=True,
        )
    except IntegrityError:
        messages.error(request, 'A plan with that name already exists.')
    else:
        messages.success(request, 'Subscription plan created.')
    return redirect('admin_dashboard')


@admin_required
def admin_vendor_detail(request, vendor_id):
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    admin_profile = _get_admin_profile(request.user)
    packages = Package.objects.filter(vendor=vendor).order_by('-created_at')

    return render(request, 'accounts/admin_vendor_detail.html', {
        'admin_profile': admin_profile,
        'vendor': vendor,
        'vendor_profile': profile,
        'packages': packages,
        'active_page': 'vendors',
    })


def vendor_public_profile(request, vendor_id):
    vendor = get_object_or_404(
        User.objects.select_related('vendor_profile'),
        id=vendor_id,
        user_type='vendor',
    )
    profile = _get_vendor_profile(vendor)
    packages = (
        Package.objects.filter(vendor=vendor, is_active=True).select_related('vendor', 'vendor__vendor_profile')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
        )
        .order_by('-created_at')
    )

    return render(request, 'accounts/vendor_public_profile.html', {
        'vendor': vendor,
        'vendor_profile': profile,
        'packages': packages,
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_package_create(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)

    if request.method == 'POST':
        form = PackageForm(request.POST, vendor=request.user)
        if form.is_valid():
            limited_time_offer = bool(form.cleaned_data.get('limited_time_offer'))
            package = form.save(commit=False)
            package.vendor = request.user
            package.save()
            _append_package_images(package, request.FILES.getlist('images'))
            notify_admins(
                f'Vendor submitted new package: {package.title}',
                Notification.TYPE_PACKAGE_SUBMISSION,
                related_object_id=package.id,
            )
            if limited_time_offer:
                notified_count = _notify_opted_in_travelers_for_limited_package_offer(package)
                if notified_count:
                    messages.info(
                        request,
                        f'Limited-time offer notifications sent to {notified_count} opted-in traveler(s).',
                    )
            messages.success(request, 'Package created successfully.')
            return redirect('vendor_packages')
    else:
        form = PackageForm(vendor=request.user)

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': False,
        'existing_images': [],
        'active_subscription': _get_active_subscription(request.user),
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_package_edit(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    package = get_object_or_404(
        Package.objects.prefetch_related('images'),
        id=package_id,
        vendor=request.user,
    )

    if request.method == 'POST':
        form = PackageForm(request.POST, instance=package, vendor=request.user)
        if form.is_valid():
            package = form.save()
            _sync_package_images(package, request.POST, request.FILES)
            messages.success(request, 'Package updated successfully.')
            return redirect('vendor_package_edit', package_id=package.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PackageForm(instance=package, vendor=request.user)

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': True,
        'package': package,
        'existing_images': package.images.all(),
        'active_subscription': _get_active_subscription(request.user),
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect
def vendor_package_delete(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    next_url = request.POST.get('next') or reverse('vendor_packages')
    if request.method != 'POST':
        return redirect(next_url)

    package = get_object_or_404(
        Package.objects.annotate(booking_count=Count('bookings')),
        id=package_id,
        vendor=request.user,
    )
    if package.booking_count:
        messages.error(
            request,
            'Cannot delete a package with existing bookings. Please set it inactive instead.',
        )
        return redirect(next_url)

    package.delete()
    messages.success(request, 'Package deleted successfully.')
    return redirect(next_url)


@require_POST
@login_required(login_url='account_login_choice')
def wishlist_toggle(request):
    if getattr(request.user, 'user_type', '') != 'traveler':
        return JsonResponse(
            {'error': 'forbidden', 'message': 'Traveler access only.'},
            status=403,
        )

    package_id = request.POST.get('package_id')
    if not package_id:
        return JsonResponse({'error': 'missing_package'}, status=400)
    try:
        package_id = int(package_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_package'}, status=400)

    existing = Wishlist.objects.filter(traveler=request.user, package_id=package_id).first()
    if existing:
        existing.delete()
        status = 'removed'
        is_wishlisted = False
    else:
        package = get_object_or_404(Package, id=package_id, is_active=True)
        try:
            Wishlist.objects.create(traveler=request.user, package=package)
        except IntegrityError:
            pass
        status = 'added'
        is_wishlisted = True
        add_points(request.user, 'wishlist', 5)
        sync_badges_for_user(request.user)

    count = Wishlist.objects.filter(traveler=request.user).count()
    return JsonResponse({
        'status': status,
        'is_wishlisted': is_wishlisted,
        'count': count,
        'package_id': package_id,
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_home(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    wishlist_ids = set(
        Wishlist.objects.filter(traveler=request.user).values_list('package_id', flat=True)
    )

    search_query = (request.GET.get('q') or '').strip()
    selected_category = (request.GET.get('category') or 'all').strip().lower()
    if selected_category not in {'all', *TRAVELER_CATEGORY_SLUGS}:
        selected_category = 'all'

    base_packages = _traveler_package_queryset()
    filtered_packages = base_packages

    if search_query:
        filtered_packages = filtered_packages.filter(
            Q(title__icontains=search_query)
            | Q(location__icontains=search_query)
            | Q(location_name__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    if selected_category != 'all':
        filtered_packages = filtered_packages.filter(category_slug=selected_category)

    category_counts = {
        'all': base_packages.count(),
        **{slug: 0 for slug in TRAVELER_CATEGORY_SLUGS},
    }
    for row in base_packages.values('category_slug').annotate(total=Count('id')):
        slug = row['category_slug']
        if slug in category_counts:
            category_counts[slug] = row['total']

    featured_packages = list(
        filtered_packages.order_by(
            '-avg_rating',
            '-review_count',
            '-views_count',
            '-created_at',
        )[:4]
    )
    featured_ids = {package.id for package in featured_packages}

    recommended_packages = list(
        filtered_packages.exclude(id__in=featured_ids).order_by(
            '-booking_count',
            '-avg_rating',
            '-review_count',
            '-views_count',
            '-created_at',
        )[:4]
    )

    recommended_ids = featured_ids | {package.id for package in recommended_packages}
    recently_added_packages = list(
        filtered_packages.exclude(id__in=recommended_ids).order_by('-created_at')[:4]
    )

    _add_category_labels(featured_packages)
    _add_category_labels(recommended_packages)
    _add_category_labels(recently_added_packages)

    recent_reviews = Review.objects.filter(package__is_active=True).select_related(
        'traveler',
        'package',
    ).order_by('-created_at')[:6]

    category_filters = [
        {'slug': 'all', 'label': 'All', 'count': category_counts['all']},
        *[
            {
                'slug': slug,
                'label': TRAVELER_CATEGORY_LABELS[slug],
                'count': category_counts[slug],
            }
            for slug in TRAVELER_CATEGORY_SLUGS
        ],
    ]

    return render(request, 'accounts/traveler_home.html', {
        'traveler_profile': profile,
        'active_page': 'explore',
        'search_query': search_query,
        'selected_category': selected_category,
        'category_filters': category_filters,
        'featured_packages': featured_packages,
        'recommended_packages': recommended_packages,
        'recently_added_packages': recently_added_packages,
        'recent_reviews': recent_reviews,
        'result_count': filtered_packages.count(),
        'can_clear_filters': bool(search_query or selected_category != 'all'),
        'wishlist_ids': wishlist_ids,
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_wishlist(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    wishlist_items = (
        Wishlist.objects.filter(traveler=request.user)
        .select_related('package', 'package__vendor')
        .prefetch_related('package__images')
        .order_by('-created_at')
    )
    wishlist_ids = set(wishlist_items.values_list('package_id', flat=True))

    return render(request, 'accounts/traveler_wishlist.html', {
        'traveler_profile': profile,
        'wishlist_items': wishlist_items,
        'wishlist_ids': wishlist_ids,
        'active_page': 'wishlist',
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_achievements(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    sync_badges_for_user(request.user)
    badges, summary, next_badge = badge_progress_for_user(request.user)
    total_points = total_points_for_user(request.user)

    earned_badges = [
        entry.badge
        for entry in UserBadge.objects.filter(user=request.user)
        .select_related('badge')
        .order_by('-earned_at')
    ]

    return render(request, 'accounts/traveler_achievements.html', {
        'traveler_profile': profile,
        'badges': badges,
        'earned_badges': earned_badges,
        'total_points': total_points,
        'earned_badge_count': summary.get('earned_count', 0),
        'total_badges': summary.get('total_badges', 0),
        'next_badge': next_badge,
        'active_page': 'achievements',
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_bookings(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    bookings = Booking.objects.filter(traveler=request.user).select_related(
        'package',
    ).order_by('-created_at')

    return render(request, 'accounts/traveler_bookings.html', {
        'traveler_profile': profile,
        'bookings': bookings,
        'active_page': 'bookings',
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_transactions(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    transactions = Transaction.objects.filter(traveler=request.user).select_related(
        'booking',
        'booking__package',
        'vendor',
    )
    transactions, filters = _apply_transaction_filters(transactions, request)
    transactions = transactions.order_by('-created_at')

    if request.GET.get('export') == 'csv':
        return _transaction_csv_response(transactions, 'traveler-transactions.csv')

    return render(request, 'accounts/traveler_transactions.html', {
        'traveler_profile': profile,
        'transactions': transactions,
        'filters': filters,
        'active_page': 'transactions',
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_transactions(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    transactions = Transaction.objects.filter(vendor=request.user).select_related(
        'booking',
        'booking__package',
        'traveler',
    )
    transactions, filters = _apply_transaction_filters(transactions, request)
    transactions = transactions.order_by('-created_at')

    if request.GET.get('export') == 'csv':
        return _transaction_csv_response(transactions, 'vendor-transactions.csv')

    return render(request, 'accounts/vendor_transactions.html', {
        'vendor_profile': vendor_profile,
        'transactions': transactions,
        'filters': filters,
        'active_page': 'transactions',
    })


@never_cache
@admin_required
def admin_transactions(request):
    admin_profile = _get_admin_profile(request.user)
    transactions = Transaction.objects.select_related(
        'booking',
        'booking__package',
        'traveler',
        'vendor',
    )
    transactions, filters = _apply_transaction_filters(transactions, request, allow_vendor=True)
    transactions = transactions.order_by('-created_at')
    vendor_choices = User.objects.filter(user_type='vendor').order_by('email')

    if request.GET.get('export') == 'csv':
        return _transaction_csv_response(transactions, 'admin-transactions.csv')

    return render(request, 'accounts/admin_transactions.html', {
        'admin_profile': admin_profile,
        'transactions': transactions,
        'filters': filters,
        'vendor_choices': vendor_choices,
        'active_page': 'transactions',
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_profile(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        wants_promotions = request.POST.get('wants_promotions') == 'on'
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender') or ''
        nationality = (request.POST.get('nationality') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('traveler_profile')

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('traveler_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.wants_promotions = wants_promotions
        request.user.save()

        profile.gender = gender
        profile.nationality = nationality
        profile.bio = bio
        profile.date_of_birth = date_of_birth or None
        uploading_new_avatar = bool(avatar)
        if remove_avatar:
            profile.avatar = None
        elif avatar:
            profile.avatar = avatar
        profile.save()
        if remove_avatar or uploading_new_avatar:
            current_avatar_name = profile.avatar.name if profile.avatar else ''
            if old_avatar_name and old_avatar_name != current_avatar_name:
                _delete_stored_file(profile, 'avatar', old_avatar_name)

        messages.success(request, 'Profile updated successfully.')
        return redirect('traveler_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    sync_badges_for_user(request.user)
    traveler_reviews = Review.objects.filter(traveler=request.user).select_related('package').order_by('-created_at')[:6]
    review_packages = Package.objects.filter(is_active=True).order_by('title')
    activity = [
        {
            'title': 'Left a review for Everest Base Camp Trek',
            'time': '2 days ago',
            'variant': 'review',
        },
        {
            'title': 'Completed Annapurna Circuit',
            'time': '1 week ago',
            'variant': 'completed',
        },
        {
            'title': 'Earned "High Altitude" badge',
            'time': '2 weeks ago',
            'variant': 'badge',
        },
    ]

    return render(request, 'accounts/traveler_profile.html', {
        'traveler_profile': profile,
        'profile': profile,
        'full_name': full_name,
        'traveler_reviews': traveler_reviews,
        'review_packages': review_packages,
        'activity': activity,
        'active_page': 'profile',
    })


@never_cache
@csrf_protect
def vendor_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        remember_me = request.POST.get('remember_me')
        next_url = _safe_next_url(request, 'vendor_dashboard')
        
        try:
            user = User.objects.get(email=email, user_type='vendor')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                vendor_profile = _get_vendor_profile(user)
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                if vendor_profile and not vendor_profile.is_approved:
                    messages.info(request, 'Your account is pending admin approval.')
                    return redirect('vendor_profile')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No vendor account found with this email')
    
    return render(request, 'accounts/vendor_login.html')

@never_cache
@csrf_protect
def vendor_register(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        business_name = (request.POST.get('business_name') or '').strip()
        owner_name = (request.POST.get('owner_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        wants_promotions = request.POST.get('wants_promotions') == 'on'
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        document = request.FILES.get('document')

        if not business_name or not owner_name or not email or not phone:
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'accounts/vendor_register.html')

        if not document:
            messages.error(request, 'Verification document is required for vendor registration.')
            return render(request, 'accounts/vendor_register.html')

        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
        allowed_mime_types = {'application/pdf', 'image/jpeg', 'image/png'}
        document_ext = Path(document.name).suffix.lower()
        document_type = (getattr(document, 'content_type', '') or '').lower()
        if document_ext not in allowed_extensions or (document_type and document_type not in allowed_mime_types):
            messages.error(request, 'Please upload a valid PDF, JPG, JPEG, or PNG file.')
            return render(request, 'accounts/vendor_register.html')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'accounts/vendor_register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'accounts/vendor_register.html')
        
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            user_type='vendor',
            phone=phone,
            is_verified=False,
            is_active=False,
            wants_promotions=wants_promotions,
        )

        if wants_promotions:
            _sync_active_special_offers_for_user(user)
        
        # Create vendor profile
        VendorProfile.objects.create(
            user=user,
            business_name=business_name,
            owner_name=owner_name,
            business_license=document,
            document=document,
        )

        notify_admins(
            f'New vendor registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        
        # Send OTP
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/vendor_register.html')

@never_cache
@csrf_protect
def traveler_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        next_url = _safe_next_url(request, 'traveler_home')
        
        try:
            user = User.objects.get(email=email, user_type='traveler')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                login(request, user)
                if _get_traveler_profile(user) is None:
                    TravelerProfile.objects.create(user=user)
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No traveler account found with this email')
    
    return render(request, 'accounts/traveler_login.html')

@never_cache
@csrf_protect
def admin_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        remember_me = request.POST.get('remember_me')
        next_url = _safe_next_url(request, 'admin_dashboard')
        
        try:
            user = User.objects.get(email=email, user_type='admin')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None and user.is_staff:
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials or insufficient permissions')
        except User.DoesNotExist:
            messages.error(request, 'No admin account found')
    
    return render(request, 'accounts/admin_login.html')

@csrf_protect
def verify_otp_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('vendor_login')
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('vendor_login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if verify_otp_util(user, otp_code):
            user.is_verified = True
            user.is_active = True
            user.save()
            login(request, user)
            del request.session['user_id']
            
            messages.success(request, 'Email verified successfully!')
            if user.user_type == 'traveler':
                if _get_traveler_profile(user) is None:
                    TravelerProfile.objects.create(user=user)
            return redirect(_dashboard_route_name(user))
        else:
            messages.error(request, 'Invalid or expired OTP')
    
    return render(request, 'accounts/verify_otp.html', {'email': user.email})

@csrf_protect
def resend_otp(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('vendor_login')
    
    try:
        user = User.objects.get(id=user_id)
        _, sent = create_otp(user)
        if sent:
            messages.success(request, 'New OTP sent to your email')
        else:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
    except User.DoesNotExist:
        messages.error(request, 'User not found')
    
    return redirect('verify_otp')

@never_cache
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('home')

@never_cache
@csrf_protect
def traveler_register(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        wants_promotions = request.POST.get('wants_promotions') == 'on' or request.POST.get('newsletter') == 'on'
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'accounts/traveler_register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'accounts/traveler_register.html')
        
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            user_type='traveler',
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            is_verified=False,
            is_active=False,
            wants_promotions=wants_promotions,
        )

        TravelerProfile.objects.create(user=user)

        notify_admins(
            f'New traveler registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        
        # Send OTP
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/traveler_register.html')


def landing(request):
    return render(request, 'landing.html')


@never_cache
def account_register_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    return render(request, 'accounts/register_choice.html')


@never_cache
def account_login_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    return render(request, 'accounts/login_choice.html')
