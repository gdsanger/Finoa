"""
CandleStream - In-memory candle buffer with Redis persistence.

Provides a ring buffer for recent candles with automatic persistence to Redis.
Used by the MarketDataStreamManager for each asset/timeframe pair.
"""
import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import List, Optional, Callable

from .candle_models import Candle, CandleStreamStatus, DataStatus
from .redis_candle_store import RedisCandleStore, get_candle_store
from .market_data_config import TimeframeConfig


logger = logging.getLogger(__name__)


class CandleStream:
    """
    In-memory ring buffer for candles with Redis persistence.
    
    Features:
    - Fixed-size ring buffer for recent candles
    - Thread-safe operations
    - Automatic persistence to Redis on append
    - Lazy loading from Redis on first access
    - Status tracking (LIVE, POLL, CACHED, OFFLINE)
    
    Usage:
        stream = CandleStream('OIL', '1m', broker='IG')
        stream.append(candle)
        candles = stream.get_recent(hours=6)
    """
    
    def __init__(
        self,
        asset_id: str,
        timeframe: str,
        broker: Optional[str] = None,
        max_candles: int = 1440,
        store: Optional[RedisCandleStore] = None,
        on_new_candle: Optional[Callable[[Candle], None]] = None,
    ):
        """
        Initialize the candle stream.
        
        Args:
            asset_id: Asset identifier (e.g., 'OIL', 'NAS100')
            timeframe: Candle timeframe (e.g., '1m', '5m')
            broker: Broker providing the data
            max_candles: Maximum number of candles to keep in memory
            store: Redis store instance (uses singleton if not provided)
            on_new_candle: Optional callback for new candles
        """
        self._asset_id = asset_id
        self._timeframe = timeframe
        self._broker = broker
        self._max_candles = max_candles
        self._store = store or get_candle_store()
        self._on_new_candle = on_new_candle
        
        self._buffer: deque = deque(maxlen=max_candles)
        self._lock = Lock()
        self._status: DataStatus = 'OFFLINE'
        self._last_update: Optional[datetime] = None
        self._error: Optional[str] = None
        self._loaded = False
        self._partial_candle: Optional[Candle] = None
    
    @property
    def asset_id(self) -> str:
        """Get the asset ID."""
        return self._asset_id
    
    @property
    def timeframe(self) -> str:
        """Get the timeframe."""
        return self._timeframe
    
    @property
    def broker(self) -> Optional[str]:
        """Get the broker providing data."""
        return self._broker
    
    @property
    def status(self) -> DataStatus:
        """Get the current data status."""
        return self._status
    
    @status.setter
    def status(self, value: DataStatus) -> None:
        """Set the data status."""
        with self._lock:
            self._status = value
    
    @property
    def last_update(self) -> Optional[datetime]:
        """Get the timestamp of the last update."""
        return self._last_update
    
    @property
    def error(self) -> Optional[str]:
        """Get the current error message."""
        return self._error
    
    @error.setter
    def error(self, value: Optional[str]) -> None:
        """Set the error message."""
        with self._lock:
            self._error = value
            if value:
                self._status = 'OFFLINE'
    
    def _ensure_loaded(self) -> None:
        """Ensure candles are loaded from Redis on first access."""
        if self._loaded:
            return
        
        with self._lock:
            if self._loaded:
                return
            
            try:
                # Load from Redis
                candles = self._store.load_candles(
                    self._asset_id,
                    self._timeframe,
                    count=self._max_candles,
                )
                
                if candles:
                    self._buffer.extend(candles)
                    self._last_update = datetime.now(timezone.utc)
                    self._status = 'CACHED'
                    logger.info(f"Loaded {len(candles)} candles for {self._asset_id}/{self._timeframe} from Redis")
                
                self._loaded = True
            except Exception as e:
                logger.error(f"Failed to load candles from Redis: {e}")
                self._loaded = True  # Don't retry on every access
    
    def append(
        self,
        candle: Candle,
        persist: bool = True,
    ) -> None:
        """
        Append a candle to the stream.
        
        Args:
            candle: Candle to append
            persist: Whether to persist to Redis
        """
        self._ensure_loaded()
        
        with self._lock:
            # Check if this is an update to an existing candle
            if self._buffer and self._buffer[-1].timestamp == candle.timestamp:
                # Update the last candle
                self._buffer[-1] = candle
            else:
                # Append new candle
                self._buffer.append(candle)
            
            self._last_update = datetime.now(timezone.utc)
            
            # Track partial candle
            if not candle.complete:
                self._partial_candle = candle
            else:
                self._partial_candle = None
        
        # Persist to Redis (outside lock)
        if persist:
            try:
                self._store.append_candle(self._asset_id, self._timeframe, candle)
            except Exception as e:
                logger.error(f"Failed to persist candle to Redis: {e}")
        
        # Notify callback
        if self._on_new_candle and candle.complete:
            try:
                self._on_new_candle(candle)
            except Exception as e:
                logger.error(f"Error in new candle callback: {e}")
    
    def append_many(
        self,
        candles: List[Candle],
        persist: bool = True,
    ) -> None:
        """
        Append multiple candles to the stream.
        
        Args:
            candles: List of candles to append
            persist: Whether to persist to Redis
        """
        if not candles:
            return
        
        self._ensure_loaded()
        
        with self._lock:
            for candle in candles:
                if self._buffer and self._buffer[-1].timestamp == candle.timestamp:
                    self._buffer[-1] = candle
                else:
                    self._buffer.append(candle)
            
            self._last_update = datetime.now(timezone.utc)
        
        # Persist to Redis
        if persist:
            try:
                self._store.append_candles(self._asset_id, self._timeframe, candles)
            except Exception as e:
                logger.error(f"Failed to persist candles to Redis: {e}")
    
    def get_recent(
        self,
        hours: Optional[float] = None,
        count: Optional[int] = None,
    ) -> List[Candle]:
        """
        Get recent candles.
        
        Args:
            hours: Time window in hours
            count: Maximum number of candles
            
        Returns:
            List of candles, ordered by timestamp ascending
        """
        self._ensure_loaded()
        
        with self._lock:
            candles = list(self._buffer)
        
        if hours is not None:
            min_ts = int((datetime.utcnow() - 
                         __import__('datetime').timedelta(hours=hours)).timestamp())
            candles = [c for c in candles if c.timestamp >= min_ts]
        
        if count is not None:
            candles = candles[-count:]
        
        return candles
    
    def get_latest(self) -> Optional[Candle]:
        """Get the most recent complete candle."""
        self._ensure_loaded()
        
        with self._lock:
            if not self._buffer:
                return None
            
            # Find the most recent complete candle
            for candle in reversed(self._buffer):
                if candle.complete:
                    return candle
            
            return None
    
    def get_partial(self) -> Optional[Candle]:
        """Get the current partial candle (if any)."""
        with self._lock:
            return self._partial_candle
    
    def get_count(self) -> int:
        """Get the number of candles in the buffer."""
        self._ensure_loaded()
        
        with self._lock:
            return len(self._buffer)
    
    def get_status(self) -> CandleStreamStatus:
        """Get the stream status."""
        self._ensure_loaded()
        
        with self._lock:
            return CandleStreamStatus(
                asset_id=self._asset_id,
                timeframe=self._timeframe,
                status=self._status,
                last_update=self._last_update,
                candle_count=len(self._buffer),
                broker=self._broker,
                error=self._error,
            )
    
    def clear(self) -> None:
        """Clear all candles from the buffer and store."""
        with self._lock:
            self._buffer.clear()
            self._last_update = None
            self._partial_candle = None
        
        try:
            self._store.clear(self._asset_id, self._timeframe)
        except Exception as e:
            logger.error(f"Failed to clear candles from Redis: {e}")
    
    def reload(self) -> None:
        """Force reload from Redis."""
        with self._lock:
            self._buffer.clear()
            self._loaded = False
        
        self._ensure_loaded()
    
    def __len__(self) -> int:
        """Get the number of candles in the buffer."""
        return self.get_count()
    
    def __iter__(self):
        """Iterate over candles."""
        return iter(self.get_recent())
