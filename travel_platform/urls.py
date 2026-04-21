# travel_platform/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views.oauth_views import google_oauth_begin, google_oauth_complete

urlpatterns = [
    path('admin/', admin.site.urls),
    path('oauth/google/login/', google_oauth_begin, name='google_oauth_begin'),
    path('oauth/complete/google-oauth2/', google_oauth_complete, name='google_oauth_complete'),
    path('auth/google/callback/', google_oauth_complete, name='google_oauth_callback'),
    path('auth/google/callback', google_oauth_complete),
    path('oauth/', include('social_django.urls', namespace='social')),
    path('', include('core.urls')),  
    path('accounts/', include('accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
