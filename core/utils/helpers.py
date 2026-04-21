"""Shared core view helpers and dependencies.

Hub module for the ``core/views/`` package — every sibling view file
imports the names it needs from here instead of pulling Django, the
models, the forms, the payments wrapper, or the eSewa service directly.
This keeps each view file short and gives us one place to update an
import path when something is renamed.

Helpers defined inline (not just re-exports):
* ``BLOG_POSTS`` / ``TAG_PATTERN`` — static blog content + @vendor tag regex
* ``_safe_related`` — guarded reverse-OneToOne lookup
* ``_user_display_name`` / ``_user_avatar_url`` / ``_public_profile_url_for_user``
* ``_vendor_display_name`` / ``_vendor_is_verified`` / ``_verified_badge_html``
* ``_caption_with_vendor_links`` — turn ``@username`` into vendor profile links
* ``_prepare_review_cards`` / ``_prepare_feed_posts`` / ``_community_posts``
* ``_get_or_create_traveler_profile``
* ``_can_access_booking_invoice``
* ``_parse_int`` / ``_parse_float``
* ``_budget_threshold`` / ``_apply_package_filters`` / ``_public_package_queryset``
* ``_wishlist_ids_for_user`` / ``_render_package_list``

Do not flatten this hub — multiple view files import from it.
"""

# NOTE: file > 300 lines — split deferred. This is a hub re-export module
# consumed by every file in core/views/; splitting would force matching
# import-path edits across all consumers.

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
    Notification,
    RewardPoint,
    TravelerProfile,
    UserBadge,
    VendorFeatureSubscription,
)

from accounts.achievements import (
    add_points,
    sync_badges_for_user,
    total_points_for_user,
    discount_for_points,
)

from accounts.notifications import create_notification, notify_admins
from core.selectors import public_package_queryset, wishlist_ids_for_user

# --- Forms, services, and invoice helpers re-exported through this hub ------
from ..forms import BookingForm, CommentForm, ContactMessageForm, PostEditForm, PostForm, ReviewForm
from ..services.search_service import budget_threshold as search_budget_threshold, filter_packages as filter_packages_service

from ..invoices import generate_invoice_pdf, invoice_data_for_booking

from ..models import (
    Booking,
    BookingTraveler,
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

# Stripe wrapper for international card payments.
from ..payments import (
    StripeError,
    create_checkout_session,
    expire_checkout_session,
    retrieve_checkout_session,
)
# eSewa V2 (HMAC-SHA256, NPR) for Nepal-side payments. Aliased so views can
# call ``build_esewa_payment_payload`` etc. without remembering the original
# function names inside the service module.
from ..services.esewa_service import (
    EsewaError,
    get_esewa_payment_url,
    build_booking_payment_payload as build_esewa_payment_payload,
    build_payment_payload as build_esewa_generic_payload,
    process_success_callback as esewa_process_success_callback,
)

# --- Static blog content ----------------------------------------------------
# Hardcoded blog posts shown on the public site. Kept inline (instead of in
# the database) so non-technical edits to copy can be made by updating this
# list directly.
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

# Matches ``@username`` mentions inside community post captions.
TAG_PATTERN = re.compile(r'@([A-Za-z0-9_.+-]+)')


def _safe_related(instance, attribute_name):
    """``getattr`` that returns ``None`` instead of raising for a missing related row.

    Useful for reverse OneToOne lookups like ``user.traveler_profile`` where
    the related object may simply not exist yet.
    """
    try:
        return getattr(instance, attribute_name)
    except ObjectDoesNotExist:
        return None


def _user_display_name(user):
    """Best-effort human label for a user (full name → username → 'Traveler')."""
    if not user:
        return "Traveler"
    full_name = user.get_full_name().strip()
    return full_name or user.username or "Traveler"


def _user_avatar_url(user):
    """Avatar URL for a user, switching on user_type to find the right profile."""
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
    """Reverse the public profile URL for a traveler or vendor (admins → '')."""
    if not user:
        return ''

    user_type = getattr(user, 'user_type', '')
    if user_type == 'traveler':
        return reverse('public_traveler_profile', kwargs={'user_id': user.id})
    if user_type == 'vendor':
        return reverse('vendor_public_profile', kwargs={'vendor_id': user.id})
    return ''


def _vendor_display_name(vendor):
    """Best-effort vendor label: business name → full name → username → 'Vendor'."""
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
    """True iff the vendor's profile has the admin-set ``is_verified`` flag."""
    if not vendor:
        return False
    profile = _safe_related(vendor, 'vendor_profile')
    return bool(profile and profile.is_verified)


def _verified_badge_html(is_verified):
    """Tiny inline 'Verified ✔' badge HTML; empty string if not verified."""
    if not is_verified:
        return ""
    return (
        '<span class="verified-badge verified-badge--tiny">'
        '<span class="verified-badge-icon">✔</span>'
        '<span>Verified</span>'
        '</span>'
    )


def _caption_with_vendor_links(post):
    """Render a community post caption as safe HTML with @vendor links.

    Replaces ``@username`` mentions with anchors to the vendor's public
    profile, escapes everything else, and appends any tagged vendors that
    were not mentioned in the caption text on a "Tagged:" line.
    """
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
    """Decorate each review with the traveler's display name, avatar, and profile URL."""
    reviews = list(review_queryset)

    for review in reviews:
        traveler = review.traveler
        review.traveler_name = _user_display_name(traveler)
        review.traveler_avatar_url = _user_avatar_url(traveler)
        review.traveler_profile_url = _public_profile_url_for_user(traveler)

    return reviews


def _prepare_feed_posts(post_queryset, viewer=None):
    """Annotate community posts with everything the feed template needs.

    For each post we attach: author name/avatar/profile URL, vendor-verified
    flag, rendered caption HTML (with @mentions linked), media items, like
    count, ``is_liked_by_current_user``, and a nested top-level/reply
    comment tree under ``prepared_comments``.
    """
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
    """Map a reward-points total to a level badge ('Beginner' / 'Pro')."""
    return 'Pro Traveler' if total_points >= 200 else 'Beginner Traveler'


def _community_posts(viewer=None):
    """Build the community feed queryset with all the prefetches the cards need."""
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
    """Return the user's TravelerProfile, creating an empty one if missing."""
    profile = _safe_related(user, 'traveler_profile')
    if profile is None:
        profile = TravelerProfile.objects.create(user=user)
    return profile


def _can_access_booking_invoice(user, booking):
    """Authorization check: only admins or the booking owner may view the invoice."""
    if not user.is_authenticated:
        return False
    if getattr(user, 'user_type', '') == 'admin' and user.is_staff:
        return True
    return booking.traveler_id == user.id


def _parse_int(value):
    """``int(value)`` that returns ``None`` for blank/invalid input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    """``float(value)`` that returns ``None`` for blank/invalid input."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _budget_threshold(queryset):
    """Wrapper around the search service so views import it via the helpers hub."""
    return search_budget_threshold(queryset)


def _apply_package_filters(request, queryset, forced_category=None, budget_threshold=None):
    """Apply the search/filter service to a package queryset using ``request.GET``."""
    return filter_packages_service(
        queryset,
        request.GET,
        forced_category=forced_category,
        budget_cutoff=budget_threshold,
    )


def _public_package_queryset():
    """Wrapper kept under its old underscore name; logic lives in the selectors layer."""
    return public_package_queryset()


def _wishlist_ids_for_user(user):
    """IDs of packages the user has wishlisted; used to mark hearts in templates."""
    return wishlist_ids_for_user(user)


def _render_package_list(request, category=None):
    """Render the public package list page, optionally scoped to TREK or TOUR."""
    VendorFeatureSubscription.expire_overdue()
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
    'Notification',
    'RewardPoint',
    'TravelerProfile',
    'UserBadge',
    'VendorFeatureSubscription',
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
    'BookingTraveler',
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
    'build_esewa_generic_payload',
    'esewa_process_success_callback',
    'create_checkout_session',
    'expire_checkout_session',
    'get_esewa_payment_url',
    'retrieve_checkout_session',
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
