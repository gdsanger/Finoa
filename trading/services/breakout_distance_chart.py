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

from ..models import TradingAsset, BreakoutRange, AssetPriceStatus, PriceSnapshot


# Trend type alias
TrendType = Literal["up", "down", "sideways"]

# Reference phase mapping: which phase's range to use for each trading phase
REFERENCE_PHASE_MAPPING = {
    'LONDON_CORE': 'ASIA_RANGE',
    'US_CORE_TRADING': 'PRE_US_RANGE',
    'PRE_US_RANGE': 'ASIA_RANGE',
    'EIA_PRE': 'PRE_US_RANGE',
    'EIA_POST': 'PRE_US_RANGE',
}

# Default trend threshold in ticks (price must move more than this to be up/down)
DEFAULT_TREND_THRESHOLD_TICKS = 15

# Price history window in minutes
PRICE_HISTORY_MINUTES = 60


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


def get_reference_phase(phase: str) -> Optional[str]:
    """
    Get the reference phase for a given trading phase.
    
    Args:
        phase: Current trading phase (e.g., 'LONDON_CORE', 'US_CORE_TRADING')
        
    Returns:
        Reference phase code (e.g., 'ASIA_RANGE', 'PRE_US_RANGE') or None
    """
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
    
    # Get first and last prices
    price_start = Decimal(str(prices[0].get('price', 0)))
    price_end = Decimal(str(prices[-1].get('price', 0)))
    
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
    reference_phase = get_reference_phase(phase)
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
    result.range_high = range_data.high
    result.range_low = range_data.low
    
    # Get min breakout distance from asset config
    min_breakout_ticks = 1  # Default
    try:
        breakout_config = asset.breakout_config
        min_breakout_ticks = breakout_config.min_breakout_distance_ticks or 1
    except AttributeError:
        pass
    
    result.min_breakout_ticks = min_breakout_ticks
    
    # Calculate breakout levels
    tick_size = asset.tick_size if asset.tick_size and asset.tick_size > 0 else Decimal('0.01')
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
