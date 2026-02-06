from django.urls import path
from . import views

urlpatterns = [
    path('traveler/login/', views.traveler_login, name='traveler_login'),
    path('traveler/register/', views.traveler_register, name='traveler_register'),  

    path('vendor/login/', views.vendor_login, name='vendor_login'),
    path('vendor/register/', views.vendor_register, name='vendor_register'),
    path('vendor/dashboard/', views.vendor_dashboard, name='vendor_dashboard'),
    path('vendor/packages/', views.vendor_packages, name='vendor_packages'),
    path('vendor/bookings/', views.vendor_bookings, name='vendor_bookings'),
    path('vendor/reviews/', views.vendor_reviews, name='vendor_reviews'),
    path('vendor/analytics/', views.vendor_analytics, name='vendor_analytics'),
    path('vendor/settings/', views.vendor_settings, name='vendor_settings'),
    
    path('admin/login/', views.admin_login, name='admin_login'),

    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    
    path('logout/', views.logout_view, name='logout'),
]
