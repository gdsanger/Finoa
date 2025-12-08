import logging

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import uuid


# =============================================================================
# Reason Codes for Diagnostics
# =============================================================================

logger = logging.getLogger(__name__)


class ReasonCode:
    """
    Structured reason codes for setup rejection tracking.
    
    These codes are used by the Strategy and Risk engines to report
    why setups were rejected, enabling diagnostics and debugging.
    """
    
    # Strategy-level rejection reasons
    STRAT_NO_RANGE = 'STRAT_NO_RANGE'
    STRAT_RANGE_INCOMPLETE = 'STRAT_RANGE_INCOMPLETE'
    STRAT_RANGE_TOO_SMALL = 'STRAT_RANGE_TOO_SMALL'
    STRAT_RANGE_TOO_LARGE = 'STRAT_RANGE_TOO_LARGE'
    STRAT_BODY_TOO_SMALL = 'STRAT_BODY_TOO_SMALL'
    STRAT_ATR_TOO_LOW = 'STRAT_ATR_TOO_LOW'
    STRAT_ATR_TOO_HIGH = 'STRAT_ATR_TOO_HIGH'
    STRAT_NO_BREAKOUT = 'STRAT_NO_BREAKOUT'
    STRAT_WRONG_DIRECTION = 'STRAT_WRONG_DIRECTION'
    STRAT_DOJI_FILTERED = 'STRAT_DOJI_FILTERED'
    STRAT_WICK_RATIO_INVALID = 'STRAT_WICK_RATIO_INVALID'
    STRAT_CONSECUTIVE_CANDLE_FAIL = 'STRAT_CONSECUTIVE_CANDLE_FAIL'
    STRAT_MOMENTUM_TOO_LOW = 'STRAT_MOMENTUM_TOO_LOW'
    STRAT_VOLATILITY_CAP_EXCEEDED = 'STRAT_VOLATILITY_CAP_EXCEEDED'
    STRAT_EVENT_MISSING = 'STRAT_EVENT_MISSING'
    STRAT_NO_CANDLE_DATA = 'STRAT_NO_CANDLE_DATA'
    STRAT_PHASE_NOT_TRADEABLE = 'STRAT_PHASE_NOT_TRADEABLE'
    STRAT_EIA_NO_IMPULSE = 'STRAT_EIA_NO_IMPULSE'
    STRAT_EIA_NO_REVERSION = 'STRAT_EIA_NO_REVERSION'
    STRAT_EIA_NO_TRENDDAY = 'STRAT_EIA_NO_TRENDDAY'
    
    # Risk-level rejection reasons
    RISK_SPREAD_TOO_WIDE = 'RISK_SPREAD_TOO_WIDE'
    RISK_ATR_OUT_OF_BOUNDS = 'RISK_ATR_OUT_OF_BOUNDS'
    RISK_MAX_DAILY_LOSS_REACHED = 'RISK_MAX_DAILY_LOSS_REACHED'
    RISK_MAX_WEEKLY_LOSS_REACHED = 'RISK_MAX_WEEKLY_LOSS_REACHED'
    RISK_MAX_ASSET_LOSS_REACHED = 'RISK_MAX_ASSET_LOSS_REACHED'
    RISK_SESSION_NOT_TRADEABLE = 'RISK_SESSION_NOT_TRADEABLE'
    RISK_EIA_WINDOW_BLOCKED = 'RISK_EIA_WINDOW_BLOCKED'
    RISK_FRIDAY_LATE = 'RISK_FRIDAY_LATE'
    RISK_WEEKEND = 'RISK_WEEKEND'
    RISK_MAX_POSITIONS_REACHED = 'RISK_MAX_POSITIONS_REACHED'
    RISK_COUNTERTREND = 'RISK_COUNTERTREND'
    RISK_SL_MISSING = 'RISK_SL_MISSING'
    RISK_SL_TOO_TIGHT = 'RISK_SL_TOO_TIGHT'
    RISK_POSITION_TOO_LARGE = 'RISK_POSITION_TOO_LARGE'
    
    # Human-readable descriptions
    DESCRIPTIONS = {
        STRAT_NO_RANGE: 'No range data available',
        STRAT_RANGE_INCOMPLETE: 'Range formation incomplete',
        STRAT_RANGE_TOO_SMALL: 'Range too small (below min ticks)',
        STRAT_RANGE_TOO_LARGE: 'Range too large (above max ticks)',
        STRAT_BODY_TOO_SMALL: 'Candle body too small',
        STRAT_ATR_TOO_LOW: 'ATR below minimum threshold',
        STRAT_ATR_TOO_HIGH: 'ATR above maximum threshold',
        STRAT_NO_BREAKOUT: 'Price within range (no breakout)',
        STRAT_WRONG_DIRECTION: 'Candle direction mismatch',
        STRAT_DOJI_FILTERED: 'Doji candle filtered out',
        STRAT_WICK_RATIO_INVALID: 'Wick ratio outside valid range',
        STRAT_CONSECUTIVE_CANDLE_FAIL: 'Consecutive candle filter failed',
        STRAT_MOMENTUM_TOO_LOW: 'Momentum below threshold',
        STRAT_VOLATILITY_CAP_EXCEEDED: 'Session volatility cap exceeded',
        STRAT_EVENT_MISSING: 'Required event context missing',
        STRAT_NO_CANDLE_DATA: 'No candle data available',
        STRAT_PHASE_NOT_TRADEABLE: 'Current phase not tradeable',
        STRAT_EIA_NO_IMPULSE: 'No clear EIA impulse detected',
        STRAT_EIA_NO_REVERSION: 'No EIA reversion pattern',
        STRAT_EIA_NO_TRENDDAY: 'No EIA trend day pattern',
        RISK_SPREAD_TOO_WIDE: 'Spread too wide',
        RISK_ATR_OUT_OF_BOUNDS: 'ATR outside allowed range',
        RISK_MAX_DAILY_LOSS_REACHED: 'Daily loss limit reached',
        RISK_MAX_WEEKLY_LOSS_REACHED: 'Weekly loss limit reached',
        RISK_MAX_ASSET_LOSS_REACHED: 'Asset loss limit reached',
        RISK_SESSION_NOT_TRADEABLE: 'Session not tradeable',
        RISK_EIA_WINDOW_BLOCKED: 'Within EIA blackout window',
        RISK_FRIDAY_LATE: 'Friday evening trading blocked',
        RISK_WEEKEND: 'Weekend trading not allowed',
        RISK_MAX_POSITIONS_REACHED: 'Maximum positions reached',
        RISK_COUNTERTREND: 'Counter-trend trade blocked',
        RISK_SL_MISSING: 'Stop loss missing',
        RISK_SL_TOO_TIGHT: 'Stop loss too tight',
        RISK_POSITION_TOO_LARGE: 'Position size too large',
    }
    
    @classmethod
    def get_description(cls, code: str) -> str:
        """Get human-readable description for a reason code."""
        return cls.DESCRIPTIONS.get(code, code)
    
    @classmethod
    def is_strategy_reason(cls, code: str) -> bool:
        """Check if a reason code is from the strategy engine."""
        return code.startswith('STRAT_')
    
    @classmethod
    def is_risk_reason(cls, code: str) -> bool:
        """Check if a reason code is from the risk engine."""
        return code.startswith('RISK_')


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
    
    # Trading Mode choices
    TRADING_MODES = [
        ('STRICT', 'Strict (Normal Trading)'),
        ('DIAGNOSTIC', 'Diagnostic (Shadow Only, Relaxed Filters)'),
    ]
    
    # Broker choices
    class BrokerKind(models.TextChoices):
        IG = "IG", "IG"
        MEXC = "MEXC", "MEXC"
        KRAKEN = "KRAKEN", "Kraken"
    
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
   
    # Broker configuration
    broker = models.CharField(
        max_length=16,
        choices=BrokerKind.choices,
        default=BrokerKind.IG,
        help_text='Broker to use for trading this asset (IG, MEXC, or Kraken)'
    )
    broker_symbol = models.CharField(
        max_length=64,
        blank=True,
        help_text='Broker-specific symbol (e.g., IG-EPIC, MEXC-Symbol, or Kraken-Symbol) if different from epic field'
    )
    quote_currency = models.CharField(
        max_length=10,
        default='USD',
        help_text='Quote currency for this asset (e.g., USD, EUR, USDT)'
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
    
    # Trading Mode
    trading_mode = models.CharField(
        max_length=20,
        choices=TRADING_MODES,
        default='STRICT',
        help_text='Trading mode: STRICT for normal trading, DIAGNOSTIC for shadow-only with relaxed filters'
    )
    
    # Asset-specific trading parameters
    tick_size = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('0.01'),
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text='Minimum price movement (e.g., 0.01 for WTI)'
    )
    min_size = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        default=Decimal('1'),
        help_text='Minimum order/position size'
    )
    max_size = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        null=True,
        blank=True,
        help_text='Maximum order/position size'
    )
    lot_size = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        null=True,
        blank=True,
        help_text='Lot size for this asset'
    )
    
    # Crypto-specific flag
    is_crypto = models.BooleanField(
        default=False,
        help_text='Whether this is a cryptocurrency asset'
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
        mode_indicator = ' [DIAG]' if self.trading_mode == 'DIAGNOSTIC' else ''
        return f"{status} {self.name} ({self.symbol}){mode_indicator}"
    
    @property
    def is_diagnostic_mode(self):
        """Check if asset is in diagnostic mode."""
        return self.trading_mode == 'DIAGNOSTIC'
    
    @property
    def effective_broker_symbol(self):
        """
        Get the effective broker symbol.
        
        Returns broker_symbol if set, otherwise falls back to epic.
        """
        return self.broker_symbol if self.broker_symbol else self.epic
    
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
                max_candle_distance_ticks=breakout_cfg.max_candle_distance_ticks,
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
    max_candle_distance_ticks = models.PositiveIntegerField(
        default=10,
        help_text='Maximum distance of candle (low for LONG, high for SHORT) from range boundary in ticks'
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
    
    # Broker order details
    broker_order_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Broker-specific order/deal ID from place_order() response'
    )
    broker_status = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Order status from broker (e.g., OPEN, PENDING, REJECTED)'
    )
    broker_error_message = models.TextField(
        null=True,
        blank=True,
        help_text='Error message from broker if order failed'
    )
    
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


class AssetPriceStatus(models.Model):
    """
    Stores the current price status for each trading asset.
    
    One record per asset, updated by the worker on each cycle.
    This allows multi-asset price tracking for the Price vs Range panel.
    """
    
    # Relationship to asset (one-to-one)
    asset = models.OneToOneField(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='price_status',
        help_text='Asset this price status belongs to'
    )
    
    # Price information
    bid_price = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Current bid price'
    )
    ask_price = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Current ask price'
    )
    spread = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Current spread'
    )

    # Last strategy status message for UI display
    last_strategy_status = models.TextField(
        blank=True,
        default='',
        help_text='Latest strategy engine status message for this asset'
    )
    
    # Timestamp
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text='Last update timestamp'
    )
    
    class Meta:
        verbose_name = 'Asset Price Status'
        verbose_name_plural = 'Asset Price Statuses'
    
    def __str__(self):
        return f"{self.asset.symbol}: {self.bid_price}/{self.ask_price}"
    
    @classmethod
    def update_price(
        cls,
        asset,
        bid_price=None,
        ask_price=None,
        spread=None,
        status_message: str | None = None,
    ):
        """
        Update or create the price status for an asset.
        
        Args:
            asset: TradingAsset instance or asset ID
            bid_price: Current bid price
            ask_price: Current ask price
            spread: Current spread
            
        Returns:
            AssetPriceStatus instance
        """
        if isinstance(asset, int):
            asset_id = asset
        else:
            asset_id = asset.id
        
        price_status, created = cls.objects.update_or_create(
            asset_id=asset_id,
            defaults={
                'bid_price': Decimal(str(bid_price)) if bid_price is not None else None,
                'ask_price': Decimal(str(ask_price)) if ask_price is not None else None,
                'spread': Decimal(str(spread)) if spread is not None else None,
                'last_strategy_status': status_message or '',
            }
        )
        return price_status
    
    @classmethod
    def get_for_asset(cls, asset):
        """
        Get the price status for an asset.
        
        Args:
            asset: TradingAsset instance or asset ID
            
        Returns:
            AssetPriceStatus instance or None
        """
        if isinstance(asset, int):
            return cls.objects.filter(asset_id=asset).first()
        return cls.objects.filter(asset=asset).first()


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
    manual_high = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Optional manual override for the range high'
    )
    manual_low = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Optional manual override for the range low'
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

    # Manual adjustments
    last_adjusted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='adjusted_breakout_ranges',
        help_text='User who last adjusted the manual high/low'
    )
    last_adjusted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of the last manual adjustment'
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

    @property
    def effective_high(self):
        """Return the manual high if set, otherwise the computed high."""
        return self.manual_high if self.manual_high is not None else self.high

    @property
    def effective_low(self):
        """Return the manual low if set, otherwise the computed low."""
        return self.manual_low if self.manual_low is not None else self.low
    
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
            'manual_high': str(self.manual_high) if self.manual_high is not None else None,
            'manual_low': str(self.manual_low) if self.manual_low is not None else None,
            'effective_high': str(self.effective_high) if self.effective_high is not None else None,
            'effective_low': str(self.effective_low) if self.effective_low is not None else None,
            'height_ticks': self.height_ticks,
            'height_points': str(self.height_points),
            'candle_count': self.candle_count,
            'atr': str(self.atr) if self.atr else None,
            'valid_flags': self.valid_flags,
            'is_valid': self.is_valid,
            'reference_range_id': self.reference_range_id,
            'last_adjusted_by': self.last_adjusted_by.username if self.last_adjusted_by else None,
            'last_adjusted_at': self.last_adjusted_at.isoformat() if self.last_adjusted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def save(self, *args, **kwargs):
        manual_fields_changed = False
        if self.pk:
            previous = BreakoutRange.objects.filter(pk=self.pk).values('manual_high', 'manual_low').first()
            if previous:
                manual_fields_changed = (
                    previous.get('manual_high') != self.manual_high
                    or previous.get('manual_low') != self.manual_low
                )
        else:
            manual_fields_changed = self.manual_high is not None or self.manual_low is not None

        if manual_fields_changed and not self.last_adjusted_at:
            self.last_adjusted_at = timezone.now()

        if manual_fields_changed:
            logger.info(
                "Manual breakout range override for %s (%s): high=%s low=%s user=%s",
                self.asset_id,
                self.phase,
                self.manual_high,
                self.manual_low,
                getattr(self.last_adjusted_by, 'username', None),
            )

        super().save(*args, **kwargs)


class AssetDiagnostics(models.Model):
    """
    Stores diagnostic statistics for a trading asset.
    
    Tracks counters and reason codes for the Strategy Engine, Risk Engine,
    and Execution Layer. Data is aggregated over configurable time windows.
    
    This model provides the "Sanity & Confidence Layer" that helps understand
    why (not) trading is happening.
    """
    
    # Session Phase choices
    SESSION_PHASES = [
        ('ASIA_RANGE', 'Asia Range'),
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
        ('EIA_PRE', 'EIA Pre'),
        ('EIA_POST', 'EIA Post'),
        ('OTHER', 'Other'),
    ]

    # Relationship to asset
    asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='diagnostics',
        help_text='Asset these diagnostics belong to'
    )

    # Time window identification
    window_start = models.DateTimeField(
        help_text='Start of the diagnostic time window'
    )
    window_end = models.DateTimeField(
        help_text='End of the diagnostic time window'
    )

    # Current session info
    current_phase = models.CharField(
        max_length=20,
        choices=SESSION_PHASES,
        default='OTHER',
        help_text='Current/last session phase'
    )
    trading_mode = models.CharField(
        max_length=20,
        choices=TradingAsset.TRADING_MODES,
        default='STRICT',
        help_text='Trading mode during this window'
    )
    last_cycle_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of the last worker cycle'
    )

    # ==========================================================================
    # Strategy Engine Counters
    # ==========================================================================
    candles_evaluated = models.PositiveIntegerField(
        default=0,
        help_text='Number of candles evaluated by strategy engine'
    )
    ranges_built_asia = models.PositiveIntegerField(
        default=0,
        help_text='Number of Asia ranges built'
    )
    ranges_built_london = models.PositiveIntegerField(
        default=0,
        help_text='Number of London Core ranges built'
    )
    ranges_built_pre_us = models.PositiveIntegerField(
        default=0,
        help_text='Number of Pre-US ranges built'
    )
    ranges_built_us_core = models.PositiveIntegerField(
        default=0,
        help_text='Number of US Core Trading ranges built'
    )
    setups_generated_total = models.PositiveIntegerField(
        default=0,
        help_text='Total number of setups generated by strategy engine'
    )
    setups_generated_breakout = models.PositiveIntegerField(
        default=0,
        help_text='Number of breakout setups generated'
    )
    setups_generated_eia_reversion = models.PositiveIntegerField(
        default=0,
        help_text='Number of EIA reversion setups generated'
    )
    setups_generated_eia_trendday = models.PositiveIntegerField(
        default=0,
        help_text='Number of EIA trend day setups generated'
    )
    setups_discarded_strategy = models.PositiveIntegerField(
        default=0,
        help_text='Number of setups discarded by strategy filters'
    )

    # ==========================================================================
    # Risk Engine Counters
    # ==========================================================================
    setups_evaluated_by_risk = models.PositiveIntegerField(
        default=0,
        help_text='Number of setups evaluated by risk engine'
    )
    setups_rejected_by_risk = models.PositiveIntegerField(
        default=0,
        help_text='Number of setups rejected by risk engine'
    )
    setups_approved_by_risk = models.PositiveIntegerField(
        default=0,
        help_text='Number of setups approved by risk engine'
    )

    # ==========================================================================
    # Execution Layer Counters
    # ==========================================================================
    orders_built = models.PositiveIntegerField(
        default=0,
        help_text='Number of orders built for execution'
    )
    orders_sent_shadow = models.PositiveIntegerField(
        default=0,
        help_text='Number of shadow orders executed'
    )
    orders_sent_live = models.PositiveIntegerField(
        default=0,
        help_text='Number of live orders sent to broker'
    )
    orders_failed = models.PositiveIntegerField(
        default=0,
        help_text='Number of orders that failed'
    )

    # ==========================================================================
    # Reason Codes (aggregated counts)
    # ==========================================================================
    reason_counts_strategy = models.JSONField(
        default=dict,
        blank=True,
        help_text='Aggregated counts of strategy rejection reason codes (e.g., {"STRAT_BODY_TOO_SMALL": 12})'
    )
    reason_counts_risk = models.JSONField(
        default=dict,
        blank=True,
        help_text='Aggregated counts of risk rejection reason codes (e.g., {"RISK_SPREAD_TOO_WIDE": 5})'
    )

    # ==========================================================================
    # Timestamps
    # ==========================================================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-window_end']
        verbose_name = 'Asset Diagnostics'
        verbose_name_plural = 'Asset Diagnostics'
        indexes = [
            models.Index(fields=['asset', '-window_end']),
            models.Index(fields=['-window_end']),
        ]

    def __str__(self):
        return f"{self.asset.symbol} Diagnostics ({self.window_start.strftime('%Y-%m-%d %H:%M')} - {self.window_end.strftime('%H:%M')})"

    def increment_strategy_reason(self, reason_code: str, count: int = 1) -> None:
        """
        Increment the count for a strategy rejection reason code.
        
        Args:
            reason_code: The reason code (e.g., 'STRAT_BODY_TOO_SMALL')
            count: Number to add (default: 1)
        """
        if not self.reason_counts_strategy:
            self.reason_counts_strategy = {}
        current = self.reason_counts_strategy.get(reason_code, 0)
        self.reason_counts_strategy[reason_code] = current + count

    def increment_risk_reason(self, reason_code: str, count: int = 1) -> None:
        """
        Increment the count for a risk rejection reason code.
        
        Args:
            reason_code: The reason code (e.g., 'RISK_SPREAD_TOO_WIDE')
            count: Number to add (default: 1)
        """
        if not self.reason_counts_risk:
            self.reason_counts_risk = {}
        current = self.reason_counts_risk.get(reason_code, 0)
        self.reason_counts_risk[reason_code] = current + count

    def get_top_strategy_reasons(self, n: int = 10) -> list:
        """
        Get the top N strategy rejection reasons sorted by count.
        
        Returns:
            List of tuples: [(reason_code, count, description), ...]
        """
        if not self.reason_counts_strategy:
            return []
        sorted_reasons = sorted(
            self.reason_counts_strategy.items(),
            key=lambda x: x[1],
            reverse=True
        )[:n]
        return [
            (code, count, ReasonCode.get_description(code))
            for code, count in sorted_reasons
        ]

    def get_top_risk_reasons(self, n: int = 10) -> list:
        """
        Get the top N risk rejection reasons sorted by count.
        
        Returns:
            List of tuples: [(reason_code, count, description), ...]
        """
        if not self.reason_counts_risk:
            return []
        sorted_reasons = sorted(
            self.reason_counts_risk.items(),
            key=lambda x: x[1],
            reverse=True
        )[:n]
        return [
            (code, count, ReasonCode.get_description(code))
            for code, count in sorted_reasons
        ]

    def get_all_top_reasons(self, n: int = 10) -> list:
        """
        Get the top N reasons from both strategy and risk engines combined.
        
        Returns:
            List of tuples: [(reason_code, count, description, source), ...]
            where source is 'strategy' or 'risk'
        """
        all_reasons = []
        
        for code, count in (self.reason_counts_strategy or {}).items():
            all_reasons.append((code, count, ReasonCode.get_description(code), 'strategy'))
        
        for code, count in (self.reason_counts_risk or {}).items():
            all_reasons.append((code, count, ReasonCode.get_description(code), 'risk'))
        
        # Sort by count descending
        all_reasons.sort(key=lambda x: x[1], reverse=True)
        return all_reasons[:n]

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'asset_symbol': self.asset.symbol if self.asset else None,
            'asset_name': self.asset.name if self.asset else None,
            'window_start': self.window_start.isoformat() if self.window_start else None,
            'window_end': self.window_end.isoformat() if self.window_end else None,
            'current_phase': self.current_phase,
            'trading_mode': self.trading_mode,
            'last_cycle_at': self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            'counters': {
                'candles_evaluated': self.candles_evaluated,
                'ranges_built': {
                    'asia': self.ranges_built_asia,
                    'london': self.ranges_built_london,
                    'pre_us': self.ranges_built_pre_us,
                    'us_core': self.ranges_built_us_core,
                },
                'setups': {
                    'generated_total': self.setups_generated_total,
                    'generated_breakout': self.setups_generated_breakout,
                    'generated_eia_reversion': self.setups_generated_eia_reversion,
                    'generated_eia_trendday': self.setups_generated_eia_trendday,
                    'discarded_strategy': self.setups_discarded_strategy,
                },
                'risk': {
                    'evaluated': self.setups_evaluated_by_risk,
                    'rejected': self.setups_rejected_by_risk,
                    'approved': self.setups_approved_by_risk,
                },
                'orders': {
                    'built': self.orders_built,
                    'sent_shadow': self.orders_sent_shadow,
                    'sent_live': self.orders_sent_live,
                    'failed': self.orders_failed,
                },
            },
            'reason_counts_strategy': self.reason_counts_strategy or {},
            'reason_counts_risk': self.reason_counts_risk or {},
            'top_reasons': self.get_all_top_reasons(10),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def get_or_create_for_window(cls, asset, window_start, window_end):
        """
        Get or create diagnostics record for a specific time window.
        
        Args:
            asset: TradingAsset instance
            window_start: Start of the time window
            window_end: End of the time window
            
        Returns:
            AssetDiagnostics instance
        """
        diagnostics, created = cls.objects.get_or_create(
            asset=asset,
            window_start=window_start,
            window_end=window_end,
            defaults={
                'trading_mode': asset.trading_mode,
            }
        )
        return diagnostics

    @classmethod
    def get_current_for_asset(cls, asset):
        """
        Get the most recent diagnostics record for an asset.
        """
        return cls.objects.filter(asset=asset).order_by('-window_end').first()

    @classmethod
    def get_aggregated_for_period(cls, asset, start_time, end_time=None):
        """
        Get aggregated diagnostics for an asset over a time period.
        
        Aggregates all diagnostics records within the specified time range.
        
        Args:
            asset: TradingAsset instance or asset ID
            start_time: Start of the time period
            end_time: End of the time period (defaults to now)
            
        Returns:
            Dict with aggregated counters and reason codes
        """
        if end_time is None:
            end_time = timezone.now()
        
        if isinstance(asset, int):
            records = cls.objects.filter(
                asset_id=asset,
                window_end__gte=start_time,
                window_start__lte=end_time
            )
        else:
            records = cls.objects.filter(
                asset=asset,
                window_end__gte=start_time,
                window_start__lte=end_time
            )
        
        # Aggregate counters
        aggregated = {
            'asset_id': asset if isinstance(asset, int) else asset.id,
            'period_start': start_time.isoformat(),
            'period_end': end_time.isoformat(),
            'record_count': records.count(),
            'counters': {
                'candles_evaluated': 0,
                'ranges_built': {'asia': 0, 'london': 0, 'pre_us': 0, 'us_core': 0},
                'setups': {
                    'generated_total': 0,
                    'generated_breakout': 0,
                    'generated_eia_reversion': 0,
                    'generated_eia_trendday': 0,
                    'discarded_strategy': 0,
                },
                'risk': {
                    'evaluated': 0,
                    'rejected': 0,
                    'approved': 0,
                },
                'orders': {
                    'built': 0,
                    'sent_shadow': 0,
                    'sent_live': 0,
                    'failed': 0,
                },
            },
            'reason_counts_strategy': {},
            'reason_counts_risk': {},
            'last_cycle_at': None,
        }
        
        for record in records:
            aggregated['counters']['candles_evaluated'] += record.candles_evaluated
            aggregated['counters']['ranges_built']['asia'] += record.ranges_built_asia
            aggregated['counters']['ranges_built']['london'] += record.ranges_built_london
            aggregated['counters']['ranges_built']['pre_us'] += record.ranges_built_pre_us
            aggregated['counters']['ranges_built']['us_core'] += record.ranges_built_us_core
            aggregated['counters']['setups']['generated_total'] += record.setups_generated_total
            aggregated['counters']['setups']['generated_breakout'] += record.setups_generated_breakout
            aggregated['counters']['setups']['generated_eia_reversion'] += record.setups_generated_eia_reversion
            aggregated['counters']['setups']['generated_eia_trendday'] += record.setups_generated_eia_trendday
            aggregated['counters']['setups']['discarded_strategy'] += record.setups_discarded_strategy
            aggregated['counters']['risk']['evaluated'] += record.setups_evaluated_by_risk
            aggregated['counters']['risk']['rejected'] += record.setups_rejected_by_risk
            aggregated['counters']['risk']['approved'] += record.setups_approved_by_risk
            aggregated['counters']['orders']['built'] += record.orders_built
            aggregated['counters']['orders']['sent_shadow'] += record.orders_sent_shadow
            aggregated['counters']['orders']['sent_live'] += record.orders_sent_live
            aggregated['counters']['orders']['failed'] += record.orders_failed
            
            # Aggregate reason codes
            for code, count in (record.reason_counts_strategy or {}).items():
                aggregated['reason_counts_strategy'][code] = aggregated['reason_counts_strategy'].get(code, 0) + count
            for code, count in (record.reason_counts_risk or {}).items():
                aggregated['reason_counts_risk'][code] = aggregated['reason_counts_risk'].get(code, 0) + count
            
            # Track the most recent last_cycle_at
            if record.last_cycle_at:
                if aggregated['last_cycle_at'] is None or record.last_cycle_at > aggregated['last_cycle_at']:
                    aggregated['last_cycle_at'] = record.last_cycle_at
        
        # Format last_cycle_at
        if aggregated['last_cycle_at']:
            aggregated['last_cycle_at'] = aggregated['last_cycle_at'].isoformat()
        
        # Compute top reasons
        all_reasons = []
        for code, count in aggregated['reason_counts_strategy'].items():
            all_reasons.append((code, count, ReasonCode.get_description(code), 'strategy'))
        for code, count in aggregated['reason_counts_risk'].items():
            all_reasons.append((code, count, ReasonCode.get_description(code), 'risk'))
        all_reasons.sort(key=lambda x: x[1], reverse=True)
        aggregated['top_reasons'] = all_reasons[:10]
        
        return aggregated


class AssetSessionPhaseConfig(models.Model):
    """
    Complete phase configuration for a specific asset and session phase.
    
    Provides unified, configurable phase settings including:
    - Time windows (start/end in UTC)
    - Phase type flags (range build, trading allowed)
    - Event requirements and mappings
    - Per-asset, per-phase active status
    
    This replaces the fragmented configuration that was previously spread
    across AssetBreakoutConfig (timing) and AssetEventConfig (events).
    
    Standard phases per asset:
    - ASIA_RANGE: Range formation (typically 00:00-08:00 UTC)
    - LONDON_CORE: Range formation (typically 08:00-12:00 UTC)  
    - PRE_US_RANGE: Range formation (typically 13:00-15:00 UTC)
    - US_CORE_TRADING: Trading session (typically 15:00-22:00 UTC)
    - EIA_PRE: Event-bound pause phase (e.g., 15:25-15:30 UTC on EIA days)
    - EIA_POST: Event-bound trading phase (e.g., 15:30-17:00 UTC on EIA days)
    """
    
    # Phase identifier choices
    PHASE_CHOICES = [
        ('ASIA_RANGE', 'Asia Range'),
        ('LONDON_CORE', 'London Core'),
        ('PRE_US_RANGE', 'Pre-US Range'),
        ('US_CORE_TRADING', 'US Core Trading'),
        ('EIA_PRE', 'EIA Pre'),
        ('EIA_POST', 'EIA Post'),
        ('OTHER', 'Other'),
    ]
    
    # Event type choices
    EVENT_TYPE_CHOICES = [
        ('NONE', 'None'),
        ('EIA', 'EIA Report'),
        ('US_MARKET_OPEN', 'US Market Open'),
        ('FOMC', 'FOMC Meeting'),
        ('NFP', 'Non-Farm Payrolls'),
        ('CPI', 'Consumer Price Index'),
        ('GDP', 'GDP Report'),
        ('CUSTOM', 'Custom Event'),
    ]
    
    # Relationship to asset
    asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='session_phase_configs',
        help_text='Asset this phase configuration belongs to'
    )
    
    # Phase identification
    phase = models.CharField(
        max_length=20,
        choices=PHASE_CHOICES,
        help_text='Session phase identifier'
    )
    
    # ==========================================================================
    # Time Configuration (UTC)
    # ==========================================================================
    start_time_utc = models.CharField(
        max_length=5,
        help_text='Phase start time in UTC (HH:MM format, e.g., "08:00")'
    )
    end_time_utc = models.CharField(
        max_length=5,
        help_text='Phase end time in UTC (HH:MM format, e.g., "12:00")'
    )
    
    # ==========================================================================
    # Phase Type Flags
    # ==========================================================================
    is_range_build_phase = models.BooleanField(
        default=False,
        help_text='Whether this phase is used for range formation (e.g., Asia, London, Pre-US)'
    )
    is_trading_phase = models.BooleanField(
        default=False,
        help_text='Whether trading signals are generated during this phase (e.g., US Core Trading, EIA Post)'
    )
    
    # ==========================================================================
    # Event Configuration
    # ==========================================================================
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default='NONE',
        help_text='Type of event associated with this phase (NONE for regular phases)'
    )
    requires_event = models.BooleanField(
        default=False,
        help_text='Whether this phase is only valid when the associated event is present'
    )
    event_offset_minutes = models.IntegerField(
        default=0,
        help_text='Time offset in minutes from the event (e.g., -5 for 5 minutes before)'
    )
    
    # ==========================================================================
    # Active Status
    # ==========================================================================
    enabled = models.BooleanField(
        default=True,
        help_text='Whether this phase is active for this asset'
    )
    
    # ==========================================================================
    # Optional Notes
    # ==========================================================================
    notes = models.TextField(
        blank=True,
        help_text='Optional notes about this phase configuration'
    )
    
    # ==========================================================================
    # Timestamps
    # ==========================================================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['asset', 'phase']
        verbose_name = 'Asset Session Phase Config'
        verbose_name_plural = 'Asset Session Phase Configs'
        unique_together = ['asset', 'phase']
        indexes = [
            models.Index(fields=['asset', 'enabled']),
        ]
    
    def __str__(self):
        status = '✓' if self.enabled else '✗'
        flags = []
        if self.is_range_build_phase:
            flags.append('Range')
        if self.is_trading_phase:
            flags.append('Trading')
        if self.requires_event:
            flags.append(f'Event:{self.event_type}')
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return f"{status} {self.asset.symbol} - {self.get_phase_display()}{flag_str}"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'phase': self.phase,
            'phase_display': self.get_phase_display(),
            'start_time_utc': self.start_time_utc,
            'end_time_utc': self.end_time_utc,
            'is_range_build_phase': self.is_range_build_phase,
            'is_trading_phase': self.is_trading_phase,
            'event_type': self.event_type,
            'event_type_display': self.get_event_type_display(),
            'requires_event': self.requires_event,
            'event_offset_minutes': self.event_offset_minutes,
            'enabled': self.enabled,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def get_default_phases_for_asset(cls, asset_symbol):
        """
        Return default phase configurations based on asset type.
        
        These defaults can be used when creating a new asset to pre-populate
        sensible phase configurations.
        
        Args:
            asset_symbol: Asset symbol (e.g., 'OIL', 'NAS100')
            
        Returns:
            List of dicts with default phase configurations
        """
        # Common phases for all assets
        base_phases = [
            {
                'phase': 'ASIA_RANGE',
                'start_time_utc': '00:00',
                'end_time_utc': '08:00',
                'is_range_build_phase': True,
                'is_trading_phase': False,
                'event_type': 'NONE',
                'requires_event': False,
                'enabled': True,
            },
            {
                'phase': 'LONDON_CORE',
                'start_time_utc': '08:00',
                'end_time_utc': '12:00',
                'is_range_build_phase': True,
                'is_trading_phase': False,
                'event_type': 'NONE',
                'requires_event': False,
                'enabled': True,
            },
            {
                'phase': 'PRE_US_RANGE',
                'start_time_utc': '13:00',
                'end_time_utc': '15:00',
                'is_range_build_phase': True,
                'is_trading_phase': False,
                'event_type': 'NONE',
                'requires_event': False,
                'enabled': True,
            },
        ]
        
        # Asset-specific configurations
        if asset_symbol in ('OIL', 'CL', 'WTI'):
            # WTI Oil specific phases
            return base_phases + [
                {
                    'phase': 'US_CORE_TRADING',
                    'start_time_utc': '15:00',
                    'end_time_utc': '22:00',
                    'is_range_build_phase': False,
                    'is_trading_phase': True,
                    'event_type': 'NONE',
                    'requires_event': False,
                    'enabled': True,
                },
                {
                    'phase': 'EIA_PRE',
                    'start_time_utc': '15:25',
                    'end_time_utc': '15:30',
                    'is_range_build_phase': False,
                    'is_trading_phase': False,
                    'event_type': 'EIA',
                    'requires_event': True,
                    'enabled': True,
                },
                {
                    'phase': 'EIA_POST',
                    'start_time_utc': '15:30',
                    'end_time_utc': '17:00',
                    'is_range_build_phase': False,
                    'is_trading_phase': True,
                    'event_type': 'EIA',
                    'requires_event': True,
                    'enabled': True,
                },
            ]
        elif asset_symbol in ('NAS100', 'NDX', 'NASDAQ'):
            # NAS100 specific phases
            return base_phases + [
                {
                    'phase': 'US_CORE_TRADING',
                    'start_time_utc': '14:30',
                    'end_time_utc': '21:00',
                    'is_range_build_phase': False,
                    'is_trading_phase': True,
                    'event_type': 'US_MARKET_OPEN',
                    'requires_event': False,  # Event optional but can be used
                    'enabled': True,
                },
            ]
        else:
            # Generic default for other assets
            return base_phases + [
                {
                    'phase': 'US_CORE_TRADING',
                    'start_time_utc': '15:00',
                    'end_time_utc': '22:00',
                    'is_range_build_phase': False,
                    'is_trading_phase': True,
                    'event_type': 'NONE',
                    'requires_event': False,
                    'enabled': True,
                },
            ]
    
    @classmethod
    def create_default_phases_for_asset(cls, asset):
        """
        Create default phase configurations for an asset.
        
        Args:
            asset: TradingAsset instance
            
        Returns:
            List of created AssetSessionPhaseConfig instances
        """
        defaults = cls.get_default_phases_for_asset(asset.symbol)
        created = []
        for phase_data in defaults:
            config, was_created = cls.objects.get_or_create(
                asset=asset,
                phase=phase_data['phase'],
                defaults=phase_data,
            )
            if was_created:
                created.append(config)
        return created
    
    @classmethod
    def get_phases_for_asset(cls, asset):
        """
        Get all phase configurations for an asset.
        
        Args:
            asset: TradingAsset instance or asset ID
            
        Returns:
            QuerySet of AssetSessionPhaseConfig instances
        """
        if isinstance(asset, int):
            return cls.objects.filter(asset_id=asset).order_by('phase')
        return cls.objects.filter(asset=asset).order_by('phase')
    
    @classmethod
    def get_enabled_phases_for_asset(cls, asset):
        """
        Get only enabled phase configurations for an asset.
        
        Args:
            asset: TradingAsset instance or asset ID
            
        Returns:
            QuerySet of enabled AssetSessionPhaseConfig instances
        """
        if isinstance(asset, int):
            return cls.objects.filter(asset_id=asset, enabled=True).order_by('phase')
        return cls.objects.filter(asset=asset, enabled=True).order_by('phase')


class PriceSnapshot(models.Model):
    """
    Stores historical price snapshots for each trading asset.
    
    Used for the Breakout Distance Chart to display the last 60 minutes
    of price history relative to the range and breakout levels.
    
    Records are automatically cleaned up after a configurable retention period
    (default: 2 hours) to keep the database lean.
    """
    
    # Relationship to asset
    asset = models.ForeignKey(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='price_snapshots',
        help_text='Asset this snapshot belongs to'
    )
    
    # Timestamp
    timestamp = models.DateTimeField(
        db_index=True,
        help_text='Time of the price snapshot'
    )
    
    # Price data (using mid price for simplicity in chart display)
    price_mid = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        help_text='Mid price (average of bid and ask)'
    )
    price_bid = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Bid price'
    )
    price_ask = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text='Ask price'
    )
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Price Snapshot'
        verbose_name_plural = 'Price Snapshots'
        indexes = [
            models.Index(fields=['asset', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.asset.symbol}: {self.price_mid} @ {self.timestamp.strftime('%H:%M:%S')}"
    
    @classmethod
    def record_snapshot(cls, asset, price_mid, price_bid=None, price_ask=None, timestamp=None):
        """
        Record a new price snapshot for an asset.
        
        Args:
            asset: TradingAsset instance
            price_mid: Mid price
            price_bid: Optional bid price
            price_ask: Optional ask price
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            PriceSnapshot instance
        """
        if timestamp is None:
            timestamp = timezone.now()
        
        return cls.objects.create(
            asset=asset,
            timestamp=timestamp,
            price_mid=Decimal(str(price_mid)),
            price_bid=Decimal(str(price_bid)) if price_bid is not None else None,
            price_ask=Decimal(str(price_ask)) if price_ask is not None else None,
        )
    
    @classmethod
    def get_recent_for_asset(cls, asset, minutes=60):
        """
        Get recent price snapshots for an asset.
        
        Args:
            asset: TradingAsset instance or asset ID
            minutes: Number of minutes of history to retrieve (default: 60)
            
        Returns:
            QuerySet of PriceSnapshot instances ordered by timestamp ascending
        """
        cutoff = timezone.now() - timedelta(minutes=minutes)
        
        if isinstance(asset, int):
            qs = cls.objects.filter(asset_id=asset, timestamp__gte=cutoff)
        else:
            qs = cls.objects.filter(asset=asset, timestamp__gte=cutoff)
        
        return qs.order_by('timestamp')
    
    @classmethod
    def cleanup_old_snapshots(cls, hours=2):
        """
        Remove price snapshots older than the retention period.
        
        Args:
            hours: Number of hours to retain (default: 2)
            
        Returns:
            Number of deleted records
        """
        cutoff = timezone.now() - timedelta(hours=hours)
        deleted_count, _ = cls.objects.filter(timestamp__lt=cutoff).delete()
        return deleted_count
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'ts': self.timestamp.isoformat(),
            'price': float(self.price_mid),
            'bid': float(self.price_bid) if self.price_bid else None,
            'ask': float(self.price_ask) if self.price_ask else None,
        }
