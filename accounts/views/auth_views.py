"""Authentication and account entry views."""

from .common import *

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
            user = User.objects.get(email=email, user_type='vendor')

            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                vendor_profile = _get_vendor_profile(user)
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                if vendor_profile and not vendor_profile.is_approved:
                    messages.info(request, 'Your account is pending admin approval.')
                    return redirect('vendor_profile')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No vendor account found with this email')
    
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
        
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            user_type='vendor',
            phone=phone,
            is_verified=False,
            is_active=False,
            wants_promotions=wants_promotions,
        )

        if wants_promotions:
            _sync_active_special_offers_for_user(user)
        
        # Create vendor profile
        VendorProfile.objects.create(
            user=user,
            business_name=business_name,
            owner_name=owner_name,
            business_license=document,
            document=document,
        )

        notify_admins(
            f'New vendor registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        
        # Send OTP
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
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


@csrf_protect
def verify_otp_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('vendor_login')
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('vendor_login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if verify_otp_util(user, otp_code):
            user.is_verified = True
            user.is_active = True
            user.save()
            login(request, user)
            del request.session['user_id']
            
            messages.success(request, 'Email verified successfully!')
            if user.user_type == 'traveler':
                if _get_traveler_profile(user) is None:
                    TravelerProfile.objects.create(user=user)
            return redirect(_dashboard_route_name(user))
        else:
            messages.error(request, 'Invalid or expired OTP')
    
    return render(request, 'accounts/verify_otp.html', {'email': user.email})


@csrf_protect
def resend_otp(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('vendor_login')
    
    try:
        user = User.objects.get(id=user_id)
        _, sent = create_otp(user)
        if sent:
            messages.success(request, 'New OTP sent to your email')
        else:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
    except User.DoesNotExist:
        messages.error(request, 'User not found')
    
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
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        wants_promotions = request.POST.get('wants_promotions') == 'on' or request.POST.get('newsletter') == 'on'
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'accounts/traveler_register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'accounts/traveler_register.html')
        
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            user_type='traveler',
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            is_verified=False,
            is_active=False,
            wants_promotions=wants_promotions,
        )

        TravelerProfile.objects.create(user=user)

        notify_admins(
            f'New traveler registered: {user.email}',
            Notification.TYPE_USER_REGISTRATION,
            related_object_id=user.id,
        )
        
        # Send OTP
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Check SMTP credentials (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD app password) and try again.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/traveler_register.html')


def landing(request):
    return render(request, 'landing.html')


@never_cache
def account_register_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    return render(request, 'accounts/register_choice.html')


@never_cache
def account_login_choice(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_route_name(request.user))
    return render(request, 'accounts/login_choice.html')
