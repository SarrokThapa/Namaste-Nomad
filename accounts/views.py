from calendar import monthrange
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.files.images import get_image_dimensions
from django.db.models import Avg, Case, CharField, Count, Max, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from core.models import Booking, Package, Review, PackageImage
from .models import User, VendorProfile, TravelerProfile, AdminProfile
from .forms import PackageForm, VendorProfileForm
from .utils import create_otp, verify_otp as verify_otp_util


def _get_vendor_profile(user):
    try:
        return user.vendor_profile
    except VendorProfile.DoesNotExist:
        return None


def _get_admin_profile(user):
    try:
        return user.admin_profile
    except AdminProfile.DoesNotExist:
        return None


def _get_traveler_profile(user):
    try:
        return user.traveler_profile
    except TravelerProfile.DoesNotExist:
        return None


def _delete_stored_file(instance, field_name, file_name):
    if not file_name:
        return
    storage = instance._meta.get_field(field_name).storage
    if storage.exists(file_name):
        storage.delete(file_name)


def _is_valid_uploaded_image(uploaded_file):
    if uploaded_file is None:
        return False
    try:
        get_image_dimensions(uploaded_file)
        uploaded_file.seek(0)
    except Exception:
        return False
    return True


def _ensure_vendor(request):
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile and not vendor_profile.is_approved:
        messages.error(request, 'Your vendor account is pending approval.')
        return False
    return True


def _ensure_vendor_account(request):
    if getattr(request.user, 'user_type', '') != 'vendor':
        messages.error(request, 'Vendor access only.')
        return False
    return True


def _ensure_traveler(request):
    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return False
    return True


def _safe_next_url(request, fallback_name):
    candidate = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(fallback_name)


TRAVELER_CATEGORY_LABELS = {
    'adventure': 'Adventure',
    'cultural': 'Cultural',
    'trekking': 'Trekking',
}
TRAVELER_CATEGORY_SLUGS = tuple(TRAVELER_CATEGORY_LABELS.keys())


def _traveler_category_expression():
    trekking_match = (
        Q(title__icontains='trek')
        | Q(description__icontains='trek')
        | Q(itinerary__icontains='trek')
        | Q(title__icontains='base camp')
        | Q(description__icontains='base camp')
        | Q(title__icontains='hike')
        | Q(description__icontains='hike')
    )
    cultural_match = (
        Q(title__icontains='cultural')
        | Q(description__icontains='cultural')
        | Q(itinerary__icontains='cultural')
        | Q(title__icontains='heritage')
        | Q(description__icontains='heritage')
        | Q(title__icontains='temple')
        | Q(description__icontains='temple')
        | Q(title__icontains='monastery')
        | Q(description__icontains='monastery')
    )
    return Case(
        When(trekking_match, then=Value('trekking')),
        When(cultural_match, then=Value('cultural')),
        default=Value('adventure'),
        output_field=CharField(),
    )


def _traveler_package_queryset():
    return (
        Package.objects.filter(is_active=True)
        .select_related('vendor')
        .prefetch_related('images')
        .annotate(
            review_count=Count('reviews', distinct=True),
            avg_rating=Avg('reviews__rating'),
            booking_count=Count(
                'bookings',
                filter=Q(bookings__status='confirmed'),
                distinct=True,
            ),
            category_slug=_traveler_category_expression(),
        )
    )


def _add_category_labels(packages):
    for package in packages:
        package.category_label = TRAVELER_CATEGORY_LABELS.get(
            getattr(package, 'category_slug', 'adventure'),
            'Adventure',
        )


def _append_package_images(package, uploaded_images):
    if not uploaded_images:
        return

    max_order = package.images.aggregate(max_order=Max('order'))['max_order'] or 0
    for offset, image in enumerate(uploaded_images, start=1):
        PackageImage.objects.create(
            package=package,
            image=image,
            order=max_order + offset,
        )


def _reorder_package_images(package, post_data):
    remaining_images = list(package.images.all())
    if not remaining_images:
        return

    sortable = []
    for image in remaining_images:
        raw_order = post_data.get(f'image_order_{image.id}', '').strip()
        try:
            desired_order = int(raw_order)
        except (TypeError, ValueError):
            desired_order = image.order
        sortable.append((max(desired_order, 0), image.created_at, image.id, image))

    sortable.sort(key=lambda item: (item[0], item[1], item[2]))
    for index, (_, _, _, image) in enumerate(sortable, start=1):
        image.order = index
    PackageImage.objects.bulk_update([item[3] for item in sortable], ['order'])


def _sync_package_images(package, post_data, files_data):
    delete_ids = []
    for raw_id in post_data.getlist('delete_images'):
        try:
            delete_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if delete_ids:
        package.images.filter(id__in=delete_ids).delete()

    _reorder_package_images(package, post_data)
    _append_package_images(package, files_data.getlist('images'))


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('admin_login')
        if getattr(request.user, 'user_type', '') != 'admin' or not request.user.is_staff:
            messages.error(request, 'Admin access only.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return never_cache(_wrapped)


@never_cache
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
        travel_date__gte=today,
        travel_date__lte=today + timedelta(days=14),
    ).exclude(status='cancelled').order_by('travel_date')[:3]

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


@never_cache
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


@never_cache
@login_required(login_url='vendor_login')
def vendor_bookings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    bookings = Booking.objects.filter(package__vendor=request.user).select_related(
        'package',
        'traveler',
    ).order_by('-created_at')
    return render(request, 'accounts/vendor_bookings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'bookings',
        'bookings': bookings,
    })


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect
def vendor_booking_status_update(request, booking_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    next_url = request.POST.get('next') or reverse('vendor_bookings')
    if request.method != 'POST':
        return redirect(next_url)

    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        package__vendor=request.user,
    )
    requested_status = (request.POST.get('status') or '').strip().lower()

    if requested_status not in {'confirmed', 'cancelled'}:
        messages.error(request, 'Invalid booking action.')
        return redirect(next_url)

    if booking.status == requested_status:
        return redirect(next_url)

    if (
        requested_status == Booking.STATUS_CONFIRMED
        and booking.payment_status != Booking.PAYMENT_STATUS_PAID
    ):
        messages.error(request, 'Only paid bookings can be confirmed.')
        return redirect(next_url)

    package = booking.package

    if requested_status == Booking.STATUS_CANCELLED and booking.status != Booking.STATUS_CANCELLED:
        package.available_slots += booking.number_of_people
        package.save(update_fields=['available_slots'])

    if requested_status == Booking.STATUS_CONFIRMED and booking.status == Booking.STATUS_CANCELLED:
        if booking.number_of_people > package.available_slots:
            messages.error(
                request,
                f'Cannot confirm booking. Only {package.available_slots} slot(s) are currently available.',
            )
            return redirect(next_url)
        package.available_slots -= booking.number_of_people
        package.save(update_fields=['available_slots'])

    booking.status = requested_status
    booking.save(update_fields=['status'])
    messages.success(request, f'Booking marked as {requested_status}.')
    return redirect(next_url)


@never_cache
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


@never_cache
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


@never_cache
@login_required(login_url='vendor_login')
def vendor_settings(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    return render(request, 'accounts/vendor_settings.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'settings',
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_profile(request):
    if not _ensure_vendor_account(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    if vendor_profile is None:
        vendor_profile = VendorProfile.objects.create(
            user=request.user,
            business_name=request.user.get_full_name() or request.user.username,
            owner_name=request.user.get_full_name() or request.user.username,
        )

    if request.method == 'POST':
        old_logo_name = vendor_profile.logo.name if vendor_profile.logo else ''
        form = VendorProfileForm(request.POST, request.FILES, instance=vendor_profile)
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        remove_logo = request.POST.get('remove_logo') == '1'

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('vendor_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.save()

        if form.is_valid():
            uploading_new_logo = bool(request.FILES.get('logo'))
            profile_instance = form.save(commit=False)

            if remove_logo:
                profile_instance.logo = None

            profile_instance.save()
            if remove_logo or uploading_new_logo:
                current_logo_name = profile_instance.logo.name if profile_instance.logo else ''
                if old_logo_name and old_logo_name != current_logo_name:
                    _delete_stored_file(profile_instance, 'logo', old_logo_name)
            messages.success(request, 'Profile updated successfully.')
            return redirect('vendor_profile')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = VendorProfileForm(instance=vendor_profile)

    packages = Package.objects.filter(vendor=request.user).prefetch_related('images').order_by('-created_at')[:6]

    return render(request, 'accounts/vendor_profile.html', {
        'vendor_profile': vendor_profile,
        'form': form,
        'packages': packages,
        'active_page': 'profile',
    })


@admin_required
def admin_dashboard(request):
    admin_profile = _get_admin_profile(request.user)
    vendors = User.objects.filter(user_type='vendor').select_related('vendor_profile').annotate(
        package_count=Count('vendor_packages', distinct=True),
    ).order_by('-date_joined')
    pending_vendors = vendors.filter(vendor_profile__is_approved=False)
    travelers = User.objects.filter(user_type='traveler').order_by('-date_joined')
    packages = Package.objects.select_related('vendor').order_by('-created_at')
    bookings = Booking.objects.select_related('package', 'traveler').order_by('-created_at')
    reviews = Review.objects.select_related('traveler', 'package').order_by('-created_at')

    total_revenue = bookings.filter(status='confirmed').aggregate(
        total=Sum('total_price')
    )['total'] or 0
    total_bookings = bookings.count()
    active_vendors = vendors.filter(is_active=True, vendor_profile__is_approved=True).count()
    total_users = vendors.count() + travelers.count()
    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    today = timezone.now().date()
    month_labels = []
    month_values = []
    for offset in range(11, -1, -1):
        total_months = today.year * 12 + (today.month - 1) - offset
        year = total_months // 12
        month = total_months % 12 + 1
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        total = bookings.filter(
            status='confirmed',
            created_at__date__range=(start, end),
        ).aggregate(total=Sum('total_price'))['total'] or 0
        month_labels.append(start.strftime('%b'))
        month_values.append(float(total))

    width = 720
    height = 200
    pad_x = 20
    pad_y = 20
    step = (width - pad_x * 2) / max(len(month_values) - 1, 1)
    max_value = max(month_values) if month_values else 0
    min_value = min(month_values) if month_values else 0
    revenue_points = []
    for idx, value in enumerate(month_values):
        x = pad_x + idx * step
        if max_value == min_value:
            y = height / 2
        else:
            ratio = (value - min_value) / (max_value - min_value)
            y = height - pad_y - ratio * (height - pad_y * 2)
        revenue_points.append(f"{x:.0f},{y:.0f}")

    activity_items = []
    for booking in bookings[:3]:
        actor = booking.traveler.get_full_name() if booking.traveler else 'Traveler'
        activity_items.append({
            'action': 'New Booking',
            'actor': actor or 'Traveler',
            'date': booking.created_at,
            'details': booking.package.title,
        })
    for vendor in vendors[:2]:
        vendor_profile = _get_vendor_profile(vendor)
        activity_items.append({
            'action': 'Vendor Registration',
            'actor': vendor_profile.business_name if vendor_profile else vendor.email,
            'date': vendor.date_joined,
            'details': 'Pending approval' if vendor_profile and not vendor_profile.is_approved else 'Approved',
        })
    for package in packages[:2]:
        activity_items.append({
            'action': 'Package Created',
            'actor': package.vendor.get_full_name() or package.vendor.email,
            'date': package.created_at,
            'details': package.title,
        })
    for review in reviews[:2]:
        activity_items.append({
            'action': 'Review Posted',
            'actor': review.traveler.get_full_name() if review.traveler else 'Traveler',
            'date': review.created_at,
            'details': f'{review.rating}-star rating',
        })
    activity_items.sort(key=lambda item: item['date'], reverse=True)
    activity_items = activity_items[:6]

    stats = {
        'total_vendors': vendors.count(),
        'pending_vendors': pending_vendors.count(),
        'total_travelers': travelers.count(),
        'total_packages': packages.count(),
        'active_packages': packages.filter(is_active=True).count(),
        'total_users': total_users,
        'active_vendors': active_vendors,
        'total_bookings': total_bookings,
        'total_revenue': float(total_revenue),
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating or 0, 1),
        'forum_posts': 0,
    }

    return render(request, 'accounts/admin_dashboard.html', {
        'admin_profile': admin_profile,
        'vendors': vendors,
        'pending_vendors': pending_vendors,
        'travelers': travelers,
        'packages': packages,
        'stats': stats,
        'revenue_points': " ".join(revenue_points),
        'revenue_labels': month_labels,
        'activity_items': activity_items,
        'active_page': 'dashboard',
    })


@admin_required
@csrf_protect
def admin_profile(request):
    profile = _get_admin_profile(request.user)
    if profile is None:
        profile = AdminProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('admin_profile')

        current_password = request.POST.get('current_password') or ''
        new_password = request.POST.get('new_password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('admin_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.save()

        profile.bio = bio
        uploading_new_avatar = bool(avatar)
        if remove_avatar:
            profile.avatar = None
        elif avatar:
            profile.avatar = avatar

        profile.save()
        if remove_avatar or uploading_new_avatar:
            current_avatar_name = profile.avatar.name if profile.avatar else ''
            if old_avatar_name and old_avatar_name != current_avatar_name:
                _delete_stored_file(profile, 'avatar', old_avatar_name)

        if current_password or new_password or confirm_password:
            if not request.user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('admin_profile')
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return redirect('admin_profile')
            if len(new_password) < 6:
                messages.error(request, 'New password must be at least 6 characters long.')
                return redirect('admin_profile')
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password updated successfully.')
        else:
            messages.success(request, 'Profile updated successfully.')

        return redirect('admin_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    pending_vendors = User.objects.filter(
        user_type='vendor',
        vendor_profile__is_approved=False,
    ).select_related('vendor_profile').order_by('-date_joined')

    return render(request, 'accounts/admin_profile.html', {
        'profile': profile,
        'full_name': full_name,
        'pending_vendors': pending_vendors,
        'active_page': 'profile',
    })


@admin_required
@csrf_protect
def admin_vendor_action(request, vendor_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    action = request.POST.get('action')

    if profile is None:
        messages.error(request, 'Vendor profile not found.')
        return redirect('admin_dashboard')

    if action == 'approve':
        profile.is_approved = True
        vendor.is_active = True
        messages.success(request, f'{vendor.email} approved.')
    elif action == 'reject':
        profile.is_approved = False
        vendor.is_active = False
        messages.success(request, f'{vendor.email} rejected.')
    elif action == 'suspend':
        vendor.is_active = False
        messages.success(request, f'{vendor.email} suspended.')
    elif action == 'activate':
        vendor.is_active = True
        messages.success(request, f'{vendor.email} activated.')
    else:
        messages.error(request, 'Invalid action.')
        return redirect('admin_dashboard')

    vendor.save()
    profile.save()
    return redirect('admin_dashboard')


@admin_required
@csrf_protect
def admin_package_toggle(request, package_id):
    if request.method != 'POST':
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    package.is_active = not package.is_active
    package.save()

    status_label = 'activated' if package.is_active else 'deactivated'
    messages.success(request, f'{package.title} {status_label}.')
    return redirect('admin_dashboard')


@admin_required
def admin_vendor_detail(request, vendor_id):
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    profile = _get_vendor_profile(vendor)
    admin_profile = _get_admin_profile(request.user)
    packages = Package.objects.filter(vendor=vendor).order_by('-created_at')

    return render(request, 'accounts/admin_vendor_detail.html', {
        'admin_profile': admin_profile,
        'vendor': vendor,
        'vendor_profile': profile,
        'packages': packages,
        'active_page': 'vendors',
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_package_create(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)

    if request.method == 'POST':
        form = PackageForm(request.POST)
        if form.is_valid():
            package = form.save(commit=False)
            package.vendor = request.user
            package.save()
            _append_package_images(package, request.FILES.getlist('images'))
            messages.success(request, 'Package created successfully.')
            return redirect('vendor_packages')
    else:
        form = PackageForm()

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': False,
        'existing_images': [],
    })


@never_cache
@login_required(login_url='vendor_login')
def vendor_package_edit(request, package_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    vendor_profile = _get_vendor_profile(request.user)
    package = get_object_or_404(
        Package.objects.prefetch_related('images'),
        id=package_id,
        vendor=request.user,
    )

    if request.method == 'POST':
        form = PackageForm(request.POST, instance=package)
        if form.is_valid():
            package = form.save()
            _sync_package_images(package, request.POST, request.FILES)
            messages.success(request, 'Package updated successfully.')
            return redirect('vendor_package_edit', package_id=package.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PackageForm(instance=package)

    return render(request, 'accounts/vendor_package_form.html', {
        'vendor_profile': vendor_profile,
        'active_page': 'packages',
        'form': form,
        'is_edit': True,
        'package': package,
        'existing_images': package.images.all(),
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_home(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    search_query = (request.GET.get('q') or '').strip()
    selected_category = (request.GET.get('category') or 'all').strip().lower()
    if selected_category not in {'all', *TRAVELER_CATEGORY_SLUGS}:
        selected_category = 'all'

    base_packages = _traveler_package_queryset()
    filtered_packages = base_packages

    if search_query:
        filtered_packages = filtered_packages.filter(
            Q(title__icontains=search_query)
            | Q(location__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    if selected_category != 'all':
        filtered_packages = filtered_packages.filter(category_slug=selected_category)

    category_counts = {
        'all': base_packages.count(),
        **{slug: 0 for slug in TRAVELER_CATEGORY_SLUGS},
    }
    for row in base_packages.values('category_slug').annotate(total=Count('id')):
        slug = row['category_slug']
        if slug in category_counts:
            category_counts[slug] = row['total']

    featured_packages = list(
        filtered_packages.order_by(
            '-avg_rating',
            '-review_count',
            '-views_count',
            '-created_at',
        )[:4]
    )
    featured_ids = {package.id for package in featured_packages}

    recommended_packages = list(
        filtered_packages.exclude(id__in=featured_ids).order_by(
            '-booking_count',
            '-avg_rating',
            '-review_count',
            '-views_count',
            '-created_at',
        )[:4]
    )

    recommended_ids = featured_ids | {package.id for package in recommended_packages}
    recently_added_packages = list(
        filtered_packages.exclude(id__in=recommended_ids).order_by('-created_at')[:4]
    )

    _add_category_labels(featured_packages)
    _add_category_labels(recommended_packages)
    _add_category_labels(recently_added_packages)

    recent_reviews = Review.objects.filter(package__is_active=True).select_related(
        'traveler',
        'package',
    ).order_by('-created_at')[:6]

    category_filters = [
        {'slug': 'all', 'label': 'All', 'count': category_counts['all']},
        *[
            {
                'slug': slug,
                'label': TRAVELER_CATEGORY_LABELS[slug],
                'count': category_counts[slug],
            }
            for slug in TRAVELER_CATEGORY_SLUGS
        ],
    ]

    return render(request, 'accounts/traveler_home.html', {
        'traveler_profile': profile,
        'active_page': 'explore',
        'search_query': search_query,
        'selected_category': selected_category,
        'category_filters': category_filters,
        'featured_packages': featured_packages,
        'recommended_packages': recommended_packages,
        'recently_added_packages': recently_added_packages,
        'recent_reviews': recent_reviews,
        'result_count': filtered_packages.count(),
        'can_clear_filters': bool(search_query or selected_category != 'all'),
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_bookings(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    bookings = Booking.objects.filter(traveler=request.user).select_related(
        'package',
    ).order_by('-created_at')

    return render(request, 'accounts/traveler_bookings.html', {
        'traveler_profile': profile,
        'bookings': bookings,
        'active_page': 'bookings',
    })


@never_cache
@login_required(login_url='traveler_login')
def traveler_profile(request):
    if not _ensure_traveler(request):
        return redirect('traveler_login')

    profile = _get_traveler_profile(request.user)
    if profile is None:
        profile = TravelerProfile.objects.create(user=request.user)

    if request.method == 'POST':
        old_avatar_name = profile.avatar.name if profile.avatar else ''
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender') or ''
        nationality = (request.POST.get('nationality') or '').strip()
        bio = (request.POST.get('bio') or '').strip()
        avatar = request.FILES.get('avatar')
        remove_avatar = request.POST.get('remove_avatar') == '1'

        if avatar and not _is_valid_uploaded_image(avatar):
            messages.error(request, 'Please upload a valid image file.')
            return redirect('traveler_profile')

        if full_name:
            parts = full_name.split()
            request.user.first_name = parts[0]
            request.user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if email and email != request.user.email:
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, 'Email is already in use.')
                return redirect('traveler_profile')
            request.user.email = email
            request.user.username = email

        request.user.phone = phone
        request.user.save()

        profile.gender = gender
        profile.nationality = nationality
        profile.bio = bio
        profile.date_of_birth = date_of_birth or None
        uploading_new_avatar = bool(avatar)
        if remove_avatar:
            profile.avatar = None
        elif avatar:
            profile.avatar = avatar
        profile.save()
        if remove_avatar or uploading_new_avatar:
            current_avatar_name = profile.avatar.name if profile.avatar else ''
            if old_avatar_name and old_avatar_name != current_avatar_name:
                _delete_stored_file(profile, 'avatar', old_avatar_name)

        messages.success(request, 'Profile updated successfully.')
        return redirect('traveler_profile')

    full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    traveler_reviews = Review.objects.filter(traveler=request.user).select_related('package').order_by('-created_at')[:6]
    review_packages = Package.objects.filter(is_active=True).order_by('title')
    activity = [
        {
            'title': 'Left a review for Everest Base Camp Trek',
            'time': '2 days ago',
            'variant': 'review',
        },
        {
            'title': 'Completed Annapurna Circuit',
            'time': '1 week ago',
            'variant': 'completed',
        },
        {
            'title': 'Earned "High Altitude" badge',
            'time': '2 weeks ago',
            'variant': 'badge',
        },
    ]

    return render(request, 'accounts/traveler_profile.html', {
        'traveler_profile': profile,
        'profile': profile,
        'full_name': full_name,
        'traveler_reviews': traveler_reviews,
        'review_packages': review_packages,
        'activity': activity,
        'active_page': 'profile',
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
                vendor_profile = _get_vendor_profile(user)
                if vendor_profile and not vendor_profile.is_approved:
                    messages.error(request, 'Your vendor account is pending approval.')
                    return redirect('vendor_login')

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
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Please check email settings or spam folder.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/vendor_register.html')

@csrf_protect
def traveler_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
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
                if _get_traveler_profile(user) is None:
                    TravelerProfile.objects.create(user=user)
                return redirect('traveler_home')
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
            messages.error(request, 'OTP email could not be sent. Please check email settings or spam folder.')
    except User.DoesNotExist:
        messages.error(request, 'User not found')
    
    return redirect('verify_otp')

@never_cache
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('home')

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

        TravelerProfile.objects.create(user=user)
        
        # Send OTP
        _, sent = create_otp(user)
        request.session['user_id'] = user.id
        
        messages.success(request, 'Registration successful! Please verify your email.')
        if not sent:
            messages.error(request, 'OTP email could not be sent. Please check email settings or spam folder.')
        return redirect('verify_otp')
    
    return render(request, 'accounts/traveler_register.html')


def landing(request):
    return render(request, 'landing.html')


def account_register_choice(request):
    return render(request, 'accounts/register_choice.html')


def account_login_choice(request):
    return render(request, 'accounts/login_choice.html')
