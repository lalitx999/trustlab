from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    StaffUser, Branch, Brand, MembershipLevel, BrandPricing,
    ServiceType, Customer, Booking, BookingPhoto,
    Job, Certificate, CertificateSendLog, Contact, Partner
)

# 1. Custom StaffUser Admin
class StaffUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'branch', 'is_staff', 'is_active')
    list_filter = ('role', 'branch', 'is_staff', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Roles & Location', {'fields': ('role', 'branch')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Roles & Location', {'fields': ('role', 'branch')}),
    )

# 2. Custom Customer Admin
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'line_id', 'membership_level', 'credit_balance', 'created_at')
    search_fields = ('full_name', 'phone_number', 'line_id', 'email')
    list_filter = ('membership_level',)

# 3. Custom Booking Admin
class BookingPhotoInline(admin.TabularInline):
    model = BookingPhoto
    extra = 1

class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'branch', 'booking_date', 'booking_time', 'service_type', 'status', 'created_at')
    list_filter = ('status', 'branch', 'booking_date', 'service_type')
    search_fields = ('id', 'customer__full_name', 'customer__phone_number')
    inlines = [BookingPhotoInline]

# 4. Custom Job Admin
class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'queue_no', 'customer', 'category', 'brand', 'model', 'status', 'result', 'payment_status', 'price')
    list_filter = ('status', 'result', 'payment_status', 'category', 'brand', 'express_service')
    search_fields = ('id', 'queue_no', 'customer__full_name', 'serial_number', 'model')

# 5. Custom Certificate Admin
class CertificateAdmin(admin.ModelAdmin):
    list_display = ('id', 'job', 'cert_status', 'created_at', 'expired_at')
    list_filter = ('cert_status',)
    search_fields = ('id', 'job__id', 'job__customer__full_name')

# 6. Custom Brand Pricing Admin
class BrandPricingAdmin(admin.ModelAdmin):
    list_display = ('category', 'brand', 'base_price', 'price_5pct', 'price_15pct', 'partner_price')
    list_filter = ('category',)
    search_fields = ('brand',)

# Register all models with the Django Admin site
admin.site.register(StaffUser, StaffUserAdmin)
admin.site.register(Branch)
admin.site.register(Brand)
admin.site.register(MembershipLevel)
admin.site.register(BrandPricing, BrandPricingAdmin)
admin.site.register(ServiceType)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Booking, BookingAdmin)
admin.site.register(BookingPhoto)
admin.site.register(Job, JobAdmin)
admin.site.register(Certificate, CertificateAdmin)
admin.site.register(CertificateSendLog)
admin.site.register(Contact)
admin.site.register(Partner)
