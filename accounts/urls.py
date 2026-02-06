from django.urls import path
from . import views

urlpatterns = [
    path('traveler/login/', views.traveler_login, name='traveler_login'),
    path('traveler/register/', views.traveler_register, name='traveler_register'),  

    path('vendor/login/', views.vendor_login, name='vendor_login'),
    path('vendor/register/', views.vendor_register, name='vendor_register'),
    path('vendor/dashboard/', views.vendor_dashboard, name='vendor_dashboard'),
    
    path('admin/login/', views.admin_login, name='admin_login'),

    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    
    path('logout/', views.logout_view, name='logout'),
]
