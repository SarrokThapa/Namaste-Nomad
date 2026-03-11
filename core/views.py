# core/views.py
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import TravelerProfile, VendorSubscription
from .forms import BookingForm, CommentForm, PostForm, ReviewForm
from .models import Booking, Comment, Package, Post, Review
from .payments import (
    StripeError,
    create_checkout_session,
    expire_checkout_session,
    retrieve_checkout_session,
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


def _prepare_review_cards(review_queryset):
    reviews = list(review_queryset)

    for review in reviews:
        traveler = review.traveler
        review.traveler_name = _user_display_name(traveler)
        review.traveler_avatar_url = _user_avatar_url(traveler)

    return reviews


def _prepare_feed_posts(post_queryset, viewer=None):
    posts = list(post_queryset)
    viewer_id = viewer.id if getattr(viewer, 'is_authenticated', False) else None

    for post in posts:
        post.author_name = _user_display_name(post.user)
        post.author_avatar_url = _user_avatar_url(post.user)

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
        status=Booking.STATUS_PAYMENT_PENDING,
        payment_status=Booking.PAYMENT_STATUS_PENDING,
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
        stale_booking.payment_status = Booking.PAYMENT_STATUS_EXPIRED
        stale_booking.payment_expires_at = None
        stale_booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _cancel_unpaid_booking(booking, payment_status):
    if (
        booking.status == Booking.STATUS_PAYMENT_PENDING
        and booking.payment_status == Booking.PAYMENT_STATUS_PENDING
    ):
        Package.objects.filter(id=booking.package_id).update(
            available_slots=F('available_slots') + booking.number_of_people,
        )
    booking.status = Booking.STATUS_CANCELLED
    booking.payment_status = payment_status
    booking.payment_expires_at = None
    booking.save(update_fields=['status', 'payment_status', 'payment_expires_at'])


def _complete_paid_booking(booking, session_data):
    booking.status = Booking.STATUS_PENDING
    booking.payment_status = Booking.PAYMENT_STATUS_PAID
    booking.payment_reference = (
        session_data.get('payment_intent')
        or session_data.get('id')
        or booking.payment_reference
    )
    booking.stripe_checkout_session_id = (
        session_data.get('id')
        or booking.stripe_checkout_session_id
    )
    if not booking.paid_at:
        booking.paid_at = timezone.now()
    booking.payment_expires_at = None
    booking.save(
        update_fields=[
            'status',
            'payment_status',
            'payment_reference',
            'stripe_checkout_session_id',
            'paid_at',
            'payment_expires_at',
        ]
    )


def home(request):
    """Landing page"""
    VendorSubscription.expire_overdue()
    today = timezone.localdate()
    active_vendor_ids = VendorSubscription.objects.filter(
        status=VendorSubscription.STATUS_ACTIVE,
        start_date__lte=today,
        end_date__gte=today,
    ).values_list('vendor_id', flat=True).distinct()
    featured_packages = (
        Package.objects.filter(
            is_active=True,
            is_featured=True,
            vendor_id__in=active_vendor_ids,
        )
        .select_related('vendor')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
        )
        .order_by('-created_at', '-views_count', '-avg_rating')[:6]
    )
    featured_ids = list(featured_packages.values_list('id', flat=True))
    popular_packages = (
        Package.objects.filter(
            is_active=True,
            category=Package.CATEGORY_TREK,
        )
        .exclude(id__in=featured_ids)
        .select_related('vendor')
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
    return render(request, 'core/home.html', {
        'reviews': reviews,
        'featured_packages': featured_packages,
        'popular_packages': popular_packages,
    })


def _public_package_queryset():
    return Package.objects.filter(is_active=True).prefetch_related('images').annotate(
        review_count=Count('reviews', distinct=True),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-created_at')


def _render_package_list(request, category=None):
    VendorSubscription.expire_overdue()
    packages = _public_package_queryset()
    package_scope = 'all'
    page_title = 'Nepal Treks & Tours'
    page_subtitle = 'Explore the Himalayas with trusted local operators.'
    empty_message = 'No packages available right now.'

    if category == Package.CATEGORY_TREK:
        packages = packages.filter(category="TREK")
        package_scope = 'treks'
        page_title = 'Nepal Treks'
        page_subtitle = 'Browse trekking adventures curated by local experts.'
        empty_message = 'No trek packages available right now.'
    elif category == Package.CATEGORY_TOUR:
        packages = packages.filter(category="TOUR")
        package_scope = 'tours'
        page_title = 'Nepal Tours'
        page_subtitle = 'Browse curated tour experiences across Nepal.'
        empty_message = 'No tour packages available right now.'

    return render(request, 'core/packages.html', {
        'packages': packages,
        'package_scope': package_scope,
        'page_title': page_title,
        'page_subtitle': page_subtitle,
        'empty_message': empty_message,
    })


def package_list(request):
    return _render_package_list(request)


def trek_package_list(request):
    return _render_package_list(request, category=Package.CATEGORY_TREK)


def tour_package_list(request):
    return _render_package_list(request, category=Package.CATEGORY_TOUR)

def package_detail(request, package_id):
    package = get_object_or_404(Package.objects.prefetch_related('images'), id=package_id)
    if not package.is_active and package.vendor != request.user:
        return render(request, 'core/package_not_available.html', status=404)

    Package.objects.filter(id=package.id).update(views_count=package.views_count + 1)
    package.views_count += 1

    reviews_base = Review.objects.filter(package=package).select_related('traveler')
    sort = (request.GET.get('sort') or 'recent').lower()
    if sort == 'highest':
        reviews = reviews_base.order_by('-rating', '-created_at')
    elif sort == 'lowest':
        reviews = reviews_base.order_by('rating', '-created_at')
    else:
        sort = 'recent'
        reviews = reviews_base.order_by('-created_at')

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
            with transaction.atomic():
                _expire_stale_pending_bookings(package_id=package.id)
                locked_package = Package.objects.select_for_update().get(id=package.id)
                number_of_people = form.cleaned_data['number_of_people']

                if number_of_people > locked_package.available_slots:
                    form.add_error(
                        'number_of_people',
                        f'Only {locked_package.available_slots} slot(s) are currently available.',
                    )
                else:
                    booking = form.save(commit=False)
                    booking.package = locked_package
                    booking.traveler = request.user
                    booking.status = Booking.STATUS_PAYMENT_PENDING
                    booking.payment_method = Booking.PAYMENT_METHOD_STRIPE
                    booking.payment_status = Booking.PAYMENT_STATUS_PENDING
                    booking.source = 'direct'
                    booking.payment_expires_at = _booking_payment_expires_at()
                    booking.save()

                    locked_package.available_slots -= number_of_people
                    locked_package.save(update_fields=['available_slots'])

            if form.errors:
                package.refresh_from_db(fields=['available_slots'])
            else:
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
                            Booking.PAYMENT_STATUS_CANCELLED,
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
                    return redirect(checkout_url)
    else:
        form = BookingForm(
            package=package,
            initial={
                'number_of_people': 1,
                'travel_date': timezone.localdate(),
                'payment_method': Booking.PAYMENT_METHOD_STRIPE,
            },
        )

    return render(request, 'core/booking_form.html', {
        'package': package,
        'form': form,
        'estimated_total': package.price,
    })


@login_required(login_url='account_login_choice')
def booking_confirmation(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status != Booking.PAYMENT_STATUS_PAID:
        session_id = request.GET.get('session_id') or booking.stripe_checkout_session_id
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
                            locked_booking.status == Booking.STATUS_PAYMENT_PENDING
                            and locked_booking.payment_status != Booking.PAYMENT_STATUS_PAID
                        ):
                            _complete_paid_booking(locked_booking, session_data)
                        booking = locked_booking
                    if booking.payment_status == Booking.PAYMENT_STATUS_PAID:
                        messages.success(
                            request,
                            'Stripe payment received. Your booking is now waiting for vendor confirmation.',
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

    return render(request, 'core/booking_confirmation.html', {'booking': booking})


@login_required(login_url='account_login_choice')
def booking_checkout_cancel(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_PAID:
        return redirect('booking_confirmation', booking_id=booking.id)

    with transaction.atomic():
        locked_booking = get_object_or_404(
            Booking.objects.select_for_update().select_related('package'),
            id=booking_id,
            traveler=request.user,
        )
        if locked_booking.payment_status == Booking.PAYMENT_STATUS_PENDING:
            _cancel_unpaid_booking(
                locked_booking,
                Booking.PAYMENT_STATUS_CANCELLED,
            )

    if booking.stripe_checkout_session_id:
        try:
            expire_checkout_session(booking.stripe_checkout_session_id)
        except StripeError:
            pass

    messages.info(
        request,
        'Stripe checkout was cancelled. Your reserved slots were released.',
    )
    return redirect('package_book', package_id=booking.package_id)


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
    return render(request, 'core/contact.html')


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


def community_feed(request):
    posts = _community_posts(viewer=request.user)

    return render(request, 'core/community_feed.html', {
        'posts': posts,
        'is_dashboard': False,
        'force_show_post_form': False,
    })


@login_required(login_url='traveler_login')
def community_dashboard(request):
    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return redirect('home')

    traveler_profile = _get_or_create_traveler_profile(request.user)
    posts = _community_posts(viewer=request.user)

    return render(request, 'core/community_dashboard.html', {
        'posts': posts,
        'is_dashboard': True,
        'force_show_post_form': True,
        'traveler_profile': traveler_profile,
        'active_page': 'community',
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
        messages.success(request, 'Post shared successfully.')
    else:
        messages.error(request, 'Please upload an image and add a caption.')

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
        messages.success(request, 'Thanks for sharing your review!')
    else:
        messages.error(request, 'Please provide a rating and comment.')

    return redirect(next_url)
