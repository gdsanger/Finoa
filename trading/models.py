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
            UsCoreConfig,
            EiaConfig,
        )
        
        # Get breakout config for this asset
        try:
            breakout_cfg = self.breakout_config
            asia_range = AsiaRangeConfig(
                start=breakout_cfg.asia_range_start,
                end=breakout_cfg.asia_range_end,
                min_range_ticks=breakout_cfg.asia_min_range_ticks,
                max_range_ticks=breakout_cfg.asia_max_range_ticks,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
            )
            us_core = UsCoreConfig(
                pre_us_start=breakout_cfg.pre_us_start,
                pre_us_end=breakout_cfg.pre_us_end,
                min_range_ticks=breakout_cfg.us_min_range_ticks,
                max_range_ticks=breakout_cfg.us_max_range_ticks,
                min_breakout_body_fraction=float(breakout_cfg.min_breakout_body_fraction),
            )
            breakout = BreakoutConfig(asia_range=asia_range, us_core=us_core)
        except AssetBreakoutConfig.DoesNotExist:
            # Use defaults if no breakout config exists
            breakout = BreakoutConfig()
        
        return StrategyConfig(
            breakout=breakout,
            eia=EiaConfig(),  # EIA config handled via event configs
            default_epic=self.epic,
            tick_size=float(self.tick_size),
        )


class AssetBreakoutConfig(models.Model):
    """
    Breakout strategy configuration specific to an asset.
    
    Defines range formation parameters, breakout candle requirements,
    and timing windows for the breakout strategy.
    """
    
    asset = models.OneToOneField(
        TradingAsset,
        on_delete=models.CASCADE,
        related_name='breakout_config',
        help_text='Asset this configuration belongs to'
    )
    
    # Asia Range Configuration
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
    
    # Pre-US / US Core Configuration
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
    
    # Breakout Candle Requirements
    min_breakout_body_fraction = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.50'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text='Minimum candle body size as fraction of range height (0.0-1.0)'
    )
    
    # Optional ATR-based filters
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
    
    # Timestamps
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
        ('US_CORE', 'US Core'),
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
        ('US_CORE', 'US Core'),
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
        ('US_CORE', 'US Core'),
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
        max_length=20,
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
