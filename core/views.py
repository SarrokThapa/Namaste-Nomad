# core/views.py
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, render

from .models import Package, Review

def home(request):
    """Landing page"""
    return render(request, 'core/home.html')

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

    reviews = Review.objects.filter(package=package).select_related('traveler').order_by('-created_at')
    rating = reviews.aggregate(avg=Avg('rating'), count=Count('id'))
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
