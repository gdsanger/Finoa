"""
MarketDataStreamManager - Central manager for all candle streams.

Provides a unified interface for accessing candle data across all assets
and brokers. Handles:
- Stream creation and lifecycle management
- Broker-agnostic data fetching
- Fallback to REST polling when streaming unavailable
- Caching and persistence coordination
"""
import logging
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Dict, List, Optional, Tuple, Callable

from core.services.broker import BrokerError

from .candle_models import Candle, CandleStreamStatus, CandleDataResponse, DataStatus
from .candle_stream import CandleStream
from .redis_candle_store import RedisCandleStore, get_candle_store
from .market_data_config import (
    MarketDataConfig, 
    TimeframeConfig, 
    WindowConfig,
    get_market_data_config,
)


logger = logging.getLogger(__name__)


class MarketDataStreamManager:
    """
    Central manager for market data streams.
    
    Provides:
    - Unified access to candle data for all assets
    - Broker-agnostic data fetching via BrokerRegistry
    - Automatic stream creation and management
    - Fallback to REST polling when streaming unavailable
    - Status tracking for UI indicators
    
    Usage:
        manager = MarketDataStreamManager()
        
        # Get candles for an asset
        candles = manager.get_candles(asset, timeframe='1m', window_hours=6)
        
        # Get stream status for UI
        status = manager.get_stream_status(asset)
    """
    
    _instance: Optional['MarketDataStreamManager'] = None
    _instance_lock: Lock = Lock()
    
    def __init__(
        self,
        config: Optional[MarketDataConfig] = None,
        store: Optional[RedisCandleStore] = None,
    ):
        """
        Initialize the stream manager.
        
        Args:
            config: Market data configuration
            store: Redis candle store
        """
        self._config = config or get_market_data_config()
        self._store = store or get_candle_store()
        
        # Stream registry: {(asset_id, timeframe): CandleStream}
        self._streams: Dict[Tuple[str, str], CandleStream] = {}
        self._lock = Lock()
        
        # Status tracking
        self._last_fetch_time: Dict[Tuple[str, str], datetime] = {}
        self._fetch_errors: Dict[Tuple[str, str], str] = {}
        self._fetch_locks: Dict[Tuple[str, str], Lock] = {}
    
    @classmethod
    def get_instance(cls) -> 'MarketDataStreamManager':
        """Get the singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._instance_lock:
            if cls._instance:
                cls._instance.close()
            cls._instance = None
    
    def _get_stream_key(self, asset_id: str, timeframe: str) -> Tuple[str, str]:
        """Get the stream registry key."""
        return (asset_id, timeframe)

    def _get_fetch_lock(self, key: Tuple[str, str]) -> Lock:
        """Get or create a fetch lock for a stream key."""
        with self._lock:
            if key not in self._fetch_locks:
                self._fetch_locks[key] = Lock()
            return self._fetch_locks[key]
    
    def get_or_create_stream(
        self,
        asset_id: str,
        timeframe: str,
        broker: Optional[str] = None,
        on_new_candle: Optional[Callable[[Candle], None]] = None,
    ) -> CandleStream:
        """
        Get or create a candle stream for an asset/timeframe pair.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            broker: Broker providing the data
            on_new_candle: Optional callback for new candles
            
        Returns:
            CandleStream instance
        """
        key = self._get_stream_key(asset_id, timeframe)
        
        with self._lock:
            if key not in self._streams:
                self._streams[key] = CandleStream(
                    asset_id=asset_id,
                    timeframe=timeframe,
                    broker=broker,
                    max_candles=self._config.redis.max_candles_per_stream,
                    store=self._store,
                    on_new_candle=on_new_candle,
                )
            return self._streams[key]
    
    def get_stream(
        self,
        asset_id: str,
        timeframe: str,
    ) -> Optional[CandleStream]:
        """
        Get an existing stream (without creating).
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            
        Returns:
            CandleStream instance or None
        """
        key = self._get_stream_key(asset_id, timeframe)
        
        with self._lock:
            return self._streams.get(key)
    
    def get_candles(
        self,
        asset,
        timeframe: str = '1m',
        window_hours: float = 6,
        force_refresh: bool = False,
    ) -> CandleDataResponse:
        """
        Get candles for an asset.
        
        This is the main entry point for retrieving candle data. It:
        1. Checks for cached data in the stream buffer
        2. Fetches from broker if data is stale or missing
        3. Persists to Redis for recovery
        4. Returns data with status information
        
        Args:
            asset: TradingAsset instance
            timeframe: Candle timeframe
            window_hours: Time window in hours
            force_refresh: Force fetch from broker
            
        Returns:
            CandleDataResponse with candles and status
        """
        # Validate timeframe
        timeframe = self._config.timeframe.validate_timeframe(timeframe)
        
        # Validate window hours based on asset category
        window_config = self._config.get_window_config_for_category(
            getattr(asset, 'category', 'commodity')
        )
        window_hours = window_config.validate_hours(window_hours)
        
        # Get or create stream
        stream = self.get_or_create_stream(
            asset_id=asset.symbol,
            timeframe=timeframe,
            broker=getattr(asset, 'broker', None),
        )

        fetch_key = self._get_stream_key(stream.asset_id, timeframe)

        # Check if we need to fetch from broker
        should_fetch = force_refresh or self._should_fetch_from_broker(
            stream, timeframe, window_hours
        )

        if should_fetch:
            fetch_lock = self._get_fetch_lock(fetch_key)
            if fetch_lock.acquire(blocking=False):
                try:
                    self._fetch_candles_from_broker(asset, stream, timeframe, window_hours)
                finally:
                    fetch_lock.release()
            else:
                logger.debug(
                    f"Fetch already in progress for {stream.asset_id}/{timeframe}, returning cached data"
                )
        
        # Get candles from stream
        candles = stream.get_recent(hours=window_hours)
        
        return CandleDataResponse(
            asset=asset.symbol,
            timeframe=timeframe,
            window_hours=window_hours,
            candles=candles,
            status=stream.get_status(),
            error=stream.error,
        )
    
    def _should_fetch_from_broker(
        self,
        stream: CandleStream,
        timeframe: str,
        window_hours: float,
    ) -> bool:
        """
        Determine if we should fetch fresh data from the broker.
        
        Args:
            stream: The candle stream
            timeframe: Candle timeframe
            window_hours: Requested window hours
            
        Returns:
            True if should fetch, False otherwise
        """
        # If stream has no data, always fetch
        if stream.get_count() == 0:
            return True
        
        # If status is OFFLINE with error, retry periodically
        if stream.status == 'OFFLINE' and stream.error:
            fetch_key = self._get_stream_key(stream.asset_id, timeframe)
            last_fetch = self._last_fetch_time.get(fetch_key)
            if last_fetch is None:
                return True
            # Retry after 60 seconds
            if (datetime.now(timezone.utc) - last_fetch).total_seconds() > 60:
                return True
            return False
        
        # Calculate expected candle interval
        tf_minutes = TimeframeConfig.to_minutes(timeframe)
        
        # If last update is older than one candle interval, fetch
        if stream.last_update:
            age_seconds = (datetime.now(timezone.utc) - stream.last_update).total_seconds()
            if age_seconds > tf_minutes * 60:
                return True
        
        # Check if we have enough data for the requested window
        expected_candles = int(window_hours * 60 / tf_minutes)
        if stream.get_count() < expected_candles * 0.8:  # 80% threshold
            return True
        
        return False
    
    def _fetch_candles_from_broker(
        self,
        asset,
        stream: CandleStream,
        timeframe: str,
        window_hours: float,
    ) -> None:
        """
        Fetch candles from the appropriate broker.
        
        Args:
            asset: TradingAsset instance
            stream: CandleStream to populate
            timeframe: Candle timeframe
            window_hours: Time window in hours
        """
        fetch_key = self._get_stream_key(stream.asset_id, timeframe)

        try:
            from core.services.broker import BrokerRegistry

            registry = BrokerRegistry()
            broker = registry.get_broker_for_asset(asset)

            try:
                # Calculate number of candles needed
                tf_minutes = TimeframeConfig.to_minutes(timeframe)
                num_points = int(window_hours * 60 / tf_minutes)

                # Get broker symbols/identifiers
                epic = getattr(asset, 'epic', asset.symbol)
                symbol = getattr(asset, 'effective_broker_symbol', epic)

                # Fetch historical prices
                if hasattr(broker, 'get_historical_prices'):
                    price_data = self._fetch_historical_prices(
                        broker,
                        symbol=symbol,
                        epic=epic,
                        timeframe=timeframe,
                        num_points=num_points,
                    )

                    # Convert to Candle objects
                    candles = []
                    for data in price_data:
                        candle = Candle(
                            timestamp=data.get('time', 0),
                            open=float(data.get('open', 0)),
                            high=float(data.get('high', 0)),
                            low=float(data.get('low', 0)),
                            close=float(data.get('close', 0)),
                            volume=float(data.get('volume')) if data.get('volume') else None,
                            complete=True,
                        )
                        candles.append(candle)

                    if candles:
                        stream.append_many(candles)
                        stream.status = 'LIVE'
                        stream.error = None
                        logger.debug(f"Fetched {len(candles)} candles for {asset.symbol}")
                else:
                    # Broker doesn't support historical prices
                    stream.status = 'POLL'
                    logger.warning(f"Broker {type(broker).__name__} doesn't support historical prices")

                self._last_fetch_time[fetch_key] = datetime.now(timezone.utc)
                self._fetch_errors.pop(fetch_key, None)

            finally:
                registry.disconnect_all()

        except BrokerError as e:
            error_msg = self._format_broker_error(e)
            stream.error = error_msg
            stream.status = 'CACHED' if stream.get_count() > 0 else 'OFFLINE'
            self._fetch_errors[fetch_key] = error_msg
            self._last_fetch_time[fetch_key] = datetime.now(timezone.utc)
            logger.warning(f"Failed to fetch candles from broker for {asset.symbol}: {e}")
        except Exception as e:
            error_msg = self._format_broker_error(e)
            stream.error = error_msg
            stream.status = 'OFFLINE'
            self._fetch_errors[fetch_key] = error_msg
            self._last_fetch_time[fetch_key] = datetime.now(timezone.utc)
            logger.warning(f"Failed to fetch candles from broker for {asset.symbol}: {e}")
    
    def _timeframe_to_ig_resolution(self, timeframe: str) -> str:
        """Convert timeframe to IG API resolution format."""
        timeframe = timeframe.lower().strip()
        
        mapping = {
            '1m': 'MINUTE',
            '2m': 'MINUTE_2',
            '3m': 'MINUTE_3',
            '5m': 'MINUTE_5',
            '10m': 'MINUTE_10',
            '15m': 'MINUTE_15',
            '30m': 'MINUTE_30',
            '1h': 'HOUR',
            '2h': 'HOUR_2',
            '3h': 'HOUR_3',
            '4h': 'HOUR_4',
            '1d': 'DAY',
            '1w': 'WEEK',
            '1M': 'MONTH',
        }

        return mapping.get(timeframe, 'MINUTE_5')

    def _timeframe_to_mexc_interval(self, timeframe: str) -> str:
        """Convert timeframe to MEXC API interval format."""
        timeframe = timeframe.lower().strip()

        valid_intervals = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1M']

        if timeframe in valid_intervals:
            return timeframe

        mapping = {
            '2m': '5m',
            '3m': '5m',
            '10m': '15m',
            '2h': '4h',
            '3h': '4h',
        }

        return mapping.get(timeframe, '5m')

    def _fetch_historical_prices(
        self,
        broker,
        symbol: str,
        epic: str,
        timeframe: str,
        num_points: int,
    ) -> List[dict]:
        """Call the broker's historical price API with broker-specific parameters."""

        try:
            from core.services.broker.mexc_broker_service import MexcBrokerService
            from core.services.broker.ig_broker_service import IgBrokerService
        except Exception:
            # Fallback to generic call if broker modules cannot be loaded
            return broker.get_historical_prices(epic=epic, num_points=num_points)

        # MEXC uses symbol/interval/limit
        if isinstance(broker, MexcBrokerService):
            interval = self._timeframe_to_mexc_interval(timeframe)
            limit = min(num_points, 1000)  # MEXC API limit
            return broker.get_historical_prices(symbol=symbol, interval=interval, limit=limit)

        # IG uses epic/resolution/num_points
        # IG has strict weekly allowance limits (~10,000 data points for demo accounts)
        # Cap at 50 points to conserve allowance while still providing useful chart data
        if isinstance(broker, IgBrokerService):
            resolution = self._timeframe_to_ig_resolution(timeframe)
            capped_points = min(num_points, 50)  # Strict cap to conserve IG allowance
            return broker.get_historical_prices(epic=epic, resolution=resolution, num_points=capped_points)

        # Generic fallback
        return broker.get_historical_prices(epic=epic, num_points=num_points)
    
    def get_stream_status(
        self,
        asset_id: str,
        timeframe: str = '1m',
    ) -> CandleStreamStatus:
        """
        Get the status of a candle stream.
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            
        Returns:
            CandleStreamStatus
        """
        stream = self.get_stream(asset_id, timeframe)
        
        if stream is None:
            return CandleStreamStatus(
                asset_id=asset_id,
                timeframe=timeframe,
                status='OFFLINE',
                error='Stream not initialized',
            )
        
        return stream.get_status()
    
    def get_all_stream_statuses(self) -> List[CandleStreamStatus]:
        """
        Get status of all active streams.
        
        Returns:
            List of CandleStreamStatus for all streams
        """
        with self._lock:
            return [stream.get_status() for stream in self._streams.values()]
    
    def append_candle(
        self,
        asset_id: str,
        timeframe: str,
        candle: Candle,
    ) -> None:
        """
        Append a candle to a stream (for streaming data).
        
        Args:
            asset_id: Asset identifier
            timeframe: Candle timeframe
            candle: Candle to append
        """
        stream = self.get_or_create_stream(asset_id, timeframe)
        stream.append(candle)
        stream.status = 'LIVE'
    
    def close(self) -> None:
        """Close all streams and connections."""
        with self._lock:
            self._streams.clear()
        
        if self._store:
            self._store.close()
    
    def reload_all(self) -> None:
        """Force reload all streams from Redis."""
        with self._lock:
            for stream in self._streams.values():
                stream.reload()

    def _format_broker_error(self, error: Exception) -> str:
        """Return a user-friendly broker error message for known cases."""
        message = str(error)

        if isinstance(error, BrokerError):
            if 'error.public-api.exceeded-account-historical-data-allowance' in message:
                return 'IG API-Limit für historische Daten erreicht. Bitte später erneut versuchen.'

        return message


# Module-level convenience functions

def get_stream_manager() -> MarketDataStreamManager:
    """Get the stream manager singleton."""
    return MarketDataStreamManager.get_instance()


def get_candles_for_asset(
    asset,
    timeframe: str = '1m',
    window_hours: float = 6,
) -> CandleDataResponse:
    """
    Convenience function to get candles for an asset.
    
    Args:
        asset: TradingAsset instance
        timeframe: Candle timeframe
        window_hours: Time window in hours
        
    Returns:
        CandleDataResponse
    """
    manager = get_stream_manager()
    return manager.get_candles(asset, timeframe, window_hours)
