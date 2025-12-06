"""
Broker configuration utilities.

Provides functions to get active broker configurations and create broker services.
Also provides a BrokerRegistry for caching and managing broker service instances.
"""
import logging
import threading
from typing import Dict, Optional

from django.core.exceptions import ImproperlyConfigured

from .broker_service import BrokerService
from .ig_broker_service import IgBrokerService
from .kraken_broker_service import KrakenBrokerService
from .mexc_broker_service import MexcBrokerService


logger = logging.getLogger(__name__)


class BrokerRegistry:
    """
    Registry for managing broker service instances.
    
    Caches broker service instances by broker type to avoid creating
    multiple connections. Provides a central point for getting the
    appropriate broker service for an asset.
    
    Thread-safe implementation using a lock for synchronized access.
    
    Usage:
        >>> registry = BrokerRegistry()
        >>> broker = registry.get_broker_for_asset(asset)
        >>> price = broker.get_symbol_price(asset.effective_broker_symbol)
    """
    
    _instance: Optional['BrokerRegistry'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    def __init__(self):
        """Initialize the broker registry."""
        self._brokers: Dict[str, BrokerService] = {}
        self._connected: Dict[str, bool] = {}
        self._lock: threading.Lock = threading.Lock()
    
    @classmethod
    def get_instance(cls) -> 'BrokerRegistry':
        """Get the singleton instance of the registry (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def get_broker_for_asset(self, asset) -> BrokerService:
        """
        Get the appropriate broker service for a trading asset.
        
        Creates and caches broker service instances. The broker is automatically
        connected if not already connected.
        
        Args:
            asset: TradingAsset instance with a broker field.
            
        Returns:
            BrokerService: The appropriate broker service (IG, MEXC, or Kraken), connected.
            
        Raises:
            ImproperlyConfigured: If no active configuration exists for the broker.
            ValueError: If the broker type is not supported.
        """
        from trading.models import TradingAsset
        
        broker_type = asset.broker
        
        with self._lock:
            # Return cached broker if available and connected
            if broker_type in self._brokers and self._connected.get(broker_type, False):
                return self._brokers[broker_type]
            
            # Create new broker service
            if broker_type == TradingAsset.BrokerKind.IG:
                broker = create_ig_broker_service()
            elif broker_type == TradingAsset.BrokerKind.MEXC:
                broker = create_mexc_broker_service()
            elif broker_type == TradingAsset.BrokerKind.KRAKEN:
                broker = create_kraken_broker_service()
            else:
                raise ValueError(f"Unsupported broker type: {broker_type}")
            
            # Connect the broker
            broker.connect()
            
            # Cache the broker
            self._brokers[broker_type] = broker
            self._connected[broker_type] = True
            
            logger.info(f"Created and connected {broker_type} broker service")
            
            return broker
    
    def get_ig_broker(self) -> IgBrokerService:
        """
        Get the IG broker service (creates and connects if needed).
        
        Returns:
            IgBrokerService: Connected IG broker service.
        """
        from trading.models import TradingAsset
        
        broker_type = TradingAsset.BrokerKind.IG
        
        with self._lock:
            if broker_type in self._brokers and self._connected.get(broker_type, False):
                return self._brokers[broker_type]
            
            broker = create_ig_broker_service()
            broker.connect()
            
            self._brokers[broker_type] = broker
            self._connected[broker_type] = True
            
            logger.info("Created and connected IG broker service")
            
            return broker
    
    def get_mexc_broker(self) -> MexcBrokerService:
        """
        Get the MEXC broker service (creates and connects if needed).
        
        Returns:
            MexcBrokerService: Connected MEXC broker service.
        """
        from trading.models import TradingAsset
        
        broker_type = TradingAsset.BrokerKind.MEXC
        
        with self._lock:
            if broker_type in self._brokers and self._connected.get(broker_type, False):
                return self._brokers[broker_type]
            
            broker = create_mexc_broker_service()
            broker.connect()
            
            self._brokers[broker_type] = broker
            self._connected[broker_type] = True
            
            logger.info("Created and connected MEXC broker service")
            
            return broker
    
    def get_kraken_broker(self) -> KrakenBrokerService:
        """
        Get the Kraken broker service (creates and connects if needed).
        
        Returns:
            KrakenBrokerService: Connected Kraken broker service.
        """
        from trading.models import TradingAsset
        
        broker_type = TradingAsset.BrokerKind.KRAKEN
        
        with self._lock:
            if broker_type in self._brokers and self._connected.get(broker_type, False):
                return self._brokers[broker_type]
            
            broker = create_kraken_broker_service()
            broker.connect()
            
            self._brokers[broker_type] = broker
            self._connected[broker_type] = True
            
            logger.info("Created and connected Kraken broker service")
            
            return broker
    
    def disconnect_all(self) -> None:
        """Disconnect all broker services."""
        with self._lock:
            for broker_type, broker in self._brokers.items():
                try:
                    if self._connected.get(broker_type, False):
                        broker.disconnect()
                        self._connected[broker_type] = False
                        logger.info(f"Disconnected {broker_type} broker service")
                except Exception as e:
                    logger.warning(f"Error disconnecting {broker_type} broker: {e}")
    
    def clear(self) -> None:
        """Disconnect and clear all cached brokers."""
        self.disconnect_all()
        with self._lock:
            self._brokers.clear()
            self._connected.clear()
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.clear()
                cls._instance = None


def get_active_ig_broker_config():
    """
    Get the active IG Broker configuration.
    
    Returns:
        IgBrokerConfig: The active configuration instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    from core.models import IgBrokerConfig
    
    config = IgBrokerConfig.objects.filter(is_active=True).first()
    if not config:
        raise ImproperlyConfigured(
            "No active IG Broker configuration found. Please configure IG Broker in the admin panel."
        )
    return config


def create_ig_broker_service() -> IgBrokerService:
    """
    Create an IgBrokerService instance from the active configuration.
    
    Returns:
        IgBrokerService: Configured broker service instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    config = get_active_ig_broker_config()
    return IgBrokerService.from_config(config)


def get_active_mexc_broker_config():
    """
    Get the active MEXC Broker configuration.
    
    Returns:
        MexcBrokerConfig: The active configuration instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    from core.models import MexcBrokerConfig
    
    config = MexcBrokerConfig.objects.filter(is_active=True).first()
    if not config:
        raise ImproperlyConfigured(
            "No active MEXC Broker configuration found. Please configure MEXC Broker in the admin panel."
        )
    return config


def create_mexc_broker_service() -> MexcBrokerService:
    """
    Create a MexcBrokerService instance from the active configuration.
    
    Returns:
        MexcBrokerService: Configured broker service instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    config = get_active_mexc_broker_config()
    return MexcBrokerService.from_config(config)


def get_active_kraken_broker_config():
    """
    Get the active Kraken Broker configuration.
    
    Returns:
        KrakenBrokerConfig: The active configuration instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    from core.models import KrakenBrokerConfig
    
    config = KrakenBrokerConfig.objects.filter(is_active=True).first()
    if not config:
        raise ImproperlyConfigured(
            "No active Kraken Broker configuration found. Please configure Kraken Broker in the admin panel."
        )
    return config


def create_kraken_broker_service() -> KrakenBrokerService:
    """
    Create a KrakenBrokerService instance from the active configuration.
    
    Returns:
        KrakenBrokerService: Configured broker service instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    config = get_active_kraken_broker_config()
    return KrakenBrokerService.from_config(config)


def get_broker_service_for_asset(asset) -> 'BrokerService':
    """
    Get the appropriate broker service for a trading asset.
    
    Args:
        asset: TradingAsset instance with a broker field.
        
    Returns:
        BrokerService: The appropriate broker service (IG, MEXC, or Kraken).
        
    Raises:
        ImproperlyConfigured: If no active configuration exists for the broker.
        ValueError: If the broker type is not supported.
    """
    from trading.models import TradingAsset
    
    if asset.broker == TradingAsset.BrokerKind.IG:
        return create_ig_broker_service()
    elif asset.broker == TradingAsset.BrokerKind.MEXC:
        return create_mexc_broker_service()
    elif asset.broker == TradingAsset.BrokerKind.KRAKEN:
        return create_kraken_broker_service()
    else:
        raise ValueError(f"Unsupported broker type: {asset.broker}")
