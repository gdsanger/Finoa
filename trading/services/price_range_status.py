"""
Price vs Range - Live Status Service.

Provides data structures and computation logic for the "Price vs Range – Live Status"
transparency feature in the Trading Diagnostics / Sanity & Confidence Layer.

This is a pure transparency feature - no trading logic involved.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Optional

from ..models import BreakoutRange, TradingAsset, WorkerStatus


# Status code type alias
StatusCode = Literal[
    "NO_RANGE",
    "INSIDE_RANGE",
    "NEAR_BREAKOUT_LONG",
    "NEAR_BREAKOUT_SHORT",
    "BREAKOUT_LONG",
    "BREAKOUT_SHORT",
]

# Status display text mapping
STATUS_TEXTS = {
    "NO_RANGE": "NO RANGE DATA",
    "INSIDE_RANGE": "INSIDE RANGE",
    "NEAR_BREAKOUT_LONG": "NEAR BREAKOUT (LONG)",
    "NEAR_BREAKOUT_SHORT": "NEAR BREAKOUT (SHORT)",
    "BREAKOUT_LONG": "BREAKOUT LONG",
    "BREAKOUT_SHORT": "BREAKOUT SHORT",
}

# Badge colors for status codes
STATUS_BADGE_COLORS = {
    "NO_RANGE": "gray",       # ⚪
    "INSIDE_RANGE": "green",  # 🟩
    "NEAR_BREAKOUT_LONG": "yellow",   # 🟨
    "NEAR_BREAKOUT_SHORT": "yellow",  # 🟨
    "BREAKOUT_LONG": "red",    # 🟥
    "BREAKOUT_SHORT": "red",   # 🟥
}


@dataclass
class PriceRangeStatus:
    """
    Data model for the "Price vs Range – Live Status" panel.
    
    Contains all information needed to display the current price
    position relative to the range for a specific asset and phase.
    """
    asset: str
    phase: str
    range_high: Optional[Decimal] = None
    range_low: Optional[Decimal] = None
    range_ticks: Optional[int] = None
    tick_size: Optional[Decimal] = None
    current_bid: Optional[Decimal] = None
    current_ask: Optional[Decimal] = None
    distance_to_high_ticks: Optional[int] = None
    distance_to_low_ticks: Optional[int] = None
    min_breakout_distance_ticks: Optional[int] = None
    status_code: StatusCode = "NO_RANGE"
    status_text: str = "NO RANGE DATA"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/JSON responses."""
        return {
            'asset': self.asset,
            'phase': self.phase,
            'range_high': str(self.range_high) if self.range_high is not None else None,
            'range_low': str(self.range_low) if self.range_low is not None else None,
            'range_ticks': self.range_ticks,
            'tick_size': str(self.tick_size) if self.tick_size is not None else None,
            'current_bid': str(self.current_bid) if self.current_bid is not None else None,
            'current_ask': str(self.current_ask) if self.current_ask is not None else None,
            'distance_to_high_ticks': self.distance_to_high_ticks,
            'distance_to_low_ticks': self.distance_to_low_ticks,
            'min_breakout_distance_ticks': self.min_breakout_distance_ticks,
            'status_code': self.status_code,
            'status_text': self.status_text,
            'badge_color': STATUS_BADGE_COLORS.get(self.status_code, 'gray'),
        }


def compute_price_range_status(
    asset: TradingAsset,
    phase: str,
    worker_status: Optional[WorkerStatus] = None,
) -> PriceRangeStatus:
    """
    Compute the price vs range status for a given asset and phase.
    
    Uses persisted range snapshots and worker status price data.
    No IG API calls are made - data comes from persistence layer only.
    
    Args:
        asset: The trading asset to compute status for.
        phase: The session phase ('ASIA_RANGE', 'LONDON_CORE', 'PRE_US_RANGE', 'US_CORE_TRADING').
        worker_status: Optional worker status for current price data.
            If not provided, will be fetched from database.
    
    Returns:
        PriceRangeStatus with computed values and status code.
    """
    # Initialize with basic info
    status = PriceRangeStatus(
        asset=asset.symbol,
        phase=phase,
        tick_size=asset.tick_size,
    )
    
    # Get worker status for current price if not provided
    if worker_status is None:
        worker_status = WorkerStatus.get_current()
    
    # Get min breakout distance from asset config
    min_breakout_distance_ticks = 1  # Default
    try:
        breakout_config = asset.breakout_config
        min_breakout_distance_ticks = breakout_config.min_breakout_distance_ticks or 1
    except Exception:
        pass
    
    status.min_breakout_distance_ticks = min_breakout_distance_ticks
    
    # Get persisted range for this asset and phase
    range_data = BreakoutRange.get_latest_for_asset_phase(asset, phase)
    
    if range_data is None:
        # No range data available
        status.status_code = "NO_RANGE"
        status.status_text = STATUS_TEXTS["NO_RANGE"]
        return status
    
    # Populate range data
    status.range_high = range_data.high
    status.range_low = range_data.low
    status.range_ticks = range_data.height_ticks
    
    # Get current price from worker status
    if worker_status and worker_status.bid_price and worker_status.ask_price:
        status.current_bid = worker_status.bid_price
        status.current_ask = worker_status.ask_price
    else:
        # No price data - can't compute status
        status.status_code = "NO_RANGE"
        status.status_text = STATUS_TEXTS["NO_RANGE"]
        return status
    
    # Calculate distances in ticks
    tick_size = asset.tick_size if asset.tick_size > 0 else Decimal('0.01')
    
    # Distance to high: how far is bid from range high
    # Positive = bid is below high, negative = bid is above high
    distance_to_high = status.range_high - status.current_bid
    status.distance_to_high_ticks = int(distance_to_high / tick_size)
    
    # Distance to low: how far is ask from range low
    # Positive = ask is above low, negative = ask is below low
    distance_to_low = status.current_ask - status.range_low
    status.distance_to_low_ticks = int(distance_to_low / tick_size)
    
    # Determine status based on price position
    status.status_code, status.status_text = _compute_status_code(
        bid=status.current_bid,
        ask=status.current_ask,
        range_high=status.range_high,
        range_low=status.range_low,
        min_breakout_distance_ticks=min_breakout_distance_ticks,
        tick_size=tick_size,
    )
    
    return status


def _compute_status_code(
    bid: Decimal,
    ask: Decimal,
    range_high: Decimal,
    range_low: Decimal,
    min_breakout_distance_ticks: int,
    tick_size: Decimal,
) -> tuple[StatusCode, str]:
    """
    Compute the status code based on price position relative to range.
    
    Status logic (matching Worker behavior):
    1. NO_RANGE → Wenn Range nicht vorhanden (handled in calling function)
    2. INSIDE RANGE → bid ≤ high AND ask ≥ low
    3. NEAR BREAKOUT LONG → distance_to_high ≤ min_breakout_distance
    4. NEAR BREAKOUT SHORT → distance_to_low ≤ min_breakout_distance
    5. BREAKOUT LONG → bid > high + min_breakout_distance
    6. BREAKOUT SHORT → ask < low − min_breakout_distance
    
    Args:
        bid: Current bid price.
        ask: Current ask price.
        range_high: Range high price.
        range_low: Range low price.
        min_breakout_distance_ticks: Minimum breakout distance in ticks.
        tick_size: Tick size for the asset.
    
    Returns:
        Tuple of (status_code, status_text).
    """
    min_breakout_distance = Decimal(min_breakout_distance_ticks) * tick_size
    
    # Calculate distances
    distance_to_high = range_high - bid  # Positive = bid below high
    distance_to_low = ask - range_low     # Positive = ask above low
    distance_to_high_ticks = int(distance_to_high / tick_size)
    distance_to_low_ticks = int(distance_to_low / tick_size)
    
    # Check BREAKOUT conditions first (price clearly outside range)
    if bid > range_high + min_breakout_distance:
        return "BREAKOUT_LONG", STATUS_TEXTS["BREAKOUT_LONG"]
    
    if ask < range_low - min_breakout_distance:
        return "BREAKOUT_SHORT", STATUS_TEXTS["BREAKOUT_SHORT"]
    
    # Check NEAR BREAKOUT conditions (price approaching boundary)
    # Near breakout long: bid close to or above high, but not full breakout
    if distance_to_high_ticks <= min_breakout_distance_ticks and bid >= range_low:
        return "NEAR_BREAKOUT_LONG", STATUS_TEXTS["NEAR_BREAKOUT_LONG"]
    
    # Near breakout short: ask close to or below low, but not full breakout  
    if distance_to_low_ticks <= min_breakout_distance_ticks and ask <= range_high:
        return "NEAR_BREAKOUT_SHORT", STATUS_TEXTS["NEAR_BREAKOUT_SHORT"]
    
    # Check INSIDE RANGE condition
    # Inside range: bid ≤ high AND ask ≥ low
    if bid <= range_high and ask >= range_low:
        return "INSIDE_RANGE", STATUS_TEXTS["INSIDE_RANGE"]
    
    # Fallback to NO_RANGE for edge cases
    return "NO_RANGE", STATUS_TEXTS["NO_RANGE"]


# Phase display names mapping
PHASE_DISPLAY_NAMES = {
    'ASIA_RANGE': 'Asia',
    'LONDON_CORE': 'London',
    'PRE_US_RANGE': 'Pre-US',
    'US_CORE_TRADING': 'US Core',
}


def get_phase_display_name(phase: str) -> str:
    """Get a human-readable display name for a phase."""
    return PHASE_DISPLAY_NAMES.get(phase, phase)
