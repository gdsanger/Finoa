"""
Broker configuration utilities.

Provides functions to get active broker configurations and create broker services.
"""
from django.core.exceptions import ImproperlyConfigured

from .ig_broker_service import IgBrokerService
from .mexc_broker_service import MexcBrokerService


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


def get_broker_service_for_asset(asset) -> 'BrokerService':
    """
    Get the appropriate broker service for a trading asset.
    
    Args:
        asset: TradingAsset instance with a broker field.
        
    Returns:
        BrokerService: The appropriate broker service (IG or MEXC).
        
    Raises:
        ImproperlyConfigured: If no active configuration exists for the broker.
        ValueError: If the broker type is not supported.
    """
    from trading.models import TradingAsset
    
    if asset.broker == TradingAsset.BrokerKind.IG:
        return create_ig_broker_service()
    elif asset.broker == TradingAsset.BrokerKind.MEXC:
        return create_mexc_broker_service()
    else:
        raise ValueError(f"Unsupported broker type: {asset.broker}")
