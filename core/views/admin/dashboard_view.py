from django.db.models import Avg, Sum
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.shortcuts import render

from accounts.models import User, VendorFeatureSubscription
from accounts.views.common import _admin_analytics_year_options, _get_admin_profile, admin_required
from core.models import Booking, Package, Review
from core.services.subscription_service import expire_overdue_subscriptions


@never_cache
@admin_required
def admin_dashboard(request):
    expire_overdue_subscriptions()

    admin_profile = _get_admin_profile(request.user)
    vendors = User.objects.filter(user_type='vendor').select_related('vendor_profile')
    pending_vendors = vendors.filter(vendor_profile__is_approved=False, is_active=True)

    bookings = Booking.objects.select_related('package', 'traveler', 'vendor', 'package__vendor').order_by('-created_at')
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')

    paid_subscriptions = VendorFeatureSubscription.objects.filter(
        payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
    )

    platform_earnings = bookings.filter(status=Booking.STATUS_CONFIRMED).aggregate(total=Sum('platform_fee'))['total'] or 0
    vendor_earnings = bookings.filter(status=Booking.STATUS_CONFIRMED).aggregate(total=Sum('vendor_amount'))['total'] or 0
    subscription_revenue = paid_subscriptions.aggregate(total=Sum('price'))['total'] or 0

    stats = {
        'platform_earnings': float(platform_earnings),
        'vendor_earnings': float(vendor_earnings),
        'subscription_revenue': float(subscription_revenue),
        'total_users': User.objects.filter(user_type__in=['traveler', 'vendor']).count(),
        'active_vendors': vendors.filter(is_active=True, vendor_profile__is_approved=True).count(),
        'total_bookings': bookings.count(),
        'total_packages': Package.objects.count(),
        'total_reviews': reviews.count(),
        'avg_rating': round(reviews.aggregate(avg=Avg('rating'))['avg'] or 0, 1),
    }

    activity_items = []
    for booking in bookings[:3]:
        actor = booking.traveler.get_full_name() if booking.traveler else 'Traveler'
        activity_items.append({
            'action': 'New Booking',
            'actor': actor or 'Traveler',
            'date': booking.created_at,
            'details': booking.package.title,
        })

    recent_packages = Package.objects.select_related('vendor').order_by('-created_at')[:2]
    for package in recent_packages:
        activity_items.append({
            'action': 'Package Created',
            'actor': package.vendor.get_full_name() or package.vendor.email,
            'date': package.created_at,
            'details': package.title,
        })

    for review in reviews[:2]:
        activity_items.append({
            'action': 'Review Posted',
            'actor': review.traveler.get_full_name() if review.traveler else 'Traveler',
            'date': review.created_at,
            'details': f'{review.rating}-star rating',
        })

    activity_items.sort(key=lambda item: item['date'], reverse=True)
    activity_items = activity_items[:6]

    current_year = timezone.localdate().year

    return render(request, 'admin/dashboard.html', {
        'admin_profile': admin_profile,
        'stats': stats,
        'activity_items': activity_items,
        'pending_vendors': pending_vendors,
        'analytics_years': _admin_analytics_year_options(),
        'selected_analytics_year': current_year,
        'active_page': 'dashboard',
        'breadcrumb': 'Dashboard',
    })
