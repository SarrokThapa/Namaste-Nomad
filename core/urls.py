# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('packages/', views.package_list, name='package_list'),
    path('packages/<int:package_id>/', views.package_detail, name='package_detail'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
]
