"""
Market Data Configuration.

Provides configuration settings for the Market Data Layer, including
window sizes, timeframes, and Redis connection settings.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# Supported timeframes
SUPPORTED_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

# Supported window sizes in hours
SUPPORTED_WINDOW_HOURS = [1, 3, 6, 8, 12, 24, 48, 72]

# Default window size in hours
DEFAULT_WINDOW_HOURS = 6

# Default timeframe
DEFAULT_TIMEFRAME = '1m'

# Default max candles to keep in memory per stream
DEFAULT_MAX_CANDLES = 1440  # 24 hours of 1-minute candles

# Redis key prefix for candle storage
REDIS_KEY_PREFIX = 'market:candles'


@dataclass
class WindowConfig:
    """
    Configuration for time window sizes.
    
    Attributes:
        min_hours: Minimum window size in hours
        max_hours: Maximum window size in hours
        default_hours: Default window size
        allowed_hours: List of allowed window sizes
    """
    min_hours: float = 1.0
    max_hours: float = 72.0
    default_hours: float = DEFAULT_WINDOW_HOURS
    allowed_hours: List[float] = field(default_factory=lambda: [1, 3, 6, 8, 12, 24, 48, 72])
    
    def validate_hours(self, hours: float) -> float:
        """
        Validate and normalize window hours.
        
        Args:
            hours: Requested window hours
            
        Returns:
            Validated hours (clamped to valid range, snapped to nearest allowed)
        """
        # Clamp to valid range
        hours = max(self.min_hours, min(hours, self.max_hours))
        
        # Snap to nearest allowed value
        closest = min(self.allowed_hours, key=lambda x: abs(x - hours))
        return closest


@dataclass
class TimeframeConfig:
    """
    Configuration for candle timeframes.
    
    Attributes:
        default: Default timeframe
        allowed: List of allowed timeframes
    """
    default: str = DEFAULT_TIMEFRAME
    allowed: List[str] = field(default_factory=lambda: SUPPORTED_TIMEFRAMES.copy())
    
    def validate_timeframe(self, timeframe: str) -> str:
        """
        Validate timeframe.
        
        Args:
            timeframe: Requested timeframe
            
        Returns:
            Validated timeframe (default if invalid)
        """
        timeframe = timeframe.lower().strip()
        if timeframe in self.allowed:
            return timeframe
        return self.default
    
    @staticmethod
    def to_minutes(timeframe: str) -> int:
        """
        Convert timeframe to minutes.
        
        Args:
            timeframe: Timeframe string (e.g., '5m', '1h')
            
        Returns:
            Number of minutes per candle
        """
        timeframe = timeframe.lower().strip()
        
        if timeframe.endswith('m'):
            try:
                return int(timeframe[:-1])
            except ValueError:
                return 1
        
        if timeframe.endswith('h'):
            try:
                return int(timeframe[:-1]) * 60
            except ValueError:
                return 60
        
        if timeframe.endswith('d'):
            try:
                return int(timeframe[:-1]) * 60 * 24
            except ValueError:
                return 60 * 24
        
        # Try to parse as plain number (minutes)
        try:
            return int(timeframe)
        except ValueError:
            return 1


@dataclass
class RedisConfig:
    """
    Redis configuration for candle storage.
    
    Attributes:
        host: Redis server host
        port: Redis server port
        db: Redis database number
        key_prefix: Prefix for all market data keys
        max_candles_per_stream: Maximum candles to store per stream
        ttl_hours: Time-to-live for stored candles in hours
    """
    host: str = 'localhost'
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    key_prefix: str = REDIS_KEY_PREFIX
    max_candles_per_stream: int = DEFAULT_MAX_CANDLES
    ttl_hours: int = 72  # 3 days retention
    
    @classmethod
    def from_django_settings(cls) -> 'RedisConfig':
        """
        Create RedisConfig from Django settings.
        
        Looks for MARKET_DATA_REDIS in Django settings.
        Falls back to defaults if not configured.
        """
        try:
            from django.conf import settings
            redis_settings = getattr(settings, 'MARKET_DATA_REDIS', {})
            return cls(
                host=redis_settings.get('HOST', 'localhost'),
                port=redis_settings.get('PORT', 6379),
                db=redis_settings.get('DB', 0),
                password=redis_settings.get('PASSWORD'),
                key_prefix=redis_settings.get('KEY_PREFIX', REDIS_KEY_PREFIX),
                max_candles_per_stream=redis_settings.get('MAX_CANDLES', DEFAULT_MAX_CANDLES),
                ttl_hours=redis_settings.get('TTL_HOURS', 72),
            )
        except Exception:
            return cls()


@dataclass
class MarketDataConfig:
    """
    Main configuration for the Market Data Layer.
    
    Combines window, timeframe, and Redis configurations.
    """
    window: WindowConfig = field(default_factory=WindowConfig)
    timeframe: TimeframeConfig = field(default_factory=TimeframeConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    
    # Per-asset-class overrides (e.g., Crypto may have different defaults)
    asset_class_overrides: Dict[str, Dict] = field(default_factory=dict)
    
    @classmethod
    def get_default(cls) -> 'MarketDataConfig':
        """Get default market data configuration."""
        return cls(
            window=WindowConfig(),
            timeframe=TimeframeConfig(),
            redis=RedisConfig.from_django_settings(),
            asset_class_overrides={
                'crypto': {
                    'window_default': 12,  # Crypto 24/7, longer windows useful
                    'max_window': 168,  # 1 week
                },
                'forex': {
                    'window_default': 6,
                },
                'commodity': {
                    'window_default': 6,
                },
                'index': {
                    'window_default': 6,
                },
            }
        )
    
    def get_window_config_for_category(self, category: str) -> WindowConfig:
        """
        Get window configuration for an asset category.
        
        Args:
            category: Asset category (e.g., 'crypto', 'commodity')
            
        Returns:
            WindowConfig with category-specific overrides applied
        """
        overrides = self.asset_class_overrides.get(category.lower(), {})
        
        if not overrides:
            return self.window
        
        return WindowConfig(
            min_hours=overrides.get('min_window', self.window.min_hours),
            max_hours=overrides.get('max_window', self.window.max_hours),
            default_hours=overrides.get('window_default', self.window.default_hours),
            allowed_hours=overrides.get('allowed_windows', self.window.allowed_hours),
        )


# Singleton configuration instance
_config: Optional[MarketDataConfig] = None


def get_market_data_config() -> MarketDataConfig:
    """
    Get the market data configuration singleton.
    
    Returns:
        MarketDataConfig instance
    """
    global _config
    if _config is None:
        _config = MarketDataConfig.get_default()
    return _config


def reset_config() -> None:
    """Reset the configuration singleton (useful for testing)."""
    global _config
    _config = None
