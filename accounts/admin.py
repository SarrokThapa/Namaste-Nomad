from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, VendorProfile, OTP

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'user_type', 'is_verified', 'is_active', 'date_joined')
    list_filter = ('user_type', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('user_type', 'phone', 'is_verified')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Info', {'fields': ('user_type', 'phone', 'is_verified')}),
    )

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'owner_name', 'user', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'created_at')
    search_fields = ('business_name', 'owner_name', 'user__email')
    actions = ['approve_vendors', 'reject_vendors']
    
    def approve_vendors(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f'{queryset.count()} vendor(s) approved successfully.')
    approve_vendors.short_description = 'Approve selected vendors'
    
    def reject_vendors(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f'{queryset.count()} vendor(s) rejected.')
    reject_vendors.short_description = 'Reject selected vendors'

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'otp_code', 'created_at', 'expires_at', 'is_used')
    list_filter = ('is_used', 'created_at')
    search_fields = ('user__email', 'otp_code')
    readonly_fields = ('created_at', 'expires_at')