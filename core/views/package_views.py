"""Package discovery and public content views."""

from ..utils.helpers import *
from ..utils.validators import *
from ..services.search_service import filter_packages
from .payment_views import *




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
    filtered_packages, filters = filter_packages(
        packages,
        request.GET,
        budget_cutoff=_budget_threshold(packages),
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
