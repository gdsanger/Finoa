"""
Data models for the Broker Service.

These models represent broker-related entities and are independent of the
specific broker implementation (IG, etc.).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderType(Enum):
    """Type of order to place."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class OrderDirection(Enum):
    """Direction of order - buy or sell."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Status of an order or position."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"


@dataclass
class AccountState:
    """
    Represents the current state of a trading account.
    
    Attributes:
        account_id: Unique identifier for the account.
        account_name: Human-readable name for the account.
        balance: Current account balance.
        available: Amount available for trading.
        equity: Total equity including open positions.
        margin_used: Amount of margin currently in use.
        margin_available: Amount of margin available for new positions.
        unrealized_pnl: Unrealized profit/loss from open positions.
        realized_pnl: Realized profit/loss.
        currency: Account currency code (e.g., 'EUR', 'USD').
        timestamp: When this state was captured.
    """
    account_id: str
    account_name: str
    balance: Decimal
    available: Decimal
    equity: Decimal
    margin_used: Decimal = Decimal('0.00')
    margin_available: Decimal = Decimal('0.00')
    unrealized_pnl: Decimal = Decimal('0.00')
    realized_pnl: Decimal = Decimal('0.00')
    currency: str = 'EUR'
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Ensure timestamp is set and values are Decimal."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        # Convert numeric values to Decimal if needed
        for field_name in ['balance', 'available', 'equity', 'margin_used',
                           'margin_available', 'unrealized_pnl', 'realized_pnl']:
            value = getattr(self, field_name)
            if not isinstance(value, Decimal):
                setattr(self, field_name, Decimal(str(value)))


@dataclass
class Position:
    """
    Represents an open trading position.
    
    Attributes:
        position_id: Unique identifier for the position.
        deal_id: Deal/order identifier that created this position.
        epic: Market identifier (e.g., 'IX.D.SPTRD.IFD.IP' for S&P 500).
        market_name: Human-readable market name.
        direction: Position direction (BUY/SELL).
        size: Position size.
        open_price: Price at which position was opened.
        current_price: Current market price.
        stop_loss: Stop loss level (if set).
        take_profit: Take profit level (if set).
        unrealized_pnl: Unrealized profit/loss.
        currency: Position currency.
        created_at: When position was opened.
    """
    position_id: str
    deal_id: str
    epic: str
    market_name: str
    direction: OrderDirection
    size: Decimal
    open_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    currency: str = 'EUR'
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """Ensure values are proper types."""
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))
        if not isinstance(self.open_price, Decimal):
            self.open_price = Decimal(str(self.open_price))
        if not isinstance(self.current_price, Decimal):
            self.current_price = Decimal(str(self.current_price))
        if not isinstance(self.unrealized_pnl, Decimal):
            self.unrealized_pnl = Decimal(str(self.unrealized_pnl))
        if self.stop_loss is not None and not isinstance(self.stop_loss, Decimal):
            self.stop_loss = Decimal(str(self.stop_loss))
        if self.take_profit is not None and not isinstance(self.take_profit, Decimal):
            self.take_profit = Decimal(str(self.take_profit))
        if isinstance(self.direction, str):
            self.direction = OrderDirection(self.direction)


@dataclass
class OrderRequest:
    """
    Request to place a new order.
    
    Attributes:
        epic: Market identifier to trade.
        direction: Order direction (BUY/SELL).
        size: Order size.
        order_type: Type of order (MARKET, LIMIT, STOP, etc.).
        limit_price: Limit price (required for limit orders).
        stop_price: Stop price (required for stop orders).
        stop_loss: Stop loss level for the position.
        take_profit: Take profit level for the position.
        guaranteed_stop: Whether stop is guaranteed (may incur additional cost).
        trailing_stop: Whether to use trailing stop.
        trailing_stop_distance: Distance for trailing stop.
        currency: Currency for the order.
    """
    epic: str
    direction: OrderDirection
    size: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    guaranteed_stop: bool = False
    trailing_stop: bool = False
    trailing_stop_distance: Optional[Decimal] = None
    currency: str = 'EUR'

    def __post_init__(self):
        """Validate and normalize order request."""
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))
        if self.limit_price is not None and not isinstance(self.limit_price, Decimal):
            self.limit_price = Decimal(str(self.limit_price))
        if self.stop_price is not None and not isinstance(self.stop_price, Decimal):
            self.stop_price = Decimal(str(self.stop_price))
        if self.stop_loss is not None and not isinstance(self.stop_loss, Decimal):
            self.stop_loss = Decimal(str(self.stop_loss))
        if self.take_profit is not None and not isinstance(self.take_profit, Decimal):
            self.take_profit = Decimal(str(self.take_profit))
        if self.trailing_stop_distance is not None and not isinstance(self.trailing_stop_distance, Decimal):
            self.trailing_stop_distance = Decimal(str(self.trailing_stop_distance))
        if isinstance(self.direction, str):
            self.direction = OrderDirection(self.direction)
        if isinstance(self.order_type, str):
            self.order_type = OrderType(self.order_type)


@dataclass
class OrderResult:
    """
    Result of an order placement or position close operation.
    
    Attributes:
        success: Whether the operation was successful.
        deal_id: Deal ID if successful.
        deal_reference: Deal reference for tracking.
        status: Status of the order.
        reason: Rejection/error reason if not successful.
        affected_deals: List of affected deal IDs.
        timestamp: When the result was received.
    """
    success: bool
    deal_id: Optional[str] = None
    deal_reference: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    reason: Optional[str] = None
    affected_deals: list = field(default_factory=list)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Ensure timestamp is set."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if isinstance(self.status, str):
            self.status = OrderStatus(self.status)


@dataclass
class SymbolPrice:
    """
    Current price information for a trading symbol/market.
    
    Attributes:
        epic: Market identifier.
        market_name: Human-readable market name.
        bid: Current bid price (sell price).
        ask: Current ask price (buy price).
        spread: Bid-ask spread.
        high: Day high.
        low: Day low.
        change: Price change from previous close.
        change_percent: Percentage change from previous close.
        timestamp: When price was captured.
    """
    epic: str
    market_name: str
    bid: Decimal
    ask: Decimal
    spread: Decimal
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    change: Optional[Decimal] = None
    change_percent: Optional[Decimal] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Ensure values are proper types."""
        if not isinstance(self.bid, Decimal):
            self.bid = Decimal(str(self.bid))
        if not isinstance(self.ask, Decimal):
            self.ask = Decimal(str(self.ask))
        if not isinstance(self.spread, Decimal):
            self.spread = Decimal(str(self.spread))
        if self.high is not None and not isinstance(self.high, Decimal):
            self.high = Decimal(str(self.high))
        if self.low is not None and not isinstance(self.low, Decimal):
            self.low = Decimal(str(self.low))
        if self.change is not None and not isinstance(self.change, Decimal):
            self.change = Decimal(str(self.change))
        if self.change_percent is not None and not isinstance(self.change_percent, Decimal):
            self.change_percent = Decimal(str(self.change_percent))
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    @property
    def mid_price(self) -> Decimal:
        """Calculate mid price between bid and ask."""
        return (self.bid + self.ask) / 2
