"""
Redis Candle Store for persistent candle storage.

Provides a Redis-backed storage layer for market candles with:
- Append-only candle writes
- Efficient range queries by timestamp
- Automatic expiration (TTL)
- Recovery on restart
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from collections import deque

from .candle_models import Candle
from .market_data_config import RedisConfig, get_market_data_config


logger = logging.getLogger(__name__)


class RedisCandleStore:
    """
    Redis-backed storage for market candles.
    
    Uses Redis Sorted Sets for efficient time-range queries:
    - Score = timestamp (allows O(log n) range queries)
    - Value = JSON-serialized candle data
    
    Key structure:
        market:candles:{asset_id}:{timeframe}
    """
    
    def __init__(self, config: Optional[RedisConfig] = None):
        """
        Initialize the Redis candle store.
        
        Args:
            config: Redis configuration. Uses default from settings if not provided.
        """
        self._config = config or get_market_data_config().redis
        self._redis_client = None
        self._connected = False
        self._fallback_store: dict = {}  # In-memory fallback when Redis unavailable
    
    def _get_redis_client(self):
        """Get or create Redis client."""
        if self._redis_client is None:
            try:
                import redis
                self._redis_client = redis.Redis(
                    host=self._config.host,
                    port=self._config.port,
                    db=self._config.db,
                    password=self._config.password,
                    decode_responses=True,
                )
                # Test connection
                self._redis_client.ping()
                self._connected = True
                logger.info(f"Connected to Redis at {self._config.host}:{self._config.port}")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. Using in-memory fallback.")
                self._redis_client = None
                self._connected = False
        return self._redis_client
    
    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self._redis_client is None:
            return False
        try:
            self._redis_client.ping()
            return True
        except Exception:
            self._connected = False
            return False
    
    def _get_key(self, asset_id: str, timeframe: str) -> str:
        """Generate Redis key for an asset/timeframe pair."""
        return f"{self._config.key_prefix}:{asset_id}:{timeframe}"
    
    def _candle_to_member_key(self, candle: Candle) -> str:
        """
        Create a deterministic member key for the candle.
        
        Uses timestamp as prefix to ensure only one candle per timestamp.
        When ZADD is called with the same member key, Redis updates the score
        and value automatically, preventing duplicates without needing ZREM.
        """
        return f"{candle.timestamp}:{json.dumps(candle.to_dict())}"
    
    def _member_key_to_candle(self, member_key: str) -> Candle:
        """Extract candle from member key."""
        # Split on first colon to separate timestamp from JSON
        _, json_part = member_key.split(':', 1)
        return Candle.from_dict(json.loads(json_part))
    
    def append_candle(
        self,
        asset_id: str,
        timeframe: str,
        candle: Candle,
    ) -> bool:
        """
        Append a candle to the store.
        
        Candles are aggregated in-memory and written only once per completed minute.
        Uses timestamp-prefixed member keys to prevent duplicates. Since the broker
        service only calls this once per completed candle, no ZREM is needed.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe (e.g., '1m', '5m')
            candle: Candle to store
            
        Returns:
            True if successfully stored, False otherwise
        """
        key = self._get_key(asset_id, timeframe)
        
        redis_client = self._get_redis_client()
        if redis_client:
            try:
                # Create member key with timestamp prefix
                # Format: "{timestamp}:{json_data}"
                member_key = self._candle_to_member_key(candle)
                
                # Clean up any old entries with same timestamp (edge case for restarts)
                # This is a single operation per completed candle, not per trade
                redis_client.zremrangebyscore(key, candle.timestamp, candle.timestamp)
                
                # Add the new candle
                redis_client.zadd(key, {member_key: candle.timestamp})
                
                # Set TTL if not already set
                ttl = redis_client.ttl(key)
                if ttl < 0:
                    redis_client.expire(key, self._config.ttl_hours * 3600)
                
                # Trim old candles if necessary
                self._trim_old_candles(redis_client, key)
                
                return True
            except Exception as e:
                logger.error(f"Failed to append candle to Redis: {e}")
        
        # Fallback to in-memory store
        return self._append_to_fallback(key, candle)
    
    def append_candles(
        self,
        asset_id: str,
        timeframe: str,
        candles: List[Candle],
    ) -> int:
        """
        Append multiple candles to the store.
        
        Each candle is written with a timestamp-prefixed key to prevent duplicates.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            candles: List of candles to store
            
        Returns:
            Number of candles successfully stored
        """
        if not candles:
            return 0
        
        key = self._get_key(asset_id, timeframe)
        
        redis_client = self._get_redis_client()
        if redis_client:
            try:
                # Remove any existing candles with the same timestamps (edge case for restarts)
                for candle in candles:
                    redis_client.zremrangebyscore(key, candle.timestamp, candle.timestamp)
                
                # Batch ZADD with timestamp-prefixed member keys
                mapping = {self._candle_to_member_key(c): c.timestamp for c in candles}
                added = redis_client.zadd(key, mapping)
                
                # Set TTL if not already set
                ttl = redis_client.ttl(key)
                if ttl < 0:
                    redis_client.expire(key, self._config.ttl_hours * 3600)
                
                # Trim old candles if necessary
                self._trim_old_candles(redis_client, key)
                
                return len(candles) if added else 0
            except Exception as e:
                logger.error(f"Failed to append candles to Redis: {e}")
        
        # Fallback
        count = 0
        for candle in candles:
            if self._append_to_fallback(key, candle):
                count += 1
        return count
    
    def _trim_old_candles(self, redis_client, key: str) -> None:
        """Remove old candles to enforce max size."""
        try:
            count = redis_client.zcard(key)
            if count > self._config.max_candles_per_stream:
                # Remove oldest entries
                excess = count - self._config.max_candles_per_stream
                redis_client.zpopmin(key, excess)
        except Exception as e:
            logger.warning(f"Failed to trim old candles: {e}")
    
    def _append_to_fallback(self, key: str, candle: Candle) -> bool:
        """Append candle to in-memory fallback store.
        
        Removes any existing candle with the same timestamp to prevent duplicates.
        """
        if key not in self._fallback_store:
            self._fallback_store[key] = deque(maxlen=self._config.max_candles_per_stream)
        
        # Remove any existing candle with the same timestamp
        store = self._fallback_store[key]
        self._fallback_store[key] = deque(
            (c for c in store if c.timestamp != candle.timestamp),
            maxlen=self._config.max_candles_per_stream
        )
        
        self._fallback_store[key].append(candle)
        return True
    
    def load_candles(
        self,
        asset_id: str,
        timeframe: str,
        window_hours: Optional[float] = None,
        count: Optional[int] = None,
    ) -> List[Candle]:
        """
        Load candles from the store.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            window_hours: Time window in hours (loads candles within this window)
            count: Maximum number of candles to load (from most recent)
            
        Returns:
            List of candles, ordered by timestamp ascending
        """
        key = self._get_key(asset_id, timeframe)
        
        redis_client = self._get_redis_client()
        if redis_client:
            try:
                if window_hours is not None:
                    # Load by time range
                    min_ts = int((datetime.now(timezone.utc) - timedelta(hours=window_hours)).timestamp())
                    max_ts = int(datetime.now(timezone.utc).timestamp()) + 60  # Plus 1 minute buffer
                    
                    results = redis_client.zrangebyscore(key, min_ts, max_ts)
                elif count is not None:
                    # Load by count (most recent N)
                    results = redis_client.zrange(key, -count, -1)
                else:
                    # Load all
                    results = redis_client.zrange(key, 0, -1)
                
                candles = [self._member_key_to_candle(r) for r in results]
                return sorted(candles, key=lambda c: c.timestamp)
            except Exception as e:
                logger.error(f"Failed to load candles from Redis: {e}")
        
        # Fallback to in-memory store
        return self._load_from_fallback(key, window_hours, count)
    
    def _load_from_fallback(
        self,
        key: str,
        window_hours: Optional[float],
        count: Optional[int],
    ) -> List[Candle]:
        """Load candles from in-memory fallback store."""
        if key not in self._fallback_store:
            return []
        
        candles = list(self._fallback_store[key])
        
        if window_hours is not None:
            min_ts = int((datetime.now(timezone.utc) - timedelta(hours=window_hours)).timestamp())
            candles = [c for c in candles if c.timestamp >= min_ts]

        if count is not None:
            candles = candles[-count:]

        return sorted(candles, key=lambda c: c.timestamp)

    def get_range(
        self,
        asset_id: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Candle]:
        """Load candles within a timestamp range (inclusive)."""
        key = self._get_key(asset_id, timeframe)
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        redis_client = self._get_redis_client()
        if redis_client:
            try:
                results = redis_client.zrangebyscore(key, start_ts, end_ts)
                candles = [self._member_key_to_candle(r) for r in results]
                return sorted(candles, key=lambda c: c.timestamp)
            except Exception as e:
                logger.error(f"Failed to load candle range from Redis: {e}")

        # Fallback to in-memory store
        if key not in self._fallback_store:
            return []

        candles = [
            c
            for c in self._fallback_store[key]
            if start_ts <= c.timestamp <= end_ts
        ]
        return sorted(candles, key=lambda c: c.timestamp)
    
    def get_latest_candle(
        self,
        asset_id: str,
        timeframe: str,
    ) -> Optional[Candle]:
        """
        Get the most recent candle.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            
        Returns:
            Most recent candle or None
        """
        candles = self.load_candles(asset_id, timeframe, count=1)
        return candles[-1] if candles else None
    
    def get_candle_count(
        self,
        asset_id: str,
        timeframe: str,
    ) -> int:
        """
        Get the number of stored candles.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            
        Returns:
            Number of stored candles
        """
        key = self._get_key(asset_id, timeframe)
        
        redis_client = self._get_redis_client()
        if redis_client:
            try:
                return redis_client.zcard(key)
            except Exception as e:
                logger.error(f"Failed to get candle count from Redis: {e}")
        
        if key in self._fallback_store:
            return len(self._fallback_store[key])
        return 0
    
    def clear(
        self,
        asset_id: str,
        timeframe: str,
    ) -> bool:
        """
        Clear all candles for an asset/timeframe pair.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            
        Returns:
            True if cleared successfully
        """
        key = self._get_key(asset_id, timeframe)
        
        redis_client = self._get_redis_client()
        if redis_client:
            try:
                redis_client.delete(key)
                return True
            except Exception as e:
                logger.error(f"Failed to clear candles from Redis: {e}")
        
        if key in self._fallback_store:
            del self._fallback_store[key]
        return True
    
    def close(self) -> None:
        """Close the Redis connection."""
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None
            self._connected = False


# Singleton instance
_store: Optional[RedisCandleStore] = None


def get_candle_store() -> RedisCandleStore:
    """Get the candle store singleton."""
    global _store
    if _store is None:
        _store = RedisCandleStore()
    return _store


def reset_candle_store() -> None:
    """Reset the candle store singleton (useful for testing)."""
    global _store
    if _store:
        _store.close()
    _store = None
