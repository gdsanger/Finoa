from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
import uuid


class TradingAsset(models.Model):
    """
    Represents a trading asset/market that Fiona can trade.
    
    Allows dynamic configuration of assets through the UI without code changes.
    Each asset has its own broker EPIC, strategy parameters, and active status.
    """
    
    STRATEGY_TYPES = [
        ('breakout_event', 'Breakout + Event'),
    ]
    
    ASSET_CATEGORIES = [
        ('commodity', 'Commodities'),
        ('index', 'Indices'),
        ('forex', 'Forex'),
        ('crypto', 'Crypto'),
        ('stock', 'Stocks'),
        ('other', 'Other'),
    ]
    
    # Basic identification
    name = models.CharField(
        max_length=100,
        help_text='Display name (e.g., "US Crude Oil", "Gold", "Nasdaq 100")'
    )
    symbol = models.CharField(
        max_length=50,
        help_text='Short symbol (e.g., "CL", "GOLD", "NAS100")'
    )
    epic = models.CharField(
        max_length=100,
        unique=True,
        help_text='Broker EPIC/Symbol for API calls (e.g., "CC.D.CL.UNC.IP")'
    )
    
    # Categorization
    category = models.CharField(
        max_length=20,
        choices=ASSET_CATEGORIES,
        default='commodity',
        help_text='Asset category for grouping'
    )
    
    # Strategy assignment
    strategy_type = models.CharField(
        max_length=50,
        choices=STRATEGY_TYPES,
        default='breakout_event',
        help_text='Strategy to use for this asset'
    )
    
    # Asset-specific trading parameters
    tick_size = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('0.01'),
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text='Minimum price movement (e.g., 0.01 for WTI)'
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this asset is actively traded by the worker'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'name']
        verbose_name = 'Trading Asset'
        verbose_name_plural = 'Trading Assets'
    
    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name} ({self.symbol})"
    
    def get_strategy_config(self):
        """
        Build a StrategyConfig object from this asset's configuration.
        
        Returns:
            StrategyConfig: Configuration object for the Strategy Engine.
        """
        from core.services.strategy.config import (
            StrategyConfig,
            BreakoutConfig,
            AsiaRangeConfig,
            LondonCoreConfig,
            UsCoreConfig,
            CandleQualityConfig,
            AdvancedFilterConfig,
            AtrConfig,
            EiaConfig,
        )
        
        # Get breakout config for this asset
        try:
            breakout_cfg = self.breakout_config
            
            # Asia Range
            asia_range = AsiaRangeConfig(
                start=breakout_cfg.asia_range_start,
                end=breakout_cfg.asia_range_end,
                min_range_ticks=breakout_cfg.asia_min_range_ticks,
                max_range_ticks=breakout_cfg.asia_max_range_ticks,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
            )
            
            # London Core (NEW)
            london_core = LondonCoreConfig(
                start=breakout_cfg.london_range_start,
                end=breakout_cfg.london_range_end,
                min_range_ticks=breakout_cfg.london_min_range_ticks,
                max_range_ticks=breakout_cfg.london_max_range_ticks,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
            )
            
            # US Core
            us_core = UsCoreConfig(
                pre_us_start=breakout_cfg.pre_us_start,
                pre_us_end=breakout_cfg.pre_us_end,
                us_core_trading_start=breakout_cfg.us_core_trading_start,
                us_core_trading_end=breakout_cfg.us_core_trading_end,
                us_core_trading_enabled=breakout_cfg.us_core_trading_enabled,
                min_range_ticks=breakout_cfg.us_min_range_ticks,
                max_range_ticks=breakout_cfg.us_max_range_ticks,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
            )
            
            # Candle Quality (NEW)
            candle_quality = CandleQualityConfig(
                min_wick_ratio=float(breakout_cfg.min_wick_ratio) if breakout_cfg.min_wick_ratio else None,
                max_wick_ratio=float(breakout_cfg.max_wick_ratio) if breakout_cfg.max_wick_ratio else None,
                min_candle_body_absolute=float(breakout_cfg.min_candle_body_absolute) if breakout_cfg.min_candle_body_absolute else None,
                max_spread_ticks=breakout_cfg.max_spread_ticks,
                filter_doji_breakouts=breakout_cfg.filter_doji_breakouts,
            )
            
            # Advanced Filter (NEW)
            advanced_filter = AdvancedFilterConfig(
                consecutive_candle_filter=breakout_cfg.consecutive_candle_filter,
                momentum_threshold=float(breakout_cfg.momentum_threshold) if breakout_cfg.momentum_threshold else None,
                volatility_throttle_min_atr=float(breakout_cfg.volatility_throttle_min_atr) if breakout_cfg.volatility_throttle_min_atr else None,
                session_volatility_cap=float(breakout_cfg.session_volatility_cap) if breakout_cfg.session_volatility_cap else None,
            )
            
            # ATR Config (Extended)
            atr = AtrConfig(
                require_atr_minimum=breakout_cfg.require_atr_minimum,
                min_atr_value=float(breakout_cfg.min_atr_value) if breakout_cfg.min_atr_value else None,
                max_atr_value=float(breakout_cfg.max_atr_value) if breakout_cfg.max_atr_value else None,
            )
            
            # Breakout Config with all components
            breakout = BreakoutConfig(
                asia_range=asia_range,
                london_core=london_core,
                us_core=us_core,
                candle_quality=candle_quality,
                advanced_filter=advanced_filter,
                atr=atr,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
                max_breakout_body_fraction=float(breakout_cfg.max_breakout_body_fraction) if breakout_cfg.max_breakout_body_fraction else None,
                min_breakout_distance_ticks=breakout_cfg.min_breakout_distance_ticks,
                min_volume_spike=float(breakout_cfg.min_volume_spike) if breakout_cfg.min_volume_spike else None,
            )
            
            # EIA Config (NEW - from breakout_cfg)
            eia = EiaConfig(
                min_body_fraction=float(breakout_cfg.eia_min_body_fraction),
                min_impulse_atr=float(breakout_cfg.eia_min_impulse_atr) if breakout_cfg.eia_min_impulse_atr else None,
                impulse_range_high=float(breakout_cfg.eia_impulse_range_high) if breakout_cfg.eia_impulse_range_high else None,
                impulse_range_low=float(breakout_cfg.eia_impulse_range_low) if breakout_cfg.eia_impulse_range_low else None,
                required_impulse_strength=float(breakout_cfg.eia_required_impulse_strength),
                reversion_window_min_sec=breakout_cfg.eia_reversion_window_min_sec,
                reversion_window_max_sec=breakout_cfg.eia_reversion_window_max_sec,
                max_impulse_duration_min=breakout_cfg.eia_max_impulse_duration_min,
            )
            
        except AssetBreakoutConfig.DoesNotExist:
            # Use defaults if no breakout config exists
            breakout = BreakoutConfig()
            eia = EiaConfig()
        
        return StrategyConfig(
            breakout=breakout,
            eia=eia,
            default_epic=self.epic,
            tick_size=float(self.tick_size),
        )


class AssetBreakoutConfig(models.Model):
    """
    Breakout strategy configuration specific to an asset.
    
    Defines range formation parameters, breakout candle requirements,
    and timing windows for the breakout strategy.
    
    Extended to support:
    - London Core Range
    - EIA Pre/Post parameters
    - Candle Quality filters
    - Advanced filters (Momentum, Volatility)
    - ATR extensions
    - Wick ratio filters
    """
    
    asset = models.OneToOneField(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='breakout_config',
        help_text='Asset this configuration belongs to'
    )
    
    # =========================================================================
    # Asia Range Configuration
    # =========================================================================
    asia_range_start = models.CharField(
        max_length=5,
        default='00:00',
        help_text='Asia range start time (UTC, HH:MM format)'
    )
    asia_range_end = models.CharField(
        max_length=5,
        default='08:00',
        help_text='Asia range end time (UTC, HH:MM format)'
    )
    asia_min_range_ticks = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1)],
        help_text='Minimum range height in ticks for valid Asia range'
    )
    asia_max_range_ticks = models.PositiveIntegerField(
        default=200,
        validators=[MinValueValidator(1)],
        help_text='Maximum range height in ticks for valid Asia range'
    )
    
    # =========================================================================
    # London Core Range Configuration (NEW)
    # =========================================================================
    london_range_start = models.CharField(
        max_length=5,
        default='08:00',
        help_text='London Core range start time (UTC, HH:MM format)'
    )
    london_range_end = models.CharField(
        max_length=5,
        default='12:00',
        help_text='London Core range end time (UTC, HH:MM format)'
    )
    london_min_range_ticks = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1)],
        help_text='Minimum range height in ticks for valid London Core range'
    )
    london_max_range_ticks = models.PositiveIntegerField(
        default=200,
        validators=[MinValueValidator(1)],
        help_text='Maximum range height in ticks for valid London Core range'
    )
    
    # =========================================================================
    # Pre-US Range Configuration (Range Formation Only)
    # =========================================================================
    pre_us_start = models.CharField(
        max_length=5,
        default='13:00',
        help_text='Pre-US range start time (UTC, HH:MM format)'
    )
    pre_us_end = models.CharField(
        max_length=5,
        default='15:00',
        help_text='Pre-US range end time (UTC, HH:MM format)'
    )
    us_min_range_ticks = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1)],
        help_text='Minimum range height in ticks for valid Pre-US range'
    )
    us_max_range_ticks = models.PositiveIntegerField(
        default=200,
        validators=[MinValueValidator(1)],
        help_text='Maximum range height in ticks for valid Pre-US range'
    )
    
    # =========================================================================
    # US Core Trading Session Configuration (Breakouts Allowed)
    # =========================================================================
    us_core_trading_start = models.CharField(
        max_length=5,
        default='15:00',
        help_text='US Core Trading session start time (UTC, HH:MM format)'
    )
    us_core_trading_end = models.CharField(
        max_length=5,
        default='22:00',
        help_text='US Core Trading session end time (UTC, HH:MM format)'
    )
    us_core_trading_enabled = models.BooleanField(
        default=True,
        help_text='Whether breakouts are allowed during US Core Trading session'
    )
    
    # =========================================================================
    # EIA Pre/Post Configuration (NEW)
    # =========================================================================
    eia_min_body_fraction = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.60'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text='Minimum body size for EIA impulse candles (0.0-1.0)'
    )
    eia_min_impulse_atr = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Minimum ATR multiplier for EIA impulse moves'
    )
    eia_impulse_range_high = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Maximum price movement for impulse range high'
    )
    eia_impulse_range_low = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Minimum price movement for impulse range low'
    )
    eia_required_impulse_strength = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.50'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text='Required impulse strength (0.0-1.0)'
    )
    eia_reversion_window_min_sec = models.PositiveIntegerField(
        default=30,
        help_text='Minimum seconds for reversion window'
    )
    eia_reversion_window_max_sec = models.PositiveIntegerField(
        default=300,
        help_text='Maximum seconds for reversion window (5 minutes default)'
    )
    eia_max_impulse_duration_min = models.PositiveIntegerField(
        default=5,
        help_text='Maximum impulse duration in minutes after event'
    )
    
    # =========================================================================
    # Breakout Candle Requirements
    # =========================================================================
    min_breakout_body_fraction = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.50'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text='Minimum candle body size as fraction of range height (0.0-1.0)'
    )
    max_breakout_body_fraction = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text='Maximum candle body size as fraction of range height (0.0-1.0)'
    )
    min_breakout_distance_ticks = models.PositiveIntegerField(
        default=1,
        help_text='Minimum distance from range in ticks for valid breakout'
    )
    
    # =========================================================================
    # Candle Quality Filters (NEW)
    # =========================================================================
    min_wick_ratio = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Minimum body-to-wick ratio for quality candles'
    )
    max_wick_ratio = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Maximum body-to-wick ratio for quality candles'
    )
    min_candle_body_absolute = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Minimum absolute candle body size (e.g., 0.05 USD)'
    )
    max_spread_ticks = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Maximum allowed spread in ticks'
    )
    filter_doji_breakouts = models.BooleanField(
        default=True,
        help_text='Filter out doji candle breakouts (very small body)'
    )
    
    # =========================================================================
    # Trend and Structure Filters (NEW)
    # =========================================================================
    consecutive_candle_filter = models.PositiveIntegerField(
        default=0,
        help_text='Number of consecutive candles required in breakout direction (0=disabled)'
    )
    momentum_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Minimum momentum threshold for valid setups'
    )
    volatility_throttle_min_atr = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Only trade when ATR > this value (volatility throttle)'
    )
    session_volatility_cap = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Only trade breakouts when session range < this value'
    )
    
    # =========================================================================
    # ATR Configuration (Extended)
    # =========================================================================
    require_atr_minimum = models.BooleanField(
        default=False,
        help_text='Whether to require minimum ATR for valid setups'
    )
    min_atr_value = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Minimum ATR value if required'
    )
    max_atr_value = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Maximum ATR value (for too volatile days)'
    )
    
    # =========================================================================
    # Volume Configuration (NEW - for future use with stocks/CFDs)
    # =========================================================================
    min_volume_spike = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Minimum volume spike multiplier for breakouts (e.g., 1.5 = 150% of avg)'
    )
    
    # =========================================================================
    # Timestamps
    # =========================================================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Asset Breakout Config'
        verbose_name_plural = 'Asset Breakout Configs'
    
    def __str__(self):
        return f"Breakout Config for {self.asset.name}"


class AssetEventConfig(models.Model):
    """
    Event/News context configuration for a specific asset and session phase.
    
    Allows defining which event types are relevant for each trading phase
    of an asset (e.g., EIA for WTI during US session, FOMC for indices, etc.)
    """
    
    SESSION_PHASES = [
        ('ASIA_RANGE', 'Asia Range'),
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
        ('US_CORE', 'US Core'),  # Deprecated, kept for backwards compatibility
        ('EIA_PRE', 'EIA Pre'),
        ('EIA_POST', 'EIA Post'),
    ]
    
    EVENT_TYPES = [
        ('NONE', 'No Event Required'),
        ('EIA', 'EIA Report'),
        ('FOMC', 'FOMC Meeting'),
        ('NFP', 'Non-Farm Payrolls'),
        ('CPI', 'Consumer Price Index'),
        ('GDP', 'GDP Report'),
        ('US_OPEN', 'US Market Open'),
        ('EU_OPEN', 'EU Market Open'),
        ('CUSTOM', 'Custom Event'),
    ]
    
    asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='event_configs',
        help_text='Asset this configuration belongs to'
    )
    
    phase = models.CharField(
        max_length=20,
        choices=SESSION_PHASES,
        help_text='Session phase this configuration applies to'
    )
    
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPES,
        default='NONE',
        help_text='Type of event relevant for this phase'
    )
    
    is_required = models.BooleanField(
        default=False,
        help_text='Whether the event context is required for setups in this phase'
    )
    
    # Optional time offset from standard phase times
    time_offset_minutes = models.IntegerField(
        default=0,
        help_text='Time offset in minutes from standard phase timing'
    )
    
    # Additional filter settings
    filter_enabled = models.BooleanField(
        default=True,
        help_text='Whether this event filter is active'
    )
    
    notes = models.TextField(
        blank=True,
        help_text='Optional notes about this event configuration'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['asset', 'phase']
        verbose_name = 'Asset Event Config'
        verbose_name_plural = 'Asset Event Configs'
        unique_together = ['asset', 'phase']
    
    def __str__(self):
        return f"{self.asset.name} - {self.get_phase_display()} ({self.get_event_type_display()})"


class Signal(models.Model):
    """
    Represents a trading signal (SetupCandidate) with KI evaluation and Risk assessment.
    """
    
    # Setup Types
    SETUP_TYPES = [
        ('BREAKOUT', 'Breakout'),
        ('EIA_REVERSION', 'EIA-Reversion'),
        ('EIA_TRENDDAY', 'EIA-TrendDay'),
    ]
    
    # Session Phases
    SESSION_PHASES = [
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
        ('US_CORE', 'US Core'),  # Deprecated, kept for backwards compatibility
        ('EIA_PRE', 'EIA Pre'),
        ('EIA_POST', 'EIA Post'),
        ('ASIAN', 'Asian Session'),
    ]
    
    # Direction
    DIRECTIONS = [
        ('LONG', 'Long'),
        ('SHORT', 'Short'),
    ]
    
    # Risk Status
    RISK_STATUS = [
        ('GREEN', 'Erlaubt'),
        ('YELLOW', 'Riskant'),
        ('RED', 'Verboten'),
    ]
    
    # Signal Status
    SIGNAL_STATUS = [
        ('ACTIVE', 'Aktiv'),
        ('EXECUTED', 'Ausgeführt'),
        ('SHADOW', 'Shadow'),
        ('REJECTED', 'Verworfen'),
    ]
    
    # Basic Info
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    setup_type = models.CharField(max_length=50, choices=SETUP_TYPES)
    session_phase = models.CharField(max_length=50, choices=SESSION_PHASES)
    instrument = models.CharField(max_length=50, default='CL')  # e.g., CL for Crude Oil
    
    # Reference to TradingAsset (optional for backwards compatibility)
    trading_asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signals',
        help_text='Trading asset this signal belongs to'
    )
    
    # Range Info
    range_high = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    range_low = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    trigger_price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    
    # KI Evaluation
    direction = models.CharField(max_length=10, choices=DIRECTIONS)
    stop_loss = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    position_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ki_reasoning = models.TextField(blank=True, help_text='Kurze KI-Begründung')
    
    # GPT Reflection
    gpt_confidence = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='GPT Confidence Score (0-100%)',
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))]
    )
    gpt_reasoning = models.TextField(blank=True, help_text='Ausführliche GPT-Begründung')
    gpt_corrected_sl = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    gpt_corrected_tp = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    gpt_corrected_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Risk Engine
    risk_status = models.CharField(max_length=10, choices=RISK_STATUS, default='GREEN')
    risk_allowed_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    risk_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        null=True, 
        blank=True,
        help_text='Risiko % vom Konto'
    )
    risk_reasoning = models.TextField(blank=True, help_text='Risk Engine Begründung')
    
    # Status
    status = models.CharField(max_length=20, choices=SIGNAL_STATUS, default='ACTIVE')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Signal'
        verbose_name_plural = 'Signals'
    
    def __str__(self):
        return f"{self.setup_type} - {self.direction} @ {self.trigger_price} ({self.session_phase})"
    
    @property
    def can_execute_live(self):
        """Check if live trade is allowed based on risk status."""
        return self.risk_status in ['GREEN', 'YELLOW'] and self.status == 'ACTIVE'
    
    @property
    def is_active(self):
        """Check if signal is still active."""
        return self.status == 'ACTIVE'


class Trade(models.Model):
    """
    Represents an executed or shadow trade based on a signal.
    """
    
    TRADE_TYPES = [
        ('LIVE', 'Live Trade'),
        ('SHADOW', 'Shadow Trade'),
    ]
    
    TRADE_STATUS = [
        ('OPEN', 'Offen'),
        ('CLOSED', 'Geschlossen'),
        ('CANCELLED', 'Abgebrochen'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signal = models.ForeignKey(Signal, on_delete=models.CASCADE, related_name='trades')
    
    trade_type = models.CharField(max_length=10, choices=TRADE_TYPES)
    status = models.CharField(max_length=20, choices=TRADE_STATUS, default='OPEN')
    
    # Execution details
    entry_price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    exit_price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    stop_loss = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    position_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # P&L
    realized_pnl = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Timestamps
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-opened_at']
        verbose_name = 'Trade'
        verbose_name_plural = 'Trades'
    
    def __str__(self):
        return f"{self.trade_type} - {self.signal.direction} ({self.status})"


class WorkerStatus(models.Model):
    """
    Stores the current status of the Fiona trading worker.
    
    Only one record is maintained (singleton pattern) representing
    the latest worker state.
    """
    
    # Session Phases (same as Strategy Engine phases)
    SESSION_PHASES = [
        ('ASIA_RANGE', 'Asia Range'),
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
        ('US_CORE', 'US Core'),  # Deprecated, kept for backwards compatibility
        ('EIA_PRE', 'EIA Pre'),
        ('EIA_POST', 'EIA Post'),
        ('FRIDAY_LATE', 'Friday Late'),
        ('OTHER', 'Other'),
    ]
    
    # Worker loop timestamp
    last_run_at = models.DateTimeField(
        help_text='Timestamp of the last worker loop execution'
    )
    
    # Current session phase
    phase = models.CharField(
        max_length=30,  # Increased to fit US_CORE_TRADING
        choices=SESSION_PHASES,
        help_text='Current session phase'
    )
    
    # Instrument/Epic being monitored
    epic = models.CharField(
        max_length=100,
        help_text='Current instrument EPIC (e.g., CC.D.CL.UNC.IP)'
    )
    
    # Price information
    bid_price = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Last bid price'
    )
    ask_price = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Last ask price'
    )
    spread = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Current spread'
    )
    
    # Strategy Engine results
    setup_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of setups found in last run'
    )
    
    # Diagnostic message explaining why no setups were found
    diagnostic_message = models.TextField(
        blank=True,
        help_text='Human-readable diagnostic message (e.g., why no setups found)'
    )
    
    # Detailed diagnostic criteria list (JSON structure)
    # Format: [{"name": "Asia Range valid", "passed": true, "detail": "Range: 74.5 - 75.5"}, ...]
    diagnostic_criteria = models.JSONField(
        default=list,
        blank=True,
        help_text='List of diagnostic criteria with pass/fail status (JSON)'
    )
    
    # Worker configuration
    worker_interval = models.PositiveIntegerField(
        default=60,
        help_text='Expected interval between worker loops in seconds'
    )
    
    class Meta:
        verbose_name = 'Worker Status'
        verbose_name_plural = 'Worker Status'
    
    def __str__(self):
        return f"Worker Status - {self.phase} @ {self.last_run_at}"
    
    @classmethod
    def get_current(cls):
        """Get the current (most recent) worker status, or None if not available."""
        return cls.objects.order_by('-last_run_at').first()
    
    @classmethod
    def update_status(
        cls,
        last_run_at,
        phase,
        epic,
        setup_count=0,
        bid_price=None,
        ask_price=None,
        spread=None,
        diagnostic_message='',
        diagnostic_criteria=None,
        worker_interval=60
    ):
        """
        Update or create the worker status record.
        
        Uses update_or_create to maintain a single status record.
        
        Args:
            diagnostic_criteria: List of dicts with keys 'name', 'passed', 'detail'.
                Example: [{"name": "Asia Range valid", "passed": True, "detail": "75.5 - 74.5"}]
        """
        # Delete all existing records and create a new one
        # This ensures we only have one record (singleton)
        cls.objects.all().delete()
        
        return cls.objects.create(
            last_run_at=last_run_at,
            phase=phase,
            epic=epic,
            setup_count=setup_count,
            bid_price=bid_price,
            ask_price=ask_price,
            spread=spread,
            diagnostic_message=diagnostic_message,
            diagnostic_criteria=diagnostic_criteria or [],
            worker_interval=worker_interval,
        )


class BreakoutRange(models.Model):
    """
    Persistent storage for breakout range snapshots per asset and per phase.
    
    Allows diagnostics data to survive worker restarts and provides historical
    range data for analysis.
    
    Each record captures a range snapshot at the end of a range-building phase
    (Asia Range, London Core, Pre-US Range). US Core Trading references
    previous ranges but doesn't build its own.
    """
    
    # Phase types that can have range data
    PHASE_CHOICES = [
        ('ASIA_RANGE', 'Asia Range'),
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
    ]
    
    # Relationship to asset
    asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='breakout_ranges',
        help_text='Asset this range belongs to'
    )
    
    # Phase identification
    phase = models.CharField(
        max_length=20,
        choices=PHASE_CHOICES,
        help_text='Session phase when this range was recorded'
    )
    
    # Time window
    start_time = models.DateTimeField(
        help_text='Start time of the range period'
    )
    end_time = models.DateTimeField(
        help_text='End time of the range period'
    )
    
    # Range data
    high = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        help_text='Highest price during the range period'
    )
    low = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        help_text='Lowest price during the range period'
    )
    height_ticks = models.PositiveIntegerField(
        default=0,
        help_text='Range height in ticks'
    )
    height_points = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
        help_text='Range height in price points (high - low)'
    )
    
    # Candle/Price data
    candle_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of candles captured during the range period'
    )
    
    # ATR at time of range capture
    atr = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='ATR value at the time of range capture'
    )
    
    # Validity flags (stored as JSON for flexibility)
    valid_flags = models.JSONField(
        default=dict,
        blank=True,
        help_text='Range validity flags (e.g., incomplete_range, too_small, too_large, body_fraction_fail, atr_fail)'
    )
    
    # Is this range considered valid for trading?
    is_valid = models.BooleanField(
        default=True,
        help_text='Whether this range is valid for breakout trading'
    )
    
    # Reference to the reference range used (for US Core Trading)
    reference_range = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dependent_ranges',
        help_text='Reference range used for trading (for US Core Trading phase)'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-end_time']
        verbose_name = 'Breakout Range'
        verbose_name_plural = 'Breakout Ranges'
        indexes = [
            models.Index(fields=['asset', 'phase', '-end_time']),
            models.Index(fields=['-end_time']),
        ]
    
    def __str__(self):
        return f"{self.asset.symbol} - {self.phase} ({self.end_time.strftime('%Y-%m-%d %H:%M')})"
    
    @classmethod
    def get_latest_for_asset_phase(cls, asset, phase):
        """
        Get the most recent range for an asset and phase.
        
        Args:
            asset: TradingAsset instance or asset ID
            phase: Phase string (e.g., 'ASIA_RANGE')
            
        Returns:
            BreakoutRange instance or None
        """
        if isinstance(asset, int):
            return cls.objects.filter(asset_id=asset, phase=phase).order_by('-end_time').first()
        return cls.objects.filter(asset=asset, phase=phase).order_by('-end_time').first()
    
    @classmethod
    def get_latest_for_asset(cls, asset):
        """
        Get the most recent ranges for an asset, one per phase.
        
        Args:
            asset: TradingAsset instance or asset ID
            
        Returns:
            Dict mapping phase to BreakoutRange instance
        """
        result = {}
        for phase_code, _ in cls.PHASE_CHOICES:
            if isinstance(asset, int):
                latest = cls.objects.filter(asset_id=asset, phase=phase_code).order_by('-end_time').first()
            else:
                latest = cls.objects.filter(asset=asset, phase=phase_code).order_by('-end_time').first()
            if latest:
                result[phase_code] = latest
        return result
    
    @classmethod
    def save_range_snapshot(
        cls,
        asset,
        phase,
        start_time,
        end_time,
        high,
        low,
        tick_size=0.01,
        candle_count=0,
        atr=None,
        valid_flags=None,
        is_valid=True,
        reference_range=None,
    ):
        """
        Save a new range snapshot.
        
        Args:
            asset: TradingAsset instance
            phase: Phase string (e.g., 'ASIA_RANGE')
            start_time: Range start time (datetime)
            end_time: Range end time (datetime)
            high: Range high price
            low: Range low price
            tick_size: Tick size for calculating ticks
            candle_count: Number of candles in the range
            atr: ATR value at time of capture
            valid_flags: Dict of validity flags
            is_valid: Whether the range is valid for trading
            reference_range: Optional reference range (for US Core Trading)
            
        Returns:
            BreakoutRange instance
        """
        from decimal import Decimal, ROUND_HALF_UP
        
        height_points = Decimal(str(high)) - Decimal(str(low))
        tick_size_decimal = Decimal(str(tick_size)) if tick_size > 0 else Decimal('0.01')
        # Use proper rounding instead of truncation for accurate tick calculations
        height_ticks = int((height_points / tick_size_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        
        return cls.objects.create(
            asset=asset,
            phase=phase,
            start_time=start_time,
            end_time=end_time,
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            height_ticks=height_ticks,
            height_points=height_points,
            candle_count=candle_count,
            atr=Decimal(str(atr)) if atr is not None else None,
            valid_flags=valid_flags or {},
            is_valid=is_valid,
            reference_range=reference_range,
        )
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'asset_symbol': self.asset.symbol if self.asset else None,
            'phase': self.phase,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'high': str(self.high),
            'low': str(self.low),
            'height_ticks': self.height_ticks,
            'height_points': str(self.height_points),
            'candle_count': self.candle_count,
            'atr': str(self.atr) if self.atr else None,
            'valid_flags': self.valid_flags,
            'is_valid': self.is_valid,
            'reference_range_id': self.reference_range_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
