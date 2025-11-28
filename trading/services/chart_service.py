"""
Chart Service for Breakout Distance Chart.

Provides data for the interactive Breakout Distance Chart including:
- 5-minute candlestick data
- Session ranges with phase-offset visualization
- Breakout context (current range, breakout levels, distances)
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal

from django.utils import timezone

from ..models import TradingAsset, BreakoutRange, PriceSnapshot, AssetPriceStatus


# Supported time windows in hours
SUPPORTED_TIME_WINDOWS = [1, 3, 6, 8, 12, 24]

# Session phase definitions with time boundaries (UTC hours)
SESSION_DEFINITIONS = {
    'ASIA_RANGE': {'start': 0, 'end': 8, 'color': 'rgba(255, 193, 7, 0.2)'},
    'LONDON_CORE': {'start': 8, 'end': 11, 'color': 'rgba(59, 130, 246, 0.2)'},
    'PRE_US_RANGE': {'start': 13, 'end': 15, 'color': 'rgba(168, 85, 247, 0.2)'},
    'US_CORE_TRADING': {'start': 15, 'end': 22, 'color': 'rgba(34, 197, 94, 0.2)'},
}

# Reference phase mapping for breakout visualization
REFERENCE_PHASE_MAPPING = {
    'LONDON_CORE': 'ASIA_RANGE',
    'US_CORE_TRADING': 'PRE_US_RANGE',
    'PRE_US_RANGE': 'ASIA_RANGE',
}


@dataclass
class CandleData:
    """5-minute candlestick data."""
    time: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float

    def to_dict(self) -> dict:
        return {
            'time': self.time,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
        }


@dataclass
class SessionRangeData:
    """Session range data for visualization."""
    phase: str
    phase_display: str
    high: Optional[float] = None
    low: Optional[float] = None
    start_time: Optional[int] = None  # Unix timestamp
    end_time: Optional[int] = None  # Unix timestamp
    is_valid: bool = False
    color: str = 'rgba(128, 128, 128, 0.2)'

    def to_dict(self) -> dict:
        return {
            'phase': self.phase,
            'phase_display': self.phase_display,
            'high': self.high,
            'low': self.low,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'is_valid': self.is_valid,
            'color': self.color,
        }


@dataclass
class BreakoutContextData:
    """Breakout context with range and level data."""
    phase: str
    reference_phase: Optional[str] = None
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    breakout_long_level: Optional[float] = None
    breakout_short_level: Optional[float] = None
    current_price: Optional[float] = None
    distance_to_high_ticks: Optional[int] = None
    distance_to_low_ticks: Optional[int] = None
    tick_size: float = 0.01
    is_above_range: bool = False
    is_below_range: bool = False
    is_inside_range: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'phase': self.phase,
            'reference_phase': self.reference_phase,
            'range_high': self.range_high,
            'range_low': self.range_low,
            'breakout_long_level': self.breakout_long_level,
            'breakout_short_level': self.breakout_short_level,
            'current_price': self.current_price,
            'distance_to_high_ticks': self.distance_to_high_ticks,
            'distance_to_low_ticks': self.distance_to_low_ticks,
            'tick_size': self.tick_size,
            'is_above_range': self.is_above_range,
            'is_below_range': self.is_below_range,
            'is_inside_range': self.is_inside_range,
            'error': self.error,
        }


@dataclass
class ChartCandlesResponse:
    """Response for candles endpoint."""
    asset: str
    timeframe: str = '5m'
    hours: int = 1
    candles: List[CandleData] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'asset': self.asset,
            'timeframe': self.timeframe,
            'hours': self.hours,
            'candle_count': len(self.candles),
            'candles': [c.to_dict() for c in self.candles],
            'error': self.error,
        }


@dataclass
class SessionRangesResponse:
    """Response for session ranges endpoint."""
    asset: str
    hours: int = 1
    ranges: Dict[str, SessionRangeData] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'asset': self.asset,
            'hours': self.hours,
            'ranges': {k: v.to_dict() for k, v in self.ranges.items()},
            'error': self.error,
        }


def get_asset_by_symbol(symbol: str) -> Optional[TradingAsset]:
    """Get asset by symbol (case-insensitive)."""
    try:
        return TradingAsset.objects.get(symbol__iexact=symbol, is_active=True)
    except TradingAsset.DoesNotExist:
        return None


def get_candles_for_asset(
    asset: TradingAsset,
    hours: int = 1,
    timeframe: str = '5m',
) -> ChartCandlesResponse:
    """
    Get candlestick data for an asset.
    
    Since IG API may not provide historical candle data easily,
    we generate candles from PriceSnapshot data or create simulated
    data for demonstration purposes.
    
    Args:
        asset: TradingAsset instance
        hours: Number of hours of history (1, 3, 6, 8, 12, 24)
        timeframe: Candle timeframe (currently only '5m' supported)
    
    Returns:
        ChartCandlesResponse with candle data
    """
    if hours not in SUPPORTED_TIME_WINDOWS:
        hours = min(SUPPORTED_TIME_WINDOWS, key=lambda x: abs(x - hours))

    now = timezone.now()
    start_time = now - timedelta(hours=hours)

    # Get price snapshots from the database
    snapshots = PriceSnapshot.objects.filter(
        asset=asset,
        timestamp__gte=start_time,
    ).order_by('timestamp')

    if not snapshots.exists():
        # Generate simulated candles for demo purposes
        return _generate_simulated_candles(asset, hours, start_time, now)

    # Aggregate snapshots into 5-minute candles
    candles = _aggregate_snapshots_to_candles(list(snapshots), timeframe_minutes=5)

    return ChartCandlesResponse(
        asset=asset.symbol,
        timeframe=timeframe,
        hours=hours,
        candles=candles,
    )


def _aggregate_snapshots_to_candles(
    snapshots: List[PriceSnapshot],
    timeframe_minutes: int = 5,
) -> List[CandleData]:
    """Aggregate price snapshots into OHLC candles."""
    if not snapshots:
        return []

    candles = []
    current_bucket_start = None
    bucket_prices = []

    for snapshot in snapshots:
        ts = snapshot.timestamp
        # Round down to nearest bucket
        bucket_start = ts.replace(
            minute=(ts.minute // timeframe_minutes) * timeframe_minutes,
            second=0,
            microsecond=0,
        )

        if current_bucket_start is None:
            current_bucket_start = bucket_start
            bucket_prices = [float(snapshot.price_mid)]
        elif bucket_start == current_bucket_start:
            bucket_prices.append(float(snapshot.price_mid))
        else:
            # New bucket - finalize previous candle
            if bucket_prices:
                candle = CandleData(
                    time=int(current_bucket_start.timestamp()),
                    open=bucket_prices[0],
                    high=max(bucket_prices),
                    low=min(bucket_prices),
                    close=bucket_prices[-1],
                )
                candles.append(candle)

            current_bucket_start = bucket_start
            bucket_prices = [float(snapshot.price_mid)]

    # Finalize last bucket
    if bucket_prices and current_bucket_start:
        candle = CandleData(
            time=int(current_bucket_start.timestamp()),
            open=bucket_prices[0],
            high=max(bucket_prices),
            low=min(bucket_prices),
            close=bucket_prices[-1],
        )
        candles.append(candle)

    return candles


def _generate_simulated_candles(
    asset: TradingAsset,
    hours: int,
    start_time: datetime,
    end_time: datetime,
) -> ChartCandlesResponse:
    """
    Generate simulated candle data for demonstration.
    
    Uses the current price (if available) or a base price, then generates
    random-walk candles to show realistic chart behavior.
    """
    import random

    # Try to get current price from price status
    base_price = 75.0  # Default fallback for oil
    tick_size = float(asset.tick_size) if asset.tick_size else 0.01

    try:
        price_status = AssetPriceStatus.get_for_asset(asset)
        if price_status and price_status.bid_price:
            base_price = float(price_status.bid_price)
    except Exception:
        pass

    # Try to get range data for realistic price levels
    latest_range = BreakoutRange.get_latest_for_asset_phase(asset, 'ASIA_RANGE')
    if latest_range:
        base_price = float((latest_range.high + latest_range.low) / 2)

    candles = []
    current_time = start_time
    current_price = base_price

    # Volatility as percentage of base price
    volatility = 0.001  # 0.1% per candle

    while current_time < end_time:
        # Generate random OHLC
        change = random.gauss(0, base_price * volatility)
        open_price = current_price
        close_price = current_price + change

        # Generate high and low with some wicks
        wick_size = abs(change) * random.uniform(0.2, 0.8) if change != 0 else base_price * volatility * 0.5

        if close_price > open_price:
            high_price = close_price + wick_size * random.uniform(0, 0.5)
            low_price = open_price - wick_size * random.uniform(0, 0.5)
        else:
            high_price = open_price + wick_size * random.uniform(0, 0.5)
            low_price = close_price - wick_size * random.uniform(0, 0.5)

        candle = CandleData(
            time=int(current_time.timestamp()),
            open=round(open_price, 4),
            high=round(high_price, 4),
            low=round(low_price, 4),
            close=round(close_price, 4),
        )
        candles.append(candle)

        current_price = close_price
        current_time += timedelta(minutes=5)

    return ChartCandlesResponse(
        asset=asset.symbol,
        timeframe='5m',
        hours=hours,
        candles=candles,
    )


def get_session_ranges_for_asset(
    asset: TradingAsset,
    hours: int = 1,
) -> SessionRangesResponse:
    """
    Get session ranges for an asset.
    
    This returns the high/low ranges for each session phase (Asia, London, US Core)
    within the requested time window. These ranges are offset by one phase,
    e.g., Asia range is displayed during London Core session.
    
    Args:
        asset: TradingAsset instance
        hours: Number of hours to look back for range data
    
    Returns:
        SessionRangesResponse with range data per session
    """
    if hours not in SUPPORTED_TIME_WINDOWS:
        hours = min(SUPPORTED_TIME_WINDOWS, key=lambda x: abs(x - hours))

    now = timezone.now()
    lookback = now - timedelta(hours=max(hours, 24))  # Always look back at least 24h for ranges

    ranges = {}
    phase_display_names = {
        'ASIA_RANGE': 'Asia Range',
        'LONDON_CORE': 'London Core',
        'PRE_US_RANGE': 'Pre-US Range',
        'US_CORE_TRADING': 'US Core Trading',
    }

    for phase, definition in SESSION_DEFINITIONS.items():
        # Get the latest range for this phase
        range_data = BreakoutRange.objects.filter(
            asset=asset,
            phase=phase,
            end_time__gte=lookback,
        ).order_by('-end_time').first()

        session_range = SessionRangeData(
            phase=phase,
            phase_display=phase_display_names.get(phase, phase),
            color=definition['color'],
        )

        if range_data:
            session_range.high = float(range_data.high)
            session_range.low = float(range_data.low)
            session_range.start_time = int(range_data.start_time.timestamp()) if range_data.start_time else None
            session_range.end_time = int(range_data.end_time.timestamp()) if range_data.end_time else None
            session_range.is_valid = range_data.is_valid

        ranges[phase] = session_range

    return SessionRangesResponse(
        asset=asset.symbol,
        hours=hours,
        ranges=ranges,
    )


def get_breakout_context_for_asset(
    asset: TradingAsset,
) -> BreakoutContextData:
    """
    Get breakout context data for an asset.
    
    Returns the current range, breakout levels, and distance calculations
    for real-time visualization.
    
    Args:
        asset: TradingAsset instance
    
    Returns:
        BreakoutContextData with range, levels, and distances
    """
    now = timezone.now()
    current_hour = now.hour
    tick_size = float(asset.tick_size) if asset.tick_size else 0.01

    # Determine current phase based on time
    current_phase = 'OTHER'
    for phase, definition in SESSION_DEFINITIONS.items():
        if definition['start'] <= current_hour < definition['end']:
            current_phase = phase
            break

    # Get reference phase for breakout levels
    reference_phase = REFERENCE_PHASE_MAPPING.get(current_phase)

    context = BreakoutContextData(
        phase=current_phase,
        reference_phase=reference_phase,
        tick_size=tick_size,
    )

    if not reference_phase:
        context.error = f"No reference range available for phase '{current_phase}'"
        return context

    # Get the reference range
    lookback = now - timedelta(hours=24)
    range_data = BreakoutRange.objects.filter(
        asset=asset,
        phase=reference_phase,
        end_time__gte=lookback,
    ).order_by('-end_time').first()

    if not range_data:
        context.error = f"No {reference_phase} range data available"
        return context

    context.range_high = float(range_data.high)
    context.range_low = float(range_data.low)

    # Calculate breakout levels
    min_breakout_ticks = 1
    try:
        breakout_config = asset.breakout_config
        min_breakout_ticks = breakout_config.min_breakout_distance_ticks or 1
    except Exception:
        pass

    breakout_distance = min_breakout_ticks * tick_size
    context.breakout_long_level = context.range_high + breakout_distance
    context.breakout_short_level = context.range_low - breakout_distance

    # Get current price
    try:
        price_status = AssetPriceStatus.get_for_asset(asset)
        if price_status and price_status.bid_price and price_status.ask_price:
            context.current_price = float((price_status.bid_price + price_status.ask_price) / 2)
        elif price_status and price_status.bid_price:
            context.current_price = float(price_status.bid_price)
    except Exception:
        pass

    # Calculate distances
    if context.current_price is not None:
        distance_to_high = context.range_high - context.current_price
        distance_to_low = context.current_price - context.range_low

        context.distance_to_high_ticks = int(distance_to_high / tick_size)
        context.distance_to_low_ticks = int(distance_to_low / tick_size)

        # Determine position relative to range
        if context.current_price > context.range_high:
            context.is_above_range = True
            context.is_inside_range = False
        elif context.current_price < context.range_low:
            context.is_below_range = True
            context.is_inside_range = False
        else:
            context.is_inside_range = True

    return context
