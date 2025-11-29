"""
MEXC Broker Service implementation.

High-level broker service that provides a clean, abstracted interface
for trading operations via MEXC API (Spot & Futures).

Note: MEXC only has Spot and Futures accounts. There is no separate
Margin account - margin trading is done through the Futures API.
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
    Supports Spot and Futures trading.
    
    Note: MEXC only has Spot and Futures accounts. The legacy "MARGIN"
    account type is treated as FUTURES for backwards compatibility.
    """
    
    DEFAULT_BASE_URL = "https://api.mexc.com"
    DEFAULT_FUTURES_BASE_URL = "https://contract.mexc.com"
    
    # Futures API position type constants
    POSITION_LONG = 1
    POSITION_SHORT = 2
    
    # Futures API order side constants
    ORDER_SIDE_OPEN_LONG = 1
    ORDER_SIDE_CLOSE_LONG = 2
    ORDER_SIDE_OPEN_SHORT = 3
    ORDER_SIDE_CLOSE_SHORT = 4
    
    # Futures API order type constants
    ORDER_TYPE_MARKET = 5
    
    # Futures API margin type constants
    MARGIN_TYPE_ISOLATED = 1
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_type: str = "SPOT",
        base_url: Optional[str] = None,
        futures_base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the MEXC Broker Service.
        
        Args:
            api_key: MEXC API key.
            api_secret: MEXC API secret.
            account_type: "SPOT" or "FUTURES" (legacy "MARGIN" is treated as "FUTURES").
            base_url: Override the base URL for Spot (optional).
            futures_base_url: Override the base URL for Futures (optional).
            timeout: Request timeout in seconds.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        # Treat legacy MARGIN as FUTURES
        self._account_type = "FUTURES" if account_type == "MARGIN" else account_type
        self._base_url = base_url or self.DEFAULT_BASE_URL
        self._futures_base_url = futures_base_url or self.DEFAULT_FUTURES_BASE_URL
        self._timeout = timeout
        self._session = requests.Session()
        self._connected = False
        logger.info(f"MexcBrokerService initialized ({self._account_type})")
    
    def _is_futures_account(self) -> bool:
        """Check if this is a Futures account."""
        return self._account_type == "FUTURES"
    
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
    
    def _get_futures_headers(self, timestamp: int, signature: str) -> dict:
        """Get headers for Futures API requests."""
        return {
            "ApiKey": self._api_key,
            "Request-Time": str(timestamp),
            "Signature": signature,
            "Content-Type": "application/json",
        }
    
    def _sign_futures_request(self, timestamp: int, params: Optional[dict] = None) -> str:
        """
        Generate HMAC SHA256 signature for Futures API request.
        
        The Futures API requires signing: api_key + timestamp + query_string
        
        Args:
            timestamp: Request timestamp in milliseconds.
            params: Request parameters to sign (optional).
            
        Returns:
            str: Hex-encoded signature.
        """
        query_string = urlencode(params) if params else ""
        sign_string = f"{self._api_key}{timestamp}{query_string}"
        signature = hmac.new(
            self._api_secret.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _futures_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Make a request to the MEXC Futures API.
        
        The Futures API uses a different authentication scheme than Spot/Margin.
        
        Args:
            method: HTTP method (GET, POST, DELETE).
            endpoint: API endpoint.
            params: Request parameters.
            
        Returns:
            dict: Response JSON.
            
        Raises:
            BrokerError: If request fails.
        """
        url = f"{self._futures_base_url}{endpoint}"
        request_params = params if params else None
        timestamp = self._get_timestamp()
        signature = self._sign_futures_request(timestamp, request_params)
        headers = self._get_futures_headers(timestamp, signature)
        
        try:
            if method == "GET":
                response = self._session.get(
                    url,
                    params=request_params,
                    headers=headers,
                    timeout=self._timeout,
                )
            elif method == "POST":
                response = self._session.post(
                    url,
                    params=request_params,
                    headers=headers,
                    timeout=self._timeout,
                )
            elif method == "DELETE":
                response = self._session.delete(
                    url,
                    params=request_params,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                raise BrokerError(f"Unsupported HTTP method: {method}")
            
            # Check for errors
            if response.status_code == 401:
                raise AuthenticationError("Invalid API credentials for Futures")
            
            if response.status_code != 200:
                error_msg = f"Futures API error: {response.status_code}"
                try:
                    error_data = response.json()
                    if 'message' in error_data:
                        error_msg = f"{error_msg} - {error_data['message']}"
                    if 'code' in error_data:
                        error_msg = f"{error_msg} (code: {error_data['code']})"
                except Exception:
                    error_msg = f"{error_msg} - {response.text}"
                raise BrokerError(error_msg)
            
            response_data = response.json()
            
            # Futures API wraps responses with success/code/data structure
            if isinstance(response_data, dict):
                if response_data.get('success') is False:
                    error_msg = response_data.get('message', 'Unknown Futures API error')
                    error_code = response_data.get('code', 'UNKNOWN')
                    raise BrokerError(f"Futures API error: {error_msg} (code: {error_code})")
                # Return the 'data' field if present, otherwise return the full response
                if 'data' in response_data:
                    return response_data['data']
            
            return response_data
            
        except requests.RequestException as e:
            raise BrokerError(f"Futures request failed: {e}")
    
    def connect(self) -> None:
        """
        Connect to MEXC and verify API credentials.
        
        For Spot accounts, verifies via /api/v3/account.
        For Futures accounts, verifies via /api/v1/private/account/assets.
        
        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If credentials are invalid.
        """
        try:
            logger.info(f"Connecting to MEXC ({self._account_type})...")
            
            if self._is_futures_account():
                # Verify Futures connection by getting account assets
                self._futures_request("GET", "/api/v1/private/account/assets")
            else:
                # Verify Spot connection by getting account info
                self._request("GET", "/api/v3/account", signed=True)
            
            self._connected = True
            logger.info(f"Successfully connected to MEXC ({self._account_type})")
            
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
        
        For Spot accounts, retrieves from /api/v3/account.
        For Futures accounts, retrieves from /api/v1/private/account/assets.
        
        Returns:
            AccountState with current balances.
        """
        self._ensure_connected()
        
        try:
            if self._is_futures_account():
                return self._get_futures_account_state()
            else:
                return self._get_spot_account_state()
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get account state: {e}")
    
    def _get_spot_account_state(self) -> AccountState:
        """Get account state from Spot API."""
        account_data = self._request("GET", "/api/v3/account", signed=True)
        
        # Get USDT balance for account state
        # Note: For proper multi-asset accounting, you'd need to convert all
        # assets to a common base currency using current market prices.
        # This implementation focuses on USDT as the primary quote currency.
        usdt_balance = Decimal('0')
        usdt_available = Decimal('0')
        
        for balance in account_data.get('balances', []):
            if balance.get('asset') == 'USDT':
                usdt_balance = Decimal(str(balance.get('free', '0'))) + Decimal(str(balance.get('locked', '0')))
                usdt_available = Decimal(str(balance.get('free', '0')))
                break
        
        return AccountState(
            account_id=str(account_data.get('accountType', 'SPOT')),
            account_name=f"MEXC {self._account_type}",
            balance=usdt_balance,
            available=usdt_available,
            equity=usdt_balance,
            margin_used=Decimal('0'),
            margin_available=usdt_available,
            unrealized_pnl=Decimal('0'),
            currency='USDT',
            timestamp=datetime.now(timezone.utc),
        )
    
    def _get_futures_account_state(self) -> AccountState:
        """
        Get account state from Futures API.
        
        The Futures API returns account assets including:
        - equity: Total equity (balance + unrealized P&L)
        - availableBalance: Available for trading
        - frozenBalance: Frozen/used margin
        - unrealisedPnl: Unrealized profit/loss
        """
        # Get account assets from Futures API
        assets_data = self._futures_request("GET", "/api/v1/private/account/assets")
        
        # Find USDT asset in the response
        # The response is a list of assets
        usdt_equity = Decimal('0')
        usdt_available = Decimal('0')
        usdt_frozen = Decimal('0')
        usdt_unrealized_pnl = Decimal('0')
        
        if isinstance(assets_data, list):
            for asset in assets_data:
                if asset.get('currency') == 'USDT':
                    usdt_equity = Decimal(str(asset.get('equity', '0')))
                    usdt_available = Decimal(str(asset.get('availableBalance', '0')))
                    usdt_frozen = Decimal(str(asset.get('frozenBalance', '0')))
                    usdt_unrealized_pnl = Decimal(str(asset.get('unrealisedPnl', '0')))
                    break
        
        # Calculate balance (equity - unrealized P&L)
        usdt_balance = usdt_equity - usdt_unrealized_pnl
        
        return AccountState(
            account_id='FUTURES',
            account_name=f"MEXC {self._account_type}",
            balance=usdt_balance,
            available=usdt_available,
            equity=usdt_equity,
            margin_used=usdt_frozen,
            margin_available=usdt_available,
            unrealized_pnl=usdt_unrealized_pnl,
            currency='USDT',
            timestamp=datetime.now(timezone.utc),
        )
    
    def get_open_positions(self) -> List[Position]:
        """
        Get all currently open positions.
        
        For spot trading, this returns non-zero balances.
        For futures trading, this returns actual futures positions.
        
        Returns:
            List[Position]: List of all open positions.
        """
        self._ensure_connected()
        
        try:
            if self._is_futures_account():
                return self._get_futures_positions()
            else:
                return self._get_spot_positions()
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get positions: {e}")
    
    def _get_spot_positions(self) -> List[Position]:
        """Get positions from Spot account (non-zero balances)."""
        positions = []
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
    
    def _get_futures_positions(self) -> List[Position]:
        """
        Get open positions from Futures account.
        
        Uses the Futures API endpoint /api/v1/private/position/open_positions.
        """
        positions = []
        
        try:
            # Get open positions from Futures API
            positions_data = self._futures_request(
                "GET",
                "/api/v1/private/position/open_positions"
            )
            
            if isinstance(positions_data, list):
                for pos in positions_data:
                    symbol = pos.get('symbol', '')
                    pos_type = pos.get('positionType', self.POSITION_LONG)
                    hold_vol = Decimal(str(pos.get('holdVol', '0')))
                    open_avg_price = Decimal(str(pos.get('openAvgPrice', '0')))
                    unrealised_pnl = Decimal(str(pos.get('unrealisedPnl', '0')))
                    
                    if hold_vol > 0:
                        # Get current price
                        try:
                            # For futures, convert symbol format if needed
                            # MEXC Futures uses symbols like "BTC_USDT"
                            spot_symbol = symbol.replace('_', '')
                            price_data = self.get_symbol_price(spot_symbol)
                            current_price = price_data.mid_price
                        except Exception:
                            current_price = Decimal('0')
                        
                        direction = OrderDirection.BUY if pos_type == self.POSITION_LONG else OrderDirection.SELL
                        
                        position = Position(
                            position_id=f"futures_{symbol}_{pos_type}",
                            deal_id=f"futures_{symbol}_{pos_type}",
                            epic=symbol,
                            market_name=symbol,
                            direction=direction,
                            size=hold_vol,
                            open_price=open_avg_price,
                            current_price=current_price,
                            unrealized_pnl=unrealised_pnl,
                            currency='USDT',
                        )
                        positions.append(position)
                        
        except BrokerError as e:
            logger.warning(f"Failed to get futures positions: {e}")
        
        return positions
    
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
        For futures trading, this closes the futures position.
        
        Args:
            position_id: ID of the position to close (format: "spot_ASSET", "futures_SYMBOL_TYPE").
        
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
            
            elif position_id.startswith("futures_"):
                # Close a futures position
                # Position ID format: futures_SYMBOL_POSTYPE (e.g., futures_BTC_USDT_1)
                parts = position_id.replace("futures_", "").rsplit("_", 1)
                if len(parts) != 2:
                    return OrderResult(
                        success=False,
                        reason=f"Invalid futures position ID format: {position_id}",
                        status=OrderStatus.REJECTED,
                    )
                
                symbol = parts[0]
                pos_type = int(parts[1])  # 1=Long, 2=Short
                
                # For futures, we need to find the position and close it
                # Get open positions to find the one to close
                try:
                    positions_data = self._futures_request(
                        "GET",
                        "/api/v1/private/position/open_positions"
                    )
                    
                    position_size = Decimal('0')
                    if isinstance(positions_data, list):
                        for pos in positions_data:
                            if pos.get('symbol') == symbol and pos.get('positionType') == pos_type:
                                position_size = Decimal(str(pos.get('holdVol', '0')))
                                break
                    
                    if position_size <= 0:
                        return OrderResult(
                            success=False,
                            reason=f"No futures position to close for {symbol}",
                            status=OrderStatus.REJECTED,
                        )
                    
                    # Close position via Futures API
                    # The close direction is opposite to position type
                    # Long -> Close Long, Short -> Close Short
                    if pos_type == self.POSITION_LONG:
                        close_side = self.ORDER_SIDE_CLOSE_LONG
                    else:
                        close_side = self.ORDER_SIDE_CLOSE_SHORT
                    
                    close_params = {
                        "symbol": symbol,
                        "vol": str(position_size),
                        "side": close_side,
                        "type": self.ORDER_TYPE_MARKET,
                        "openType": self.MARGIN_TYPE_ISOLATED,
                    }
                    
                    response = self._futures_request(
                        "POST",
                        "/api/v1/private/order/submit",
                        params=close_params
                    )
                    
                    order_id = str(response.get('orderId', '')) if response else ''
                    
                    return OrderResult(
                        success=True,
                        deal_id=order_id,
                        deal_reference=order_id,
                        status=OrderStatus.PENDING,
                    )
                    
                except BrokerError as e:
                    return OrderResult(
                        success=False,
                        reason=f"Failed to close futures position: {e}",
                        status=OrderStatus.REJECTED,
                    )
            
            # Handle legacy margin_ prefix - treat as futures
            elif position_id.startswith("margin_"):
                # Legacy margin positions should be handled as futures
                logger.warning(f"Legacy margin position ID '{position_id}' - MEXC has no margin API, treating as futures")
                return OrderResult(
                    success=False,
                    reason="Margin positions are not supported on MEXC. Use 'futures_' prefix for futures positions.",
                    status=OrderStatus.REJECTED,
                )
            
            else:
                # Try to cancel an order by ID
                return OrderResult(
                    success=False,
                    reason="Order cancellation requires symbol. Use spot_ASSET or futures_SYMBOL_TYPE format for positions.",
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
