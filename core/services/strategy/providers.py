"""
Protocol definitions for the Strategy Engine.

Defines the MarketStateProvider interface that must be implemented
by data providers to supply market data to the Strategy Engine.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Protocol

from .models import Candle, SessionPhase


class MarketStateProvider(Protocol):
    """
    Protocol for providing market state data to the Strategy Engine.
    
    Implementations must provide market data including phase information,
    candle data, and derived metrics like ATR and daily high/low.
    """

    def get_phase(self, ts: datetime) -> SessionPhase:
        """
        Get the current market session phase for a given timestamp.
        
        Args:
            ts: Timestamp to evaluate.
            
        Returns:
            SessionPhase indicating the current market phase.
        """
        ...

    def get_recent_candles(
        self,
        epic: str,
        timeframe: str,
        limit: int
    ) -> list[Candle]:
        """
        Get recent candles for a market.
        
        Args:
            epic: Market identifier.
            timeframe: Candle timeframe (e.g., '1m', '5m', '1h').
            limit: Maximum number of candles to return.
            
        Returns:
            List of Candle objects, most recent last.
        """
        ...

    def get_daily_high_low(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the current day's high and low prices.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        ...

    def get_asia_range(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the Asia session range (high, low).
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        ...

    def get_pre_us_range(self, epic: str) -> Optional[tuple[float, float]]:
        """
        Get the pre-US session range (high, low).
        
        Args:
            epic: Market identifier.
            
        Returns:
            Tuple of (high, low) or None if not available.
        """
        ...

    def get_atr(
        self,
        epic: str,
        timeframe: str,
        period: int
    ) -> Optional[float]:
        """
        Get the Average True Range for a market.
        
        Args:
            epic: Market identifier.
            timeframe: Candle timeframe for ATR calculation.
            period: Number of periods for ATR calculation.
            
        Returns:
            ATR value or None if not available.
        """
        ...

    def get_eia_timestamp(self) -> Optional[datetime]:
        """
        Get the expected/actual EIA release timestamp.
        
        Returns:
            EIA release timestamp or None if not applicable.
        """
        ...


class BaseMarketStateProvider(ABC):
    """
    Abstract base class for MarketStateProvider implementations.
    
    Provides default implementations for some methods that can be
    overridden by concrete implementations.
    """

    @abstractmethod
    def get_phase(self, ts: datetime) -> SessionPhase:
        """Get the current market session phase."""
        pass

    @abstractmethod
    def get_recent_candles(
        self,
        epic: str,
        timeframe: str,
        limit: int
    ) -> list[Candle]:
        """Get recent candles for a market."""
        pass

    def get_daily_high_low(self, epic: str) -> Optional[tuple[float, float]]:
        """Get the current day's high and low prices."""
        return None

    def get_asia_range(self, epic: str) -> Optional[tuple[float, float]]:
        """Get the Asia session range."""
        return None

    def get_pre_us_range(self, epic: str) -> Optional[tuple[float, float]]:
        """Get the pre-US session range."""
        return None

    def get_atr(
        self,
        epic: str,
        timeframe: str,
        period: int
    ) -> Optional[float]:
        """Get the Average True Range for a market."""
        return None

    def get_eia_timestamp(self) -> Optional[datetime]:
        """Get the expected/actual EIA release timestamp."""
        return None
