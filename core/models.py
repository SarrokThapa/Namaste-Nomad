from datetime import date

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
    number_of_people = models.PositiveIntegerField(default=1)
    travel_date = models.DateField(default=date.today)
    special_notes = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='direct')
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.package_id:
            self.total_price = (self.package.price or 0) * self.number_of_people
        if self.travel_date:
            if not self.start_date:
                self.start_date = self.travel_date
            if not self.end_date:
                self.end_date = self.travel_date
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
    image = models.ImageField(upload_to='community_posts/')
    caption = models.TextField(max_length=2200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.user.username} - {self.created_at:%Y-%m-%d %H:%M}"


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
