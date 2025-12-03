"""
Data models for the Risk Engine.

These models represent risk configuration and evaluation results,
independent of specific broker or strategy implementations.
"""
from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
import yaml

if TYPE_CHECKING:
    from core.services.broker.models import OrderRequest


@dataclass
class RiskConfig:
    """
    Configuration for the Risk Engine.
    
    Defines all risk limits and rules that the Risk Engine will enforce.
    Can be loaded from a YAML configuration file.
    
    Attributes:
        max_risk_per_trade_percent: Maximum risk per trade as percent of equity (e.g., 1.0 = 1%).
        max_daily_loss_percent: Maximum daily loss as percent of equity.
        max_weekly_loss_percent: Maximum weekly loss as percent of equity.
        max_open_positions: Maximum number of concurrent open positions.
        allow_countertrend: Whether to allow trades against the higher timeframe trend.
        max_position_size: Maximum position size (contracts).
        sl_min_ticks: Minimum stop loss distance in ticks.
        tp_min_ticks: Minimum take profit distance in ticks.
        deny_eia_window_minutes: Minutes before/after EIA to deny new trades.
        deny_friday_after: Time (CET) after which no trades on Friday.
        deny_overnight: Whether to deny overnight positions.
        tick_size: Size of one tick for the traded instrument.
        tick_value: Value of one tick in account currency.
        leverage: Leverage for margin trading (e.g., 20.0 for 1:20, 1.0 for no leverage).
    """
    max_risk_per_trade_percent: Decimal = Decimal('1.0')
    max_daily_loss_percent: Decimal = Decimal('3.0')
    max_weekly_loss_percent: Decimal = Decimal('6.0')
    
    max_open_positions: int = 1
    allow_countertrend: bool = False
    max_position_size: Decimal = Decimal('5.0')
    
    sl_min_ticks: int = 5
    tp_min_ticks: int = 5
    
    deny_eia_window_minutes: int = 5
    deny_friday_after: str = '21:00'
    deny_overnight: bool = True
    
    # Instrument-specific settings
    tick_size: Decimal = Decimal('0.01')
    tick_value: Decimal = Decimal('10.0')  # USD per tick for CL contract
    leverage: Decimal = Decimal('1.0')  # Leverage for margin trading (1.0 = no leverage)
    
    def __post_init__(self):
        """Ensure Decimal fields are proper types."""
        # Dynamically identify and convert Decimal fields
        # This approach is more maintainable than hardcoding field names
        
        # Get type hints to properly evaluate type annotations
        type_hints = typing.get_type_hints(self.__class__)
        
        for field in dataclasses.fields(self):
            # Check if this field is typed as Decimal
            field_type = type_hints.get(field.name)
            if field_type is Decimal:
                value = getattr(self, field.name)
                if not isinstance(value, Decimal):
                    setattr(self, field.name, Decimal(str(value)))

    @classmethod
    def from_dict(cls, data: dict) -> 'RiskConfig':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with configuration values.
            
        Returns:
            RiskConfig: New instance with values from dictionary.
        """
        return cls(
            max_risk_per_trade_percent=Decimal(str(data.get('max_risk_per_trade_percent', '1.0'))),
            max_daily_loss_percent=Decimal(str(data.get('max_daily_loss_percent', '3.0'))),
            max_weekly_loss_percent=Decimal(str(data.get('max_weekly_loss_percent', '6.0'))),
            max_open_positions=data.get('max_open_positions', 1),
            allow_countertrend=data.get('allow_countertrend', False),
            max_position_size=Decimal(str(data.get('max_position_size', '5.0'))),
            sl_min_ticks=data.get('sl_min_ticks', 5),
            tp_min_ticks=data.get('tp_min_ticks', 5),
            deny_eia_window_minutes=data.get('deny_eia_window_minutes', 5),
            deny_friday_after=data.get('deny_friday_after', '21:00'),
            deny_overnight=data.get('deny_overnight', True),
            tick_size=Decimal(str(data.get('tick_size', '0.01'))),
            tick_value=Decimal(str(data.get('tick_value', '10.0'))),
            leverage=Decimal(str(data.get('leverage', '1.0'))),
        )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'RiskConfig':
        """
        Load configuration from a YAML file.
        
        Args:
            yaml_path: Path to the YAML configuration file.
            
        Returns:
            RiskConfig: New instance with values from YAML file.
        """
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_yaml_string(cls, yaml_string: str) -> 'RiskConfig':
        """
        Load configuration from a YAML string.
        
        Args:
            yaml_string: YAML configuration as a string.
            
        Returns:
            RiskConfig: New instance with values from YAML string.
        """
        data = yaml.safe_load(yaml_string)
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Dictionary representation of the configuration.
        """
        return {
            'max_risk_per_trade_percent': float(self.max_risk_per_trade_percent),
            'max_daily_loss_percent': float(self.max_daily_loss_percent),
            'max_weekly_loss_percent': float(self.max_weekly_loss_percent),
            'max_open_positions': self.max_open_positions,
            'allow_countertrend': self.allow_countertrend,
            'max_position_size': float(self.max_position_size),
            'sl_min_ticks': self.sl_min_ticks,
            'tp_min_ticks': self.tp_min_ticks,
            'deny_eia_window_minutes': self.deny_eia_window_minutes,
            'deny_friday_after': self.deny_friday_after,
            'deny_overnight': self.deny_overnight,
            'tick_size': float(self.tick_size),
            'tick_value': float(self.tick_value),
            'leverage': float(self.leverage),
        }

    def to_yaml(self) -> str:
        """
        Convert to YAML string.
        
        Returns:
            str: YAML representation of the configuration.
        """
        return yaml.dump(self.to_dict(), default_flow_style=False)

    def get_friday_cutoff_time(self) -> time:
        """
        Parse and return the Friday cutoff time.
        
        Returns:
            time: Friday cutoff time object.
        """
        parts = self.deny_friday_after.split(':')
        return time(int(parts[0]), int(parts[1]))


@dataclass
class RiskEvaluationResult:
    """
    Result of a risk evaluation by the Risk Engine.
    
    This is the output of RiskEngine.evaluate() and indicates whether
    a proposed trade is allowed, why, and optionally provides an
    adjusted order if the original was modified to fit risk limits.
    
    Attributes:
        allowed: Whether the trade is allowed.
        reason: Human-readable explanation of the decision.
        adjusted_order: Optional modified order request that fits risk limits.
        violations: List of specific rule violations found.
        risk_metrics: Dictionary of calculated risk metrics.
    """
    allowed: bool
    reason: str
    adjusted_order: Optional[OrderRequest] = None
    violations: list = field(default_factory=list)
    risk_metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Dictionary representation of the result.
        """
        adjusted_order_dict = None
        if self.adjusted_order is not None:
            # OrderRequest from broker.models has to_dict method
            adjusted_order_dict = self.adjusted_order.to_dict()
        
        return {
            'allowed': self.allowed,
            'reason': self.reason,
            'adjusted_order': adjusted_order_dict,
            'violations': self.violations,
            'risk_metrics': self.risk_metrics,
        }

    def to_json(self) -> str:
        """
        Convert to JSON string for serialization.
        
        Returns:
            str: JSON representation of the result.
        """
        import json
        return json.dumps(self.to_dict(), indent=2)
