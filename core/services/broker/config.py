"""
Broker configuration utilities.

Provides functions to get active broker configurations and create broker services.
"""
from django.core.exceptions import ImproperlyConfigured

from .ig_broker_service import IgBrokerService


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
