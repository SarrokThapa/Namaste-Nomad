"""Authentication and account entry views."""

from .common import *
from ..services import oauth_service, otp_service, email_service
from ..services import password_reset_service as prs

@never_cache
@csrf_protect
def vendor_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        remember_me = request.POST.get('remember_me')
        next_url = _safe_next_url(request, 'vendor_dashboard')

        try:
            vendor_user = User.objects.get(email=email, user_type='vendor')
        except User.DoesNotExist:
            messages.error(request, 'No vendor account found with this email')
            return render(request, 'accounts/vendor_login.html')

        # Block unapproved vendors before authenticating
        vendor_profile = _get_vendor_profile(vendor_user)
        if vendor_profile and not vendor_profile.is_approved:
            messages.error(request, 'Your account is pending admin approval. Please wait for confirmation email.')
            return render(request, 'accounts/vendor_login.html')

        user = authenticate(request, username=vendor_user.username, password=password)
        if user is not None:
            login(request, user)
            if not remember_me:
                request.session.set_expiry(0)
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid credentials')

    return render(request, 'accounts/vendor_login.html')


@never_cache
@csrf_protect
def vendor_register(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        business_name = (request.POST.get('business_name') or '').strip()
        owner_name = (request.POST.get('owner_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        wants_promotions = request.POST.get('wants_promotions') == 'on'
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        document = request.FILES.get('document')

        if not business_name or not owner_name or not email or not phone:
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'accounts/vendor_register.html')

        if not document:
            messages.error(request, 'Verification document is required for vendor registration.')
            return render(request, 'accounts/vendor_register.html')

        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
        allowed_mime_types = {'application/pdf', 'image/jpeg', 'image/png'}
        document_ext = Path(document.name).suffix.lower()
        document_type = (getattr(document, 'content_type', '') or '').lower()
        if document_ext not in allowed_extensions or (document_type and document_type not in allowed_mime_types):
            messages.error(request, 'Please upload a valid PDF, JPG, JPEG, or PNG file.')
            return render(request, 'accounts/vendor_register.html')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'accounts/vendor_register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'accounts/vendor_register.html')

        # Store registration data in session — user is NOT created yet
        doc_content = document.read()
        otp_service.store_registration_data(request, {
            'user_type': 'vendor',
            'business_name': business_name,
            'owner_name': owner_name,
            'email': email,
            'phone': phone,
            'password': password,
            'wants_promotions': wants_promotions,
            'document_name': document.name,
            'document_content_type': document.content_type or '',
            'document_bytes': doc_content.hex(),
        })

        # Generate & send OTP
        otp_code = otp_service.generate_otp()
        otp_service.store_otp(request, otp_code)
        sent = email_service.send_otp_email(email, otp_code)

        messages.success(request, 'Please verify your email to complete registration.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
        return redirect('verify_otp')

    return render(request, 'accounts/vendor_register.html')


@never_cache
@csrf_protect
def traveler_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        next_url = _safe_next_url(request, 'traveler_home')
        
        try:
            user = User.objects.get(email=email, user_type='traveler')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                login(request, user)
                if _get_traveler_profile(user) is None:
                    TravelerProfile.objects.create(user=user)
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No traveler account found with this email')
    
    return render(request, 'accounts/traveler_login.html')


@never_cache
@csrf_protect
def admin_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        remember_me = request.POST.get('remember_me')
        next_url = _safe_next_url(request, 'admin_dashboard')
        
        try:
            user = User.objects.get(email=email, user_type='admin')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None and user.is_staff:
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials or insufficient permissions')
        except User.DoesNotExist:
            messages.error(request, 'No admin account found')
    
    return render(request, 'accounts/admin_login.html')


def _create_user_from_registration(data):
    """Create user (and profile) from session-stored registration data.

    Returns the created User or None on failure.
    """
    email = data['email']

    # Guard against double-submission
    if User.objects.filter(email=email).exists():
        return None

    user_type = data['user_type']

    if user_type == 'traveler':
        user = User.objects.create_user(
            username=email,
            email=email,
            password=data['password'],
            user_type='traveler',
            phone=data.get('phone', ''),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            is_verified=True,
            is_active=True,
            wants_promotions=data.get('wants_promotions', False),
        )
        TravelerProfile.objects.create(user=user)
        if data.get('wants_promotions'):
            _sync_active_special_offers_for_user(user)
        notify_admins(
            f'New traveler registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        return user

    if user_type == 'vendor':
        from django.core.files.base import ContentFile

        user = User.objects.create_user(
            username=email,
            email=email,
            password=data['password'],
            user_type='vendor',
            phone=data.get('phone', ''),
            is_verified=True,
            is_active=False,  # vendor stays inactive until admin approval
            wants_promotions=data.get('wants_promotions', False),
        )
        # Reconstruct uploaded document from hex-encoded bytes
        doc_bytes = bytes.fromhex(data.get('document_bytes', ''))
        doc_name = data.get('document_name', 'document')
        doc_file = ContentFile(doc_bytes, name=doc_name)

        VendorProfile.objects.create(
            user=user,
            business_name=data.get('business_name', ''),
            owner_name=data.get('owner_name', ''),
            business_license=doc_file,
            document=doc_file,
        )
        if data.get('wants_promotions'):
            _sync_active_special_offers_for_user(user)
        notify_admins(
            f'New vendor registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        return user

    return None


@csrf_protect
def verify_otp_view(request):
    reg_data = otp_service.get_registration_data(request)
    if not reg_data:
        return redirect('account_register_choice')

    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        result = otp_service.verify_otp(request, otp_code)

        if result == 'expired':
            messages.error(request, 'OTP expired. Request a new one.')
            return render(request, 'accounts/verify_otp.html', {'email': reg_data['email']})

        if result == 'invalid':
            messages.error(request, 'Invalid OTP. Please try again.')
            return render(request, 'accounts/verify_otp.html', {'email': reg_data['email']})

        # OTP is valid — now create the user account
        user = _create_user_from_registration(reg_data)
        if user is None:
            messages.error(request, 'Registration failed. Please try again.')
            otp_service.clear_registration_session(request)
            return redirect('account_register_choice')

        otp_service.clear_registration_session(request)

        # Send appropriate email based on role
        if user.user_type == 'traveler':
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            email_service.send_traveler_welcome(user)
            messages.success(request, 'Email verified successfully! Welcome to Namaste Nomad!')
            return redirect('traveler_home')
        elif user.user_type == 'vendor':
            email_service.send_vendor_under_review(user)
            messages.success(
                request,
                'Email verified! Your vendor account is now under review. '
                'You will receive an email once your account is approved.',
            )
            return redirect('account_login_choice')

    return render(request, 'accounts/verify_otp.html', {'email': reg_data['email']})


@csrf_protect
def resend_otp(request):
    reg_data = otp_service.get_registration_data(request)
    if not reg_data:
        return redirect('account_register_choice')

    otp_code = otp_service.generate_otp()
    otp_service.store_otp(request, otp_code)
    sent = email_service.send_otp_email(reg_data['email'], otp_code)

    if sent:
        messages.success(request, 'New OTP sent to your email.')
    else:
        messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')

    return redirect('verify_otp')


@never_cache
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('home')


@never_cache
@csrf_protect
def traveler_register(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        wants_promotions = request.POST.get('wants_promotions') == 'on' or request.POST.get('newsletter') == 'on'
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'accounts/traveler_register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'accounts/traveler_register.html')

        # Store registration data in session — user is NOT created yet
        otp_service.store_registration_data(request, {
            'user_type': 'traveler',
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone,
            'password': password,
            'wants_promotions': wants_promotions,
        })

        # Generate & send OTP
        otp_code = otp_service.generate_otp()
        otp_service.store_otp(request, otp_code)
        sent = email_service.send_otp_email(email, otp_code)

        messages.success(request, 'Please verify your email to complete registration.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
        return redirect('verify_otp')

    return render(request, 'accounts/traveler_register.html')


def landing(request):
    return render(request, 'landing.html')


@never_cache
@csrf_protect
def forgot_password(request):
    """Step 1 — user enters their email address."""
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()

        if not email:
            messages.error(request, 'Please enter your email address.')
            return render(request, 'accounts/forgot_password.html')

        if prs.is_rate_limited(email):
            messages.error(request, 'Too many reset requests. Please try again in an hour.')
            return render(request, 'accounts/forgot_password.html')

        if User.objects.filter(email=email).exists():
            otp_record, otp_code = prs.create_reset_otp(email)
            prs.store_reset_session(request, email, otp_record.id)
            email_service.send_password_reset_otp(email, otp_code)
        else:
            # Don't reveal whether email exists — show same message
            prs.store_email_only_session(request, email)

        messages.success(request, 'Reset code sent to your email.')
        return redirect('forgot_password_verify')

    return render(request, 'accounts/forgot_password.html')


@never_cache
@csrf_protect
def forgot_password_verify(request):
    """Step 2 — user enters the 6-digit OTP."""
    email = prs.get_reset_email(request)
    if not email:
        return redirect('forgot_password')

    masked = prs.mask_email(email)
    resend_seconds = prs.seconds_until_resend(request)

    if request.method == 'POST':
        submitted = (request.POST.get('otp_code') or '').strip()
        result = prs.verify_reset_otp(request, submitted)

        if result == 'valid':
            return redirect('forgot_password_new_password')

        if result == 'expired':
            messages.error(request, 'Code expired. Please request a new one.')
        elif result == 'blocked':
            messages.error(request, 'Too many wrong attempts. Please try again in 15 minutes.')
        elif result == 'error':
            messages.error(request, 'Invalid or expired code. Please request a new one.')
        else:
            messages.error(request, 'Invalid code. Please try again.')

        resend_seconds = prs.seconds_until_resend(request)
        return render(request, 'accounts/forgot_password_verify.html', {
            'masked_email': masked,
            'resend_seconds': resend_seconds,
        })

    return render(request, 'accounts/forgot_password_verify.html', {
        'masked_email': masked,
        'resend_seconds': resend_seconds,
    })


@csrf_protect
def forgot_password_resend(request):
    """Resend a fresh OTP — enforces 60-second cooldown."""
    email = prs.get_reset_email(request)
    if not email:
        return redirect('forgot_password')

    if prs.seconds_until_resend(request) > 0:
        messages.error(request, 'Please wait before requesting a new code.')
        return redirect('forgot_password_verify')

    if prs.is_rate_limited(email):
        messages.error(request, 'Too many reset requests. Please try again in an hour.')
        return redirect('forgot_password_verify')

    if User.objects.filter(email=email).exists():
        otp_record, otp_code = prs.create_reset_otp(email)
        prs.refresh_resend_cooldown(request, otp_record.id)
        email_service.send_password_reset_otp(email, otp_code)
        messages.success(request, 'New reset code sent to your email.')
    else:
        prs.store_email_only_session(request, email)
        messages.success(request, 'New reset code sent to your email.')

    return redirect('forgot_password_verify')


@never_cache
@csrf_protect
def forgot_password_new_password(request):
    """Step 3 — user sets a new password (only reachable after OTP verified)."""
    if not prs.is_reset_verified(request):
        return redirect('forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password') or ''
        confirm = request.POST.get('confirm_password') or ''

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'accounts/forgot_password_new_password.html')

        if password != confirm:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/forgot_password_new_password.html')

        email = prs.consume_reset_otp(request)
        if not email:
            messages.error(request, 'Session expired. Please start over.')
            prs.clear_reset_session(request)
            return redirect('forgot_password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, 'Account not found. Please contact support.')
            prs.clear_reset_session(request)
            return redirect('forgot_password')

        user.set_password(password)
        user.save(update_fields=['password'])
        prs.clear_reset_session(request)
        email_service.send_password_changed_confirmation(user)
        messages.success(request, 'Password reset successful! Please login with your new password.')
        return redirect('account_login_choice')

    return render(request, 'accounts/forgot_password_new_password.html')


@never_cache
def account_register_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    oauth_service.tag_google_oauth_start(request, intent='register')
    return render(request, 'accounts/register_choice.html')


@never_cache
def account_login_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    oauth_service.tag_google_oauth_start(request, intent='login')
    return render(request, 'accounts/login_choice.html')


@never_cache
def oauth_post_login_redirect(request):
    if not request.user.is_authenticated:
        return redirect('account_login_choice')

    if getattr(request.user, 'user_type', '') == 'admin':
        oauth_service.clear_oauth_session_markers(request)
        logout(request)
        messages.error(request, 'Google OAuth is available only for traveler accounts.')
        return redirect('account_login_choice')

    # Vendors cannot use Google OAuth — block them
    if getattr(request.user, 'user_type', '') == 'vendor':
        oauth_service.clear_oauth_session_markers(request)
        logout(request)
        messages.error(request, 'Google OAuth is only available for travelers. Vendors must use email/password login.')
        return redirect('account_login_choice')

    is_new_user = oauth_service.pop_oauth_new_user_flag(request)

    # New users are now auto-assigned as travelers in the pipeline,
    # so no role selection needed — just redirect.
    if is_new_user:
        oauth_service.clear_oauth_session_markers(request)
        messages.success(request, 'Welcome to Namaste Nomad!')
        return redirect('traveler_home')

    oauth_service.clear_oauth_session_markers(request)
    return redirect(oauth_service.dashboard_route_name_for_user(request.user))


@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect
def oauth_role_selection(request):
    """Google OAuth role selection — now auto-assigns traveler only."""
    # Google OAuth is traveler-only now; redirect if role is already set
    if not oauth_service.user_needs_role_selection(request.user):
        oauth_service.clear_oauth_session_markers(request)
        return redirect(oauth_service.dashboard_route_name_for_user(request.user))

    # Edge case: user somehow landed here without a role — auto-assign traveler
    try:
        oauth_service.assign_user_role(request.user, 'traveler')
        email_service.send_traveler_welcome(request.user)
    except ValueError:
        pass

    oauth_service.clear_oauth_session_markers(request)
    messages.success(request, 'Welcome to Namaste Nomad!')
    return redirect('traveler_home')
