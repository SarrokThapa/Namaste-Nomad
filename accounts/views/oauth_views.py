"""Google OAuth views with explicit callback URI support.

These wrappers let us control the exact redirect URI used in the OAuth flow
so it can match the URI registered in Google Cloud Console.
"""

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from social_core.actions import do_auth, do_complete
from social_django.utils import load_backend, load_strategy
from social_django.views import _do_login

from accounts.services.oauth_service import GOOGLE_BACKEND_NAME

DEFAULT_GOOGLE_CALLBACK_PATH = '/oauth/complete/google-oauth2/'


def _google_callback_uri():
    callback_uri = (getattr(settings, 'GOOGLE_CALLBACK_URL', '') or '').strip()
    return callback_uri or DEFAULT_GOOGLE_CALLBACK_PATH


def _load_google_backend(request):
    strategy = load_strategy(request)
    backend = load_backend(strategy, GOOGLE_BACKEND_NAME, _google_callback_uri())

    request.social_strategy = strategy
    if not hasattr(request, 'strategy'):
        request.strategy = strategy
    request.backend = backend
    return backend


@never_cache
def google_oauth_begin(request):
    backend = _load_google_backend(request)
    return do_auth(backend, redirect_name=REDIRECT_FIELD_NAME)


@never_cache
@csrf_exempt
def google_oauth_complete(request):
    backend = _load_google_backend(request)
    return do_complete(
        backend,
        _do_login,
        user=request.user,
        redirect_name=REDIRECT_FIELD_NAME,
        request=request,
    )
