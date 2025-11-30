"""
Breakout Distance Chart Service.

Provides data for the Breakout Distance Chart feature in the Trading Diagnostics
/ Sanity & Confidence Layer.

This chart shows:
- The range (band) from the reference phase
- Breakout levels (long/short)
- Price history for the last 60 minutes
- Trend indicator (up/down/sideways)
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Optional, List, Dict, Any
from datetime import timedelta

from django.utils import timezone

from ..models import (
    AssetSessionPhaseConfig,
    TradingAsset,
    BreakoutRange,
    AssetPriceStatus,
    PriceSnapshot,
)


# Trend type alias
TrendType = Literal["up", "down", "sideways"]

# Reference phase fallback mapping: used when no per-asset config is available
REFERENCE_PHASE_MAPPING = {
    'LONDON_CORE': 'ASIA_RANGE',
    'US_CORE_TRADING': 'PRE_US_RANGE',
    'PRE_US_RANGE': 'LONDON_CORE',
    'EIA_PRE': 'PRE_US_RANGE',
    'EIA_POST': 'PRE_US_RANGE',
}

# Default trend threshold in ticks (price must move more than this to be up/down)
DEFAULT_TREND_THRESHOLD_TICKS = 15

# Price history window in minutes
PRICE_HISTORY_MINUTES = 60

# Default tick size fallback
DEFAULT_TICK_SIZE = Decimal('0.01')


@dataclass
class BreakoutDistanceChartData:
    """
    Data model for the Breakout Distance Chart.
    
    Contains all information needed to render the chart.
    """
    # Asset and phase info
    asset: str
    phase: str
    reference_phase: Optional[str] = None
    
    # Range data
    range_high: Optional[Decimal] = None
    range_low: Optional[Decimal] = None
    tick_size: Optional[Decimal] = None
    min_breakout_ticks: int = 1
    breakout_long_level: Optional[Decimal] = None
    breakout_short_level: Optional[Decimal] = None
    
    # Trend indicator
    trend: TrendType = "sideways"
    
    # Price history (list of dicts with 'ts' and 'price' keys)
    prices: List[Dict[str, Any]] = field(default_factory=list)
    
    # Error message if data unavailable
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/JSON responses."""
        return {
            'asset': self.asset,
            'phase': self.phase,
            'reference_phase': self.reference_phase,
            'range': {
                'high': float(self.range_high) if self.range_high is not None else None,
                'low': float(self.range_low) if self.range_low is not None else None,
                'tick_size': float(self.tick_size) if self.tick_size is not None else None,
                'min_breakout_ticks': self.min_breakout_ticks,
                'breakout_long_level': float(self.breakout_long_level) if self.breakout_long_level is not None else None,
                'breakout_short_level': float(self.breakout_short_level) if self.breakout_short_level is not None else None,
            },
            'trend': self.trend,
            'prices': self.prices,
            'error': self.error,
        }


def _time_to_minutes(time_str: str) -> Optional[int]:
    """Convert HH:MM time string to minutes since midnight."""

    try:
        hours, minutes = map(int, time_str.split(":"))
        return hours * 60 + minutes
    except Exception:
        return None


def get_reference_phase(asset: TradingAsset, phase: str) -> Optional[str]:
    """
    Get the reference phase for a given trading phase.

    Prefers the asset's configured session phases (with custom time windows)
    to determine the most recent range-building phase before the current one.
    Falls back to the default REFERENCE_PHASE_MAPPING when no configuration is
    available for the asset or phase.

    Args:
        asset: TradingAsset instance for which the phase mapping is evaluated
        phase: Current trading phase (e.g., 'LONDON_CORE', 'US_CORE_TRADING')

    Returns:
        Reference phase code (e.g., 'ASIA_RANGE', 'PRE_US_RANGE') or None
    """

    if phase not in REFERENCE_PHASE_MAPPING:
        return None

    try:
        phase_configs = list(AssetSessionPhaseConfig.get_enabled_phases_for_asset(asset))
    except Exception:
        phase_configs = []

    if not phase_configs:
        return REFERENCE_PHASE_MAPPING.get(phase)

    current_config = next((cfg for cfg in phase_configs if cfg.phase == phase), None)
    if not current_config:
        return REFERENCE_PHASE_MAPPING.get(phase)

    def sort_key(cfg: AssetSessionPhaseConfig) -> int:
        minutes = _time_to_minutes(cfg.start_time_utc)
        return minutes if minutes is not None else (24 * 60 + 1)

    sorted_configs = sorted(phase_configs, key=sort_key)

    try:
        current_index = sorted_configs.index(current_config)
    except ValueError:
        return REFERENCE_PHASE_MAPPING.get(phase)

    total_configs = len(sorted_configs)
    for offset in range(1, total_configs + 1):
        previous_config = sorted_configs[(current_index - offset) % total_configs]
        if (
            previous_config.is_range_build_phase
            and previous_config.enabled
            and previous_config.phase != phase
        ):
            return previous_config.phase

    return REFERENCE_PHASE_MAPPING.get(phase)


def compute_trend(prices: List[Dict[str, Any]], tick_size: Decimal, threshold_ticks: int = DEFAULT_TREND_THRESHOLD_TICKS) -> TrendType:
    """
    Compute the trend based on price movement over the time window.
    
    Args:
        prices: List of price dicts with 'price' key
        tick_size: Size of one tick
        threshold_ticks: Minimum movement in ticks to be considered up/down
        
    Returns:
        'up', 'down', or 'sideways'
    """
    if not prices or len(prices) < 2:
        return "sideways"
    
    # Get first and last prices, skip if missing
    first_price = prices[0].get('price')
    last_price = prices[-1].get('price')
    
    if first_price is None or last_price is None:
        return "sideways"
    
    price_start = Decimal(str(first_price))
    price_end = Decimal(str(last_price))
    
    # Calculate change in price and ticks
    price_change = price_end - price_start
    threshold = Decimal(threshold_ticks) * tick_size
    
    if price_change > threshold:
        return "up"
    elif price_change < -threshold:
        return "down"
    else:
        return "sideways"


def get_breakout_distance_chart_data(
    asset: TradingAsset,
    phase: str,
    trend_threshold_ticks: int = DEFAULT_TREND_THRESHOLD_TICKS,
) -> BreakoutDistanceChartData:
    """
    Get breakout distance chart data for an asset and phase.
    
    Args:
        asset: TradingAsset instance
        phase: Current trading phase
        trend_threshold_ticks: Minimum movement to be considered up/down
        
    Returns:
        BreakoutDistanceChartData with chart data or error message
    """
    # Initialize result
    result = BreakoutDistanceChartData(
        asset=asset.symbol,
        phase=phase,
        tick_size=asset.tick_size,
    )
    
    # Get reference phase
    reference_phase = get_reference_phase(asset, phase)
    result.reference_phase = reference_phase
    
    if reference_phase is None:
        result.error = f"No breakout distance chart available for phase '{phase}'."
        return result
    
    # Get reference range
    range_data = BreakoutRange.get_latest_for_asset_phase(asset, reference_phase)
    
    if range_data is None:
        result.error = f"No reference range available for {reference_phase}."
        return result
    
    # Populate range data
    result.range_high = range_data.effective_high
    result.range_low = range_data.effective_low
    
    # Get min breakout distance from asset config
    min_breakout_ticks = 1  # Default
    try:
        breakout_config = asset.breakout_config
        min_breakout_ticks = breakout_config.min_breakout_distance_ticks or 1
    except AttributeError:
        pass
    
    result.min_breakout_ticks = min_breakout_ticks
    
    # Calculate breakout levels
    tick_size = asset.tick_size if asset.tick_size and asset.tick_size > 0 else DEFAULT_TICK_SIZE
    breakout_distance = Decimal(min_breakout_ticks) * tick_size
    
    result.breakout_long_level = result.range_high + breakout_distance
    result.breakout_short_level = result.range_low - breakout_distance
    
    # Get price history for last 60 minutes
    price_snapshots = PriceSnapshot.get_recent_for_asset(asset, minutes=PRICE_HISTORY_MINUTES)
    
    if not price_snapshots.exists():
        result.error = "No recent price data available for this asset/phase."
        return result
    
    # Convert to list of dicts
    result.prices = [snapshot.to_dict() for snapshot in price_snapshots]
    
    # Compute trend
    result.trend = compute_trend(result.prices, tick_size, trend_threshold_ticks)
    
    return result


def get_breakout_distance_chart_data_by_code(
    asset_code: str,
    phase: str,
) -> BreakoutDistanceChartData:
    """
    Get breakout distance chart data by asset code (symbol).
    
    Args:
        asset_code: Asset symbol (e.g., 'OIL', 'NAS100')
        phase: Current trading phase
        
    Returns:
        BreakoutDistanceChartData with chart data or error message
    """
    try:
        asset = TradingAsset.objects.get(symbol__iexact=asset_code, is_active=True)
    except TradingAsset.DoesNotExist:
        return BreakoutDistanceChartData(
            asset=asset_code,
            phase=phase,
            error=f"Asset '{asset_code}' not found or not active.",
        )
    
    return get_breakout_distance_chart_data(asset, phase)
