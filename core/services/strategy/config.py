"""
Configuration for the Strategy Engine.

Provides StrategyConfig dataclass for configuring breakout and EIA strategies.

Extended to support:
- London Core Range
- EIA Pre/Post parameters
- Candle Quality filters
- Advanced filters (Momentum, Volatility)
- ATR extensions
- Wick ratio filters
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
class LondonCoreConfig:
    """Configuration for London Core session breakout strategy (NEW)."""
    start: str = "08:00"  # UTC time
    end: str = "12:00"    # UTC time
    min_range_ticks: int = 10
    max_range_ticks: int = 200
    min_breakout_body_fraction: float = 0.5
    require_volume_spike: bool = False
    require_clean_range: bool = False


@dataclass
class UsCoreConfig:
    """Configuration for US Core session breakout strategy.
    
    Includes both:
    - Pre-US Range period (range formation, 13:00-15:00 UTC default)
    - US Core Trading session (trading, 15:00-22:00 UTC default)
    """
    # Pre-US Range (range formation only)
    pre_us_start: str = "13:00"  # UTC time
    pre_us_end: str = "15:00"    # UTC time
    
    # US Core Trading session (breakouts allowed)
    us_core_trading_start: str = "15:00"  # UTC time
    us_core_trading_end: str = "23:59"    # UTC time
    us_core_trading_enabled: bool = True   # Whether trading is enabled in this session
    
    # Range requirements (for Pre-US Range)
    min_range_ticks: int = 10
    max_range_ticks: int = 200
    min_breakout_body_fraction: float = 0.5
    require_volume_spike: bool = False
    require_clean_range: bool = False


@dataclass
class CandleQualityConfig:
    """Configuration for candle quality filters (NEW)."""
    min_wick_ratio: Optional[float] = None
    max_wick_ratio: Optional[float] = None
    min_candle_body_absolute: Optional[float] = None
    max_spread_ticks: Optional[int] = None
    filter_doji_breakouts: bool = True


@dataclass
class AdvancedFilterConfig:
    """Configuration for advanced filters (NEW)."""
    consecutive_candle_filter: int = 0
    momentum_threshold: Optional[float] = None
    volatility_throttle_min_atr: Optional[float] = None
    session_volatility_cap: Optional[float] = None


@dataclass
class AtrConfig:
    """Configuration for ATR-based filters (Extended)."""
    require_atr_minimum: bool = False
    min_atr_value: Optional[float] = None
    max_atr_value: Optional[float] = None


@dataclass
class BreakoutConfig:
    """Configuration for breakout strategies."""
    asia_range: AsiaRangeConfig = field(default_factory=AsiaRangeConfig)
    london_core: LondonCoreConfig = field(default_factory=LondonCoreConfig)
    us_core: UsCoreConfig = field(default_factory=UsCoreConfig)
    candle_quality: CandleQualityConfig = field(default_factory=CandleQualityConfig)
    advanced_filter: AdvancedFilterConfig = field(default_factory=AdvancedFilterConfig)
    atr: AtrConfig = field(default_factory=AtrConfig)
    # Global breakout requirements
    min_breakout_body_fraction: float = 0.5
    max_breakout_body_fraction: Optional[float] = None
    min_breakout_distance_ticks: int = 1
    max_candle_distance_ticks: int = 10
    min_volume_spike: Optional[float] = None


@dataclass
class EiaConfig:
    """Configuration for EIA (Energy Information Administration) strategies."""
    impulse_window_minutes: int = 3
    reversion_min_retrace_fraction: float = 0.5
    trend_min_follow_candles: int = 3
    # EIA Pre/Post parameters (NEW)
    min_body_fraction: float = 0.6
    min_impulse_atr: Optional[float] = None
    impulse_range_high: Optional[float] = None
    impulse_range_low: Optional[float] = None
    required_impulse_strength: float = 0.5
    reversion_window_min_sec: int = 30
    reversion_window_max_sec: int = 300
    max_impulse_duration_min: int = 5


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
        london_core_data = breakout_data.get('london_core', {})
        us_core_data = breakout_data.get('us_core', {})
        candle_quality_data = breakout_data.get('candle_quality', {})
        advanced_filter_data = breakout_data.get('advanced_filter', {})
        atr_data = breakout_data.get('atr', {})

        asia_range = AsiaRangeConfig(
            start=asia_range_data.get('start', '00:00'),
            end=asia_range_data.get('end', '08:00'),
            min_range_ticks=asia_range_data.get('min_range_ticks', 10),
            max_range_ticks=asia_range_data.get('max_range_ticks', 200),
            min_breakout_body_fraction=asia_range_data.get('min_breakout_body_fraction', 0.5),
            require_volume_spike=asia_range_data.get('require_volume_spike', False),
            require_clean_range=asia_range_data.get('require_clean_range', False),
        )

        london_core = LondonCoreConfig(
            start=london_core_data.get('start', '08:00'),
            end=london_core_data.get('end', '13:00'),
            min_range_ticks=london_core_data.get('min_range_ticks', 10),
            max_range_ticks=london_core_data.get('max_range_ticks', 200),
            min_breakout_body_fraction=london_core_data.get('min_breakout_body_fraction', 0.5),
            require_volume_spike=london_core_data.get('require_volume_spike', False),
            require_clean_range=london_core_data.get('require_clean_range', False),
        )

        us_core = UsCoreConfig(
            pre_us_start=us_core_data.get('pre_us_start', '13:00'),
            pre_us_end=us_core_data.get('pre_us_end', '15:00'),
            us_core_trading_start=us_core_data.get('us_core_trading_start', '15:00'),
            us_core_trading_end=us_core_data.get('us_core_trading_end', '22:00'),
            us_core_trading_enabled=us_core_data.get('us_core_trading_enabled', True),
            min_range_ticks=us_core_data.get('min_range_ticks', 10),
            max_range_ticks=us_core_data.get('max_range_ticks', 200),
            min_breakout_body_fraction=us_core_data.get('min_breakout_body_fraction', 0.5),
            require_volume_spike=us_core_data.get('require_volume_spike', False),
            require_clean_range=us_core_data.get('require_clean_range', False),
        )

        candle_quality = CandleQualityConfig(
            min_wick_ratio=candle_quality_data.get('min_wick_ratio'),
            max_wick_ratio=candle_quality_data.get('max_wick_ratio'),
            min_candle_body_absolute=candle_quality_data.get('min_candle_body_absolute'),
            max_spread_ticks=candle_quality_data.get('max_spread_ticks'),
            filter_doji_breakouts=candle_quality_data.get('filter_doji_breakouts', True),
        )

        advanced_filter = AdvancedFilterConfig(
            consecutive_candle_filter=advanced_filter_data.get('consecutive_candle_filter', 0),
            momentum_threshold=advanced_filter_data.get('momentum_threshold'),
            volatility_throttle_min_atr=advanced_filter_data.get('volatility_throttle_min_atr'),
            session_volatility_cap=advanced_filter_data.get('session_volatility_cap'),
        )

        atr = AtrConfig(
            require_atr_minimum=atr_data.get('require_atr_minimum', False),
            min_atr_value=atr_data.get('min_atr_value'),
            max_atr_value=atr_data.get('max_atr_value'),
        )

        breakout = BreakoutConfig(
            asia_range=asia_range,
            london_core=london_core,
            us_core=us_core,
            candle_quality=candle_quality,
            advanced_filter=advanced_filter,
            atr=atr,
            min_breakout_body_fraction=breakout_data.get('min_breakout_body_fraction', 0.5),
            max_breakout_body_fraction=breakout_data.get('max_breakout_body_fraction'),
            min_breakout_distance_ticks=breakout_data.get('min_breakout_distance_ticks', 1),
            max_candle_distance_ticks=breakout_data.get('max_candle_distance_ticks', 10),
            min_volume_spike=breakout_data.get('min_volume_spike'),
        )

        eia = EiaConfig(
            impulse_window_minutes=eia_data.get('impulse_window_minutes', 3),
            reversion_min_retrace_fraction=eia_data.get('reversion_min_retrace_fraction', 0.5),
            trend_min_follow_candles=eia_data.get('trend_min_follow_candles', 3),
            min_body_fraction=eia_data.get('min_body_fraction', 0.6),
            min_impulse_atr=eia_data.get('min_impulse_atr'),
            impulse_range_high=eia_data.get('impulse_range_high'),
            impulse_range_low=eia_data.get('impulse_range_low'),
            required_impulse_strength=eia_data.get('required_impulse_strength', 0.5),
            reversion_window_min_sec=eia_data.get('reversion_window_min_sec', 30),
            reversion_window_max_sec=eia_data.get('reversion_window_max_sec', 300),
            max_impulse_duration_min=eia_data.get('max_impulse_duration_min', 5),
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
                'london_core': {
                    'start': self.breakout.london_core.start,
                    'end': self.breakout.london_core.end,
                    'min_range_ticks': self.breakout.london_core.min_range_ticks,
                    'max_range_ticks': self.breakout.london_core.max_range_ticks,
                    'min_breakout_body_fraction': self.breakout.london_core.min_breakout_body_fraction,
                    'require_volume_spike': self.breakout.london_core.require_volume_spike,
                    'require_clean_range': self.breakout.london_core.require_clean_range,
                },
                'us_core': {
                    'pre_us_start': self.breakout.us_core.pre_us_start,
                    'pre_us_end': self.breakout.us_core.pre_us_end,
                    'us_core_trading_start': self.breakout.us_core.us_core_trading_start,
                    'us_core_trading_end': self.breakout.us_core.us_core_trading_end,
                    'us_core_trading_enabled': self.breakout.us_core.us_core_trading_enabled,
                    'min_range_ticks': self.breakout.us_core.min_range_ticks,
                    'max_range_ticks': self.breakout.us_core.max_range_ticks,
                    'min_breakout_body_fraction': self.breakout.us_core.min_breakout_body_fraction,
                    'require_volume_spike': self.breakout.us_core.require_volume_spike,
                    'require_clean_range': self.breakout.us_core.require_clean_range,
                },
                'candle_quality': {
                    'min_wick_ratio': self.breakout.candle_quality.min_wick_ratio,
                    'max_wick_ratio': self.breakout.candle_quality.max_wick_ratio,
                    'min_candle_body_absolute': self.breakout.candle_quality.min_candle_body_absolute,
                    'max_spread_ticks': self.breakout.candle_quality.max_spread_ticks,
                    'filter_doji_breakouts': self.breakout.candle_quality.filter_doji_breakouts,
                },
                'advanced_filter': {
                    'consecutive_candle_filter': self.breakout.advanced_filter.consecutive_candle_filter,
                    'momentum_threshold': self.breakout.advanced_filter.momentum_threshold,
                    'volatility_throttle_min_atr': self.breakout.advanced_filter.volatility_throttle_min_atr,
                    'session_volatility_cap': self.breakout.advanced_filter.session_volatility_cap,
                },
                'atr': {
                    'require_atr_minimum': self.breakout.atr.require_atr_minimum,
                    'min_atr_value': self.breakout.atr.min_atr_value,
                    'max_atr_value': self.breakout.atr.max_atr_value,
                },
                'min_breakout_body_fraction': self.breakout.min_breakout_body_fraction,
                'max_breakout_body_fraction': self.breakout.max_breakout_body_fraction,
                'min_breakout_distance_ticks': self.breakout.min_breakout_distance_ticks,
                'max_candle_distance_ticks': self.breakout.max_candle_distance_ticks,
                'min_volume_spike': self.breakout.min_volume_spike,
            },
            'eia': {
                'impulse_window_minutes': self.eia.impulse_window_minutes,
                'reversion_min_retrace_fraction': self.eia.reversion_min_retrace_fraction,
                'trend_min_follow_candles': self.eia.trend_min_follow_candles,
                'min_body_fraction': self.eia.min_body_fraction,
                'min_impulse_atr': self.eia.min_impulse_atr,
                'impulse_range_high': self.eia.impulse_range_high,
                'impulse_range_low': self.eia.impulse_range_low,
                'required_impulse_strength': self.eia.required_impulse_strength,
                'reversion_window_min_sec': self.eia.reversion_window_min_sec,
                'reversion_window_max_sec': self.eia.reversion_window_max_sec,
                'max_impulse_duration_min': self.eia.max_impulse_duration_min,
            },
            'default_epic': self.default_epic,
            'tick_size': self.tick_size,
        }
