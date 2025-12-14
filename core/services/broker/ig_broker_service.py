"""
IG Broker Service implementation.

High-level broker service that uses IgApiClient to provide a clean,
abstracted interface for trading operations via IG.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from dateutil import parser as dateutil_parser

from .broker_service import BrokerService, BrokerError, AuthenticationError
from .ig_api_client import IgApiClient, IgSession
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


class IgBrokerService(BrokerService):
    """
    IG implementation of the BrokerService interface.
    
    Provides high-level trading operations using the IG Web API.
    """

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        account_type: str = "DEMO",
        account_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the IG Broker Service.
        
        Args:
            api_key: IG API key.
            username: IG account username/identifier.
            password: IG account password.
            account_type: "DEMO" or "LIVE".
            account_id: Specific account ID to use (if multiple accounts).
            base_url: Override the base URL (optional).
            timeout: Request timeout in seconds.
        """
        self._client = IgApiClient(
            api_key=api_key,
            username=username,
            password=password,
            account_type=account_type,
            account_id=account_id,
            base_url=base_url,
            timeout=timeout,
        )
        self._connected = False
        logger.info(f"IgBrokerService initialized ({account_type})")

    @classmethod
    def from_config(cls, config) -> 'IgBrokerService':
        """
        Create service from an IgBrokerConfig model instance.
        
        Args:
            config: IgBrokerConfig model instance.
        
        Returns:
            IgBrokerService instance.
        """
        return cls(
            api_key=config.api_key,
            username=config.username,
            password=config.password,
            account_type=config.account_type,
            account_id=config.account_id or None,
            base_url=config.api_base_url or None,
            timeout=config.timeout_seconds,
        )

    def connect(self) -> None:
        """
        Connect to IG and establish a session.
        
        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If credentials are invalid.
        """
        try:
            logger.info("Connecting to IG...")
            self._client.login()
            self._connected = True
            logger.info("Successfully connected to IG")
        except AuthenticationError:
            self._connected = False
            raise
        except BrokerError as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to IG: {e}")

    def disconnect(self) -> None:
        """
        Disconnect from IG and end the session.
        """
        try:
            logger.info("Disconnecting from IG...")
            self._client.logout()
        finally:
            self._connected = False
            logger.info("Disconnected from IG")

    def is_connected(self) -> bool:
        """
        Check if service is connected.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        return self._connected and self._client.is_authenticated

    def _ensure_connected(self) -> None:
        """Ensure service is connected, raise if not."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IG. Call connect() first.")

    def get_account_state(self) -> AccountState:
        """
        Get current account state.
        
        Returns:
            AccountState with current balance, equity, margin, etc.
        """
        self._ensure_connected()
        
        try:
            account_data = self._client.get_account_details()
            balance_data = account_data.get("balance", {})
            
            return AccountState(
                account_id=account_data.get("accountId", ""),
                account_name=account_data.get("accountName", ""),
                balance=Decimal(str(balance_data.get("balance", 0))),
                available=Decimal(str(balance_data.get("available", 0))),
                equity=Decimal(str(balance_data.get("balance", 0))),
                margin_used=Decimal(str(balance_data.get("deposit", 0))),
                margin_available=Decimal(str(balance_data.get("available", 0))),
                unrealized_pnl=Decimal(str(balance_data.get("profitLoss", 0))),
                currency=account_data.get("currency", "EUR"),
                timestamp=datetime.now(timezone.utc),
            )
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get account state: {e}")

    def get_open_positions(self) -> List[Position]:
        """
        Get all open positions.
        
        Returns:
            List of Position objects.
        """
        self._ensure_connected()
        
        try:
            positions_data = self._client.get_positions()
            positions = []
            
            for pos in positions_data:
                position_data = pos.get("position", {})
                market_data = pos.get("market", {})
                
                direction_str = position_data.get("direction", "BUY")
                direction = OrderDirection.BUY if direction_str == "BUY" else OrderDirection.SELL
                
                # Calculate current price based on direction
                bid = Decimal(str(market_data.get("bid", 0)))
                offer = Decimal(str(market_data.get("offer", 0)))
                current_price = bid if direction == OrderDirection.BUY else offer
                
                position = Position(
                    position_id=position_data.get("dealId", ""),
                    deal_id=position_data.get("dealId", ""),
                    epic=market_data.get("epic", ""),
                    market_name=market_data.get("instrumentName", ""),
                    direction=direction,
                    size=Decimal(str(position_data.get("size", 0))),
                    open_price=Decimal(str(position_data.get("level", 0))),
                    current_price=current_price,
                    stop_loss=Decimal(str(position_data.get("stopLevel"))) if position_data.get("stopLevel") else None,
                    take_profit=Decimal(str(position_data.get("limitLevel"))) if position_data.get("limitLevel") else None,
                    unrealized_pnl=Decimal(str(position_data.get("profit", 0))),
                    currency=position_data.get("currency", "EUR"),
                    created_at=dateutil_parser.parse(position_data["createdDateUTC"]) if position_data.get("createdDateUTC") else None,
                )
                positions.append(position)
            
            return positions
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get positions: {e}")

    def get_symbol_price(self, epic: str) -> SymbolPrice:
        """
        Get current price for a market.
        
        Args:
            epic: Market EPIC code.
        
        Returns:
            SymbolPrice with current bid/ask and other price data.
        """
        self._ensure_connected()
        
        if not epic:
            raise ValueError("Epic cannot be empty")
        
        try:
            market_data = self._client.get_market(epic)
            snapshot = market_data.get("snapshot", {})
            instrument = market_data.get("instrument", {})
            
            bid = Decimal(str(snapshot.get("bid", 0)))
            offer = Decimal(str(snapshot.get("offer", 0)))
            
            return SymbolPrice(
                epic=epic,
                market_name=instrument.get("name", ""),
                bid=bid,
                ask=offer,
                spread=offer - bid,
                high=Decimal(str(snapshot.get("high"))) if snapshot.get("high") else None,
                low=Decimal(str(snapshot.get("low"))) if snapshot.get("low") else None,
                change=Decimal(str(snapshot.get("netChange"))) if snapshot.get("netChange") else None,
                change_percent=Decimal(str(snapshot.get("percentageChange"))) if snapshot.get("percentageChange") else None,
                timestamp=datetime.now(timezone.utc),
            )
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get price for {epic}: {e}")

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
            # Map order type and direction to IG format
            direction = "BUY" if order.direction == OrderDirection.BUY else "SELL"
            
            # Map order type
            order_type = "MARKET"
            level = None
            
            if order.order_type == OrderType.LIMIT:
                order_type = "LIMIT"
                level = order.limit_price
            elif order.order_type == OrderType.STOP:
                order_type = "STOP"
                level = order.stop_price
            elif order.order_type in [OrderType.BUY_LIMIT, OrderType.SELL_LIMIT]:
                order_type = "LIMIT"
                level = order.limit_price
            elif order.order_type in [OrderType.BUY_STOP, OrderType.SELL_STOP]:
                order_type = "STOP"
                level = order.stop_price
            
            # Create position
            response = self._client.create_position(
                epic=order.epic,
                direction=direction,
                size=order.size,
                order_type=order_type,
                currency_code=order.currency,
                stop_level=order.stop_loss,
                limit_level=order.take_profit,
                guaranteed_stop=order.guaranteed_stop,
                level=level,
            )
            
            deal_reference = response.get("dealReference")
            
            if not deal_reference:
                return OrderResult(
                    success=False,
                    reason="No deal reference returned",
                    status=OrderStatus.REJECTED,
                )
            
            # Confirm the deal
            confirmation = self._client.confirm_deal(deal_reference)
            deal_status = confirmation.get("dealStatus", "")
            
            if deal_status == "ACCEPTED":
                return OrderResult(
                    success=True,
                    deal_id=confirmation.get("dealId"),
                    deal_reference=deal_reference,
                    status=OrderStatus.OPEN,
                    affected_deals=[
                        d.get("dealId") for d in confirmation.get("affectedDeals", [])
                    ],
                )
            else:
                return OrderResult(
                    success=False,
                    deal_reference=deal_reference,
                    status=OrderStatus.REJECTED,
                    reason=confirmation.get("reason", "Order rejected"),
                )
                
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to place order: {e}")

    def close_position(self, position_id: str) -> OrderResult:
        """
        Close an existing position.
        
        Args:
            position_id: Deal ID of the position to close.
        
        Returns:
            OrderResult with close confirmation.
        """
        self._ensure_connected()
        
        if not position_id:
            raise ValueError("Position ID cannot be empty")
        
        try:
            # First, get position details to know direction and size
            positions = self.get_open_positions()
            position = None
            for pos in positions:
                if pos.deal_id == position_id or pos.position_id == position_id:
                    position = pos
                    break
            
            if not position:
                return OrderResult(
                    success=False,
                    reason=f"Position {position_id} not found",
                    status=OrderStatus.REJECTED,
                )
            
            # Close direction is opposite to open direction
            close_direction = "SELL" if position.direction == OrderDirection.BUY else "BUY"
            
            # Close the position
            response = self._client.close_position(
                deal_id=position.deal_id,
                direction=close_direction,
                size=position.size,
            )
            
            deal_reference = response.get("dealReference")
            
            if not deal_reference:
                return OrderResult(
                    success=False,
                    reason="No deal reference returned",
                    status=OrderStatus.REJECTED,
                )
            
            # Confirm the deal
            confirmation = self._client.confirm_deal(deal_reference)
            deal_status = confirmation.get("dealStatus", "")
            
            if deal_status == "ACCEPTED":
                return OrderResult(
                    success=True,
                    deal_id=confirmation.get("dealId"),
                    deal_reference=deal_reference,
                    status=OrderStatus.CLOSED,
                    affected_deals=[
                        d.get("dealId") for d in confirmation.get("affectedDeals", [])
                    ],
                )
            else:
                return OrderResult(
                    success=False,
                    deal_reference=deal_reference,
                    status=OrderStatus.REJECTED,
                    reason=confirmation.get("reason", "Close order rejected"),
                )
                
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to close position: {e}")

    def get_historical_prices(
        self,
        epic: str,
        resolution: str = "MINUTE",
        num_points: int = 720,
    ) -> List[dict]:
        """
        Get historical price data (candles) for a market.
        
        Uses the IG REST API /prices/{epic} endpoint to fetch historical
        OHLC candlestick data.
        
        Args:
            epic: Market EPIC code (e.g., 'CC.D.CL.UNC.IP').
            resolution: Price resolution (default: 'MINUTE' for 1m candles). One of:
                - 'MINUTE', 'MINUTE_2', 'MINUTE_3', 'MINUTE_5', 
                  'MINUTE_10', 'MINUTE_15', 'MINUTE_30'
                - 'HOUR', 'HOUR_2', 'HOUR_3', 'HOUR_4'
                - 'DAY', 'WEEK', 'MONTH'
            num_points: Number of data points to retrieve (default: 720 = 12 hours of 1m candles).
        
        Returns:
            List of price data dictionaries, each containing:
                - time: Unix timestamp in seconds
                - open: Open price (mid)
                - high: High price (mid)
                - low: Low price (mid)
                - close: Close price (mid)
        
        Raises:
            ConnectionError: If not connected to the broker.
            BrokerError: If prices cannot be retrieved.
        """
        self._ensure_connected()
        
        try:
            response = self._client.get_prices(
                epic=epic,
                resolution=resolution,
                num_points=num_points,
            )
            
            prices = response.get("prices", [])
            candles = []
            
            for price_data in prices:
                # Parse timestamp
                snapshot_time = price_data.get("snapshotTimeUTC")
                if snapshot_time:
                    try:
                        dt = dateutil_parser.parse(snapshot_time)
                        timestamp = int(dt.timestamp())
                    except (ValueError, TypeError):
                        continue
                else:
                    continue
                
                # Extract mid prices (average of bid and ask)
                open_price = price_data.get("openPrice", {})
                close_price = price_data.get("closePrice", {})
                high_price = price_data.get("highPrice", {})
                low_price = price_data.get("lowPrice", {})
                
                # Calculate mid prices
                def get_mid(price_obj):
                    bid = price_obj.get("bid")
                    ask = price_obj.get("ask")
                    if bid is not None and ask is not None:
                        return (float(bid) + float(ask)) / 2
                    elif bid is not None:
                        return float(bid)
                    elif ask is not None:
                        return float(ask)
                    last_traded = price_obj.get("lastTraded")
                    return float(last_traded) if last_traded is not None else None
                
                candle = {
                    "time": timestamp,
                    "open": get_mid(open_price),
                    "high": get_mid(high_price),
                    "low": get_mid(low_price),
                    "close": get_mid(close_price),
                }
                
                # Only add if we have valid data
                if all(v is not None for v in [candle["open"], candle["high"], candle["low"], candle["close"]]):
                    candles.append(candle)
            
            logger.debug(f"Retrieved {len(candles)} candles for {epic}")
            return candles
            
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"Failed to get historical prices for {epic}: {e}")
