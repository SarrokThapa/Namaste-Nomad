from django.contrib import admin
from .models import Booking, Package, Review


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('title', 'vendor', 'price', 'is_active', 'views_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'vendor__email')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('package', 'traveler', 'status', 'source', 'start_date', 'end_date', 'total_price')
    list_filter = ('status', 'source', 'start_date')
    search_fields = ('package__title', 'traveler__email')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('package', 'traveler', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('package__title', 'traveler__email')
