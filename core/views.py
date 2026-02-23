# core/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ReviewForm
from .models import Package, Review

def home(request):
    """Landing page"""
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')[:6]
    review_packages = Package.objects.filter(is_active=True).order_by('title')
    can_review = request.user.is_authenticated and getattr(request.user, 'user_type', '') == 'traveler'
    return render(request, 'core/home.html', {
        'reviews': reviews,
        'review_packages': review_packages,
        'can_review': can_review,
    })

def package_list(request):
    packages = Package.objects.filter(is_active=True).prefetch_related('images').annotate(
        review_count=Count('reviews', distinct=True),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-created_at')
    return render(request, 'core/packages.html', {
        'packages': packages,
    })

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

def contact(request):
    """Contact page"""
    return render(request, 'core/contact.html')


@login_required(login_url='account_login_choice')
def submit_review(request):
    if request.method != 'POST':
        return redirect('home')

    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return redirect('home')

    review_packages = Package.objects.filter(is_active=True)
    form = ReviewForm(request.POST, package_queryset=review_packages)
    if form.is_valid():
        review = form.save(commit=False)
        review.traveler = request.user
        review.save()
        messages.success(request, 'Thanks for sharing your review!')
    else:
        messages.error(request, 'Please provide a rating and comment.')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('home')
    return redirect(next_url)
