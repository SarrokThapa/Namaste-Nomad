from django.contrib import admin
from accounts.models import Notification, User
from accounts.notifications import create_notification

from .models import (
    Booking,
    Comment,
    ContactMessage,
    Discount,
    Package,
    Post,
    PostMedia,
    Review,
    SpecialOffer,
    SupportMessage,
    Transaction,
    TravelTip,
)


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
        'payment_reference',
        'esewa_transaction_id',
        'paid_amount',
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


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'transaction_type',
        'booking',
        'vendor_subscription',
        'vendor_feature',
        'traveler',
        'vendor',
        'total_amount',
        'payment_method',
        'payment_status',
        'created_at',
    )
    list_filter = ('transaction_type', 'payment_method', 'payment_status', 'created_at')
    search_fields = (
        'transaction_id',
        'booking__id',
        'vendor_subscription__id',
        'vendor_feature__id',
        'traveler__email',
        'vendor__email',
        'booking__package__title',
    )


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'subject', 'is_resolved', 'created_at')
    list_filter = ('is_resolved', 'created_at')
    search_fields = ('full_name', 'email', 'subject', 'message')


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'percentage', 'fixed_amount', 'max_discount_cap', 'is_used', 'expires_at', 'source')
    list_filter = ('is_used', 'source', 'expires_at', 'created_at')
    search_fields = ('user__email', 'user__username')


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'conversation',
        'sender',
        'related_booking',
        'is_admin_reply',
        'is_system_generated',
        'created_at',
    )
    list_filter = ('is_admin_reply', 'is_system_generated', 'created_at')
    search_fields = ('sender__email', 'message', 'conversation__user__email')


class PromotionsNotificationAdminMixin:
    notification_message = ''

    def _notify_opted_in_users(self, obj):
        recipients = User.objects.filter(is_active=True, wants_promotions=True)
        for user in recipients:
            create_notification(
                user,
                self.notification_message.format(title=obj.title),
                Notification.TYPE_PROMOTION,
                related_object_id=obj.id,
            )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and obj.is_active:
            self._notify_opted_in_users(obj)


@admin.register(TravelTip)
class TravelTipAdmin(PromotionsNotificationAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'summary', 'content')
    notification_message = 'New travel tip: {title}'


@admin.register(SpecialOffer)
class SpecialOfferAdmin(PromotionsNotificationAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'valid_until', 'is_active', 'created_at')
    list_filter = ('is_active', 'valid_until', 'created_at')
    search_fields = ('title', 'summary', 'content')
    notification_message = 'Special offer available: {title}'
