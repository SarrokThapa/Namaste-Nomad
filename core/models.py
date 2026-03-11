from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Package(models.Model):
    DIFFICULTY_CHOICES = (
        ('easy', 'Easy'),
        ('moderate', 'Moderate'),
        ('challenging', 'Challenging'),
        ('expedition', 'Expedition'),
    )
    CATEGORY_TREK = 'TREK'
    CATEGORY_TOUR = 'TOUR'
    CATEGORY_CHOICES = (
        (CATEGORY_TREK, 'Trek'),
        (CATEGORY_TOUR, 'Tour'),
    )

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_packages',
    )
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default=CATEGORY_TREK)
    location = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    itinerary = models.TextField(blank=True)
    inclusions = models.TextField(blank=True)
    exclusions = models.TextField(blank=True)
    duration_days = models.PositiveSmallIntegerField(blank=True, null=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, blank=True)
    group_size = models.PositiveSmallIntegerField(blank=True, null=True)
    available_slots = models.PositiveIntegerField(default=10)
    available_from = models.DateField(blank=True, null=True)
    available_until = models.DateField(blank=True, null=True)
    best_season = models.CharField(max_length=100, blank=True)
    image_url = models.URLField(blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    def is_in_season(self, on_date=None):
        check_date = on_date or timezone.localdate()
        if not self.available_from or not self.available_until:
            return False
        return self.available_from <= check_date <= self.available_until

    def season_badge(self, on_date=None):
        check_date = on_date or timezone.localdate()
        if not self.available_from or not self.available_until:
            return 'Not Available'
        if check_date < self.available_from:
            return 'Not Available'
        if check_date > self.available_until:
            return 'Season Closed'
        return ''


class PackageImage(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='package_images/')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('order', 'created_at', 'id')

    def __str__(self):
        return f"{self.package.title} Image"


class Booking(models.Model):
    COMMISSION_VENDOR_RATE = Decimal('0.75')
    COMMISSION_PLATFORM_RATE = Decimal('0.25')

    STATUS_PAYMENT_PENDING = 'payment_pending'
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PAYMENT_PENDING, 'Payment Pending'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PAYMENT_METHOD_STRIPE = 'stripe'
    PAYMENT_METHOD_ESEWA = 'esewa'
    PAYMENT_METHOD_KHALTI = 'khalti'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_STRIPE, 'Stripe'),
        (PAYMENT_METHOD_ESEWA, 'eSewa'),
        (PAYMENT_METHOD_KHALTI, 'Khalti'),
    ]

    PAYMENT_STATUS_PENDING = 'pending'
    PAYMENT_STATUS_PAID = 'paid'
    PAYMENT_STATUS_CANCELLED = 'cancelled'
    PAYMENT_STATUS_EXPIRED = 'expired'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_PENDING, 'Pending'),
        (PAYMENT_STATUS_PAID, 'Paid'),
        (PAYMENT_STATUS_CANCELLED, 'Cancelled'),
        (PAYMENT_STATUS_EXPIRED, 'Expired'),
    ]

    SOURCE_CHOICES = [
        ('direct', 'Direct'),
        ('partner', 'Partner'),
        ('social', 'Social'),
        ('marketplace', 'Marketplace'),
    ]

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='bookings')
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='traveler_bookings',
        null=True,
        blank=True,
    )
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='vendor_bookings',
        null=True,
        blank=True,
    )
    number_of_people = models.PositiveIntegerField(default=1)
    travel_date = models.DateField(default=date.today)
    special_notes = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PAYMENT_PENDING)
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=PAYMENT_METHOD_STRIPE,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_STATUS_PENDING,
    )
    payment_reference = models.CharField(max_length=255, blank=True)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_expires_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='direct')
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    vendor_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=Decimal('0.00'),
    )
    platform_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=Decimal('0.00'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        computed_fields = set()

        if self.package_id:
            package_price = self.package.price or Decimal('0')
            if not isinstance(package_price, Decimal):
                package_price = Decimal(str(package_price))
            new_total = package_price * self.number_of_people
            if self.total_price != new_total:
                self.total_price = new_total
                computed_fields.add('total_price')
            if not self.vendor_id:
                self.vendor = self.package.vendor
                computed_fields.add('vendor')

        total_price = self.total_price
        if total_price is not None:
            if not isinstance(total_price, Decimal):
                total_price = Decimal(str(total_price))
            vendor_amount = (total_price * self.COMMISSION_VENDOR_RATE).quantize(Decimal('0.01'))
            platform_fee = (total_price * self.COMMISSION_PLATFORM_RATE).quantize(Decimal('0.01'))
            if vendor_amount + platform_fee != total_price:
                platform_fee = total_price - vendor_amount
            if self.vendor_amount != vendor_amount:
                self.vendor_amount = vendor_amount
                computed_fields.add('vendor_amount')
            if self.platform_fee != platform_fee:
                self.platform_fee = platform_fee
                computed_fields.add('platform_fee')
        if self.travel_date:
            if not self.start_date:
                self.start_date = self.travel_date
            if not self.end_date:
                self.end_date = self.travel_date
        if update_fields is not None and computed_fields:
            kwargs['update_fields'] = list(set(update_fields) | computed_fields)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.package.title} ({self.status})"


class Review(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='reviews')
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='traveler_reviews',
        null=True,
        blank=True,
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.package.title} - {self.rating}"


class Post(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_posts',
    )
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='liked_community_posts',
        blank=True,
    )
    image = models.ImageField(upload_to='community_posts/', blank=True, null=True)
    caption = models.TextField(max_length=2200)
    tagged_vendors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='tagged_posts',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.user.username} - {self.created_at:%Y-%m-%d %H:%M}"


class PostMedia(models.Model):
    MEDIA_IMAGE = 'image'
    MEDIA_VIDEO = 'video'
    MEDIA_TYPE_CHOICES = (
        (MEDIA_IMAGE, 'Image'),
        (MEDIA_VIDEO, 'Video'),
    )

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='media')
    media_file = models.FileField(upload_to='community_posts/')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default=MEDIA_IMAGE)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('order', 'created_at', 'id')

    def __str__(self):
        return f"PostMedia {self.post_id} ({self.media_type})"


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='replies',
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_comments',
    )
    body = models.TextField(max_length=800)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at',)

    def __str__(self):
        return f"{self.user.username} on post #{self.post_id}"
