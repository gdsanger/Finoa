"""
Shadow Trader Service for Fiona trading system.

The ShadowTraderService handles the simulation of trades that are not
executed on the broker, either due to risk denial or user choice.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union
import uuid

from core.services.broker.broker_service import BrokerService
from core.services.broker.models import OrderRequest, OrderDirection
from core.services.strategy.models import SetupCandidate
from core.services.weaviate.models import (
    ShadowTrade,
    MarketSnapshot,
    TradeDirection,
    TradeStatus,
)
from core.services.weaviate.weaviate_service import WeaviateService
from fiona.ki.models.ki_evaluation_result import KiEvaluationResult

from .models import ExecutionConfig, ExitReason


class ShadowTraderService:
    """
    Shadow Trader Service for simulated trade tracking.
    
    The ShadowTraderService:
    - Creates shadow trades from proposed orders
    - Simulates trade lifecycle based on market prices
    - Tracks simulated exits (SL/TP hits, time exits)
    - Records performance for analysis
    
    Shadow trades are useful for:
    - Risk-denied trade evaluation
    - Strategy validation without capital risk
    - Comparing shadow performance to real trades
    
    Example:
        >>> service = ShadowTraderService(broker, weaviate, config)
        >>> shadow = service.open_shadow_trade(setup, ki_eval, order, now)
        >>> # Later, simulate exit
        >>> service.check_and_close_shadow_trade(shadow.id, current_price)
    """

    def __init__(
        self,
        broker_service: Optional[BrokerService] = None,
        weaviate_service: Optional[WeaviateService] = None,
        config: Optional[ExecutionConfig] = None,
    ):
        """
        Initialize the ShadowTraderService.
        
        Args:
            broker_service: BrokerService for market data.
            weaviate_service: WeaviateService for persistence.
            config: ExecutionConfig for behavior settings.
        """
        self._broker = broker_service
        self._weaviate = weaviate_service or WeaviateService()
        self._config = config or ExecutionConfig()
        
        # In-memory tracking of open shadow trades
        self._open_shadows: dict[str, ShadowTrade] = {}

    @property
    def config(self) -> ExecutionConfig:
        """Get the current configuration."""
        return self._config

    def open_shadow_trade(
        self,
        setup: SetupCandidate,
        ki_eval: Optional[KiEvaluationResult],
        order: OrderRequest,
        now: Optional[datetime] = None,
        skip_reason: Optional[str] = None,
    ) -> ShadowTrade:
        """
        Create and open a new shadow trade.
        
        Args:
            setup: SetupCandidate that triggered the trade.
            ki_eval: KiEvaluationResult from KI Layer (optional).
            order: OrderRequest with trade parameters.
            now: Current timestamp (defaults to UTC now).
            skip_reason: Reason why this is a shadow trade.
            
        Returns:
            ShadowTrade: The newly created shadow trade.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Get entry price (current market price)
        entry_price = self._get_current_price(order.epic)
        
        # Generate trade ID
        trade_id = str(uuid.uuid4())
        
        # Create shadow trade
        shadow = ShadowTrade(
            id=trade_id,
            created_at=now,
            setup_id=setup.id,
            ki_evaluation_id=ki_eval.id if ki_eval else None,
            epic=order.epic,
            direction=self._order_to_trade_direction(order.direction),
            size=order.size,
            entry_price=entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=TradeStatus.OPEN,
            opened_at=now,
            skip_reason=skip_reason,
            meta={
                'setup_kind': setup.setup_kind.value if hasattr(setup.setup_kind, 'value') else setup.setup_kind,
                'direction': setup.direction,
            },
        )
        
        # Track in memory
        self._open_shadows[trade_id] = shadow
        
        # Persist to Weaviate
        self._weaviate.store_shadow_trade(shadow)
        
        return shadow

    def check_and_close_shadow_trade(
        self,
        trade_id: str,
        current_price: Optional[Decimal] = None,
        now: Optional[datetime] = None,
    ) -> Optional[ShadowTrade]:
        """
        Check if a shadow trade should be closed based on SL/TP.
        
        Args:
            trade_id: ID of the shadow trade.
            current_price: Current market price (fetched if not provided).
            now: Current timestamp.
            
        Returns:
            ShadowTrade if closed, None if still open.
        """
        shadow = self._open_shadows.get(trade_id)
        if shadow is None:
            return None
        
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Get current price if not provided
        if current_price is None:
            current_price = self._get_current_price(shadow.epic)
        
        # Check exit conditions
        exit_reason = self._check_exit_conditions(shadow, current_price)
        
        if exit_reason is not None:
            # Close the shadow trade
            return self._close_shadow_trade(shadow, current_price, exit_reason, now)
        
        return None

    def close_shadow_trade(
        self,
        trade_id: str,
        exit_price: Optional[Decimal] = None,
        exit_reason: str = "MANUAL",
        now: Optional[datetime] = None,
    ) -> ShadowTrade:
        """
        Manually close a shadow trade.
        
        Args:
            trade_id: ID of the shadow trade.
            exit_price: Exit price (fetched if not provided).
            exit_reason: Reason for closing.
            now: Current timestamp.
            
        Returns:
            ShadowTrade: The closed shadow trade.
            
        Raises:
            ValueError: If trade not found.
        """
        shadow = self._open_shadows.get(trade_id)
        if shadow is None:
            raise ValueError(f"Shadow trade not found: {trade_id}")
        
        if now is None:
            now = datetime.now(timezone.utc)
        
        if exit_price is None:
            exit_price = self._get_current_price(shadow.epic)
        
        return self._close_shadow_trade(shadow, exit_price, exit_reason, now)

    def get_open_shadow_trades(self) -> list[ShadowTrade]:
        """
        Get all open shadow trades.
        
        Returns:
            List of open ShadowTrades.
        """
        return list(self._open_shadows.values())

    def poll_shadow_trades(self) -> list[ShadowTrade]:
        """
        Poll all open shadow trades for exit conditions.
        
        Checks all open shadow trades against current market prices
        and closes any that have hit SL/TP.
        
        Returns:
            List of shadow trades that were closed.
        """
        closed_trades = []
        now = datetime.now(timezone.utc)
        
        # Create a copy of keys to avoid modification during iteration
        trade_ids = list(self._open_shadows.keys())
        
        for trade_id in trade_ids:
            shadow = self._open_shadows.get(trade_id)
            if shadow is None:
                continue
            
            try:
                current_price = self._get_current_price(shadow.epic)
                exit_reason = self._check_exit_conditions(shadow, current_price)
                
                if exit_reason is not None:
                    closed = self._close_shadow_trade(shadow, current_price, exit_reason, now)
                    closed_trades.append(closed)
            except Exception:
                # Log error but continue with other trades
                pass
        
        return closed_trades

    def capture_market_snapshot(
        self,
        trade_id: str,
        is_shadow: bool = True,
        now: Optional[datetime] = None,
    ) -> Optional[MarketSnapshot]:
        """
        Capture a market snapshot for a trade.
        
        Args:
            trade_id: ID of the trade.
            is_shadow: Whether this is for a shadow trade.
            now: Current timestamp.
            
        Returns:
            MarketSnapshot if captured, None otherwise.
        """
        # Find the trade
        shadow = self._open_shadows.get(trade_id)
        if shadow is None:
            return None
        
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Get market data
        try:
            if self._broker is not None:
                price = self._broker.get_symbol_price(shadow.epic)
                
                snapshot = MarketSnapshot(
                    id=str(uuid.uuid4()),
                    trade_id=trade_id,
                    is_shadow=is_shadow,
                    created_at=now,
                    epic=shadow.epic,
                    bid=price.bid,
                    ask=price.ask,
                    spread=price.spread,
                    high=price.high,
                    low=price.low,
                )
                
                # Persist to Weaviate
                self._weaviate.store_market_snapshot(snapshot)
                
                # Update trade's snapshot list
                if shadow.market_snapshot_ids is None:
                    shadow.market_snapshot_ids = []
                shadow.market_snapshot_ids.append(snapshot.id)
                
                return snapshot
        except Exception:
            pass
        
        return None

    # =========================================================================
    # Private helper methods
    # =========================================================================

    def _get_current_price(self, epic: str) -> Decimal:
        """
        Get current market price.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Decimal: Current mid price.
        """
        if self._broker is not None:
            try:
                price = self._broker.get_symbol_price(epic)
                return price.mid_price
            except Exception:
                pass
        
        # Fallback
        return Decimal('0.00')

    def _check_exit_conditions(
        self,
        shadow: ShadowTrade,
        current_price: Decimal,
    ) -> Optional[str]:
        """
        Check if a shadow trade has hit SL or TP.
        
        Args:
            shadow: The shadow trade.
            current_price: Current market price.
            
        Returns:
            Exit reason if exit condition met, None otherwise.
        """
        if shadow.direction == TradeDirection.LONG:
            # Long position
            if shadow.stop_loss is not None and current_price <= shadow.stop_loss:
                return ExitReason.SL_HIT.value
            if shadow.take_profit is not None and current_price >= shadow.take_profit:
                return ExitReason.TP_HIT.value
        else:
            # Short position
            if shadow.stop_loss is not None and current_price >= shadow.stop_loss:
                return ExitReason.SL_HIT.value
            if shadow.take_profit is not None and current_price <= shadow.take_profit:
                return ExitReason.TP_HIT.value
        
        return None

    def _close_shadow_trade(
        self,
        shadow: ShadowTrade,
        exit_price: Decimal,
        exit_reason: str,
        now: datetime,
    ) -> ShadowTrade:
        """
        Close a shadow trade.
        
        Args:
            shadow: The shadow trade to close.
            exit_price: Exit price.
            exit_reason: Reason for closing.
            now: Current timestamp.
            
        Returns:
            ShadowTrade: The closed shadow trade.
        """
        # Calculate P&L
        pnl = self._calculate_pnl(shadow, exit_price)
        pnl_percent = self._calculate_pnl_percent(shadow, exit_price)
        
        # Update shadow trade
        shadow.exit_price = exit_price
        shadow.exit_reason = exit_reason
        shadow.closed_at = now
        shadow.status = TradeStatus.CLOSED
        shadow.theoretical_pnl = pnl
        shadow.theoretical_pnl_percent = pnl_percent
        
        # Remove from open trades
        if shadow.id in self._open_shadows:
            del self._open_shadows[shadow.id]
        
        # Update in Weaviate
        self._weaviate.store_shadow_trade(shadow)
        
        return shadow

    def _calculate_pnl(
        self,
        shadow: ShadowTrade,
        exit_price: Decimal,
    ) -> Decimal:
        """
        Calculate theoretical P&L for a shadow trade.
        
        Args:
            shadow: The shadow trade.
            exit_price: Exit price.
            
        Returns:
            Decimal: Theoretical P&L.
        """
        price_diff = exit_price - shadow.entry_price
        
        if shadow.direction == TradeDirection.SHORT:
            price_diff = -price_diff
        
        # Simplified P&L calculation (without tick value)
        return price_diff * shadow.size

    def _calculate_pnl_percent(
        self,
        shadow: ShadowTrade,
        exit_price: Decimal,
    ) -> float:
        """
        Calculate theoretical P&L percentage.
        
        Args:
            shadow: The shadow trade.
            exit_price: Exit price.
            
        Returns:
            float: P&L as percentage of entry price.
        """
        if shadow.entry_price == 0:
            return 0.0
        
        price_diff = exit_price - shadow.entry_price
        
        if shadow.direction == TradeDirection.SHORT:
            price_diff = -price_diff
        
        return float((price_diff / shadow.entry_price) * 100)

    def _order_to_trade_direction(self, order_direction: OrderDirection) -> TradeDirection:
        """Convert OrderDirection to TradeDirection."""
        if order_direction == OrderDirection.BUY:
            return TradeDirection.LONG
        return TradeDirection.SHORT
