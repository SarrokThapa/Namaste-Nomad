"""Google OAuth (social-auth) integration helpers.

Owns the social-auth pipeline step that normalises new Google users,
the role-selection helpers used after a first-time Google login, and
the post-login dashboard routing for OAuth users.
"""

from django.db import IntegrityError
from django.urls import reverse
from social_django.models import UserSocialAuth

from accounts.models import TravelerProfile, User, VendorProfile
from accounts.services import email_service

GOOGLE_BACKEND_NAME = 'google-oauth2'
SESSION_OAUTH_IS_NEW = 'oauth_is_new_user'
SESSION_OAUTH_BACKEND = 'oauth_backend_name'


def link_existing_user_by_email(strategy, details, backend, uid=None, user=None, *args, **kwargs):
    """Link Google OAuth to an existing account before creating a new user.

    This prevents duplicate users when a traveler already registered with
    email/password before Google OAuth was introduced.
    """
    if backend.name != GOOGLE_BACKEND_NAME or user is not None:
        return {}

    email = (details.get('email') or '').strip().lower()
    if not email:
        return {}

    # check if account already exists before creating oauth user
    existing_users = User.objects.filter(email__iexact=email).order_by('date_joined', 'id')
    primary_user = existing_users.first()
    if primary_user is None:
        return {}

    if uid:
        social_record = (
            UserSocialAuth.objects.select_related('user')
            .filter(provider=backend.name, uid=str(uid))
            .first()
        )
        if social_record and social_record.user_id != primary_user.id:
            social_record.user = primary_user
            try:
                social_record.save(update_fields=['user'])
            except IntegrityError:
                # If a conflicting link already exists for the target user, keep one canonical record.
                social_record.delete()

    return {
        'user': primary_user,
        'is_new': False,
    }


def social_auth_user_setup(strategy, details, backend, user=None, is_new=False, *args, **kwargs):
    """Normalize OAuth users and remember whether this was first-time signup."""
    if user is None or backend.name != GOOGLE_BACKEND_NAME:
        return {}

    changed_fields = []

    email = (details.get('email') or user.email or '').strip().lower()
    if email and user.email != email:
        user.email = email
        changed_fields.append('email')

    if email and not user.username:
        user.username = email
        changed_fields.append('username')

    first_name = (details.get('first_name') or '').strip()
    if first_name and not user.first_name:
        user.first_name = first_name
        changed_fields.append('first_name')

    last_name = (details.get('last_name') or '').strip()
    if last_name and not user.last_name:
        user.last_name = last_name
        changed_fields.append('last_name')

    if not user.is_active:
        user.is_active = True
        changed_fields.append('is_active')

    if not user.is_verified:
        user.is_verified = True
        changed_fields.append('is_verified')

    # New social accounts start without a role and pick one in the next step.
    if is_new and user.user_type not in {'traveler', 'vendor', 'admin'}:
        user.user_type = 'traveler'
        changed_fields.append('user_type')

    if changed_fields:
        user.save(update_fields=list(dict.fromkeys(changed_fields)))

    # Auto-create traveler profile and send welcome email for new Google users
    if is_new and user.user_type == 'traveler':
        TravelerProfile.objects.get_or_create(user=user)
        email_service.send_traveler_welcome(user)

    strategy.session_set(SESSION_OAUTH_IS_NEW, bool(is_new))
    strategy.session_set(SESSION_OAUTH_BACKEND, backend.name)
    return {}


def was_google_oauth_login(request):
    """Return True if the current session was authenticated via Google OAuth."""
    return request.session.get(SESSION_OAUTH_BACKEND) == GOOGLE_BACKEND_NAME


def pop_oauth_new_user_flag(request):
    """Pop and return the "new OAuth user" flag from the session (one-shot)."""
    return bool(request.session.pop(SESSION_OAUTH_IS_NEW, False))


def clear_oauth_session_markers(request):
    """Remove the OAuth backend/new-user markers from the session (logout/cleanup)."""
    request.session.pop(SESSION_OAUTH_IS_NEW, None)
    request.session.pop(SESSION_OAUTH_BACKEND, None)


def user_needs_role_selection(user):
    """Return True if the user has no valid role yet and must pick one before continuing."""
    return getattr(user, 'user_type', '') not in {'traveler', 'vendor', 'admin'}


def assign_user_role(user, role):
    """Assign a role to a fresh OAuth user. Only 'traveler' is currently supported."""
    role = (role or '').strip().lower()
    if role != 'traveler':
        raise ValueError('Google OAuth is only available for traveler accounts.')

    if getattr(user, 'user_type', '') == 'admin':
        raise ValueError('Admin accounts cannot use Google OAuth role selection.')

    updates = []
    if user.user_type != role:
        user.user_type = role
        updates.append('user_type')

    if not user.is_active:
        user.is_active = True
        updates.append('is_active')

    if not user.is_verified:
        user.is_verified = True
        updates.append('is_verified')

    if updates:
        user.save(update_fields=updates)

    TravelerProfile.objects.get_or_create(user=user)


def dashboard_route_name_for_user(user):
    """Return the URL-name of the post-login landing page based on the user's role."""
    user_type = getattr(user, 'user_type', '')
    if user_type == 'traveler':
        return 'traveler_home'
    if user_type == 'vendor':
        try:
            vendor_profile = user.vendor_profile
        except VendorProfile.DoesNotExist:
            return 'vendor_dashboard'
        return 'vendor_profile' if not vendor_profile.is_approved else 'vendor_dashboard'
    return 'home'


def tag_google_oauth_start(request, intent='login'):
    """Tag the session with the user's OAuth intent ('login' or 'register') before the redirect."""
    request.session['oauth_intent'] = intent


def role_selection_page_context(request):
    """Return template context for the OAuth role-selection page."""
    return {
        'oauth_intent': request.session.get('oauth_intent', 'login'),
        'google_backend_name': GOOGLE_BACKEND_NAME,
    }


def build_google_oauth_url():
    """Return the URL that kicks off the Google OAuth flow."""
    return reverse('google_oauth_begin')
