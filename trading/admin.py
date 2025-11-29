from django.contrib import admin
from .models import TradingAsset, AssetBreakoutConfig, AssetEventConfig, Signal, Trade, WorkerStatus, AssetPriceStatus


class AssetBreakoutConfigInline(admin.StackedInline):
    """Inline admin for breakout configuration."""
    model = AssetBreakoutConfig
    can_delete = False
    extra = 1
    max_num = 1
    fieldsets = (
        ('Asia Range', {
            'fields': (
                ('asia_range_start', 'asia_range_end'),
                ('asia_min_range_ticks', 'asia_max_range_ticks'),
            )
        }),
        ('Pre-US Range (Range Formation Only)', {
            'fields': (
                ('pre_us_start', 'pre_us_end'),
                ('us_min_range_ticks', 'us_max_range_ticks'),
            ),
            'description': 'Time window for Pre-US Range formation (no breakouts). Default: 13:00-15:00 UTC'
        }),
        ('US Core Trading Session (Breakouts Allowed)', {
            'fields': (
                ('us_core_trading_start', 'us_core_trading_end'),
                'us_core_trading_enabled',
            ),
            'description': 'Time window for US Core Trading session (breakouts active). Default: 15:00-22:00 UTC'
        }),
        ('Breakout Requirements', {
            'fields': (
                'min_breakout_body_fraction',
                ('require_atr_minimum', 'min_atr_value'),
            )
        }),
    )


class AssetEventConfigInline(admin.TabularInline):
    """Inline admin for event configurations."""
    model = AssetEventConfig
    extra = 0
    fields = ('phase', 'event_type', 'is_required', 'filter_enabled', 'time_offset_minutes')


@admin.register(TradingAsset)
class TradingAssetAdmin(admin.ModelAdmin):
    """Admin for managing trading assets."""
    list_display = ['name', 'symbol', 'epic', 'broker', 'category', 'strategy_type', 'is_crypto', 'is_active', 'updated_at']
    list_filter = ['is_active', 'broker', 'category', 'strategy_type', 'is_crypto']
    search_fields = ['name', 'symbol', 'epic', 'broker_symbol']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [AssetBreakoutConfigInline, AssetEventConfigInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'symbol', 'epic', 'category', 'is_crypto')
        }),
        ('Broker Configuration', {
            'fields': ('broker', 'broker_symbol', 'quote_currency'),
            'description': 'Configure which broker to use for this asset. broker_symbol is optional if same as epic.'
        }),
        ('Strategy & Trading', {
            'fields': ('strategy_type', 'tick_size', 'is_active')
        }),
        ('Size Constraints', {
            'fields': ('min_size', 'max_size', 'lot_size'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_assets', 'deactivate_assets']
    
    @admin.action(description='Activate selected assets')
    def activate_assets(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} asset(s) activated.')
    
    @admin.action(description='Deactivate selected assets')
    def deactivate_assets(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} asset(s) deactivated.')


@admin.register(AssetBreakoutConfig)
class AssetBreakoutConfigAdmin(admin.ModelAdmin):
    """Admin for breakout configurations."""
    list_display = ['asset', 'asia_range_start', 'asia_range_end', 'pre_us_start', 'pre_us_end', 'us_core_trading_start', 'us_core_trading_end', 'us_core_trading_enabled', 'updated_at']
    list_filter = ['asset__category', 'us_core_trading_enabled']
    search_fields = ['asset__name', 'asset__symbol']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Asset', {
            'fields': ('asset',)
        }),
        ('Asia Range Configuration', {
            'fields': (
                ('asia_range_start', 'asia_range_end'),
                ('asia_min_range_ticks', 'asia_max_range_ticks'),
            )
        }),
        ('Pre-US Range Configuration (Range Formation Only)', {
            'fields': (
                ('pre_us_start', 'pre_us_end'),
                ('us_min_range_ticks', 'us_max_range_ticks'),
            ),
            'description': 'Time window for Pre-US Range formation. No breakouts generated during this phase.'
        }),
        ('US Core Trading Session (Breakouts Allowed)', {
            'fields': (
                ('us_core_trading_start', 'us_core_trading_end'),
                'us_core_trading_enabled',
            ),
            'description': 'Time window for US Core Trading. Breakouts are generated during this phase if enabled.'
        }),
        ('Breakout Candle Requirements', {
            'fields': ('min_breakout_body_fraction',)
        }),
        ('ATR Filter', {
            'fields': (('require_atr_minimum', 'min_atr_value'),),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AssetEventConfig)
class AssetEventConfigAdmin(admin.ModelAdmin):
    """Admin for event configurations."""
    list_display = ['asset', 'phase', 'event_type', 'is_required', 'filter_enabled', 'updated_at']
    list_filter = ['asset', 'phase', 'event_type', 'is_required', 'filter_enabled']
    search_fields = ['asset__name', 'notes']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Asset & Phase', {
            'fields': ('asset', 'phase')
        }),
        ('Event Configuration', {
            'fields': ('event_type', 'is_required', 'time_offset_minutes', 'filter_enabled')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    """Admin for trading signals."""
    list_display = ['setup_type', 'instrument', 'trading_asset', 'direction', 'trigger_price', 'risk_status', 'status', 'created_at']
    list_filter = ['setup_type', 'direction', 'risk_status', 'status', 'session_phase', 'trading_asset']
    search_fields = ['instrument', 'ki_reasoning', 'gpt_reasoning']
    readonly_fields = ['id', 'created_at', 'updated_at', 'executed_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'trading_asset', 'instrument', 'setup_type', 'session_phase')
        }),
        ('Trade Setup', {
            'fields': ('direction', 'trigger_price', 'range_high', 'range_low')
        }),
        ('Position & Risk', {
            'fields': ('stop_loss', 'take_profit', 'position_size', 'risk_status', 'risk_allowed_size', 'risk_percentage')
        }),
        ('KI Evaluation', {
            'fields': ('ki_reasoning', 'gpt_confidence', 'gpt_reasoning', 'gpt_corrected_sl', 'gpt_corrected_tp', 'gpt_corrected_size'),
            'classes': ('collapse',)
        }),
        ('Risk Details', {
            'fields': ('risk_reasoning',),
            'classes': ('collapse',)
        }),
        ('Status & Timestamps', {
            'fields': ('status', 'created_at', 'updated_at', 'executed_at')
        }),
    )


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    """Admin for trades."""
    list_display = ['signal', 'trade_type', 'status', 'entry_price', 'exit_price', 'realized_pnl', 'opened_at']
    list_filter = ['trade_type', 'status']
    readonly_fields = ['id', 'opened_at', 'closed_at']
    date_hierarchy = 'opened_at'
    
    fieldsets = (
        ('Trade Info', {
            'fields': ('id', 'signal', 'trade_type', 'status')
        }),
        ('Execution', {
            'fields': ('entry_price', 'exit_price', 'stop_loss', 'take_profit', 'position_size')
        }),
        ('P&L', {
            'fields': ('realized_pnl',)
        }),
        ('Timestamps', {
            'fields': ('opened_at', 'closed_at')
        }),
    )


@admin.register(WorkerStatus)
class WorkerStatusAdmin(admin.ModelAdmin):
    """Admin for worker status."""
    list_display = ['phase', 'epic', 'bid_price', 'setup_count', 'last_run_at']
    readonly_fields = ['last_run_at', 'phase', 'epic', 'bid_price', 'ask_price', 'spread', 'setup_count', 'diagnostic_message', 'diagnostic_criteria', 'worker_interval']


@admin.register(AssetPriceStatus)
class AssetPriceStatusAdmin(admin.ModelAdmin):
    """Admin for asset price status."""
    list_display = ['asset', 'bid_price', 'ask_price', 'spread', 'updated_at']
    readonly_fields = ['asset', 'bid_price', 'ask_price', 'spread', 'updated_at']
    list_filter = ['asset']

