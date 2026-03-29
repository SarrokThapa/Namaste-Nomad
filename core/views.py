# core/views.py
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Min, OuterRef, Prefetch, Q, Subquery, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.utils.html import escape, mark_safe

from accounts.models import (
    FeatureSlot,
    Notification,
    RewardPoint,
    TravelerProfile,
    UserBadge,
    VendorFeature,
    VendorSubscription,
)
from accounts.achievements import (
    add_points,
    sync_badges_for_user,
    total_points_for_user,
    discount_for_points,
)
from accounts.notifications import create_notification, notify_admins
from .forms import BookingForm, CommentForm, ContactMessageForm, PostEditForm, PostForm, ReviewForm
from .invoices import generate_invoice_pdf, invoice_data_for_booking
from .models import (
    Booking,
    Comment,
    Discount,
    Package,
    Post,
    PostMedia,
    Review,
    SpecialOffer,
    SupportConversation,
    SupportMessage,
    Transaction,
    TravelTip,
    Wishlist,
)
from .payments import (
    EsewaError,
    StripeError,
    build_esewa_payment_payload,
    create_checkout_session,
    expire_checkout_session,
    get_esewa_payment_url,
    retrieve_checkout_session,
    verify_esewa_payment,
)

BLOG_POSTS = [
    {
        'slug': 'top-5-treks-in-nepal',
        'title': 'Top 5 Treks in Nepal',
        'excerpt': 'A practical guide to Nepal\'s most iconic routes, from Everest to Tilicho.',
        'published_on': date(2026, 2, 18),
        'read_time': '6 min read',
        'image_path': 'images/featured/everest-base-camp.jpg',
        'intro': (
            'Nepal offers trekking routes for every type of traveler. If you are planning your first '
            'high-altitude adventure, start with trails that combine scenic value, accessible logistics, '
            'and reliable local support.'
        ),
        'sections': [
            {
                'heading': '1. Everest Base Camp Trek',
                'body': (
                    'Best for dramatic Himalayan views and classic lodge trekking. It is physically '
                    'demanding, but the route has excellent tea-house infrastructure.'
                ),
            },
            {
                'heading': '2. Annapurna Circuit',
                'body': (
                    'Best for diversity. You pass through subtropical valleys, alpine regions, and '
                    'high mountain passes in a single itinerary.'
                ),
            },
            {
                'heading': '3. Manaslu Circuit',
                'body': (
                    'Best for remote trail experience. Visitor numbers are lower, and the cultural '
                    'immersion in mountain villages is exceptional.'
                ),
            },
            {
                'heading': '4. Tilicho Lake Trek',
                'body': (
                    'Best for short high-impact adventure. The turquoise alpine lake setting is one of '
                    'the most memorable viewpoints in Nepal.'
                ),
            },
            {
                'heading': '5. Langtang Valley Trek',
                'body': (
                    'Best for accessibility from Kathmandu. It combines mountain scenery with strong '
                    'Tamang cultural heritage.'
                ),
            },
        ],
    },
    {
        'slug': 'best-time-to-visit-annapurna',
        'title': 'Best Time to Visit Annapurna',
        'excerpt': 'When to go, what to expect by season, and how weather affects your itinerary.',
        'published_on': date(2026, 1, 27),
        'read_time': '5 min read',
        'image_path': 'images/featured/annapurna-circuit.jpg',
        'intro': (
            'Annapurna is possible in most seasons, but weather patterns can change your experience '
            'significantly. Choosing the right season improves visibility, trail comfort, and safety.'
        ),
        'sections': [
            {
                'heading': 'Spring (March to May)',
                'body': (
                    'Rhododendron forests bloom, temperatures are moderate, and the skies are often clear. '
                    'This is one of the most popular windows for Annapurna.'
                ),
            },
            {
                'heading': 'Autumn (September to November)',
                'body': (
                    'Post-monsoon air quality and mountain visibility are excellent. Trails are busy, '
                    'but logistics are very reliable.'
                ),
            },
            {
                'heading': 'Winter (December to February)',
                'body': (
                    'Lower traffic and quiet trails can be great, but high passes may be icy or blocked. '
                    'Use experienced local operators for route planning.'
                ),
            },
            {
                'heading': 'Monsoon (June to August)',
                'body': (
                    'Frequent rain, leeches, and cloud cover make this the most challenging season. '
                    'Some lower routes are still possible with flexible planning.'
                ),
            },
        ],
    },
    {
        'slug': 'hidden-lakes-in-nepal',
        'title': 'Hidden Lakes in Nepal',
        'excerpt': 'Lesser-known alpine lakes worth adding to your itinerary beyond the popular routes.',
        'published_on': date(2025, 12, 9),
        'read_time': '7 min read',
        'image_path': 'images/featured/tilicho-lake.jpg',
        'intro': (
            'Beyond the famous circuits, Nepal has remarkable high-altitude lakes with quieter trails '
            'and unique landscapes. These destinations are perfect for photographers and slow travelers.'
        ),
        'sections': [
            {
                'heading': 'Kapuche Lake',
                'body': (
                    'Known as one of the lowest glacial lakes in the world, Kapuche offers dramatic scenery '
                    'with relatively short approach treks.'
                ),
            },
            {
                'heading': 'Dudh Pokhari',
                'body': (
                    'A sacred alpine lake in the Lamjung region. The route is peaceful and culturally rich, '
                    'especially during local festival periods.'
                ),
            },
            {
                'heading': 'Gokyo Lakes',
                'body': (
                    'Not exactly hidden but often overshadowed by EBC itineraries. The turquoise lake chain '
                    'and Gokyo Ri viewpoint are exceptional.'
                ),
            },
            {
                'heading': 'Rara Lake',
                'body': (
                    'Nepal\'s largest lake with deep blue water and pine forests. It requires longer travel '
                    'logistics but rewards you with a very different landscape.'
                ),
            },
        ],
    },
]


def _safe_related(instance, attribute_name):
    try:
        return getattr(instance, attribute_name)
    except ObjectDoesNotExist:
        return None


def _user_display_name(user):
    if not user:
        return "Traveler"
    full_name = user.get_full_name().strip()
    return full_name or user.username or "Traveler"


def _user_avatar_url(user):
    if not user:
        return ""

    user_type = getattr(user, 'user_type', '')
    if user_type == 'traveler':
        profile = _safe_related(user, 'traveler_profile')
        if profile and profile.avatar:
            return profile.avatar.url
    elif user_type == 'vendor':
        profile = _safe_related(user, 'vendor_profile')
        if profile and profile.logo:
            return profile.logo.url
    elif user_type == 'admin':
        profile = _safe_related(user, 'admin_profile')
        if profile and profile.avatar:
            return profile.avatar.url

    return ""


def _public_profile_url_for_user(user):
    if not user:
        return ''

    user_type = getattr(user, 'user_type', '')
    if user_type == 'traveler':
        return reverse('public_traveler_profile', kwargs={'user_id': user.id})
    if user_type == 'vendor':
        return reverse('vendor_public_profile', kwargs={'vendor_id': user.id})
    return ''


def _vendor_display_name(vendor):
    if not vendor:
        return "Vendor"

    profile = _safe_related(vendor, 'vendor_profile')
    if profile:
        business_name = (profile.business_name or '').strip()
        if business_name:
            return business_name

    full_name = vendor.get_full_name().strip()
    if full_name:
        return full_name

    username = (getattr(vendor, 'username', '') or '').strip()
    if username and '@' not in username:
        return username

    return "Vendor"


def _vendor_is_verified(vendor):
    if not vendor:
        return False
    profile = _safe_related(vendor, 'vendor_profile')
    return bool(profile and profile.is_verified)


def _verified_badge_html(is_verified):
    if not is_verified:
        return ""
    return (
        '<span class="verified-badge verified-badge--tiny">'
        '<span class="verified-badge-icon">✔</span>'
        '<span>Verified</span>'
        '</span>'
    )


TAG_PATTERN = re.compile(r'@([A-Za-z0-9_.+-]+)')


def _caption_with_vendor_links(post):
    caption = post.caption or ""
    if not caption:
        caption = ""

    tagged_vendors = list(getattr(post, 'tagged_vendors', []).all())
    vendor_lookup = {
        vendor.username.lower(): (
            _vendor_display_name(vendor),
            reverse('vendor_public_profile', kwargs={'vendor_id': vendor.id}),
            _vendor_is_verified(vendor),
        )
        for vendor in tagged_vendors
    }
    escaped_caption = escape(caption)

    def _replace(match):
        username = match.group(1)
        key = username.lower()
        if key in vendor_lookup:
            display, url, is_verified = vendor_lookup[key]
            safe_display = escape(display)
            return (
                f'<a class="tagged-mention" href="{url}">@{safe_display}</a>'
                f'{_verified_badge_html(is_verified)}'
            )
        return f'@{username}'

    linked = TAG_PATTERN.sub(_replace, escaped_caption)

    # Append tagged vendors not already mentioned in the caption.
    if tagged_vendors:
        mentioned = {match.group(1).lower() for match in TAG_PATTERN.finditer(caption)}
        missing = [vendor for vendor in tagged_vendors if vendor.username.lower() not in mentioned]
        if missing:
            extras = " ".join(
                f'<a class="tagged-mention" href="{reverse("vendor_public_profile", kwargs={"vendor_id": vendor.id})}">@{escape(_vendor_display_name(vendor))}</a>'
                f'{_verified_badge_html(_vendor_is_verified(vendor))}'
                for vendor in missing
            )
            tag_line = f'<span class="caption-tags"><span class="caption-tags-label">Tagged:</span> {extras}</span>'
            if linked:
                linked = f"{linked}<br>{tag_line}"
            else:
                linked = tag_line

    linked = linked.replace('\n', '<br>')
    return mark_safe(linked)


def _prepare_review_cards(review_queryset):
    reviews = list(review_queryset)

    for review in reviews:
        traveler = review.traveler
        review.traveler_name = _user_display_name(traveler)
        review.traveler_avatar_url = _user_avatar_url(traveler)
        review.traveler_profile_url = _public_profile_url_for_user(traveler)

    return reviews


def _prepare_feed_posts(post_queryset, viewer=None):
    posts = list(post_queryset)
    viewer_id = viewer.id if getattr(viewer, 'is_authenticated', False) else None

    for post in posts:
        if getattr(post.user, 'user_type', '') == 'vendor':
            post.author_name = _vendor_display_name(post.user)
        else:
            post.author_name = _user_display_name(post.user)
        post.author_avatar_url = _user_avatar_url(post.user)
        post.author_profile_url = _public_profile_url_for_user(post.user)
        post.author_is_verified_vendor = (
            getattr(post.user, 'user_type', '') == 'vendor'
            and _vendor_is_verified(post.user)
        )
        post.caption_html = _caption_with_vendor_links(post)

        media_items = list(getattr(post, 'media', []).all())
        if not media_items and post.image:
            media_items = [{'media_file': post.image, 'media_type': PostMedia.MEDIA_IMAGE}]
        post.media_items = media_items
        post.media_count = len(media_items)

        like_user_ids = {user.id for user in post.likes.all()}
        post.like_count = len(like_user_ids)
        post.is_liked_by_current_user = viewer_id in like_user_ids if viewer_id else False

        all_comments = list(post.comments.all())
        post.comment_count = len(all_comments)
        comment_lookup = {}
        top_level_comments = []

        for comment in all_comments:
            comment.author_name = _user_display_name(comment.user)
            comment.author_avatar_url = _user_avatar_url(comment.user)
            comment.author_profile_url = _public_profile_url_for_user(comment.user)
            comment.prepared_replies = []
            comment_lookup[comment.id] = comment

        for comment in all_comments:
            if comment.parent_id:
                parent = comment_lookup.get(comment.parent_id)
                if parent:
                    parent.prepared_replies.append(comment)
            else:
                top_level_comments.append(comment)

        post.prepared_comments = top_level_comments

    return posts


def _traveler_level_label(total_points):
    return 'Pro Traveler' if total_points >= 200 else 'Beginner Traveler'


def _community_posts(viewer=None):
    user_model = get_user_model()
    comment_queryset = Comment.objects.select_related(
        'user',
        'user__traveler_profile',
        'user__vendor_profile',
        'user__admin_profile',
    ).order_by('created_at')

    return _prepare_feed_posts(
        Post.objects.select_related(
            'user',
            'user__traveler_profile',
            'user__vendor_profile',
            'user__admin_profile',
        ).prefetch_related(
            Prefetch('comments', queryset=comment_queryset),
            Prefetch('likes', queryset=user_model.objects.only('id')),
            Prefetch(
                'tagged_vendors',
                queryset=user_model.objects.select_related('vendor_profile').only(
                    'id',
                    'username',
                    'first_name',
                    'last_name',
                    'user_type',
                    'vendor_profile__business_name',
                ),
            ),
            Prefetch('media', queryset=PostMedia.objects.all()),
        ),
        viewer=viewer,
    )


def _get_or_create_traveler_profile(user):
    profile = _safe_related(user, 'traveler_profile')
    if profile is None:
        profile = TravelerProfile.objects.create(user=user)
    return profile


def _stripe_checkout_ttl_minutes():
    try:
        minutes = int(getattr(settings, 'STRIPE_CHECKOUT_TTL_MINUTES', 30))
    except (TypeError, ValueError):
        minutes = 30
    return max(minutes, 30)


def _booking_payment_expires_at():
    return timezone.now() + timedelta(minutes=_stripe_checkout_ttl_minutes())


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


def _mark_payment_failed(booking):
    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return
    booking.payment_status = Booking.PAYMENT_STATUS_FAILED
    booking.save(update_fields=['payment_status'])


def _as_money_decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _best_available_discount_for_user(user, original_total):
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


def _can_access_booking_invoice(user, booking):
    if not user.is_authenticated:
        return False
    if getattr(user, 'user_type', '') == 'admin' and user.is_staff:
        return True
    return booking.traveler_id == user.id


def _notify_booking_created(booking):
    if booking.vendor:
        create_notification(
            booking.vendor,
            f'New booking request for {booking.package.title}.',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    notify_admins(
        f'New booking created for {booking.package.title}.',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _notify_booking_paid(booking):
    if booking.vendor:
        create_notification(
            booking.vendor,
            f'Payment completed for booking #{booking.id} ({booking.package.title}).',
            Notification.TYPE_BOOKING,
            related_object_id=booking.id,
        )
    notify_admins(
        f'Payment completed for booking #{booking.id} ({booking.package.title}).',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _get_or_create_open_support_conversation_for_user(user):
    conversation = (
        SupportConversation.objects.filter(
            user=user,
            status=SupportConversation.STATUS_OPEN,
        )
        .order_by('-created_at', '-id')
        .first()
    )
    if conversation is not None:
        return conversation
    return SupportConversation.objects.create(user=user)


def _vendor_display_for_auto_message(vendor):
    if vendor is None:
        return 'Vendor Team'
    full_name = vendor.get_full_name().strip()
    if full_name:
        return full_name
    return vendor.username or vendor.email or 'Vendor Team'


def _send_post_booking_vendor_message(booking):
    traveler = booking.traveler
    vendor = booking.vendor or booking.package.vendor
    if traveler is None or vendor is None:
        return

    existing_message = SupportMessage.objects.filter(
        related_booking=booking,
        is_system_generated=True,
        sender=vendor,
    ).exists()
    if existing_message:
        return

    conversation = _get_or_create_open_support_conversation_for_user(traveler)
    traveler_name = traveler.get_full_name().strip() or traveler.username or 'Traveler'
    vendor_name = _vendor_display_for_auto_message(vendor)
    travel_date_label = booking.travel_date.strftime('%b %d, %Y')
    vendor_phone = (getattr(vendor, 'phone', '') or '').strip() or 'N/A'
    vendor_email = (getattr(vendor, 'email', '') or '').strip() or 'N/A'

    message_body = (
        f'Hello {traveler_name},\n\n'
        'Thank you for booking with us!\n\n'
        f'Package: {booking.package.title}\n'
        f'Travel Date: {travel_date_label}\n'
        f'People: {booking.number_of_people}\n\n'
        'For further details, feel free to contact us:\n'
        f'Phone: {vendor_phone}\n'
        f'Email: {vendor_email}\n\n'
        'We will also reach out to you shortly.\n\n'
        'Thank you for choosing our service!\n\n'
        f'- {vendor_name}'
    )

    SupportMessage.objects.create(
        conversation=conversation,
        sender=vendor,
        related_booking=booking,
        message=message_body,
        is_admin_reply=True,
        is_system_generated=True,
    )

    create_notification(
        traveler,
        'You received a message from vendor',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )
    create_notification(
        vendor,
        'Booking confirmed successfully',
        Notification.TYPE_BOOKING,
        related_object_id=booking.id,
    )


def _render_esewa_checkout(request, booking):
    success_url = request.build_absolute_uri(
        reverse('booking_esewa_success', kwargs={'booking_id': booking.id}),
    )
    failure_url = request.build_absolute_uri(
        reverse('booking_esewa_failure', kwargs={'booking_id': booking.id}),
    )
    payload = build_esewa_payment_payload(
        booking=booking,
        success_url=success_url,
        failure_url=failure_url,
    )
    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': booking,
            'esewa_payment_url': get_esewa_payment_url(),
            'esewa_payload': payload,
        },
    )


def home(request):
    """Landing page"""
    VendorSubscription.expire_overdue()
    VendorFeature.expire_overdue()
    wishlist_ids = _wishlist_ids_for_user(request.user)
    today = timezone.localdate()
    homepage_slot_capacity = FeatureSlot.objects.filter(is_active=True).aggregate(total=Sum('max_slots'))['total'] or 0
    active_vendor_ids = VendorFeature.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).values_list('vendor_id', flat=True).distinct()
    active_subscriptions = VendorSubscription.objects.filter(
        status=VendorSubscription.STATUS_ACTIVE,
        start_date__lte=today,
        end_date__gte=today,
    )
    latest_subscription_end = active_subscriptions.filter(vendor_id=OuterRef('vendor_id')).order_by('-end_date').values('end_date')[:1]
    highest_subscription_price = active_subscriptions.filter(vendor_id=OuterRef('vendor_id')).order_by('-price').values('price')[:1]
    featured_packages = (
        Package.objects.filter(
            is_active=True,
            is_featured=True,
            vendor_id__in=active_vendor_ids,
        )
        .select_related('vendor', 'vendor__vendor_profile')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
            priority_subscription_end=Subquery(latest_subscription_end),
            priority_subscription_price=Subquery(highest_subscription_price),
        )
        .order_by('-priority_subscription_end', '-priority_subscription_price', '-created_at', '-views_count', '-avg_rating')[:homepage_slot_capacity or 0]
    )
    featured_ids = list(featured_packages.values_list('id', flat=True))
    popular_packages = (
        Package.objects.filter(
            is_active=True,
            category=Package.CATEGORY_TREK,
        )
        .exclude(id__in=featured_ids)
        .select_related('vendor', 'vendor__vendor_profile')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
        )
        .order_by('-views_count', '-avg_rating', '-created_at')[:8]
    )
    reviews = _prepare_review_cards(
        Review.objects.select_related('traveler', 'traveler__traveler_profile', 'package').order_by('-created_at')[:5]
    )

    travel_tips = TravelTip.objects.filter(is_active=True).order_by('-created_at')[:3]
    special_offers = SpecialOffer.objects.filter(is_active=True).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).order_by('-created_at')[:3]

    recommended_packages = Package.objects.none()
    show_promotions = bool(
        request.user.is_authenticated
        and getattr(request.user, 'wants_promotions', False)
    )
    if show_promotions:
        wishlist_package_ids = Wishlist.objects.filter(traveler=request.user).values_list('package_id', flat=True)
        preferred_categories = Package.objects.filter(id__in=wishlist_package_ids).values_list('category', flat=True)
        preferred_locations = Package.objects.filter(id__in=wishlist_package_ids).exclude(location_name='').values_list('location_name', flat=True)

        recommendation_filters = Q(is_active=True)
        if preferred_categories:
            recommendation_filters &= Q(category__in=preferred_categories)
        if preferred_locations:
            recommendation_filters &= Q(location_name__in=preferred_locations)

        recommended_packages = (
            Package.objects.filter(recommendation_filters)
            .exclude(id__in=featured_ids)
            .select_related('vendor', 'vendor__vendor_profile')
            .prefetch_related('images')
            .annotate(
                review_count=Count('reviews', distinct=True),
                avg_rating=Avg('reviews__rating'),
            )
            .order_by('-views_count', '-avg_rating', '-created_at')[:4]
        )

    return render(request, 'core/home.html', {
        'reviews': reviews,
        'featured_packages': featured_packages,
        'popular_packages': popular_packages,
        'travel_tips': travel_tips,
        'special_offers': special_offers,
        'recommended_packages': recommended_packages,
        'show_promotions': show_promotions,
        'wishlist_ids': wishlist_ids,
    })


def destinations_api(request):
    destinations = set()
    for location_name, location in Package.objects.filter(is_active=True).values_list(
        'location_name',
        'location',
    ):
        if location_name:
            destinations.add(location_name.strip())
        if location:
            destinations.add(location.strip())
    return JsonResponse(sorted(destinations), safe=False)


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _budget_threshold(queryset):
    prices = list(queryset.values_list('price', flat=True).order_by('price'))
    if not prices:
        return None
    index = max(0, int(len(prices) * 0.25) - 1)
    return float(prices[index])


def _apply_package_filters(request, queryset, forced_category=None, budget_threshold=None):
    params = request.GET
    search_term = (params.get('q') or params.get('destination') or '').strip()
    date_from_raw = (params.get('date_from') or '').strip()
    date_to_raw = (params.get('date_to') or '').strip()
    travelers = _parse_int(params.get('travelers'))
    package_type = (params.get('package_type') or '').strip().lower()
    price_min = _parse_float(params.get('price_min'))
    price_max = _parse_float(params.get('price_max'))
    duration_filters = params.getlist('duration')
    difficulty_filters = params.getlist('difficulty')
    rating_min = _parse_int(params.get('rating'))
    season_filters = params.getlist('season')
    amenity_filters = params.getlist('amenities')
    verified_only = (params.get('verified_only') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    quick_filter = (params.get('quick') or '').strip().lower()
    sort = (params.get('sort') or 'popular').strip().lower()

    if search_term:
        queryset = queryset.filter(
            Q(title__icontains=search_term)
            | Q(location__icontains=search_term)
            | Q(location_name__icontains=search_term)
        )

    date_from = parse_date(date_from_raw) if date_from_raw else None
    date_to = parse_date(date_to_raw) if date_to_raw else None
    if date_from:
        queryset = queryset.filter(
            available_from__isnull=False,
            available_until__isnull=False,
            available_from__lte=date_from,
            available_until__gte=date_from,
        )
    if date_to:
        queryset = queryset.filter(
            available_from__isnull=False,
            available_until__isnull=False,
            available_from__lte=date_to,
            available_until__gte=date_to,
        )
    if travelers:
        queryset = queryset.filter(available_slots__gte=travelers)

    if forced_category:
        package_type = Package.CATEGORY_TREK.lower() if forced_category == Package.CATEGORY_TREK else Package.CATEGORY_TOUR.lower()
    elif package_type in {'trek', 'treks'}:
        queryset = queryset.filter(category=Package.CATEGORY_TREK)
        package_type = 'trek'
    elif package_type in {'tour', 'tours'}:
        queryset = queryset.filter(category=Package.CATEGORY_TOUR)
        package_type = 'tour'
    else:
        package_type = ''

    if price_min is not None and price_max is not None and price_min > price_max:
        price_min, price_max = price_max, price_min
    if price_min is not None:
        queryset = queryset.filter(price__gte=price_min)
    if price_max is not None:
        queryset = queryset.filter(price__lte=price_max)

    if duration_filters:
        duration_query = Q()
        for key in duration_filters:
            if key == '1-3':
                duration_query |= Q(duration_days__gte=1, duration_days__lte=3)
            elif key == '4-7':
                duration_query |= Q(duration_days__gte=4, duration_days__lte=7)
            elif key == '8-14':
                duration_query |= Q(duration_days__gte=8, duration_days__lte=14)
            elif key == '15+':
                duration_query |= Q(duration_days__gte=15)
        if duration_query:
            queryset = queryset.filter(duration_query)

    if difficulty_filters:
        normalized = set()
        for value in difficulty_filters:
            value = value.strip().lower()
            if value == 'hard':
                normalized.update({'challenging', 'expedition'})
            else:
                normalized.add(value)
        queryset = queryset.filter(difficulty__in=normalized)

    if rating_min:
        queryset = queryset.filter(avg_rating__gte=rating_min)

    if season_filters:
        season_query = Q()
        for season in season_filters:
            season_query |= Q(best_season__icontains=season)
        queryset = queryset.filter(season_query)

    amenities_map = {
        'guide': 'has_guide',
        'meals': 'includes_meals',
        'accommodation': 'includes_accommodation',
        'transport': 'includes_transport',
        'permit': 'includes_permits',
    }
    for amenity in amenity_filters:
        field = amenities_map.get(amenity)
        if field:
            queryset = queryset.filter(**{field: True})

    if verified_only:
        queryset = queryset.filter(vendor__vendor_profile__is_verified=True)

    if quick_filter == 'best_rated':
        queryset = queryset.filter(avg_rating__gte=4.5)
    elif quick_filter == 'budget':
        threshold = budget_threshold
        if threshold is None:
            threshold = _budget_threshold(queryset)
        if threshold is not None:
            queryset = queryset.filter(price__lte=threshold)
    elif quick_filter == 'featured':
        queryset = queryset.filter(is_featured=True)
    elif quick_filter == 'beginner':
        queryset = queryset.filter(difficulty__in=['easy', 'moderate'])

    if sort == 'price_low':
        queryset = queryset.order_by('-is_featured', 'price', '-avg_rating')
    elif sort == 'price_high':
        queryset = queryset.order_by('-is_featured', '-price', '-avg_rating')
    elif sort == 'rating':
        queryset = queryset.order_by('-is_featured', '-avg_rating', '-review_count')
    elif sort == 'newest':
        queryset = queryset.order_by('-is_featured', '-created_at')
    else:
        sort = 'popular'
        queryset = queryset.order_by('-is_featured', '-booking_count', '-views_count', '-created_at')

    applied = {
        'destination': search_term,
        'date_from': date_from_raw,
        'date_to': date_to_raw,
        'travelers': travelers or '',
        'package_type': package_type,
        'price_min': price_min,
        'price_max': price_max,
        'duration': duration_filters,
        'difficulty': difficulty_filters,
        'rating': rating_min or '',
        'season': season_filters,
        'amenities': amenity_filters,
        'verified_only': verified_only,
        'quick': quick_filter,
        'sort': sort,
    }
    return queryset, applied


def _public_package_queryset():
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


def _wishlist_ids_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return set()
    if getattr(user, 'user_type', '') != 'traveler':
        return set()
    return set(Wishlist.objects.filter(traveler=user).values_list('package_id', flat=True))


def _render_package_list(request, category=None):
    VendorSubscription.expire_overdue()
    wishlist_ids = _wishlist_ids_for_user(request.user)
    packages = _public_package_queryset()
    package_scope = 'all'
    package_type_slug = ''
    page_title = 'Nepal Treks & Tours'
    page_subtitle = 'Explore the Himalayas with trusted local operators.'
    empty_message = 'No packages available yet'

    if category == Package.CATEGORY_TREK:
        packages = packages.filter(category="TREK")
        package_scope = 'treks'
        package_type_slug = 'trek'
        page_title = 'Nepal Treks'
        page_subtitle = 'Browse trekking adventures curated by local experts.'
        empty_message = 'No packages available yet'
    elif category == Package.CATEGORY_TOUR:
        packages = packages.filter(category="TOUR")
        package_scope = 'tours'
        package_type_slug = 'tour'
        page_title = 'Nepal Tours'
        page_subtitle = 'Browse curated tour experiences across Nepal.'
        empty_message = 'No packages available yet'

    price_stats = packages.aggregate(min_price=Min('price'), max_price=Max('price'))
    min_price = float(price_stats['min_price'] or 0)
    max_price = float(price_stats['max_price'] or min_price or 0)
    filtered_packages, filters = _apply_package_filters(
        request,
        packages,
        forced_category=category,
        budget_threshold=_budget_threshold(packages),
    )
    if filters['price_min'] is None:
        filters['price_min'] = min_price
    if filters['price_max'] is None:
        filters['price_max'] = max_price
    result_count = filtered_packages.count()

    return render(request, 'core/packages.html', {
        'packages': filtered_packages,
        'package_scope': package_scope,
        'package_type_slug': package_type_slug,
        'page_title': page_title,
        'page_subtitle': page_subtitle,
        'empty_message': empty_message,
        'filters': filters,
        'price_min': min_price,
        'price_max': max_price,
        'result_count': result_count,
        'wishlist_ids': wishlist_ids,
    })


def package_list(request):
    return _render_package_list(request)


def trek_package_list(request):
    return _render_package_list(request, category=Package.CATEGORY_TREK)


def tour_package_list(request):
    return _render_package_list(request, category=Package.CATEGORY_TOUR)

def explore_map(request):
    return render(request, 'core/explore_map.html')


def packages_map_api(request):
    packages = (
        Package.objects.filter(is_active=True, latitude__isnull=False, longitude__isnull=False)
        .prefetch_related('images')
    )
    data = []
    for package in packages:
        if package.latitude is None or package.longitude is None:
            continue
        images = list(package.images.all())
        cover = images[0] if images else None
        image_url = cover.image.url if cover else package.image_url
        data.append({
            'id': package.id,
            'name': package.title,
            'location_name': package.location_name or package.location or '',
            'lat': package.latitude,
            'lng': package.longitude,
            'price': float(package.price) if package.price is not None else None,
            'url': reverse('package_detail', kwargs={'package_id': package.id}),
            'details_url': reverse('package_details_api', kwargs={'package_id': package.id}),
            'image': image_url,
            'category': package.category,
        })

    return JsonResponse(data, safe=False)


def package_details_api(request, package_id):
    package = get_object_or_404(
        Package.objects.prefetch_related('images'),
        id=package_id,
        is_active=True,
    )

    image_urls = []
    for package_image in package.images.all():
        try:
            image_urls.append(package_image.image.url)
        except (ValueError, AttributeError):
            continue

    if not image_urls and package.image_url:
        image_urls.append(package.image_url)

    return JsonResponse({
        'name': package.title,
        'images': image_urls,
        'description': package.description or '',
    })


def packages_search_api(request):
    packages = _public_package_queryset()
    wishlist_ids = _wishlist_ids_for_user(request.user)
    filtered_packages, filters = _apply_package_filters(
        request,
        packages,
        budget_threshold=_budget_threshold(packages),
    )
    packages_list = list(filtered_packages)
    html = render_to_string(
        'core/includes/package_cards.html',
        {
            'packages': packages_list,
            'empty_message': 'No packages match your filters.',
            'wishlist_ids': wishlist_ids,
        },
        request=request,
    )
    return JsonResponse({
        'html': html,
        'count': len(packages_list),
        'filters': filters,
    })

def package_detail(request, package_id):
    package = get_object_or_404(
        Package.objects.select_related('vendor', 'vendor__vendor_profile').prefetch_related('images'),
        id=package_id,
    )
    if not package.is_active and package.vendor != request.user:
        return render(request, 'core/package_not_available.html', status=404)

    Package.objects.filter(id=package.id).update(views_count=package.views_count + 1)
    package.views_count += 1

    wishlist_ids = _wishlist_ids_for_user(request.user)
    reviews_base = Review.objects.filter(package=package).select_related('traveler', 'traveler__traveler_profile')
    sort = (request.GET.get('sort') or 'recent').lower()
    if sort == 'highest':
        reviews = reviews_base.order_by('-rating', '-created_at')
    elif sort == 'lowest':
        reviews = reviews_base.order_by('rating', '-created_at')
    else:
        sort = 'recent'
        reviews = reviews_base.order_by('-created_at')
    reviews = _prepare_review_cards(reviews)

    rating = reviews_base.aggregate(avg=Avg('rating'), count=Count('id'))
    rating_counts = {entry['rating']: entry['count'] for entry in reviews_base.values('rating').annotate(count=Count('id'))}
    total_reviews = rating.get('count') or 0
    rating_breakdown = []
    for stars in range(5, 0, -1):
        count = rating_counts.get(stars, 0)
        percent = int(round((count / total_reviews) * 100)) if total_reviews else 0
        rating_breakdown.append({
            'stars': stars,
            'count': count,
            'percent': percent,
        })

    can_review = request.user.is_authenticated and getattr(request.user, 'user_type', '') == 'traveler'
    season_open = package.is_in_season()
    can_book = request.user.is_authenticated and getattr(request.user, 'user_type', '') == 'traveler' and season_open
    facts = [
        {
            'label': 'Duration',
            'value': f"{package.duration_days} days" if package.duration_days else 'Contact vendor',
        },
        {
            'label': 'Difficulty',
            'value': package.get_difficulty_display() if package.difficulty else 'Contact vendor',
        },
        {
            'label': 'Available Slots',
            'value': str(package.available_slots),
        },
        {
            'label': 'Available From',
            'value': package.available_from.strftime('%b %d, %Y') if package.available_from else 'Not set',
        },
        {
            'label': 'Available Until',
            'value': package.available_until.strftime('%b %d, %Y') if package.available_until else 'Not set',
        },
        {
            'label': 'Group Size',
            'value': str(package.group_size) if package.group_size else 'Contact vendor',
        },
        {
            'label': 'Best Season',
            'value': package.best_season or 'Contact vendor',
        },
    ]
    inclusions = [item.strip() for item in (package.inclusions or '').splitlines() if item.strip()]
    exclusions = [item.strip() for item in (package.exclusions or '').splitlines() if item.strip()]
    itinerary_points = [item.strip() for item in (package.itinerary or '').splitlines() if item.strip()]

    images = list(package.images.all())

    return render(request, 'core/package_detail.html', {
        'package': package,
        'reviews': reviews,
        'rating': rating,
        'rating_breakdown': rating_breakdown,
        'review_sort': sort,
        'can_review': can_review,
        'can_book': can_book,
        'season_open': season_open,
        'facts': facts,
        'inclusions': inclusions,
        'exclusions': exclusions,
        'itinerary_points': itinerary_points,
        'images': images,
        'wishlist_ids': wishlist_ids,
    })


@login_required(login_url='account_login_choice')
def package_book(request, package_id):
    package = get_object_or_404(Package, id=package_id, is_active=True)

    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Only traveler accounts can create bookings.')
        return redirect('package_detail', package_id=package.id)

    if not package.is_in_season():
        messages.error(request, 'This package is currently not available for booking.')
        return redirect('package_detail', package_id=package.id)

    with transaction.atomic():
        _expire_stale_pending_bookings(package_id=package.id)
    package.refresh_from_db(fields=['available_slots'])

    if request.method == 'POST':
        form = BookingForm(request.POST, package=package)
        if form.is_valid():
            selected_payment_method = form.cleaned_data['payment_method']
            booking = None
            booking_created = False
            with transaction.atomic():
                _expire_stale_pending_bookings(package_id=package.id)
                locked_package = Package.objects.select_for_update().get(id=package.id)
                number_of_people = form.cleaned_data['number_of_people']
                travel_date = form.cleaned_data['travel_date']
                special_notes = form.cleaned_data.get('special_notes', '')
                original_total = (locked_package.price * number_of_people).quantize(Decimal('0.01'))
                best_discount, _best_amount = _best_available_discount_for_user(
                    request.user,
                    original_total,
                )
                existing_pending_booking = (
                    Booking.objects.select_for_update()
                    .filter(
                        package=locked_package,
                        traveler=request.user,
                        status=Booking.STATUS_PENDING,
                        payment_status__in=[
                            Booking.PAYMENT_STATUS_PENDING,
                            Booking.PAYMENT_STATUS_FAILED,
                        ],
                    )
                    .order_by('-created_at')
                    .first()
                )
                slot_delta = number_of_people
                if existing_pending_booking is not None:
                    slot_delta -= existing_pending_booking.number_of_people

                if slot_delta > locked_package.available_slots:
                    form.add_error(
                        'number_of_people',
                        f'Only {locked_package.available_slots} slot(s) are currently available.',
                    )
                else:
                    booking = existing_pending_booking
                    if booking is None:
                        booking = form.save(commit=False)
                        booking.package = locked_package
                        booking.traveler = request.user
                        booking_created = True
                    else:
                        booking.number_of_people = number_of_people
                        booking.travel_date = travel_date
                        booking.start_date = travel_date
                        booking.end_date = travel_date
                        booking.special_notes = special_notes
                        booking.payment_reference = ''
                        booking.stripe_checkout_session_id = ''
                        booking.esewa_transaction_id = ''
                        booking.paid_amount = None
                        booking.paid_at = None

                    booking.status = Booking.STATUS_PENDING
                    booking.payment_method = selected_payment_method
                    booking.payment_status = Booking.PAYMENT_STATUS_PENDING
                    booking.source = 'direct'
                    booking.discount = best_discount
                    booking.payment_expires_at = _booking_payment_expires_at()
                    booking.save()

                    if slot_delta != 0:
                        locked_package.available_slots -= slot_delta
                        locked_package.save(update_fields=['available_slots'])

            if form.errors:
                package.refresh_from_db(fields=['available_slots'])
            else:
                if booking.payment_method == Booking.PAYMENT_METHOD_STRIPE:
                    success_url = (
                        request.build_absolute_uri(
                            reverse('booking_confirmation', kwargs={'booking_id': booking.id}),
                        )
                        + '?session_id={CHECKOUT_SESSION_ID}'
                    )
                    cancel_url = request.build_absolute_uri(
                        reverse('booking_checkout_cancel', kwargs={'booking_id': booking.id}),
                    )
                    try:
                        session_data = create_checkout_session(
                            booking=booking,
                            success_url=success_url,
                            cancel_url=cancel_url,
                        )
                        checkout_url = session_data.get('url')
                        if not checkout_url:
                            raise StripeError('Stripe did not return a checkout URL.')
                    except StripeError as exc:
                        with transaction.atomic():
                            locked_booking = Booking.objects.select_for_update().get(id=booking.id)
                            _cancel_unpaid_booking(
                                locked_booking,
                                Booking.PAYMENT_STATUS_FAILED,
                            )
                        form.add_error(None, str(exc))
                        package.refresh_from_db(fields=['available_slots'])
                    else:
                        booking.stripe_checkout_session_id = session_data.get('id', '')
                        booking.payment_reference = (
                            session_data.get('payment_intent')
                            or session_data.get('id', '')
                        )
                        booking.save(update_fields=['stripe_checkout_session_id', 'payment_reference'])
                        if booking_created:
                            _notify_booking_created(booking)
                        return redirect(checkout_url)
                elif booking.payment_method == Booking.PAYMENT_METHOD_ESEWA:
                    try:
                        response = _render_esewa_checkout(request, booking)
                    except EsewaError as exc:
                        with transaction.atomic():
                            locked_booking = Booking.objects.select_for_update().get(id=booking.id)
                            _cancel_unpaid_booking(
                                locked_booking,
                                Booking.PAYMENT_STATUS_FAILED,
                            )
                        form.add_error(None, str(exc))
                        package.refresh_from_db(fields=['available_slots'])
                    else:
                        if booking_created:
                            _notify_booking_created(booking)
                        return response
                else:
                    form.add_error('payment_method', 'Unsupported payment method selected.')
    else:
        form = BookingForm(
            package=package,
            initial={
                'number_of_people': 1,
                'travel_date': timezone.localdate(),
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

    reward_points = total_points_for_user(request.user)
    discount_percent, next_discount_points = discount_for_points(reward_points)
    preview_people = 1
    posted_people = request.POST.get('number_of_people')
    if posted_people:
        try:
            preview_people = max(1, int(posted_people))
        except (TypeError, ValueError):
            preview_people = 1
    preview_original_total = (package.price * preview_people).quantize(Decimal('0.01'))
    available_discount, available_discount_amount = _best_available_discount_for_user(
        request.user,
        preview_original_total,
    )
    preview_final_total = (preview_original_total - available_discount_amount).quantize(Decimal('0.01'))

    return render(request, 'core/booking_form.html', {
        'package': package,
        'form': form,
        'estimated_total': preview_final_total,
        'original_total': preview_original_total,
        'discount_amount': available_discount_amount,
        'available_discount': available_discount,
        'reward_points': reward_points,
        'discount_percent': discount_percent,
        'next_discount_points': next_discount_points,
    })


@login_required(login_url='account_login_choice')
def booking_confirmation(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if (
        booking.payment_method == Booking.PAYMENT_METHOD_STRIPE
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        session_id = request.GET.get('session_id')
        if session_id:
            try:
                session_data = retrieve_checkout_session(session_id)
            except StripeError as exc:
                messages.warning(request, f'Payment verification is still pending: {exc}')
            else:
                is_paid = (
                    session_data.get('status') == 'complete'
                    and session_data.get('payment_status') == 'paid'
                    and str(session_data.get('client_reference_id')) == str(booking.id)
                )
                if is_paid:
                    with transaction.atomic():
                        locked_booking = get_object_or_404(
                            Booking.objects.select_for_update().select_related('package', 'traveler'),
                            id=booking_id,
                            traveler=request.user,
                        )
                        if (
                            locked_booking.status == Booking.STATUS_PENDING
                            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
                        ):
                            _complete_paid_booking(
                                locked_booking,
                                payment_reference=(
                                    session_data.get('payment_intent')
                                    or session_data.get('id')
                                    or locked_booking.payment_reference
                                ),
                                stripe_checkout_session_id=(
                                    session_data.get('id')
                                    or locked_booking.stripe_checkout_session_id
                                ),
                                paid_amount=_as_money_decimal(locked_booking.total_price),
                            )
                            _notify_booking_paid(locked_booking)
                        booking = locked_booking
                    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
                        messages.success(
                            request,
                            'Stripe payment received. Your booking is confirmed.',
                        )
                    else:
                        messages.warning(
                            request,
                            'This booking is no longer awaiting payment. Please contact support if you were charged.',
                        )
                else:
                    messages.warning(
                        request,
                        'Your Stripe checkout is not marked as paid yet.',
                    )

    can_continue_payment = (
        booking.status == Booking.STATUS_PENDING
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    )
    return render(
        request,
        'core/booking_confirmation.html',
        {
            'booking': booking,
            'can_continue_payment': can_continue_payment,
        },
    )


@login_required(login_url='account_login_choice')
def booking_checkout_cancel(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    with transaction.atomic():
        locked_booking = get_object_or_404(
            Booking.objects.select_for_update().select_related('package'),
            id=booking_id,
            traveler=request.user,
        )
        if (
            locked_booking.status == Booking.STATUS_PENDING
            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
        ):
            _cancel_unpaid_booking(
                locked_booking,
                Booking.PAYMENT_STATUS_FAILED,
            )

    if (
        booking.payment_method == Booking.PAYMENT_METHOD_STRIPE
        and booking.stripe_checkout_session_id
    ):
        try:
            expire_checkout_session(booking.stripe_checkout_session_id)
        except StripeError:
            pass

    messages.info(
        request,
        'Payment was cancelled. Your reserved slots were released.',
    )
    return redirect('package_book', package_id=booking.package_id)


@login_required(login_url='account_login_choice')
def booking_stripe_checkout(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.status != Booking.STATUS_PENDING:
        messages.error(request, 'This booking is no longer awaiting payment.')
        return redirect('booking_confirmation', booking_id=booking.id)

    success_url = (
        request.build_absolute_uri(
            reverse('booking_confirmation', kwargs={'booking_id': booking.id}),
        )
        + '?session_id={CHECKOUT_SESSION_ID}'
    )
    cancel_url = request.build_absolute_uri(
        reverse('booking_checkout_cancel', kwargs={'booking_id': booking.id}),
    )

    try:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            if locked_booking.status != Booking.STATUS_PENDING:
                messages.error(request, 'This booking is no longer awaiting payment.')
                return redirect('booking_confirmation', booking_id=locked_booking.id)

            locked_booking.payment_method = Booking.PAYMENT_METHOD_STRIPE
            locked_booking.payment_status = Booking.PAYMENT_STATUS_PENDING
            locked_booking.payment_expires_at = _booking_payment_expires_at()
            locked_booking.esewa_transaction_id = ''

            session_data = create_checkout_session(
                booking=locked_booking,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            checkout_url = session_data.get('url')
            if not checkout_url:
                raise StripeError('Stripe did not return a checkout URL.')

            locked_booking.stripe_checkout_session_id = session_data.get('id', '')
            locked_booking.payment_reference = (
                session_data.get('payment_intent')
                or session_data.get('id', '')
            )
            locked_booking.save(
                update_fields=[
                    'payment_method',
                    'payment_status',
                    'payment_expires_at',
                    'esewa_transaction_id',
                    'stripe_checkout_session_id',
                    'payment_reference',
                ]
            )
    except StripeError as exc:
        messages.error(request, str(exc))
        return redirect('booking_confirmation', booking_id=booking.id)

    return redirect(checkout_url)


@login_required(login_url='account_login_choice')
def booking_esewa_checkout(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.status != Booking.STATUS_PENDING:
        messages.error(request, 'This booking is no longer awaiting payment.')
        return redirect('booking_confirmation', booking_id=booking.id)

    try:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            if locked_booking.status != Booking.STATUS_PENDING:
                messages.error(request, 'This booking is no longer awaiting payment.')
                return redirect('booking_confirmation', booking_id=locked_booking.id)

            locked_booking.payment_method = Booking.PAYMENT_METHOD_ESEWA
            locked_booking.payment_status = Booking.PAYMENT_STATUS_PENDING
            locked_booking.payment_expires_at = _booking_payment_expires_at()
            locked_booking.stripe_checkout_session_id = ''
            locked_booking.payment_reference = ''
            locked_booking.save(
                update_fields=[
                    'payment_method',
                    'payment_status',
                    'payment_expires_at',
                    'stripe_checkout_session_id',
                    'payment_reference',
                ]
            )
        return _render_esewa_checkout(request, locked_booking)
    except EsewaError as exc:
        messages.error(request, str(exc))
        return redirect('booking_confirmation', booking_id=booking.id)


@login_required(login_url='account_login_choice')
def booking_esewa_success(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_method != Booking.PAYMENT_METHOD_ESEWA:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        messages.success(request, 'Payment already confirmed for this booking.')
        return redirect('booking_confirmation', booking_id=booking.id)

    transaction_id = (
        (request.GET.get('refId') or '')
        or (request.GET.get('rid') or '')
    ).strip()
    callback_pid = (
        (request.GET.get('pid') or '')
        or (request.GET.get('oid') or '')
    ).strip()
    callback_amount_raw = (
        (request.GET.get('amt') or '')
        or (request.GET.get('tAmt') or '')
    ).strip()
    expected_pid = str(booking.id)
    expected_amount = _as_money_decimal(booking.total_price)
    callback_amount = _as_money_decimal(callback_amount_raw) if callback_amount_raw else expected_amount

    if not transaction_id:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Missing eSewa transaction id.')
        return redirect('booking_confirmation', booking_id=booking.id)

    if callback_pid and callback_pid != expected_pid:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Product ID mismatch.')
        return redirect('booking_confirmation', booking_id=booking.id)

    if expected_amount is None or callback_amount != expected_amount:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment verification failed. Amount mismatch.')
        return redirect('booking_confirmation', booking_id=booking.id)

    try:
        is_verified = verify_esewa_payment(
            amount=expected_amount,
            transaction_id=transaction_id,
            product_id=expected_pid,
        )
    except EsewaError as exc:
        messages.warning(request, f'eSewa verification is pending: {exc}')
        return redirect('booking_confirmation', booking_id=booking.id)

    if not is_verified:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)
        messages.error(request, 'Payment Failed. Try again.')
        return redirect('booking_confirmation', booking_id=booking.id)

    with transaction.atomic():
        locked_booking = get_object_or_404(
            Booking.objects.select_for_update().select_related('package', 'traveler'),
            id=booking_id,
            traveler=request.user,
        )
        if (
            locked_booking.status == Booking.STATUS_PENDING
            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
        ):
            _complete_paid_booking(
                locked_booking,
                payment_reference=transaction_id,
                esewa_transaction_id=transaction_id,
                paid_amount=expected_amount,
            )
            _notify_booking_paid(locked_booking)
        booking = locked_booking

    messages.success(request, 'Payment Successful. Your booking is confirmed.')
    return redirect('booking_confirmation', booking_id=booking.id)


@login_required(login_url='account_login_choice')
def booking_esewa_failure(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_method != Booking.PAYMENT_METHOD_ESEWA:
        return redirect('booking_confirmation', booking_id=booking.id)

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        with transaction.atomic():
            locked_booking = get_object_or_404(
                Booking.objects.select_for_update(),
                id=booking_id,
                traveler=request.user,
            )
            _mark_payment_failed(locked_booking)

    messages.error(request, 'Payment Failed. Try again.')
    return redirect('booking_confirmation', booking_id=booking.id)


@login_required(login_url='account_login_choice')
def booking_invoice(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler', 'vendor'),
        id=booking_id,
    )
    if not _can_access_booking_invoice(request.user, booking):
        raise Http404('Invoice not found.')

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        messages.error(request, 'Invoice is available only after successful payment.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    return render(
        request,
        'core/invoice_detail.html',
        {
            'booking': booking,
            'invoice': invoice_data_for_booking(booking),
        },
    )


@login_required(login_url='account_login_choice')
def booking_invoice_download(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler', 'vendor'),
        id=booking_id,
    )
    if not _can_access_booking_invoice(request.user, booking):
        raise Http404('Invoice not found.')

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        messages.error(request, 'Invoice is available only after successful payment.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    try:
        pdf_bytes = generate_invoice_pdf(booking.id)
    except (Booking.DoesNotExist, ValueError, RuntimeError) as exc:
        messages.error(request, str(exc))
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')
    except Exception:
        messages.error(request, 'Unable to generate invoice for this booking.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    filename = f"invoice_{booking.id}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def about(request):
    """About page"""
    return render(request, 'core/about.html')


def blog_list(request):
    posts = sorted(BLOG_POSTS, key=lambda item: item['published_on'], reverse=True)
    return render(request, 'core/blog.html', {'posts': posts})


def blog_detail(request, slug):
    post = next((item for item in BLOG_POSTS if item['slug'] == slug), None)
    if post is None:
        raise Http404('Blog post not found.')
    return render(request, 'core/blog_detail.html', {'post': post})


def contact(request):
    """Contact page"""
    initial = {}
    if request.user.is_authenticated:
        initial['email'] = request.user.email or ''
        initial['full_name'] = request.user.get_full_name().strip() or request.user.username

    if request.method == 'POST':
        form = ContactMessageForm(request.POST)
        if form.is_valid():
            contact_message = form.save(commit=False)
            if request.user.is_authenticated:
                contact_message.user = request.user
            contact_message.save()

            recipients = []
            recipients.extend(getattr(settings, 'CONTACT_RECEIVER_EMAILS', []) or [])
            fallback_recipient = getattr(settings, 'CONTACT_RECEIVER_EMAIL', '') or getattr(settings, 'EMAIL_HOST_USER', '')
            if fallback_recipient:
                recipients.append(fallback_recipient)
            recipients = list(dict.fromkeys([email for email in recipients if email]))

            if recipients:
                sender_label = contact_message.full_name
                if request.user.is_authenticated:
                    sender_label = f'{sender_label} ({request.user.email})'
                email_subject = f'[Namaste Nomad] New Contact Message: {contact_message.subject}'
                email_body = (
                    f'You received a new contact message.\n\n'
                    f'Name: {contact_message.full_name}\n'
                    f'Email: {contact_message.email}\n'
                    f'Subject: {contact_message.subject}\n'
                    f'Sender: {sender_label}\n\n'
                    f'Message:\n{contact_message.message}\n\n'
                    f'Submitted at: {contact_message.created_at:%Y-%m-%d %H:%M:%S %Z}'
                )
                try:
                    send_mail(
                        subject=email_subject,
                        message=email_body,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', '') or None,
                        recipient_list=recipients,
                        fail_silently=False,
                    )
                except Exception:
                    messages.warning(
                        request,
                        'Message saved, but email notification to admin could not be sent right now.',
                    )

            messages.success(request, 'Message sent successfully')
            return redirect('contact')
    else:
        form = ContactMessageForm(initial=initial)

    faq_items = [
        {
            'question': 'How do I book a package?',
            'answer': 'Open any package, select travel date and travelers, then complete secure checkout.',
        },
        {
            'question': 'How can vendors join?',
            'answer': 'Register as a vendor, complete profile verification, and publish packages after approval.',
        },
        {
            'question': 'Can I customize an itinerary?',
            'answer': 'Yes. Send your request through this form and our team will connect you with suitable vendors.',
        },
    ]

    return render(
        request,
        'core/contact.html',
        {
            'form': form,
            'faq_items': faq_items,
            'office_lat': 28.2096,
            'office_lng': 83.9856,
        },
    )


def review_list(request):
    sort = (request.GET.get('sort') or 'recent').lower()
    reviews_base = Review.objects.select_related('traveler', 'traveler__traveler_profile', 'package')
    if sort == 'highest':
        reviews_base = reviews_base.order_by('-rating', '-created_at')
    elif sort == 'lowest':
        reviews_base = reviews_base.order_by('rating', '-created_at')
    else:
        sort = 'recent'
        reviews_base = reviews_base.order_by('-created_at')

    summary = reviews_base.aggregate(avg_rating=Avg('rating'), total_reviews=Count('id'))
    total_reviews = summary.get('total_reviews') or 0
    avg_rating = summary.get('avg_rating') or 0

    rating_counts = {
        item['rating']: item['total']
        for item in reviews_base.values('rating').annotate(total=Count('id'))
    }
    rating_breakdown = []
    for stars in range(5, 0, -1):
        count = rating_counts.get(stars, 0)
        percent = int(round((count / total_reviews) * 100)) if total_reviews else 0
        rating_breakdown.append({
            'stars': stars,
            'count': count,
            'percent': percent,
        })

    paginator = Paginator(reviews_base, 8)
    page_obj = paginator.get_page(request.GET.get('page'))
    reviews = _prepare_review_cards(page_obj.object_list)

    can_review = request.user.is_authenticated and getattr(request.user, 'user_type', '') == 'traveler'
    review_packages = Package.objects.filter(is_active=True).order_by('title')
    is_logged_in = request.user.is_authenticated

    return render(request, 'core/reviews.html', {
        'reviews': reviews,
        'page_obj': page_obj,
        'review_sort': sort,
        'rating_breakdown': rating_breakdown,
        'avg_rating': avg_rating,
        'total_reviews': total_reviews,
        'can_review': can_review,
        'is_logged_in': is_logged_in,
        'review_packages': review_packages,
    })


def public_traveler_profile(request, user_id):
    User = get_user_model()
    traveler = get_object_or_404(
        User.objects.select_related('traveler_profile'),
        id=user_id,
        user_type='traveler',
    )
    traveler_profile = _safe_related(traveler, 'traveler_profile')

    comment_queryset = Comment.objects.select_related(
        'user',
        'user__traveler_profile',
        'user__vendor_profile',
        'user__admin_profile',
    ).order_by('created_at')
    posts = _prepare_feed_posts(
        Post.objects.filter(user=traveler)
        .select_related(
            'user',
            'user__traveler_profile',
            'user__vendor_profile',
            'user__admin_profile',
        )
        .prefetch_related(
            Prefetch('comments', queryset=comment_queryset),
            Prefetch('likes', queryset=User.objects.only('id')),
            Prefetch('media', queryset=PostMedia.objects.all()),
        )
        .order_by('-created_at'),
        viewer=request.user,
    )

    for post in posts:
        if post.media_items:
            post.primary_media = post.media_items[0]
        else:
            post.primary_media = None

    reviews = _prepare_review_cards(
        Review.objects.filter(traveler=traveler)
        .select_related('traveler', 'traveler__traveler_profile', 'package')
        .order_by('-created_at')
    )

    earned_badges = list(
        UserBadge.objects.filter(user=traveler)
        .select_related('badge')
        .order_by('-earned_at')
    )
    total_points = total_points_for_user(traveler)
    total_trips_completed = Booking.objects.filter(
        traveler=traveler,
        status=Booking.STATUS_CONFIRMED,
    ).count()

    highlighted_posts = sorted(
        [post for post in posts if post.like_count > 0],
        key=lambda post: (post.like_count, post.comment_count, post.created_at),
        reverse=True,
    )[:3]

    return render(request, 'core/public_traveler_profile.html', {
        'traveler': traveler,
        'traveler_profile': traveler_profile,
        'posts': posts,
        'reviews': reviews,
        'earned_badges': earned_badges,
        'reward_events': RewardPoint.objects.filter(user=traveler).order_by('-created_at')[:6],
        'total_points': total_points,
        'total_trips_completed': total_trips_completed,
        'total_posts': len(posts),
        'total_achievements': len(earned_badges),
        'traveler_level': _traveler_level_label(total_points),
        'highlighted_posts': highlighted_posts,
        'is_own_profile': request.user.is_authenticated and request.user.id == traveler.id,
    })


def community_feed(request):
    posts = _community_posts(viewer=request.user)
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    return render(request, 'core/community_feed.html', {
        'posts': posts,
        'is_dashboard': False,
        'force_show_post_form': False,
        'vendors': vendors,
    })


@login_required(login_url='traveler_login')
def community_dashboard(request):
    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return redirect('home')

    traveler_profile = _get_or_create_traveler_profile(request.user)
    posts = _community_posts(viewer=request.user)
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    return render(request, 'core/community_dashboard.html', {
        'posts': posts,
        'is_dashboard': True,
        'force_show_post_form': True,
        'traveler_profile': traveler_profile,
        'active_page': 'community',
        'vendors': vendors,
    })


@login_required(login_url='account_login_choice')
def community_post_create(request):
    next_url = request.POST.get('next') or reverse('community_feed')
    if request.method != 'POST':
        return redirect(next_url)

    form = PostForm(request.POST, request.FILES)
    if form.is_valid():
        post = form.save(commit=False)
        post.user = request.user
        post.save()
        if getattr(request.user, 'user_type', '') == 'traveler':
            add_points(request.user, 'post', 10)
            sync_badges_for_user(request.user)
        media_files = form.cleaned_data.get('media_files', [])
        for index, media_file in enumerate(media_files, start=1):
            content_type = (getattr(media_file, 'content_type', '') or '').lower()
            media_type = (
                PostMedia.MEDIA_VIDEO
                if content_type.startswith('video/')
                else PostMedia.MEDIA_IMAGE
            )
            PostMedia.objects.create(
                post=post,
                media_file=media_file,
                media_type=media_type,
                order=index,
            )

        tag_ids = []
        for raw_id in request.POST.getlist('tagged_vendors'):
            try:
                tag_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if tag_ids:
            vendors = get_user_model().objects.filter(user_type='vendor', id__in=tag_ids)
            post.tagged_vendors.set(vendors)
            for vendor in vendors:
                if vendor.id != request.user.id:
                    create_notification(
                        vendor,
                        f'You were tagged in a community post by {post.user.get_full_name() or post.user.username}.',
                        Notification.TYPE_COMMUNITY_POST,
                        related_object_id=post.id,
                    )
        else:
            post.tagged_vendors.clear()

        notify_admins(
            f'New community post created by {post.user.get_full_name() or post.user.username}.',
            Notification.TYPE_COMMUNITY_POST,
            related_object_id=post.id,
        )
        messages.success(request, 'Post shared successfully.')
    else:
        messages.error(request, 'Please upload at least one photo or video and add a caption.')

    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_post_edit(request, post_id):
    post = get_object_or_404(
        Post.objects.select_related('user').prefetch_related('media', 'tagged_vendors'),
        id=post_id,
        user=request.user,
    )
    next_url = request.POST.get('next') or request.GET.get('next') or reverse('community_feed')
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    if request.method == 'POST':
        form = PostEditForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            media_files = request.FILES.getlist('media_files')
            remove_ids = []
            for raw_id in request.POST.getlist('remove_media'):
                try:
                    remove_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
            remove_legacy = request.POST.get('remove_legacy') == '1'

            existing_media_ids = set(post.media.values_list('id', flat=True))
            remove_ids = [media_id for media_id in remove_ids if media_id in existing_media_ids]
            remaining = len(existing_media_ids) - len(remove_ids)
            if post.image and not remove_legacy:
                remaining += 1
            remaining += len(media_files)

            if remaining < 1:
                form.add_error(None, 'Please keep at least one photo or video.')
            else:
                with transaction.atomic():
                    post.caption = form.cleaned_data['caption']
                    post.save(update_fields=['caption'])

                    if remove_ids:
                        PostMedia.objects.filter(post=post, id__in=remove_ids).delete()

                    if remove_legacy and post.image:
                        post.image.delete(save=False)
                        post.image = None
                        post.save(update_fields=['image'])

                    if media_files:
                        max_order = post.media.aggregate(max_order=Max('order'))['max_order'] or 0
                        for offset, media_file in enumerate(media_files, start=1):
                            content_type = (getattr(media_file, 'content_type', '') or '').lower()
                            media_type = (
                                PostMedia.MEDIA_VIDEO
                                if content_type.startswith('video/')
                                else PostMedia.MEDIA_IMAGE
                            )
                            PostMedia.objects.create(
                                post=post,
                                media_file=media_file,
                                media_type=media_type,
                                order=max_order + offset,
                            )

                    tag_ids = []
                    for raw_id in request.POST.getlist('tagged_vendors'):
                        try:
                            tag_ids.append(int(raw_id))
                        except (TypeError, ValueError):
                            continue
                    if tag_ids:
                        tagged = get_user_model().objects.filter(user_type='vendor', id__in=tag_ids)
                        post.tagged_vendors.set(tagged)
                    else:
                        post.tagged_vendors.clear()

                messages.success(request, 'Post updated successfully.')
                return redirect(next_url)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PostEditForm(instance=post)

    existing_media = list(post.media.all())
    legacy_media = post.image

    return render(request, 'core/community_post_edit.html', {
        'post': post,
        'form': form,
        'vendors': vendors,
        'existing_media': existing_media,
        'legacy_media': legacy_media,
        'next_url': next_url,
        'selected_vendor_ids': {vendor.id for vendor in post.tagged_vendors.all()},
    })


@login_required(login_url='account_login_choice')
def community_post_delete(request, post_id):
    if request.method != 'POST':
        return redirect('community_feed')
    post = get_object_or_404(Post, id=post_id, user=request.user)
    next_url = request.POST.get('next') or reverse('community_feed')
    post.delete()
    messages.success(request, 'Post deleted.')
    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_comment_create(request, post_id):
    next_url = request.POST.get('next') or f"{reverse('community_feed')}#post-{post_id}"
    if request.method != 'POST':
        return redirect(next_url)

    post = get_object_or_404(Post, id=post_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.user = request.user
        parent_id = request.POST.get('parent_id')
        if parent_id:
            parent_comment = get_object_or_404(Comment, id=parent_id, post=post)
            if parent_comment.parent_id:
                messages.error(request, 'Replies can only be added to top-level comments.')
                return redirect(next_url)
            if request.user.id != post.user_id:
                messages.error(request, 'Only the original poster can reply to comments.')
                return redirect(next_url)
            comment.parent = parent_comment
        comment.save()
        if post.user_id != request.user.id:
            create_notification(
                post.user,
                f'{request.user.get_full_name() or request.user.username} commented on your post.',
                Notification.TYPE_COMMENT,
                related_object_id=post.id,
            )
        if comment.parent_id and comment.parent.user_id != request.user.id:
            create_notification(
                comment.parent.user,
                f'{request.user.get_full_name() or request.user.username} replied to your comment.',
                Notification.TYPE_COMMENT,
                related_object_id=post.id,
            )
        messages.success(request, 'Comment added.')
    else:
        messages.error(request, 'Please write a comment before submitting.')

    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_post_like_toggle(request, post_id):
    next_url = request.POST.get('next') or f"{reverse('community_feed')}#post-{post_id}"
    if request.method != 'POST':
        return redirect(next_url)

    post = get_object_or_404(Post, id=post_id)
    if post.likes.filter(id=request.user.id).exists():
        post.likes.remove(request.user)
    else:
        post.likes.add(request.user)
        if post.user_id != request.user.id:
            if getattr(post.user, 'user_type', '') == 'traveler':
                add_points(post.user, 'like_received', 2)
                sync_badges_for_user(post.user)
            create_notification(
                post.user,
                f'{request.user.get_full_name() or request.user.username} liked your community post.',
                Notification.TYPE_LIKE,
                related_object_id=post.id,
            )

    return redirect(next_url)


@login_required(login_url='account_login_choice')
def submit_review(request):
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('review_list')
    if request.method != 'POST':
        return redirect(next_url)

    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return redirect(next_url)

    review_packages = Package.objects.filter(is_active=True)
    form = ReviewForm(request.POST, package_queryset=review_packages)
    if form.is_valid():
        review = form.save(commit=False)
        review.traveler = request.user
        review.save()
        add_points(request.user, 'review', 15)
        sync_badges_for_user(request.user)
        messages.success(request, 'Thanks for sharing your review!')
    else:
        messages.error(request, 'Please provide a rating and comment.')

    return redirect(next_url)
