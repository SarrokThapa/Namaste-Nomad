"""Shared core view helpers and dependencies."""

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

from ..forms import BookingForm, CommentForm, ContactMessageForm, PostEditForm, PostForm, ReviewForm

from ..invoices import generate_invoice_pdf, invoice_data_for_booking

from ..models import (
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

from ..payments import (
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

TAG_PATTERN = re.compile(r'@([A-Za-z0-9_.+-]+)')

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


def _can_access_booking_invoice(user, booking):
    if not user.is_authenticated:
        return False
    if getattr(user, 'user_type', '') == 'admin' and user.is_staff:
        return True
    return booking.traveler_id == user.id


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

__all__ = [
    'date',
    'timedelta',
    'Decimal',
    'InvalidOperation',
    're',
    'settings',
    'messages',
    'get_user_model',
    'login_required',
    'send_mail',
    'ObjectDoesNotExist',
    'Paginator',
    'transaction',
    'Avg',
    'Count',
    'F',
    'Max',
    'Min',
    'OuterRef',
    'Prefetch',
    'Q',
    'Subquery',
    'Sum',
    'Http404',
    'HttpResponse',
    'JsonResponse',
    'get_object_or_404',
    'redirect',
    'render',
    'render_to_string',
    'reverse',
    'parse_date',
    'timezone',
    'escape',
    'mark_safe',
    'FeatureSlot',
    'Notification',
    'RewardPoint',
    'TravelerProfile',
    'UserBadge',
    'VendorFeature',
    'VendorSubscription',
    'add_points',
    'sync_badges_for_user',
    'total_points_for_user',
    'discount_for_points',
    'create_notification',
    'notify_admins',
    'BookingForm',
    'CommentForm',
    'ContactMessageForm',
    'PostEditForm',
    'PostForm',
    'ReviewForm',
    'generate_invoice_pdf',
    'invoice_data_for_booking',
    'Booking',
    'Comment',
    'Discount',
    'Package',
    'Post',
    'PostMedia',
    'Review',
    'SpecialOffer',
    'SupportConversation',
    'SupportMessage',
    'Transaction',
    'TravelTip',
    'Wishlist',
    'EsewaError',
    'StripeError',
    'build_esewa_payment_payload',
    'create_checkout_session',
    'expire_checkout_session',
    'get_esewa_payment_url',
    'retrieve_checkout_session',
    'verify_esewa_payment',
    'BLOG_POSTS',
    'TAG_PATTERN',
    '_safe_related',
    '_user_display_name',
    '_user_avatar_url',
    '_public_profile_url_for_user',
    '_vendor_display_name',
    '_vendor_is_verified',
    '_verified_badge_html',
    '_caption_with_vendor_links',
    '_prepare_review_cards',
    '_prepare_feed_posts',
    '_traveler_level_label',
    '_community_posts',
    '_get_or_create_traveler_profile',
    '_can_access_booking_invoice',
    '_parse_int',
    '_parse_float',
    '_budget_threshold',
    '_apply_package_filters',
    '_public_package_queryset',
    '_wishlist_ids_for_user',
    '_render_package_list',
]
