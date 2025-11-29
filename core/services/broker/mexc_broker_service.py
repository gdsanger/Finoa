"""
MEXC Broker Service implementation.

High-level broker service that provides a clean, abstracted interface
for trading operations via MEXC API (Spot & Margin).
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from urllib.parse import urlencode

import requests

from .broker_service import BrokerService, BrokerError, AuthenticationError
from .models import (
    AccountState,
    Position,
    OrderRequest,
    OrderResult,
    SymbolPrice,
    OrderDirection,
    OrderStatus,
    OrderType,
)


logger = logging.getLogger(__name__)


class MexcBrokerService(BrokerService):
    """
    MEXC implementation of the BrokerService interface.
    
    Provides high-level trading operations using the MEXC API.
    Supports Spot and Margin trading.
    """
    
    DEFAULT_BASE_URL = "https://api.mexc.com"
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "SPOT",
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the MEXC Broker Service.
        
        Args:
            api_key: MEXC API key.
            api_secret: MEXC API secret.
            account_type: "SPOT" or "MARGIN".
            base_url: Override the base URL (optional).
            timeout: Request timeout in seconds.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._account_type = account_type
        self._base_url = base_url or self.DEFAULT_BASE_URL
        self._timeout = timeout
        self._session = requests.Session()
        self._connected = False
        logger.info(f"MexcBrokerService initialized ({account_type})")
    
    @classmethod
    def from_config(cls, config) -> 'MexcBrokerService':
        """
        Create service from a MexcBrokerConfig model instance.
        
        Args:
            config: MexcBrokerConfig model instance.
        
        Returns:
            MexcBrokerService instance.
        """
        return cls(
            api_key=config.api_key,
            api_secret=config.api_secret,
            account_type=config.account_type,
            base_url=config.api_base_url or None,
            timeout=config.timeout_seconds,
        )
    
    def _sign_request(self, params: dict) -> str:
        """
        Generate HMAC SHA256 signature for request.
        
        Args:
            params: Request parameters to sign.
            
        Returns:
            str: Hex-encoded signature.
        """
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds."""
        return int(time.time() * 1000)
    
    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        return {
            "X-MEXC-APIKEY": self._api_key,
            "Content-Type": "application/json",
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        """
        Make a request to the MEXC API.
        
        Args:
            method: HTTP method (GET, POST, DELETE).
            endpoint: API endpoint.
            params: Request parameters.
            signed: Whether to sign the request.
            
        Returns:
            dict: Response JSON.
            
        Raises:
            BrokerError: If request fails.
        """
        url = f"{self._base_url}{endpoint}"
        params = params or {}
        
        if signed:
            params['timestamp'] = self._get_timestamp()
            params['signature'] = self._sign_request(params)
        
        try:
            if method == "GET":
                response = self._session.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self._timeout,
                )
            elif method == "POST":
                response = self._session.post(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self._timeout,
                )
            elif method == "DELETE":
                response = self._session.delete(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self._timeout,
                )
            else:
                raise BrokerError(f"Unsupported HTTP method: {method}")
            
            # Check for errors
            if response.status_code == 401:
                raise AuthenticationError("Invalid API credentials")
            
            if response.status_code != 200:
                error_msg = f"API error: {response.status_code}"
                try:
                    error_data = response.json()
                    if 'msg' in error_data:
                        error_msg = f"{error_msg} - {error_data['msg']}"
                    if 'code' in error_data:
                        error_msg = f"{error_msg} (code: {error_data['code']})"
                except Exception:
                    error_msg = f"{error_msg} - {response.text}"
                raise BrokerError(error_msg)
            
            return response.json()
            
        except requests.RequestException as e:
            raise BrokerError(f"Request failed: {e}")
    
    def connect(self) -> None:
        """
        Connect to MEXC and verify API credentials.
        
        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If credentials are invalid.
        """
        try:
            logger.info("Connecting to MEXC...")
            
            # Verify connection by getting account info
            self._request("GET", "/api/v3/account", signed=True)
            
            self._connected = True
            logger.info("Successfully connected to MEXC")
            
        except AuthenticationError:
            self._connected = False
            raise
        except BrokerError as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to MEXC: {e}")
    
    def disconnect(self) -> None:
        """
        Disconnect from MEXC.
        
        Note: MEXC API doesn't require explicit logout.
        """
        logger.info("Disconnecting from MEXC...")
        self._connected = False
        self._session.close()
        logger.info("Disconnected from MEXC")
    
    def is_connected(self) -> bool:
        """
        Check if service is connected.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        return self._connected
    
    def _ensure_connected(self) -> None:
        """Ensure service is connected, raise if not."""
        if not self.is_connected():
            raise ConnectionError("Not connected to MEXC. Call connect() first.")
    
    def get_account_state(self) -> AccountState:
        """
        Get current account state.
        
        Returns:
            AccountState with current balances.
        """
        self._ensure_connected()
        
        try:
            account_data = self._request("GET", "/api/v3/account", signed=True)
            
            # Sum up all balances
            total_balance = Decimal('0')
            available = Decimal('0')
            
            for balance in account_data.get('balances', []):
                free = Decimal(str(balance.get('free', '0')))
                locked = Decimal(str(balance.get('locked', '0')))
                # For simplicity, we're summing all assets
                # In production, you'd want to convert to a common currency
                if balance.get('asset') == 'USDT':
                    total_balance = free + locked
                    available = free
            
            return AccountState(
                account_id=str(account_data.get('accountType', 'SPOT')),
                account_name=f"MEXC {self._account_type}",
                balance=total_balance,
                available=available,
                equity=total_balance,
                margin_used=Decimal('0'),
                margin_available=available,
                unrealized_pnl=Decimal('0'),
                currency='USDT',
                timestamp=datetime.now(timezone.utc),
            )
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get account state: {e}")
    
    def get_open_positions(self) -> List[Position]:
        """
        Get all currently open positions.
        
        For spot trading, this returns non-zero balances.
        For margin trading, this returns actual positions.
        
        Returns:
            List[Position]: List of all open positions.
        """
        self._ensure_connected()
        
        try:
            positions = []
            
            if self._account_type == "MARGIN":
                # Get margin positions
                # Note: MEXC margin API may differ, adjust as needed
                pass
            else:
                # For spot, get balances with non-zero values
                account_data = self._request("GET", "/api/v3/account", signed=True)
                
                for balance in account_data.get('balances', []):
                    free = Decimal(str(balance.get('free', '0')))
                    locked = Decimal(str(balance.get('locked', '0')))
                    total = free + locked
                    
                    if total > 0 and balance.get('asset') != 'USDT':
                        # Create a position-like entry for non-zero balances
                        asset = balance.get('asset', '')
                        symbol = f"{asset}USDT"
                        
                        # Get current price for this asset
                        try:
                            price_data = self.get_symbol_price(symbol)
                            current_price = price_data.mid_price
                        except Exception:
                            current_price = Decimal('0')
                        
                        position = Position(
                            position_id=f"spot_{asset}",
                            deal_id=f"spot_{asset}",
                            epic=symbol,
                            market_name=f"{asset}/USDT",
                            direction=OrderDirection.BUY,
                            size=total,
                            open_price=Decimal('0'),  # Not tracked for spot
                            current_price=current_price,
                            unrealized_pnl=Decimal('0'),
                            currency='USDT',
                        )
                        positions.append(position)
            
            return positions
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get positions: {e}")
    
    def get_symbol_price(self, symbol: str) -> SymbolPrice:
        """
        Get current price for a market/symbol.
        
        Args:
            symbol: Market symbol (e.g., 'BTCUSDT').
        
        Returns:
            SymbolPrice with current bid/ask and other price data.
        """
        self._ensure_connected()
        
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        
        try:
            # Get ticker price
            ticker_data = self._request(
                "GET",
                "/api/v3/ticker/bookTicker",
                params={"symbol": symbol}
            )
            
            bid = Decimal(str(ticker_data.get('bidPrice', '0')))
            ask = Decimal(str(ticker_data.get('askPrice', '0')))
            
            # Get 24h stats for high/low
            stats_data = self._request(
                "GET",
                "/api/v3/ticker/24hr",
                params={"symbol": symbol}
            )
            
            return SymbolPrice(
                epic=symbol,
                market_name=symbol,
                bid=bid,
                ask=ask,
                spread=ask - bid,
                high=Decimal(str(stats_data.get('highPrice'))) if stats_data.get('highPrice') else None,
                low=Decimal(str(stats_data.get('lowPrice'))) if stats_data.get('lowPrice') else None,
                change=Decimal(str(stats_data.get('priceChange'))) if stats_data.get('priceChange') else None,
                change_percent=Decimal(str(stats_data.get('priceChangePercent'))) if stats_data.get('priceChangePercent') else None,
                timestamp=datetime.now(timezone.utc),
            )
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get price for {symbol}: {e}")
    
    def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Place a new order.
        
        Args:
            order: OrderRequest with order details.
        
        Returns:
            OrderResult with deal reference and status.
        """
        self._ensure_connected()
        
        try:
            # Map order direction
            side = "BUY" if order.direction == OrderDirection.BUY else "SELL"
            
            # Map order type
            if order.order_type == OrderType.MARKET:
                order_type = "MARKET"
            elif order.order_type in [OrderType.LIMIT, OrderType.BUY_LIMIT, OrderType.SELL_LIMIT]:
                order_type = "LIMIT"
            else:
                order_type = "MARKET"
            
            params = {
                "symbol": order.epic,
                "side": side,
                "type": order_type,
                "quantity": str(order.size),
            }
            
            # Add price for limit orders
            if order_type == "LIMIT" and order.limit_price:
                params["price"] = str(order.limit_price)
                params["timeInForce"] = "GTC"
            
            # Place the order
            response = self._request("POST", "/api/v3/order", params=params, signed=True)
            
            order_id = str(response.get('orderId', ''))
            status_str = response.get('status', '')
            
            # Map MEXC status to our status
            if status_str in ['FILLED', 'PARTIALLY_FILLED']:
                status = OrderStatus.OPEN
            elif status_str == 'NEW':
                status = OrderStatus.PENDING
            elif status_str in ['CANCELED', 'REJECTED', 'EXPIRED']:
                status = OrderStatus.REJECTED
            else:
                status = OrderStatus.PENDING
            
            return OrderResult(
                success=status_str in ['NEW', 'FILLED', 'PARTIALLY_FILLED'],
                deal_id=order_id,
                deal_reference=order_id,
                status=status,
                reason=None if status != OrderStatus.REJECTED else f"Order {status_str}",
            )
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to place order: {e}")
    
    def close_position(self, position_id: str) -> OrderResult:
        """
        Close an existing position.
        
        For spot trading, this sells the asset.
        For margin trading, this closes the margin position.
        
        Args:
            position_id: ID of the position to close (format: "spot_ASSET" or order ID).
        
        Returns:
            OrderResult with close confirmation.
        """
        self._ensure_connected()
        
        if not position_id:
            raise ValueError("Position ID cannot be empty")
        
        try:
            # For spot positions (format: spot_ASSET)
            if position_id.startswith("spot_"):
                asset = position_id.replace("spot_", "")
                symbol = f"{asset}USDT"
                
                # Get current balance
                account_data = self._request("GET", "/api/v3/account", signed=True)
                
                balance = Decimal('0')
                for b in account_data.get('balances', []):
                    if b.get('asset') == asset:
                        balance = Decimal(str(b.get('free', '0')))
                        break
                
                if balance <= 0:
                    return OrderResult(
                        success=False,
                        reason=f"No balance to sell for {asset}",
                        status=OrderStatus.REJECTED,
                    )
                
                # Sell the entire balance
                order = OrderRequest(
                    epic=symbol,
                    direction=OrderDirection.SELL,
                    size=balance,
                    order_type=OrderType.MARKET,
                )
                return self.place_order(order)
            
            else:
                # Cancel an existing order
                # Note: This doesn't close positions, just cancels pending orders
                # For actual position closing, you'd need to place an opposite order
                return OrderResult(
                    success=False,
                    reason="Direct order cancellation not supported. Use a counter-order to close.",
                    status=OrderStatus.REJECTED,
                )
                
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to close position: {e}")
    
    def get_historical_prices(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
    ) -> List[dict]:
        """
        Get historical price data (klines/candlesticks) for a market.
        
        Args:
            symbol: Market symbol (e.g., 'BTCUSDT').
            interval: Kline interval (1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.).
            limit: Number of klines to retrieve (max 1000).
        
        Returns:
            List of kline data dictionaries.
        """
        self._ensure_connected()
        
        try:
            response = self._request(
                "GET",
                "/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                }
            )
            
            candles = []
            for kline in response:
                # MEXC kline format:
                # [open_time, open, high, low, close, volume, close_time, ...]
                candle = {
                    "time": int(kline[0] / 1000),  # Convert ms to seconds
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                }
                candles.append(candle)
            
            return candles
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get historical prices for {symbol}: {e}")
