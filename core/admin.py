from django.contrib import admin
from .models import Account, Category, Booking, RecurringBooking, Payee, KIGateConfig, OpenAIConfig


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'note']


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'initial_balance', 'is_active', 'is_liquidity_relevant']
    list_filter = ['type', 'is_active', 'is_liquidity_relevant']
    search_fields = ['name']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'type']
    list_filter = ['type']
    search_fields = ['name']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_date', 'account', 'amount', 'category', 'payee', 'status', 'is_transfer']
    list_filter = ['status', 'is_transfer', 'booking_date', 'account', 'payee']
    search_fields = ['description']
    date_hierarchy = 'booking_date'


@admin.register(RecurringBooking)
class RecurringBookingAdmin(admin.ModelAdmin):
    list_display = ['description', 'account', 'amount', 'payee', 'frequency', 'start_date', 'is_active']
    list_filter = ['frequency', 'is_active', 'source', 'payee']
    search_fields = ['description']


@admin.register(KIGateConfig)
class KIGateConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'base_url', 'default_agent_name', 'default_provider', 'default_model', 'is_active', 'updated_at']
    list_filter = ['is_active', 'default_provider']
    search_fields = ['name', 'default_agent_name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'is_active')
        }),
        ('Connection Settings', {
            'fields': ('base_url', 'api_key', 'timeout_seconds')
        }),
        ('Default Parameters', {
            'fields': ('default_agent_name', 'default_provider', 'default_model', 'default_user_id', 'max_tokens')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(OpenAIConfig)
class OpenAIConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'base_url', 'default_model', 'default_vision_model', 'is_active', 'updated_at']
    list_filter = ['is_active']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'is_active')
        }),
        ('Connection Settings', {
            'fields': ('base_url', 'api_key', 'timeout_seconds')
        }),
        ('Model Settings', {
            'fields': ('default_model', 'default_vision_model')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
