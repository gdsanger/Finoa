from django.db import models
from decimal import Decimal
import uuid


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
        help_text='GPT Confidence Score (0-100%)'
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
