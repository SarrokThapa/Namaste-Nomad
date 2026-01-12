from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from .models import User, VendorProfile
from .utils import create_otp, verify_otp as verify_otp_util

@csrf_protect
def vendor_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me')
        
        try:
            user = User.objects.get(email=email, user_type='vendor')
            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                if not user.is_verified:
                    create_otp(user)
                    request.session['user_id'] = user.id
                    messages.info(request, 'Please verify your email with the OTP sent.')
                    return redirect('verify_otp')
                
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                return redirect('vendor_dashboard')
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No vendor account found with this email')
    
    return render(request, 'accounts/vendor_login.html')

@csrf_protect
def vendor_register(request):
    if request.method == 'POST':
        business_name = request.POST.get('business_name')
        owner_name = request.POST.get('owner_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        business_license = request.FILES.get('business_license')
        
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
            phone=phone
        )
        
        # Create vendor profile
        VendorProfile.objects.create(
            user=user,
            business_name=business_name,
            owner_name=owner_name,
            business_license=business_license
        )
        
        # Send OTP
        create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/vendor_register.html')

@csrf_protect
def traveler_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        try:
            user = User.objects.get(email=email, user_type='traveler')
            user = authenticate(request, username=user.username, password=password)
            
            if user is not None:
                if not user.is_verified:
                    create_otp(user)
                    request.session['user_id'] = user.id
                    messages.info(request, 'Please verify your email with the OTP sent.')
                    return redirect('verify_otp')
                
                login(request, user)
                return redirect('traveler_dashboard')
            else:
                messages.error(request, 'Invalid credentials')
        except User.DoesNotExist:
            messages.error(request, 'No traveler account found with this email')
    
    return render(request, 'accounts/traveler_login.html')

@csrf_protect
def admin_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me')
        
        try:
            user = User.objects.get(email=email, user_type='admin')
            user = authenticate(request, username=user.username, password=password)
            
            if user is not None and user.is_staff:
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                return redirect('admin_dashboard')
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
            user.save()
            login(request, user)
            del request.session['user_id']
            
            messages.success(request, 'Email verified successfully!')
            if user.user_type == 'vendor':
                return redirect('vendor_dashboard')
            else:
                return redirect('traveler_dashboard')
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
        create_otp(user)
        messages.success(request, 'New OTP sent to your email')
    except User.DoesNotExist:
        messages.error(request, 'User not found')
    
    return redirect('verify_otp')

def logout_view(request):
    logout(request)
    return redirect('vendor_login')

@csrf_protect
def traveler_register(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
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
            last_name=last_name
        )
        
        # Send OTP
        create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/traveler_register.html')