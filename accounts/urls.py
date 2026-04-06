from django.urls import path
from core.views.admin.booking_view import admin_bookings
from core.views.admin.dashboard_view import admin_dashboard
from core.views.admin.settings_view import admin_settings
from core.views.admin.subscription_view import admin_subscriptions
from core.views.admin.user_view import admin_users
from core.views.admin.vendor_view import admin_vendors
from core.views.admin.package_view import admin_packages
from core.views.admin.review_view import admin_reviews
from core.views.admin.report_view import admin_reports
from .views.admin_views import (
    admin_analytics_api,
    admin_feature_plan_create,
    admin_feature_toggle,
    admin_package_toggle,
    admin_profile,
    admin_subscription_deactivate,
    admin_support_chat,
    admin_support_inbox,
    admin_traveler_action,
    admin_transactions,
    admin_vendor_action,
    admin_vendor_detail,
)
from .views.auth_views import (
    account_login_choice,
    account_register_choice,
    admin_login,
    forgot_password,
    forgot_password_new_password,
    forgot_password_resend,
    forgot_password_verify,
    logout_view,
    oauth_post_login_redirect,
    oauth_role_selection,
    resend_otp,
    traveler_login,
    traveler_register,
    vendor_login,
    vendor_register,
    verify_otp_view,
)
from .views.profile_views import (
    traveler_achievements,
    traveler_bookings,
    traveler_home,
    traveler_profile,
    traveler_transactions,
    traveler_wishlist,
    vendor_profile,
    vendor_public_profile,
    wishlist_toggle,
)
from .views.vendor.vendor_booking import (
    vendor_booking_status_update,
    vendor_bookings,
    vendor_reviews,
)
from .views.vendor.vendor_dashboard import (
    notifications_data,
    notifications_list,
    notifications_mark_read,
    support_chat,
    support_widget_data,
    support_widget_send,
    vendor_dashboard,
    vendor_settings,
    vendor_transactions,
)
from .views.vendor.vendor_package import (
    vendor_feature_toggle,
    vendor_package_create,
    vendor_package_delete,
    vendor_package_edit,
    vendor_packages,
)
from .views.vendor.vendor_subscription import (
    vendor_plan_esewa_failure,
    vendor_plan_esewa_success,
    vendor_plan_purchase,
    vendor_plan_stripe_cancel,
    vendor_plan_stripe_success,
)

urlpatterns = [
    path('login/', account_login_choice, name='account_login_choice'),
    path('register/', account_register_choice, name='account_register_choice'),
    path('traveler/login/', traveler_login, name='traveler_login'),
    path('traveler/register/', traveler_register, name='traveler_register'),
    path('traveler/home/', traveler_home, name='traveler_home'),
    path('traveler/wishlist/', traveler_wishlist, name='traveler_wishlist'),
    path('traveler/achievements/', traveler_achievements, name='traveler_achievements'),
    path('traveler/bookings/', traveler_bookings, name='traveler_bookings'),
    path('traveler/transactions/', traveler_transactions, name='traveler_transactions'),
    path('traveler/profile/', traveler_profile, name='traveler_profile'),
    path('wishlist/toggle/', wishlist_toggle, name='wishlist_toggle'),

    path('vendors/<int:vendor_id>/', vendor_public_profile, name='vendor_public_profile'),

    path('vendor/login/', vendor_login, name='vendor_login'),
    path('vendor/register/', vendor_register, name='vendor_register'),
    path('vendor/packages/new/', vendor_package_create, name='vendor_package_create'),
    path('vendor/packages/<int:package_id>/edit/', vendor_package_edit, name='vendor_package_edit'),
    path('vendor/packages/<int:package_id>/delete/', vendor_package_delete, name='vendor_package_delete'),
    path('vendor/dashboard/', vendor_dashboard, name='vendor_dashboard'),
    path('vendor/profile/', vendor_profile, name='vendor_profile'),
    path('vendor/packages/', vendor_packages, name='vendor_packages'),
    path('vendor/packages/<int:package_id>/feature/', vendor_feature_toggle, name='vendor_feature_toggle'),
    path('vendor/bookings/', vendor_bookings, name='vendor_bookings'),
    path('vendor/transactions/', vendor_transactions, name='vendor_transactions'),
    path('vendor/bookings/<int:booking_id>/status/', vendor_booking_status_update, name='vendor_booking_status_update'),
    path('vendor/reviews/', vendor_reviews, name='vendor_reviews'),
    path('vendor/settings/', vendor_settings, name='vendor_settings'),
    path('vendor/feature-plans/<int:plan_id>/purchase/', vendor_plan_purchase, name='vendor_plan_purchase'),
    path('vendor/feature-plans/esewa/success/', vendor_plan_esewa_success, name='vendor_plan_esewa_success'),
    path('vendor/feature-plans/esewa/failure/', vendor_plan_esewa_failure, name='vendor_plan_esewa_failure'),
    path('vendor/feature-plans/stripe/success/', vendor_plan_stripe_success, name='vendor_plan_stripe_success'),
    path('vendor/feature-plans/stripe/cancel/', vendor_plan_stripe_cancel, name='vendor_plan_stripe_cancel'),

    path('support/chat/', support_chat, name='support_chat'),
    path('support/widget/', support_widget_data, name='support_widget_data'),
    path('support/widget/send/', support_widget_send, name='support_widget_send'),
    path('notifications/', notifications_list, name='notifications_list'),
    path('notifications/data/', notifications_data, name='notifications_data'),
    path('notifications/read/', notifications_mark_read, name='notifications_mark_read'),
    
    path('admin/login/', admin_login, name='admin_login'),
    path('admin/support/', admin_support_inbox, name='admin_support_inbox'),
    path('admin/support/<int:conversation_id>/', admin_support_chat, name='admin_support_chat'),
    path('admin/dashboard/', admin_dashboard, name='admin_dashboard'),
    path('admin/subscriptions/', admin_subscriptions, name='admin_subscriptions'),
    path('admin/users/', admin_users, name='admin_users'),
    path('admin/bookings/', admin_bookings, name='admin_bookings'),
    path('admin/vendors/', admin_vendors, name='admin_vendors'),
    path('admin/packages/', admin_packages, name='admin_packages'),
    path('admin/reviews/', admin_reviews, name='admin_reviews'),
    path('admin/reports/', admin_reports, name='admin_reports'),
    path('admin/analytics/', admin_analytics_api, name='admin_analytics_api'),
    path('admin/transactions/', admin_transactions, name='admin_transactions'),
    path('admin/profile/', admin_profile, name='admin_profile'),
    path('admin/settings/', admin_settings, name='admin_settings'),
    path('admin/vendors/<int:vendor_id>/', admin_vendor_detail, name='admin_vendor_detail'),
    path('admin/vendors/<int:vendor_id>/action/', admin_vendor_action, name='admin_vendor_action'),
    path('admin/travelers/<int:traveler_id>/action/', admin_traveler_action, name='admin_traveler_action'),
    path('admin/packages/<int:package_id>/toggle/', admin_package_toggle, name='admin_package_toggle'),
    path('admin/packages/<int:package_id>/feature/', admin_feature_toggle, name='admin_feature_toggle'),
    path('admin/feature-plans/new/', admin_feature_plan_create, name='admin_feature_plan_create'),
    path('admin/subscriptions/<int:subscription_id>/deactivate/', admin_subscription_deactivate, name='admin_subscription_deactivate'),

    path('verify-otp/', verify_otp_view, name='verify_otp'),
    path('resend-otp/', resend_otp, name='resend_otp'),
    path('forgot-password/', forgot_password, name='forgot_password'),
    path('forgot-password/verify/', forgot_password_verify, name='forgot_password_verify'),
    path('forgot-password/resend/', forgot_password_resend, name='forgot_password_resend'),
    path('forgot-password/new-password/', forgot_password_new_password, name='forgot_password_new_password'),
    path('oauth/post-login/', oauth_post_login_redirect, name='oauth_post_login_redirect'),
    path('oauth/role-selection/', oauth_role_selection, name='oauth_role_selection'),
    
    path('logout/', logout_view, name='logout'),
]
