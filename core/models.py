from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Package(models.Model):
    DIFFICULTY_CHOICES = (
        ('easy', 'Easy'),
        ('moderate', 'Moderate'),
        ('challenging', 'Challenging'),
        ('expedition', 'Expedition'),
    )

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_packages',
    )
    title = models.CharField(max_length=200)
    location = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    itinerary = models.TextField(blank=True)
    inclusions = models.TextField(blank=True)
    exclusions = models.TextField(blank=True)
    duration_days = models.PositiveSmallIntegerField(blank=True, null=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, blank=True)
    group_size = models.PositiveSmallIntegerField(blank=True, null=True)
    best_season = models.CharField(max_length=100, blank=True)
    image_url = models.URLField(blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


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
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
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
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='direct')
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

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
