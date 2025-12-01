"""
Broker Service module for Finoa.

Provides abstraction layer for broker integrations (IG, MEXC, etc.)
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

from .mexc_broker_service import MexcBrokerService
from .mexc_market_data import MexcMarketDataFetcher, MexcMarketDataError

from .config import (
    get_active_ig_broker_config,
    create_ig_broker_service,
    get_active_mexc_broker_config,
    create_mexc_broker_service,
    get_broker_service_for_asset,
    BrokerRegistry,
)

from .ig_market_state_provider import IGMarketStateProvider, SessionTimesConfig

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
    # MEXC implementation
    'MexcBrokerService',
    'MexcMarketDataFetcher',
    'MexcMarketDataError',
    # Config utilities
    'get_active_ig_broker_config',
    'create_ig_broker_service',
    'get_active_mexc_broker_config',
    'create_mexc_broker_service',
    'get_broker_service_for_asset',
    'BrokerRegistry',
    # Market State Provider
    'IGMarketStateProvider',
    'SessionTimesConfig',
]
