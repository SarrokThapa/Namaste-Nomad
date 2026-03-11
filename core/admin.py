from django.contrib import admin
from .models import Booking, Comment, Package, Post, PostMedia, Review


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('title', 'vendor', 'price', 'is_active', 'is_featured', 'views_count', 'created_at')
    list_filter = ('is_active', 'is_featured', 'created_at')
    search_fields = ('title', 'vendor__email')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'package',
        'traveler',
        'vendor',
        'status',
        'payment_method',
        'payment_status',
        'source',
        'travel_date',
        'number_of_people',
        'total_price',
        'vendor_amount',
        'platform_fee',
        'created_at',
    )
    list_filter = ('status', 'payment_method', 'payment_status', 'source', 'travel_date', 'created_at')
    search_fields = ('package__title', 'traveler__email', 'vendor__email')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('package', 'traveler', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('package__title', 'traveler__email')


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'caption')


@admin.register(PostMedia)
class PostMediaAdmin(admin.ModelAdmin):
    list_display = ('id', 'post', 'media_type', 'order', 'created_at')
    list_filter = ('media_type', 'created_at')
    search_fields = ('post__caption', 'post__user__username', 'post__user__email')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'post', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('post__caption', 'user__username', 'user__email', 'body')
