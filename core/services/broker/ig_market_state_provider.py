"""
IG Market State Provider for Fiona Strategy Engine.

Implements the MarketStateProvider protocol using the IG Broker Service
to fetch real market data.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.services.strategy.models import Candle, SessionPhase
from core.services.strategy.providers import BaseMarketStateProvider
from .ig_broker_service import IgBrokerService


logger = logging.getLogger(__name__)


# Default session phase time boundaries (UTC)
# Asia session: 00:00 - 08:00 UTC
# London session: 08:00 - 15:00 UTC (core: 08:00 - 11:00)
# Pre-US Range: 13:00 - 15:00 UTC (range formation only)
# US Core Trading: 15:00 - 22:00 UTC (breakouts allowed)
# EIA release: typically Wednesday 15:30 UTC
DEFAULT_SESSION_TIMES = {
    'asia_start': 0,   # 00:00 UTC
    'asia_end': 8,     # 08:00 UTC
    'london_core_start': 8,   # 08:00 UTC
    'london_core_end': 11,    # 11:00 UTC
    'pre_us_start': 13,       # 13:00 UTC (Pre-US Range start)
    'pre_us_end': 15,         # 15:00 UTC (Pre-US Range end)
    'us_core_trading_start': 15,  # 15:00 UTC (US Core Trading start)
    'us_core_trading_end': 22,    # 22:00 UTC (US Core Trading end)
    'us_core_start': 14,      # 14:00 UTC (deprecated, for backwards compat)
    'us_core_end': 17,        # 17:00 UTC (deprecated, for backwards compat)
    'friday_late': 21,        # 21:00 UTC
}

# Keep alias for backwards compatibility
SESSION_TIMES = DEFAULT_SESSION_TIMES


@dataclass
class SessionTimesConfig:
    """
    Configurable session time boundaries.
    
    Times are in hours (0-23) for start/end, or (hour, minute) tuples
    for more precise control.
    
    The US session is split into two phases:
    - Pre-US Range (13:00-15:00 UTC): Range formation only, no breakouts
    - US Core Trading (15:00-22:00 UTC): Trading allowed, breakouts enabled
    """
    asia_start: int = 0         # 00:00 UTC
    asia_end: int = 8           # 08:00 UTC
    london_core_start: int = 8  # 08:00 UTC
    london_core_end: int = 11   # 11:00 UTC
    
    # Pre-US Range (range formation only)
    pre_us_start: int = 13      # 13:00 UTC
    pre_us_end: int = 15        # 15:00 UTC
    
    # US Core Trading session (breakouts allowed)
    us_core_trading_start: int = 15  # 15:00 UTC
    us_core_trading_end: int = 22    # 22:00 UTC
    us_core_trading_enabled: bool = True
    
    # Deprecated: kept for backwards compatibility
    us_core_start: int = 14     # 14:00 UTC
    us_core_end: int = 17       # 17:00 UTC
    
    friday_late: int = 21       # 21:00 UTC
    
    # Optional minute-level precision (0-59)
    asia_start_minute: int = 0
    asia_end_minute: int = 0
    london_core_start_minute: int = 0
    london_core_end_minute: int = 0
    pre_us_start_minute: int = 0
    pre_us_end_minute: int = 0
    us_core_trading_start_minute: int = 0
    us_core_trading_end_minute: int = 0
    us_core_start_minute: int = 0
    us_core_end_minute: int = 0
    
    @classmethod
    def from_time_strings(
        cls,
        asia_start: str = "00:00",
        asia_end: str = "08:00",
        london_core_start: str = "08:00",
        london_core_end: str = "11:00",
        pre_us_start: str = "13:00",
        pre_us_end: str = "15:00",
        us_core_trading_start: str = "15:00",
        us_core_trading_end: str = "22:00",
        us_core_trading_enabled: bool = True,
        us_core_start: str = "14:00",
        us_core_end: str = "17:00",
        friday_late: int = 21,
    ) -> 'SessionTimesConfig':
        """
        Create SessionTimesConfig from HH:MM time strings.
        
        Args:
            asia_start: Asia range start (HH:MM format, e.g., "00:00")
            asia_end: Asia range end (HH:MM format, e.g., "08:00")
            london_core_start: London core start (HH:MM format)
            london_core_end: London core end (HH:MM format)
            pre_us_start: Pre-US range start (HH:MM format, default: "13:00")
            pre_us_end: Pre-US range end (HH:MM format, default: "15:00")
            us_core_trading_start: US Core Trading start (HH:MM format, default: "15:00")
            us_core_trading_end: US Core Trading end (HH:MM format, default: "22:00")
            us_core_trading_enabled: Whether trading is enabled in US Core Trading
            us_core_start: Deprecated, kept for backwards compatibility
            us_core_end: Deprecated, kept for backwards compatibility
            friday_late: Friday late cutoff hour
            
        Returns:
            SessionTimesConfig instance with parsed time values.
        """
        def parse_time(time_str: str) -> tuple[int, int]:
            """Parse HH:MM string to (hour, minute) tuple."""
            if ':' in time_str:
                parts = time_str.split(':')
                return int(parts[0]), int(parts[1])
            return int(time_str), 0
        
        asia_start_h, asia_start_m = parse_time(asia_start)
        asia_end_h, asia_end_m = parse_time(asia_end)
        london_start_h, london_start_m = parse_time(london_core_start)
        london_end_h, london_end_m = parse_time(london_core_end)
        pre_us_start_h, pre_us_start_m = parse_time(pre_us_start)
        pre_us_end_h, pre_us_end_m = parse_time(pre_us_end)
        us_trading_start_h, us_trading_start_m = parse_time(us_core_trading_start)
        us_trading_end_h, us_trading_end_m = parse_time(us_core_trading_end)
        us_start_h, us_start_m = parse_time(us_core_start)
        us_end_h, us_end_m = parse_time(us_core_end)
        
        return cls(
            asia_start=asia_start_h,
            asia_end=asia_end_h,
            london_core_start=london_start_h,
            london_core_end=london_end_h,
            pre_us_start=pre_us_start_h,
            pre_us_end=pre_us_end_h,
            us_core_trading_start=us_trading_start_h,
            us_core_trading_end=us_trading_end_h,
            us_core_trading_enabled=us_core_trading_enabled,
            us_core_start=us_start_h,
            us_core_end=us_end_h,
            friday_late=friday_late,
            asia_start_minute=asia_start_m,
            asia_end_minute=asia_end_m,
            london_core_start_minute=london_start_m,
            london_core_end_minute=london_end_m,
            pre_us_start_minute=pre_us_start_m,
            pre_us_end_minute=pre_us_end_m,
            us_core_trading_start_minute=us_trading_start_m,
            us_core_trading_end_minute=us_trading_end_m,
            us_core_start_minute=us_start_m,
            us_core_end_minute=us_end_m,
        )


class IGMarketStateProvider(BaseMarketStateProvider):
    """
    Market state provider using IG Broker Service.
    
    Provides real-time market data from IG for the Strategy Engine.
    Note: Some methods use cached/simulated data as IG API may not
    provide all required historical data in all scenarios.
    """

    def __init__(
        self,
        broker_service: IgBrokerService,
        eia_timestamp: Optional[datetime] = None,
        session_times: Optional[SessionTimesConfig] = None,
    ):
        """
        Initialize the IG Market State Provider.
        
        Args:
            broker_service: Connected IgBrokerService instance.
            eia_timestamp: Optional EIA release timestamp for current week.
            session_times: Optional custom session time configuration.
                          If not provided, uses default session times.
        """
        self._broker = broker_service
        self._eia_timestamp = eia_timestamp
        self._session_times = session_times or SessionTimesConfig()
        
        # Cache for session ranges
        self._asia_range_cache: dict[str, tuple[float, float]] = {}
        self._pre_us_range_cache: dict[str, tuple[float, float]] = {}
        
        # Cache for candles (limited history)
        self._candle_cache: dict[str, list[Candle]] = {}
        
        logger.info("IGMarketStateProvider initialized")
    
    def set_session_times(self, session_times: SessionTimesConfig) -> None:
        """
        Update the session time configuration.
        
        Args:
            session_times: New session time configuration.
        """
        self._session_times = session_times
        logger.info(f"Session times updated: US Core {session_times.us_core_start}:{session_times.us_core_start_minute:02d} - {session_times.us_core_end}:{session_times.us_core_end_minute:02d}")

    def get_phase(self, ts: datetime) -> SessionPhase:
        """
        Get the current market session phase for a given timestamp.
        
        Uses configurable session times from self._session_times.
        
        Args:
            ts: Timestamp to evaluate (should be UTC).
            
        Returns:
            SessionPhase indicating the current market phase.
        """
        # Ensure we're working with UTC
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        hour = ts.hour
        minute = ts.minute
        weekday = ts.weekday()
        
        # Helper to convert hour:minute to total minutes for comparison
        def to_minutes(h: int, m: int) -> int:
            return h * 60 + m
        
        current_time = to_minutes(hour, minute)
        cfg = self._session_times
        
        # Check EIA window first (takes priority)
        if self._eia_timestamp:
            eia_start = self._eia_timestamp - timedelta(minutes=5)
            eia_end = self._eia_timestamp + timedelta(minutes=30)
            
            if eia_start <= ts < self._eia_timestamp:
                return SessionPhase.EIA_PRE
            elif self._eia_timestamp <= ts <= eia_end:
                return SessionPhase.EIA_POST
        
        # Friday late restriction
        if weekday == 4 and hour >= cfg.friday_late:
            return SessionPhase.FRIDAY_LATE
        
        # Weekend
        if weekday >= 5:  # Saturday or Sunday
            return SessionPhase.OTHER
        
        # Asia Range (default: 00:00 - 08:00 UTC)
        asia_start = to_minutes(cfg.asia_start, cfg.asia_start_minute)
        asia_end = to_minutes(cfg.asia_end, cfg.asia_end_minute)
        if asia_start <= current_time < asia_end:
            return SessionPhase.ASIA_RANGE
        
        # London Core (default: 08:00 - 11:00 UTC)
        london_start = to_minutes(cfg.london_core_start, cfg.london_core_start_minute)
        london_end = to_minutes(cfg.london_core_end, cfg.london_core_end_minute)
        if london_start <= current_time < london_end:
            return SessionPhase.LONDON_CORE
        
        # Pre-US Range (default: 13:00 - 15:00 UTC) - Range formation only
        pre_us_start = to_minutes(cfg.pre_us_start, cfg.pre_us_start_minute)
        pre_us_end = to_minutes(cfg.pre_us_end, cfg.pre_us_end_minute)
        if pre_us_start <= current_time < pre_us_end:
            return SessionPhase.PRE_US_RANGE
        
        # US Core Trading (default: 15:00 - 22:00 UTC) - Trading allowed
        if cfg.us_core_trading_enabled:
            us_trading_start = to_minutes(cfg.us_core_trading_start, cfg.us_core_trading_start_minute)
            us_trading_end = to_minutes(cfg.us_core_trading_end, cfg.us_core_trading_end_minute)
            if us_trading_start <= current_time < us_trading_end:
                return SessionPhase.US_CORE_TRADING
        else:
            # Deprecated US Core (kept for backwards compatibility)
            # Only used if us_core_trading_enabled is False
            us_start = to_minutes(cfg.us_core_start, cfg.us_core_start_minute)
            us_end = to_minutes(cfg.us_core_end, cfg.us_core_end_minute)
            if us_start <= current_time < us_end:
                return SessionPhase.US_CORE
        
        return SessionPhase.OTHER

    def get_recent_candles(
        self,
        epic: str,
        timeframe: str,
        limit: int
    ) -> list[Candle]:
        """
        Get recent candles for a market.
        
        Note: IG API has limited historical data access via REST.
        This implementation returns cached/simulated candles or
        creates a single candle from current price data.
        
        Args:
            epic: Market identifier.
            timeframe: Candle timeframe (e.g., '1m', '5m', '1h').
            limit: Maximum number of candles to return.
            
        Returns:
            List of Candle objects, most recent last.
        """
        try:
            # Get current market data
            price = self._broker.get_symbol_price(epic)
            
            # Create a candle from current price data
            now = datetime.now(timezone.utc)
            current_candle = Candle(
                timestamp=now,
                open=float(price.mid_price),
                high=float(price.high) if price.high else float(price.mid_price),
                low=float(price.low) if price.low else float(price.mid_price),
                close=float(price.mid_price),
                volume=None,
            )
            
            # For now, return cached candles plus current
            cache_key = f"{epic}_{timeframe}"
            cached = self._candle_cache.get(cache_key, [])
            
            # Add current candle and limit
            candles = cached + [current_candle]
            candles = candles[-limit:]
            
            # Update cache
            self._candle_cache[cache_key] = candles[-50:]  # Keep last 50
            
            return candles
            
        except Exception as e:
            logger.warning(f"Failed to get candles for {epic}: {e}")
            return []

    def update_candle_from_price(self, epic: str, timeframe: str = '1m') -> None:
        """
        Update the candle cache with current price data.
        
        Call this periodically to build up candle history.
        
        Args:
            epic: Market identifier.
            timeframe: Candle timeframe.
        """
        try:
            price = self._broker.get_symbol_price(epic)
            now = datetime.now(timezone.utc)
            
            candle = Candle(
                timestamp=now,
                open=float(price.mid_price),
                high=float(price.high) if price.high else float(price.mid_price),
                low=float(price.low) if price.low else float(price.mid_price),
                close=float(price.mid_price),
                volume=None,
            )
            
            cache_key = f"{epic}_{timeframe}"
            if cache_key not in self._candle_cache:
                self._candle_cache[cache_key] = []
            
            self._candle_cache[cache_key].append(candle)
            # Keep last 100 candles
            self._candle_cache[cache_key] = self._candle_cache[cache_key][-100:]
            
        except Exception as e:
            logger.warning(f"Failed to update candle for {epic}: {e}")

    def get_daily_high_low(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the current day's high and low prices.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        try:
            price = self._broker.get_symbol_price(epic)
            if price.high is not None and price.low is not None:
                return (float(price.high), float(price.low))
            return None
        except Exception as e:
            logger.warning(f"Failed to get daily high/low for {epic}: {e}")
            return None

    def get_asia_range(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the Asia session range (high, low).
        
        Note: This uses cached values that should be updated
        after Asia session ends.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        return self._asia_range_cache.get(epic)

    def set_asia_range(self, epic: str, high: float, low: float) -> None:
        """
        Set the Asia session range for a market.
        
        Call this after Asia session ends to record the range.
        
        Args:
            epic: Market identifier.
            high: Asia session high.
            low: Asia session low.
        """
        self._asia_range_cache[epic] = (high, low)
        logger.info(f"Asia range set for {epic}: high={high}, low={low}")

    def get_pre_us_range(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the pre-US session range (high, low).
        
        Note: This uses cached values that should be updated
        before US core session.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        return self._pre_us_range_cache.get(epic)

    def set_pre_us_range(self, epic: str, high: float, low: float) -> None:
        """
        Set the pre-US session range for a market.
        
        Call this before US core session to record the range.
        
        Args:
            epic: Market identifier.
            high: Pre-US session high.
            low: Pre-US session low.
        """
        self._pre_us_range_cache[epic] = (high, low)
        logger.info(f"Pre-US range set for {epic}: high={high}, low={low}")

    def get_atr(
        self,
        epic: str,
        timeframe: str,
        period: int
    ) -> Optional[float]:
        """
        Get the Average True Range for a market.
        
        Note: This is estimated from cached candle data.
        
        Args:
            epic: Market identifier.
            timeframe: Candle timeframe for ATR calculation.
            period: Number of periods for ATR calculation.
            
        Returns:
            ATR value or None if not available.
        """
        cache_key = f"{epic}_{timeframe}"
        candles = self._candle_cache.get(cache_key, [])
        
        if len(candles) < period:
            # Not enough data, estimate from daily range
            daily = self.get_daily_high_low(epic)
            if daily:
                return (daily[0] - daily[1]) / 2  # Rough estimate
            return None
        
        # Calculate ATR from cached candles
        tr_values = []
        for i in range(1, min(len(candles), period + 1)):
            candle = candles[-i]
            prev_candle = candles[-(i + 1)] if i + 1 <= len(candles) else candle
            
            tr = max(
                candle.high - candle.low,
                abs(candle.high - prev_candle.close),
                abs(candle.low - prev_candle.close)
            )
            tr_values.append(tr)
        
        if tr_values:
            return sum(tr_values) / len(tr_values)
        return None

    def get_eia_timestamp(self) -> Optional[datetime]:
        """
        Get the expected/actual EIA release timestamp.
        
        Returns:
            EIA release timestamp or None if not applicable.
        """
        return self._eia_timestamp

    def set_eia_timestamp(self, timestamp: datetime) -> None:
        """
        Set the EIA release timestamp.
        
        Args:
            timestamp: EIA release timestamp.
        """
        self._eia_timestamp = timestamp
        logger.info(f"EIA timestamp set: {timestamp}")

    def clear_session_caches(self) -> None:
        """
        Clear session range caches.
        
        Call this at the start of a new trading day.
        """
        self._asia_range_cache.clear()
        self._pre_us_range_cache.clear()
        logger.info("Session range caches cleared")
