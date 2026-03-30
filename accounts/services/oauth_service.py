from django.urls import reverse

from accounts.models import TravelerProfile, VendorProfile

GOOGLE_BACKEND_NAME = 'google-oauth2'
SESSION_OAUTH_IS_NEW = 'oauth_is_new_user'
SESSION_OAUTH_BACKEND = 'oauth_backend_name'


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
        user.user_type = ''
        changed_fields.append('user_type')

    if changed_fields:
        user.save(update_fields=list(dict.fromkeys(changed_fields)))

    strategy.session_set(SESSION_OAUTH_IS_NEW, bool(is_new))
    strategy.session_set(SESSION_OAUTH_BACKEND, backend.name)
    return {}


def was_google_oauth_login(request):
    return request.session.get(SESSION_OAUTH_BACKEND) == GOOGLE_BACKEND_NAME


def pop_oauth_new_user_flag(request):
    return bool(request.session.pop(SESSION_OAUTH_IS_NEW, False))


def clear_oauth_session_markers(request):
    request.session.pop(SESSION_OAUTH_IS_NEW, None)
    request.session.pop(SESSION_OAUTH_BACKEND, None)


def user_needs_role_selection(user):
    return getattr(user, 'user_type', '') not in {'traveler', 'vendor', 'admin'}


def assign_user_role(user, role):
    role = (role or '').strip().lower()
    if role not in {'traveler', 'vendor'}:
        raise ValueError('Invalid role selected.')

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

    if role == 'traveler':
        TravelerProfile.objects.get_or_create(user=user)
    elif role == 'vendor':
        defaults = {
            'business_name': (user.get_full_name() or user.username or 'Vendor').strip(),
            'owner_name': (user.get_full_name() or user.username or 'Vendor').strip(),
            'is_approved': False,
        }
        VendorProfile.objects.get_or_create(user=user, defaults=defaults)


def dashboard_route_name_for_user(user):
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
    request.session['oauth_intent'] = intent


def role_selection_page_context(request):
    return {
        'oauth_intent': request.session.get('oauth_intent', 'login'),
        'google_backend_name': GOOGLE_BACKEND_NAME,
    }


def build_google_oauth_url():
    return reverse('social:begin', args=[GOOGLE_BACKEND_NAME])
