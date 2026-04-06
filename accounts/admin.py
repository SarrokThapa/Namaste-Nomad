from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    FeaturedPackage,
    FeaturePlan,
    Notification,
    OTP,
    User,
    VendorFeatureSubscription,
    VendorProfile,
)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'user_type', 'wants_promotions', 'is_verified', 'is_active', 'date_joined')
    list_filter = ('user_type', 'wants_promotions', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('user_type', 'phone', 'is_verified', 'wants_promotions')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Info', {'fields': ('user_type', 'phone', 'is_verified', 'wants_promotions')}),
    )

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'owner_name', 'user', 'document', 'is_approved', 'is_verified', 'created_at')
    list_filter = ('is_approved', 'is_verified', 'created_at')
    search_fields = ('business_name', 'owner_name', 'user__email')
    actions = ['approve_vendors', 'reject_vendors', 'verify_vendors', 'unverify_vendors']
    
    def approve_vendors(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f'{queryset.count()} vendor(s) approved successfully.')
    approve_vendors.short_description = 'Approve selected vendors'
    
    def reject_vendors(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f'{queryset.count()} vendor(s) rejected.')
    reject_vendors.short_description = 'Reject selected vendors'

    def verify_vendors(self, request, queryset):
        queryset.update(is_verified=True)
        self.message_user(request, f'{queryset.count()} vendor(s) verified.')
    verify_vendors.short_description = 'Verify selected vendors'

    def unverify_vendors(self, request, queryset):
        queryset.update(is_verified=False)
        self.message_user(request, f'{queryset.count()} vendor(s) unverified.')
    unverify_vendors.short_description = 'Unverify selected vendors'

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'otp_code', 'created_at', 'expires_at', 'is_used')
    list_filter = ('is_used', 'created_at')
    search_fields = ('user__email', 'otp_code')
    readonly_fields = ('created_at', 'expires_at')


@admin.register(FeaturePlan)
class FeaturePlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slots_count', 'price', 'duration_days', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name',)


@admin.register(VendorFeatureSubscription)
class VendorFeatureSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'vendor',
        'plan_name',
        'slots_total',
        'price',
        'start_date',
        'end_date',
        'payment_status',
        'payment_method',
        'is_active',
        'created_at',
    )
    list_filter = ('is_active', 'payment_status', 'payment_method', 'start_date', 'end_date', 'created_at')
    search_fields = ('vendor__email', 'plan_name', 'transaction_id')


@admin.register(FeaturedPackage)
class FeaturedPackageAdmin(admin.ModelAdmin):
    list_display = ('package', 'subscription', 'is_active', 'featured_date')
    list_filter = ('is_active', 'featured_date')
    search_fields = ('package__title', 'subscription__vendor__email')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'message', 'is_read', 'created_at')
    list_filter = ('type', 'is_read', 'created_at')
    search_fields = ('user__email', 'message')
