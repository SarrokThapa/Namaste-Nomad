"""Package search and filter service for public discovery pages."""

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import FeaturedPackage
from core.models import Package


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


def _getlist(params, key):
    if hasattr(params, 'getlist'):
        return params.getlist(key)
    value = params.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def budget_threshold(queryset):
    prices = list(queryset.values_list('price', flat=True).order_by('price'))
    if not prices:
        return None
    index = max(0, int(len(prices) * 0.25) - 1)
    return float(prices[index])


def trending_destinations():
    return [
        'Kathmandu',
        'Pokhara',
        'Everest Region',
        'Annapurna',
    ]


def filter_packages(queryset, params, forced_category=None, budget_cutoff=None):
    search_term = (params.get('q') or params.get('destination') or '').strip()
    single_date_raw = (params.get('date') or '').strip()
    date_from_raw = (params.get('date_from') or '').strip()
    date_to_raw = (params.get('date_to') or '').strip()
    travelers = _parse_int(params.get('travelers') or params.get('people'))
    package_type = (params.get('package_type') or '').strip().lower()
    price_min = _parse_float(params.get('price_min'))
    price_max = _parse_float(params.get('price_max'))
    duration_filters = [str(value).strip() for value in _getlist(params, 'duration') if str(value).strip()]
    difficulty_filters = [str(value).strip().lower() for value in _getlist(params, 'difficulty') if str(value).strip()]
    difficulty_single = (params.get('difficulty') or '').strip().lower()
    rating_min = _parse_int(params.get('rating'))
    season_filters = [str(value).strip().lower() for value in _getlist(params, 'season') if str(value).strip()]
    amenity_filters = [str(value).strip().lower() for value in _getlist(params, 'amenities') if str(value).strip()]
    verified_only = (params.get('verified_only') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    quick_filter = (params.get('quick') or '').strip().lower()
    sort = (params.get('sort') or 'popular').strip().lower()

    if difficulty_single and difficulty_single not in {'difficulty level', 'all'}:
        difficulty_filters.append(difficulty_single)
    difficulty_filters = list(dict.fromkeys(difficulty_filters))

    if search_term:
        queryset = queryset.filter(
            Q(title__icontains=search_term)
            | Q(location__icontains=search_term)
            | Q(location_name__icontains=search_term)
        )

    date_exact = parse_date(single_date_raw) if single_date_raw else None
    if date_exact:
        queryset = queryset.filter(
            available_from__isnull=False,
            available_until__isnull=False,
            available_from__lte=date_exact,
            available_until__gte=date_exact,
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

    today = timezone.localdate()
    featured_subquery = FeaturedPackage.objects.filter(
        package=OuterRef('pk'),
        is_active=True,
        subscription__is_active=True,
        subscription__payment_status='paid',
        subscription__start_date__lte=today,
        subscription__end_date__gte=today,
    )
    queryset = queryset.annotate(_featured=Exists(featured_subquery))

    if quick_filter == 'best_rated':
        queryset = queryset.filter(avg_rating__gte=4.5)
    elif quick_filter == 'budget':
        threshold = budget_cutoff
        if threshold is None:
            threshold = budget_threshold(queryset)
        if threshold is not None:
            queryset = queryset.filter(price__lte=threshold)
    elif quick_filter == 'featured':
        queryset = queryset.filter(_featured=True)
    elif quick_filter == 'beginner':
        queryset = queryset.filter(difficulty__in=['easy', 'moderate'])

    if sort == 'price_low':
        queryset = queryset.order_by('-_featured', 'price', '-avg_rating')
    elif sort == 'price_high':
        queryset = queryset.order_by('-_featured', '-price', '-avg_rating')
    elif sort == 'rating':
        queryset = queryset.order_by('-_featured', '-avg_rating', '-review_count')
    elif sort == 'newest':
        queryset = queryset.order_by('-_featured', '-created_at')
    else:
        sort = 'popular'
        queryset = queryset.order_by('-_featured', '-booking_count', '-views_count', '-created_at')

    applied = {
        'destination': search_term,
        'date': single_date_raw,
        'date_from': date_from_raw,
        'date_to': date_to_raw,
        'travelers': travelers or '',
        'people': travelers or '',
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
