"""Admin: high-level reports page (earnings, totals, recent bookings)."""

from django.db.models import Avg, Sum
from django.shortcuts import render

from accounts.models import User, VendorFeatureSubscription
from accounts.views.common import _get_admin_profile, admin_required
from core.models import Booking, Package, Review


@admin_required
def admin_reports(request):
    """Aggregate platform/vendor/subscription revenue and recent bookings for the reports page."""
    bookings = Booking.objects.filter(traveler__isnull=False)
    confirmed_bookings = bookings.filter(status=Booking.STATUS_CONFIRMED)
    paid_subscriptions = VendorFeatureSubscription.objects.filter(
        payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
    )

    stats = {
        'platform_earnings': float(confirmed_bookings.aggregate(total=Sum('platform_fee'))['total'] or 0),
        'vendor_earnings': float(confirmed_bookings.aggregate(total=Sum('vendor_amount'))['total'] or 0),
        'subscription_revenue': float(paid_subscriptions.aggregate(total=Sum('price'))['total'] or 0),
        'total_users': User.objects.filter(user_type__in=['traveler', 'vendor']).count(),
        'total_bookings': bookings.count(),
        'total_packages': Package.objects.count(),
        'total_reviews': Review.objects.filter(traveler__isnull=False).count(),
        'avg_rating': round(Review.objects.filter(traveler__isnull=False).aggregate(avg=Avg('rating'))['avg'] or 0, 1),
    }

    recent_bookings = Booking.objects.filter(traveler__isnull=False).select_related(
        'traveler',
        'package',
    ).order_by('-created_at')[:10]

    return render(request, 'admin/reports.html', {
        'admin_profile': _get_admin_profile(request.user),
        'stats': stats,
        'recent_bookings': recent_bookings,
        'active_page': 'reports',
        'breadcrumb': 'Reports',
    })
