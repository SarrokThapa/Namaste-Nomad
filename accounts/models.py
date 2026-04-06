from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('vendor', 'Vendor'),
        ('traveler', 'Traveler'),
        ('admin', 'Admin'),
    )
    
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)
    phone = models.CharField(max_length=20, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    wants_promotions = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.username} - {self.user_type}"

class VendorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    business_name = models.CharField(max_length=255)
    owner_name = models.CharField(max_length=255)
    tagline = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    business_address = models.TextField(blank=True)
    description = models.TextField(blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=120, blank=True)
    routing_number = models.CharField(max_length=120, blank=True)
    paypal_email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to='vendor_logos/', blank=True, null=True)
    cover_image = models.FileField(upload_to='vendor_covers/', blank=True, null=True)
    business_license = models.FileField(upload_to='licenses/', blank=True, null=True)
    document = models.FileField(upload_to='vendor_documents/', blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.business_name


class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile')
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='admin_avatars/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} Admin Profile"


class TravelerProfile(models.Model):
    GENDER_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
        ('', 'Prefer not to say'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='traveler_profile')
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} Profile"

class OTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=5)
        super().save(*args, **kwargs)
    
    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp_code}"


class FeaturePlan(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slots_count = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('price', 'slots_count', 'name')

    def __str__(self):
        return f"{self.name} ({self.slots_count} slots, {self.duration_days}d)"


class VendorFeatureSubscription(models.Model):
    PAYMENT_STATUS_PENDING = 'pending'
    PAYMENT_STATUS_PAID = 'paid'
    PAYMENT_STATUS_CHOICES = (
        (PAYMENT_STATUS_PENDING, 'Pending'),
        (PAYMENT_STATUS_PAID, 'Paid'),
    )

    PAYMENT_METHOD_ESEWA = 'esewa'
    PAYMENT_METHOD_STRIPE = 'stripe'
    PAYMENT_METHOD_CHOICES = (
        (PAYMENT_METHOD_ESEWA, 'eSewa'),
        (PAYMENT_METHOD_STRIPE, 'Stripe'),
    )

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feature_subscriptions',
    )
    plan = models.ForeignKey(
        FeaturePlan,
        on_delete=models.SET_NULL,
        related_name='subscriptions',
        null=True,
    )
    plan_name = models.CharField(max_length=100)
    slots_total = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_PENDING)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default=PAYMENT_METHOD_ESEWA)
    transaction_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-start_date', '-id')

    @property
    def slots_used(self):
        return self.featured_packages.filter(is_active=True).count()

    @property
    def slots_remaining(self):
        return max(self.slots_total - self.slots_used, 0)

    @property
    def is_expired(self):
        return self.end_date < timezone.localdate()

    @classmethod
    def expire_overdue(cls, vendor=None):
        today = timezone.localdate()
        overdue = cls.objects.filter(is_active=True, end_date__lt=today)
        if vendor is not None:
            overdue = overdue.filter(vendor=vendor)
        expired_ids = list(overdue.values_list('id', flat=True))
        if expired_ids:
            FeaturedPackage.objects.filter(
                subscription_id__in=expired_ids,
                is_active=True,
            ).update(is_active=False)
            overdue.update(is_active=False)
        return expired_ids

    @classmethod
    def active_for_vendor(cls, vendor):
        cls.expire_overdue(vendor=vendor)
        today = timezone.localdate()
        return cls.objects.filter(
            vendor=vendor,
            is_active=True,
            payment_status=cls.PAYMENT_STATUS_PAID,
            start_date__lte=today,
            end_date__gte=today,
        ).order_by('-end_date').first()

    def __str__(self):
        return f"{self.vendor.email} - {self.plan_name} ({self.slots_used}/{self.slots_total})"


class FeaturedPackage(models.Model):
    subscription = models.ForeignKey(
        VendorFeatureSubscription,
        on_delete=models.CASCADE,
        related_name='featured_packages',
    )
    package = models.ForeignKey(
        'core.Package',
        on_delete=models.CASCADE,
        related_name='featured_entries',
    )
    featured_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('-featured_date',)
        constraints = [
            models.UniqueConstraint(
                fields=['subscription', 'package'],
                name='unique_featured_package_per_subscription',
            ),
        ]

    def __str__(self):
        return f"{self.package.title} (via {self.subscription.plan_name})"


class PasswordResetOTP(models.Model):
    email = models.EmailField(db_index=True)
    otp_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    verified = models.BooleanField(default=False)
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"PasswordResetOTP for {self.email}"


class Notification(models.Model):
    TYPE_BOOKING = 'booking'
    TYPE_COMMUNITY_POST = 'community_post'
    TYPE_LIKE = 'like'
    TYPE_COMMENT = 'comment'
    TYPE_VENDOR_APPROVAL = 'vendor_approval'
    TYPE_ADMIN_MESSAGE = 'admin_message'
    TYPE_PACKAGE_APPROVED = 'package_approved'
    TYPE_SUPPORT_MESSAGE = 'support_message'
    TYPE_PACKAGE_SUBMISSION = 'package_submission'
    TYPE_USER_REGISTRATION = 'user_registration'
    TYPE_PROMOTION = 'promotion'

    TYPE_CHOICES = (
        (TYPE_BOOKING, 'Booking'),
        (TYPE_COMMUNITY_POST, 'Community Post'),
        (TYPE_LIKE, 'Like'),
        (TYPE_COMMENT, 'Comment'),
        (TYPE_VENDOR_APPROVAL, 'Vendor Approval'),
        (TYPE_ADMIN_MESSAGE, 'Admin Message'),
        (TYPE_PACKAGE_APPROVED, 'Package Approved'),
        (TYPE_SUPPORT_MESSAGE, 'Support Message'),
        (TYPE_PACKAGE_SUBMISSION, 'Package Submission'),
        (TYPE_USER_REGISTRATION, 'User Registration'),
        (TYPE_PROMOTION, 'Promotion'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    message = models.TextField()
    type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"Notification #{self.id} ({self.user.username})"


class Badge(models.Model):
    CONDITION_FIRST_POST = 'first_post'
    CONDITION_FIRST_WISHLIST = 'first_wishlist'
    CONDITION_FIRST_BOOKING_CONFIRMED = 'first_booking_confirmed'
    CONDITION_POST_LIKES = 'post_likes'
    CONDITION_FIRST_REVIEW = 'first_review'
    CONDITION_TREK_BOOKINGS_CONFIRMED = 'trek_bookings_confirmed'

    CONDITION_CHOICES = (
        (CONDITION_FIRST_POST, 'First Post'),
        (CONDITION_FIRST_WISHLIST, 'First Wishlist'),
        (CONDITION_FIRST_BOOKING_CONFIRMED, 'First Booking Confirmed'),
        (CONDITION_POST_LIKES, 'Post Likes'),
        (CONDITION_FIRST_REVIEW, 'First Review'),
        (CONDITION_TREK_BOOKINGS_CONFIRMED, 'Trek Bookings Confirmed'),
    )

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField()
    icon = models.CharField(max_length=20)
    condition_type = models.CharField(max_length=40, choices=CONDITION_CHOICES)
    condition_value = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ('id',)

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='earned_badges',
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name='earned_by',
    )
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-earned_at',)
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'badge'],
                name='unique_user_badge',
            )
        ]

    def __str__(self):
        return f"{self.user.username} earned {self.badge.name}"


class RewardPoint(models.Model):
    ACTION_POST = 'post'
    ACTION_LIKE_RECEIVED = 'like_received'
    ACTION_REVIEW = 'review'
    ACTION_WISHLIST = 'wishlist'
    ACTION_BOOKING_CONFIRMED = 'booking_confirmed'

    ACTION_CHOICES = (
        (ACTION_POST, 'Community Post'),
        (ACTION_LIKE_RECEIVED, 'Like Received'),
        (ACTION_REVIEW, 'Review'),
        (ACTION_WISHLIST, 'Wishlist'),
        (ACTION_BOOKING_CONFIRMED, 'Booking Confirmed'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reward_points',
    )
    points = models.IntegerField()
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.user.username}: {self.points} ({self.action_type})"
