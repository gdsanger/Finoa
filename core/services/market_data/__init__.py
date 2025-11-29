"""
Market Data Layer module for Finoa.

Provides a unified interface for market data across all broker integrations:
- Broker-agnostic candle streaming
- Redis-backed persistence for recovery
- In-memory ring buffers for fast access
- Configurable window sizes

Usage:
    from core.services.market_data import get_candles_for_asset, get_stream_manager
    
    # Get candles for an asset
    response = get_candles_for_asset(asset, timeframe='1m', window_hours=6)
    
    # Access the stream manager directly
    manager = get_stream_manager()
    candles = manager.get_candles(asset, timeframe='5m', window_hours=12)
"""

from .candle_models import (
    Candle,
    CandleStreamStatus,
    CandleDataResponse,
    DataStatus,
)

from .market_data_config import (
    MarketDataConfig,
    WindowConfig,
    TimeframeConfig,
    RedisConfig,
    get_market_data_config,
    reset_config,
    SUPPORTED_TIMEFRAMES,
    SUPPORTED_WINDOW_HOURS,
    DEFAULT_TIMEFRAME,
    DEFAULT_WINDOW_HOURS,
)

from .redis_candle_store import (
    RedisCandleStore,
    get_candle_store,
    reset_candle_store,
)

from .candle_stream import CandleStream

from .market_data_stream_manager import (
    MarketDataStreamManager,
    get_stream_manager,
    get_candles_for_asset,
)


__all__ = [
    # Candle models
    'Candle',
    'CandleStreamStatus',
    'CandleDataResponse',
    'DataStatus',
    
    # Configuration
    'MarketDataConfig',
    'WindowConfig',
    'TimeframeConfig',
    'RedisConfig',
    'get_market_data_config',
    'reset_config',
    'SUPPORTED_TIMEFRAMES',
    'SUPPORTED_WINDOW_HOURS',
    'DEFAULT_TIMEFRAME',
    'DEFAULT_WINDOW_HOURS',
    
    # Redis store
    'RedisCandleStore',
    'get_candle_store',
    'reset_candle_store',
    
    # Candle stream
    'CandleStream',
    
    # Stream manager
    'MarketDataStreamManager',
    'get_stream_manager',
    'get_candles_for_asset',
]
