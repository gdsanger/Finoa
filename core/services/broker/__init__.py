"""
Broker Service module for Finoa.

Provides abstraction layer for broker integrations (IG, etc.)
"""

from .models import (
    AccountState,
    Position,
    OrderRequest,
    OrderResult,
    SymbolPrice,
    OrderType,
    OrderDirection,
    PositionDirection,
    Direction,
    OrderStatus,
    BrokerErrorData,
)

from .broker_service import BrokerService, BrokerError, AuthenticationError

from .ig_api_client import IgApiClient

from .ig_broker_service import IgBrokerService

from .config import get_active_ig_broker_config, create_ig_broker_service

from .ig_market_state_provider import IGMarketStateProvider

__all__ = [
    # Data models
    'AccountState',
    'Position',
    'OrderRequest',
    'OrderResult',
    'SymbolPrice',
    'OrderType',
    'OrderDirection',
    'PositionDirection',
    'Direction',
    'OrderStatus',
    'BrokerErrorData',
    # Service interface
    'BrokerService',
    'BrokerError',
    'AuthenticationError',
    # IG implementation
    'IgApiClient',
    'IgBrokerService',
    # Config utilities
    'get_active_ig_broker_config',
    'create_ig_broker_service',
    # Market State Provider
    'IGMarketStateProvider',
]
