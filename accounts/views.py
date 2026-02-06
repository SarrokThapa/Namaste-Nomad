from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect

from core.models import Booking, Package, Review
from .models import User, VendorProfile
from .utils import create_otp, verify_otp as verify_otp_util


def _get_vendor_profile(user):
    try:
        return user.vendor_profile
    except VendorProfile.DoesNotExist:
        return None


def _ensure_vendor(request):
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    return True


@login_required(login_url='vendor_login')
def vendor_dashboard(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)

    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('total_price')
    )['total'] or 0
    active_packages = vendor_packages.filter(is_active=True).count()
    total_bookings = vendor_bookings.count()
    pending_bookings = vendor_bookings.filter(status='pending').count()
    average_rating = Review.objects.filter(package__vendor=request.user).aggregate(
        avg=Avg('rating')
    )['avg'] or 0

    today = timezone.now().date()
    weekly_revenue = []
    max_revenue = 0
    end = today
    periods = []
    for _ in range(4):
        start = end - timedelta(days=6)
        periods.append((start, end))
        end = start - timedelta(days=1)
    periods.reverse()

    for index, (start, end) in enumerate(periods, start=1):
        total = vendor_bookings.filter(
            status='confirmed',
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('total_price'))['total'] or 0
        total_value = float(total)
        max_revenue = max(max_revenue, total_value)
        weekly_revenue.append({
            'label': f'Week {index}',
            'value': total_value,
        })

    for entry in weekly_revenue:
        if max_revenue == 0:
            entry['percent'] = 12
        else:
            entry['percent'] = max(12, int((entry['value'] / max_revenue) * 100))

    daily_counts = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = vendor_bookings.filter(created_at__date=day).count()
        daily_counts.append({
            'label': day.strftime('%a'),
            'value': count,
        })

    values = [item['value'] for item in daily_counts]
    max_value = max(values) if values else 0
    min_value = min(values) if values else 0

    width = 320
    height = 160
    padding_x = 10
    padding_y = 20
    step = (width - padding_x * 2) / max(len(values) - 1, 1)
    line_points = []
    for idx, value in enumerate(values):
        x = padding_x + idx * step
        if max_value == min_value:
            y = height / 2
        else:
            ratio = (value - min_value) / (max_value - min_value)
            y = height - padding_y - ratio * (height - padding_y * 2)
        line_points.append(f"{x:.0f},{y:.0f}")
    line_points_str = " ".join(line_points)

    source_totals = {key: 0 for key, _ in Booking.SOURCE_CHOICES}
    for row in vendor_bookings.values('source').annotate(count=Count('id')):
        source_totals[row['source']] = row['count']

    total_sources = sum(source_totals.values())
    source_order = ['direct', 'partner', 'social', 'marketplace']
    source_labels = dict(Booking.SOURCE_CHOICES)
    source_colors = {
        'direct': '#1d4ed8',
        'partner': '#1e3a8a',
        'social': '#60a5fa',
        'marketplace': '#bfdbfe',
    }
    source_breakdown = []
    current = 0
    segments = []
    for source in source_order:
        count = source_totals.get(source, 0)
        percent = (count / total_sources * 100) if total_sources else 0
        source_breakdown.append({
            'key': source,
            'label': source_labels.get(source, source.title()),
            'count': count,
            'percent': round(percent),
            'color': source_colors[source],
        })
        if percent > 0:
            next_point = current + percent
            segments.append(f"{source_colors[source]} {current:.1f}% {next_point:.1f}%")
            current = next_point

    if not segments:
        pie_gradient = "conic-gradient(#e5e7eb 0 100%)"
    else:
        if current < 100:
            segments.append(f"#e5e7eb {current:.1f}% 100%")
        pie_gradient = f"conic-gradient({', '.join(segments)})"

    upcoming_bookings = vendor_bookings.filter(
        start_date__gte=today,
        start_date__lte=today + timedelta(days=14),
    ).exclude(status='cancelled').order_by('start_date')[:3]

    package_performance = vendor_packages.annotate(
        booking_count=Count('bookings'),
        avg_rating=Avg('reviews__rating'),
    ).order_by('-booking_count', '-views_count')[:3]

    return render(request, 'accounts/vendor_dashboard.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'dashboard',
        'stats': {
            'total_revenue': float(total_revenue),
            'active_packages': active_packages,
            'total_bookings': total_bookings,
            'pending_bookings': pending_bookings,
            'average_rating': round(average_rating or 0, 1),
        },
        'weekly_revenue': weekly_revenue,
        'line_points': line_points_str,
        'daily_counts': daily_counts,
        'pie_gradient': pie_gradient,
        'source_breakdown': source_breakdown,
        'upcoming_bookings': upcoming_bookings,
        'package_performance': package_performance,
    })


@login_required(login_url='vendor_login')
def vendor_packages(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    packages = Package.objects.filter(vendor=request.user).annotate(
        booking_count=Count('bookings'),
    ).order_by('-created_at')
    return render(request, 'accounts/vendor_packages.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'packages': packages,
    })


@login_required(login_url='vendor_login')
def vendor_bookings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    bookings = Booking.objects.filter(package__vendor=request.user).order_by('-created_at')
    return render(request, 'accounts/vendor_bookings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'bookings',
        'bookings': bookings,
    })


@login_required(login_url='vendor_login')
def vendor_reviews(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    reviews = Review.objects.filter(package__vendor=request.user).order_by('-created_at')
    return render(request, 'accounts/vendor_reviews.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'reviews',
        'reviews': reviews,
    })


@login_required(login_url='vendor_login')
def vendor_analytics(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    vendor_packages = Package.objects.filter(vendor=request.user)
    vendor_bookings = Booking.objects.filter(package__vendor=request.user)
    total_revenue = vendor_bookings.filter(status='confirmed').aggregate(
        total=Sum('total_price')
    )['total'] or 0

    analytics = {
        'packages': vendor_packages.count(),
        'bookings': vendor_bookings.count(),
        'revenue': float(total_revenue),
        'reviews': Review.objects.filter(package__vendor=request.user).count(),
        'avg_rating': Review.objects.filter(package__vendor=request.user).aggregate(
            avg=Avg('rating')
        )['avg'] or 0,
    }

    return render(request, 'accounts/vendor_analytics.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'analytics',
        'analytics': analytics,
    })


@login_required(login_url='vendor_login')
def vendor_settings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    return render(request, 'accounts/vendor_settings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'settings',
    })


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


def landing(request):
    return render(request, 'landing.html')
