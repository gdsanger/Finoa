"""
Candle data models for the Market Data Layer.

Provides standardized candle representation used across all broker integrations.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any, Literal


# Data status enum for indicating data source
DataStatus = Literal["LIVE", "POLL", "CACHED", "OFFLINE"]


@dataclass
class Candle:
    """
    Represents a single OHLCV candle.
    
    Attributes:
        timestamp: Unix timestamp in seconds for the candle start time
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        volume: Trading volume (optional)
        complete: Whether the candle is complete or still forming
    """
    timestamp: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    complete: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert candle to dictionary for API responses."""
        result = {
            'time': self.timestamp,
            'open': round(self.open, 6),
            'high': round(self.high, 6),
            'low': round(self.low, 6),
            'close': round(self.close, 6),
        }
        if self.volume is not None:
            result['volume'] = round(self.volume, 4)
        if not self.complete:
            result['complete'] = False
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Candle':
        """Create a Candle instance from a dictionary."""
        return cls(
            timestamp=data.get('time', data.get('timestamp', 0)),
            open=float(data.get('open', 0)),
            high=float(data.get('high', 0)),
            low=float(data.get('low', 0)),
            close=float(data.get('close', 0)),
            volume=float(data['volume']) if 'volume' in data and data['volume'] is not None else None,
            complete=data.get('complete', True),
        )
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Candle):
            return False
        return self.timestamp == other.timestamp
    
    def __hash__(self) -> int:
        return hash(self.timestamp)


@dataclass
class CandleStreamStatus:
    """
    Status information for a candle stream.
    
    Attributes:
        asset_id: The asset ID this stream is for
        timeframe: The timeframe (e.g., '1m', '5m')
        status: Current data status (LIVE, POLL, CACHED, OFFLINE)
        last_update: Timestamp of last candle update
        candle_count: Number of candles in the buffer
        broker: The broker providing the data
        error: Optional error message if status is OFFLINE
    """
    asset_id: str
    timeframe: str
    status: DataStatus
    last_update: Optional[datetime] = None
    candle_count: int = 0
    broker: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'asset_id': self.asset_id,
            'timeframe': self.timeframe,
            'status': self.status,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'candle_count': self.candle_count,
            'broker': self.broker,
            'error': self.error,
        }


@dataclass
class CandleDataResponse:
    """
    Response model for candle data API endpoints.
    
    Attributes:
        asset: Asset symbol
        timeframe: Candle timeframe
        window_hours: Time window in hours
        candles: List of candles
        status: Data stream status
        error: Optional error message
    """
    asset: str
    timeframe: str
    window_hours: float
    candles: List[Candle]
    status: CandleStreamStatus
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'asset': self.asset,
            'timeframe': self.timeframe,
            'window_hours': self.window_hours,
            'candle_count': len(self.candles),
            'candles': [c.to_dict() for c in self.candles],
            'status': self.status.to_dict(),
            'error': self.error,
        }
