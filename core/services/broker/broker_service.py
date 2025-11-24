"""
Abstract Broker Service interface.

Defines the contract that all broker implementations must follow.
This ensures Finoa is independent of specific broker implementations.
"""
from abc import ABC, abstractmethod
from typing import List

from .models import (
    AccountState,
    Position,
    OrderRequest,
    OrderResult,
    SymbolPrice,
)


class BrokerService(ABC):
    """
    Abstract base class for broker service implementations.
    
    All broker integrations (IG, etc.) should implement this interface
    to ensure consistent behavior across different brokers.
    """

    @abstractmethod
    def connect(self) -> None:
        """
        Establish connection to the broker API.
        
        This should handle authentication and session creation.
        
        Raises:
            ConnectionError: If connection cannot be established.
            AuthenticationError: If credentials are invalid.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Close the connection to the broker API.
        
        This should handle proper session cleanup and logout.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if the service is currently connected.
        
        Returns:
            bool: True if connected and session is valid, False otherwise.
        """
        pass

    @abstractmethod
    def get_account_state(self) -> AccountState:
        """
        Get the current account state.
        
        Returns:
            AccountState: Current account information including balance,
                         equity, margin, and P&L.
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If account information cannot be retrieved.
        """
        pass

    @abstractmethod
    def get_open_positions(self) -> List[Position]:
        """
        Get all currently open positions.
        
        Returns:
            List[Position]: List of all open positions.
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If positions cannot be retrieved.
        """
        pass

    @abstractmethod
    def get_symbol_price(self, epic: str) -> SymbolPrice:
        """
        Get current price information for a market/symbol.
        
        Args:
            epic: Market identifier (e.g., 'IX.D.SPTRD.IFD.IP' for IG).
        
        Returns:
            SymbolPrice: Current price information for the market.
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If price cannot be retrieved.
            ValueError: If epic is invalid.
        """
        pass

    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Place a new order.
        
        Args:
            order: OrderRequest with details of the order to place.
        
        Returns:
            OrderResult: Result of the order placement.
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If order cannot be placed.
            ValueError: If order request is invalid.
        """
        pass

    @abstractmethod
    def close_position(self, position_id: str) -> OrderResult:
        """
        Close an existing position.
        
        Args:
            position_id: ID of the position to close.
        
        Returns:
            OrderResult: Result of the close operation.
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If position cannot be closed.
            ValueError: If position_id is invalid.
        """
        pass


class BrokerError(Exception):
    """Exception raised for broker-related errors."""
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        """
        Initialize BrokerError.
        
        Args:
            message: Human-readable error message.
            code: Error code from the broker (if available).
            details: Additional error details.
        """
        super().__init__(message)
        self.code = code
        self.details = details or {}


class AuthenticationError(BrokerError):
    """Exception raised when authentication fails."""
    pass
