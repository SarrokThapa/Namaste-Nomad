from datetime import timedelta

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
    is_approved = models.BooleanField(default=False)
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
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)
    
    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp_code}"


class VendorSubscriptionPlan(models.Model):
    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField()
    max_featured_packages = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('price', 'duration_days', 'name')

    def __str__(self):
        return self.name


class VendorSubscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
    )

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_subscriptions',
    )
    plan = models.ForeignKey(
        VendorSubscriptionPlan,
        on_delete=models.SET_NULL,
        related_name='subscriptions',
        blank=True,
        null=True,
    )
    plan_name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField()
    max_featured_packages = models.PositiveIntegerField(blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-start_date', '-id')

    def is_active(self, on_date=None):
        check_date = on_date or timezone.localdate()
        return (
            self.status == self.STATUS_ACTIVE
            and self.start_date <= check_date <= self.end_date
        )

    @classmethod
    def expire_overdue(cls, vendor=None):
        today = timezone.localdate()
        overdue = cls.objects.filter(status=cls.STATUS_ACTIVE, end_date__lt=today)
        if vendor is not None:
            overdue = overdue.filter(vendor=vendor)
        vendor_ids = list(overdue.values_list('vendor_id', flat=True).distinct())
        overdue.update(status=cls.STATUS_EXPIRED)

        if vendor_ids:
            active_vendor_ids = set(
                cls.objects.filter(
                    vendor_id__in=vendor_ids,
                    status=cls.STATUS_ACTIVE,
                    start_date__lte=today,
                    end_date__gte=today,
                ).values_list('vendor_id', flat=True)
            )
            vendors_to_unfeature = [vendor_id for vendor_id in vendor_ids if vendor_id not in active_vendor_ids]
            if vendors_to_unfeature:
                from core.models import Package
                Package.objects.filter(
                    vendor_id__in=vendors_to_unfeature,
                    is_featured=True,
                ).update(is_featured=False)
        return vendor_ids

    @classmethod
    def active_for_vendor(cls, vendor):
        cls.expire_overdue(vendor=vendor)
        today = timezone.localdate()
        return (
            cls.objects.filter(
                vendor=vendor,
                status=cls.STATUS_ACTIVE,
                start_date__lte=today,
                end_date__gte=today,
            )
            .order_by('-end_date', '-start_date')
            .first()
        )

    def __str__(self):
        return f"{self.vendor.email} - {self.plan_name} ({self.status})"
