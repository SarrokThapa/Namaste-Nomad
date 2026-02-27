# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('community/', views.community_feed, name='community_feed'),
    path('dashboard/community/', views.community_dashboard, name='community_dashboard'),
    path('community/posts/new/', views.community_post_create, name='community_post_create'),
    path('community/posts/<int:post_id>/comment/', views.community_comment_create, name='community_comment_create'),
    path('packages/', views.package_list, name='package_list'),
    path('packages/<int:package_id>/', views.package_detail, name='package_detail'),
    path('reviews/', views.review_list, name='review_list'),
    path('reviews/submit/', views.submit_review, name='submit_review'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
]
