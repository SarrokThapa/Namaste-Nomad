# core/views.py
from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import TravelerProfile
from .forms import CommentForm, PostForm, ReviewForm
from .models import Comment, Package, Post, Review

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


def home(request):
    """Landing page"""
    reviews = _prepare_review_cards(
        Review.objects.select_related('traveler', 'traveler__traveler_profile', 'package').order_by('-created_at')[:5]
    )
    return render(request, 'core/home.html', {
        'reviews': reviews,
    })


def _public_package_queryset():
    return Package.objects.filter(is_active=True).prefetch_related('images').annotate(
        review_count=Count('reviews', distinct=True),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-created_at')


def _render_package_list(request, category=None):
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
        'facts': facts,
        'inclusions': inclusions,
        'exclusions': exclusions,
        'itinerary_points': itinerary_points,
        'images': images,
    })

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
