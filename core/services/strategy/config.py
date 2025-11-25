"""
Configuration for the Strategy Engine.

Provides StrategyConfig dataclass for configuring breakout and EIA strategies.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AsiaRangeConfig:
    """Configuration for Asia Range breakout strategy."""
    start: str = "00:00"  # UTC time
    end: str = "08:00"    # UTC time
    min_range_ticks: int = 10
    max_range_ticks: int = 200
    min_breakout_body_fraction: float = 0.5
    require_volume_spike: bool = False
    require_clean_range: bool = False


@dataclass
class UsCoreConfig:
    """Configuration for US Core session breakout strategy."""
    pre_us_start: str = "13:00"  # UTC time
    pre_us_end: str = "15:00"    # UTC time
    min_range_ticks: int = 10
    max_range_ticks: int = 200
    min_breakout_body_fraction: float = 0.5
    require_volume_spike: bool = False
    require_clean_range: bool = False


@dataclass
class BreakoutConfig:
    """Configuration for breakout strategies."""
    asia_range: AsiaRangeConfig = field(default_factory=AsiaRangeConfig)
    us_core: UsCoreConfig = field(default_factory=UsCoreConfig)


@dataclass
class EiaConfig:
    """Configuration for EIA (Energy Information Administration) strategies."""
    impulse_window_minutes: int = 3
    reversion_min_retrace_fraction: float = 0.5
    trend_min_follow_candles: int = 3


@dataclass
class StrategyConfig:
    """
    Main configuration for the Strategy Engine.
    
    Attributes:
        breakout: Configuration for breakout strategies.
        eia: Configuration for EIA strategies.
        default_epic: Default market identifier for strategies.
        tick_size: Size of one tick for the market (for range calculations).
    """
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    eia: EiaConfig = field(default_factory=EiaConfig)
    default_epic: str = "CC.D.CL.UNC.IP"  # WTI Crude Oil
    tick_size: float = 0.01  # Default tick size

    @classmethod
    def from_dict(cls, data: dict) -> 'StrategyConfig':
        """
        Create StrategyConfig from dictionary (e.g., from YAML).
        
        Args:
            data: Configuration dictionary.
            
        Returns:
            StrategyConfig instance.
        """
        breakout_data = data.get('breakout', {})
        eia_data = data.get('eia', {})

        asia_range_data = breakout_data.get('asia_range', {})
        us_core_data = breakout_data.get('us_core', {})

        asia_range = AsiaRangeConfig(
            start=asia_range_data.get('start', '00:00'),
            end=asia_range_data.get('end', '08:00'),
            min_range_ticks=asia_range_data.get('min_range_ticks', 10),
            max_range_ticks=asia_range_data.get('max_range_ticks', 200),
            min_breakout_body_fraction=asia_range_data.get('min_breakout_body_fraction', 0.5),
            require_volume_spike=asia_range_data.get('require_volume_spike', False),
            require_clean_range=asia_range_data.get('require_clean_range', False),
        )

        us_core = UsCoreConfig(
            pre_us_start=us_core_data.get('pre_us_start', '13:00'),
            pre_us_end=us_core_data.get('pre_us_end', '15:00'),
            min_range_ticks=us_core_data.get('min_range_ticks', 10),
            max_range_ticks=us_core_data.get('max_range_ticks', 200),
            min_breakout_body_fraction=us_core_data.get('min_breakout_body_fraction', 0.5),
            require_volume_spike=us_core_data.get('require_volume_spike', False),
            require_clean_range=us_core_data.get('require_clean_range', False),
        )

        breakout = BreakoutConfig(asia_range=asia_range, us_core=us_core)

        eia = EiaConfig(
            impulse_window_minutes=eia_data.get('impulse_window_minutes', 3),
            reversion_min_retrace_fraction=eia_data.get('reversion_min_retrace_fraction', 0.5),
            trend_min_follow_candles=eia_data.get('trend_min_follow_candles', 3),
        )

        return cls(
            breakout=breakout,
            eia=eia,
            default_epic=data.get('default_epic', 'CC.D.CL.UNC.IP'),
            tick_size=data.get('tick_size', 0.01),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'breakout': {
                'asia_range': {
                    'start': self.breakout.asia_range.start,
                    'end': self.breakout.asia_range.end,
                    'min_range_ticks': self.breakout.asia_range.min_range_ticks,
                    'max_range_ticks': self.breakout.asia_range.max_range_ticks,
                    'min_breakout_body_fraction': self.breakout.asia_range.min_breakout_body_fraction,
                    'require_volume_spike': self.breakout.asia_range.require_volume_spike,
                    'require_clean_range': self.breakout.asia_range.require_clean_range,
                },
                'us_core': {
                    'pre_us_start': self.breakout.us_core.pre_us_start,
                    'pre_us_end': self.breakout.us_core.pre_us_end,
                    'min_range_ticks': self.breakout.us_core.min_range_ticks,
                    'max_range_ticks': self.breakout.us_core.max_range_ticks,
                    'min_breakout_body_fraction': self.breakout.us_core.min_breakout_body_fraction,
                    'require_volume_spike': self.breakout.us_core.require_volume_spike,
                    'require_clean_range': self.breakout.us_core.require_clean_range,
                },
            },
            'eia': {
                'impulse_window_minutes': self.eia.impulse_window_minutes,
                'reversion_min_retrace_fraction': self.eia.reversion_min_retrace_fraction,
                'trend_min_follow_candles': self.eia.trend_min_follow_candles,
            },
            'default_epic': self.default_epic,
            'tick_size': self.tick_size,
        }
