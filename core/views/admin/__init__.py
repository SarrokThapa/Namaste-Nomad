from .booking_view import admin_bookings
from .dashboard_view import admin_dashboard
from .package_view import admin_packages
from .report_view import admin_reports
from .review_view import admin_reviews
from .settings_view import admin_settings
from .subscription_view import admin_subscriptions
from .user_view import admin_users
from .vendor_view import admin_vendors

__all__ = [
	'admin_dashboard',
	'admin_subscriptions',
	'admin_users',
	'admin_bookings',
	'admin_vendors',
	'admin_packages',
	'admin_reviews',
	'admin_reports',
	'admin_settings',
]
