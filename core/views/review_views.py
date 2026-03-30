"""Review listing and submission views."""

from ..utils.helpers import *


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
