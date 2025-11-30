"""
Execution Service for Fiona trading system.

The ExecutionService orchestrates signals from Strategy Engine, KI Layer,
and Risk Engine to present trade proposals to users and execute trades.
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
from typing import Optional, Union
import uuid

from core.services.broker.broker_service import BrokerService, BrokerError
from core.services.broker.models import (
    OrderRequest,
    OrderResult,
    OrderDirection,
    OrderStatus,
    SymbolPrice,
)
from core.services.strategy.models import SetupCandidate
from core.services.risk.models import RiskEvaluationResult
from core.services.weaviate.models import (
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
    TradeDirection,
    TradeStatus,
)
from core.services.weaviate.weaviate_service import WeaviateService
from fiona.ki.models.ki_evaluation_result import KiEvaluationResult

from .models import ExecutionSession, ExecutionState, ExecutionConfig


logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Exception raised for execution-related errors."""
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        """
        Initialize ExecutionError.
        
        Args:
            message: Human-readable error message.
            code: Error code (if available).
            details: Additional error details.
        """
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ExecutionService:
    """
    Execution Layer v1.0 for Fiona trading system.
    
    The ExecutionService:
    - Receives signals from Strategy Engine, KI Layer, and Risk Engine
    - Presents trade proposals to users
    - Executes trades upon user confirmation (or simulates shadow trades)
    - Tracks trade lifecycle and persists to Weaviate
    
    In v1.0, there is no fully automatic trading - every real trade
    requires explicit user confirmation.
    
    Example:
        >>> service = ExecutionService(broker, weaviate, config)
        >>> session = service.propose_trade(setup, ki_eval, risk_eval)
        >>> if session.state == ExecutionState.WAITING_FOR_USER:
        ...     trade = service.confirm_live_trade(session.id)
        >>> elif session.state == ExecutionState.SHADOW_ONLY:
        ...     shadow = service.confirm_shadow_trade(session.id)
    """

    def __init__(
        self,
        broker_service: Optional[BrokerService] = None,
        weaviate_service: Optional[WeaviateService] = None,
        config: Optional[ExecutionConfig] = None,
        broker_registry=None,
        shadow_only: bool = False,
    ):
        """
        Initialize the ExecutionService.
        
        Args:
            broker_service: BrokerService instance for live trades.
            weaviate_service: WeaviateService for persistence.
            config: ExecutionConfig for behavior settings.
            broker_registry: BrokerRegistry for per-asset broker selection.
            shadow_only: Whether to run in shadow-only mode.
        """
        self._broker = broker_service
        self._weaviate = weaviate_service or WeaviateService()
        self._config = config or ExecutionConfig()
        self._broker_registry = broker_registry
        self._shadow_only = shadow_only
        
        # In-memory session storage (replace with persistent storage if needed)
        self._sessions: dict[str, ExecutionSession] = {}

    @property
    def config(self) -> ExecutionConfig:
        """Get the current configuration."""
        return self._config

    @property
    def broker_registry(self):
        """Get the broker registry."""
        return self._broker_registry

    def set_broker_registry(self, registry, shadow_only: bool = False) -> None:
        """
        Set the broker registry for per-asset broker selection.
        
        Args:
            registry: BrokerRegistry instance.
            shadow_only: Whether to run in shadow-only mode.
        """
        self._broker_registry = registry
        self._shadow_only = shadow_only

    def propose_trade(
        self,
        setup: SetupCandidate,
        ki_eval: Optional[KiEvaluationResult] = None,
        risk_eval: Optional[RiskEvaluationResult] = None,
    ) -> ExecutionSession:
        """
        Create a new ExecutionSession for a trade proposal.
        
        Combines signals from Strategy Engine, KI Layer, and Risk Engine
        to create a concrete trade proposal for the user.
        
        Args:
            setup: SetupCandidate from Strategy Engine.
            ki_eval: KiEvaluationResult from KI Layer (optional).
            risk_eval: RiskEvaluationResult from Risk Engine (optional).
            
        Returns:
            ExecutionSession: New session ready for user decision.
            
        Raises:
            ExecutionError: If session cannot be created.
        """
        now = datetime.now(timezone.utc)
        session_id = str(uuid.uuid4())
        
        logger.debug(
            "Creating trade proposal session",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": setup.id,
                    "epic": setup.epic,
                    "setup_kind": setup.setup_kind.value if isinstance(setup.setup_kind, Enum) else str(setup.setup_kind),
                    "direction": setup.direction,
                    "reference_price": setup.reference_price,
                    "ki_evaluation_id": ki_eval.id if ki_eval else None,
                    "risk_allowed": risk_eval.allowed if risk_eval else None,
                    "timestamp": now.isoformat(),
                }
            }
        )
        
        # Build the proposed order from setup and KI evaluation
        proposed_order = self._build_order_from_signals(setup, ki_eval)
        
        # Determine initial state based on risk evaluation
        if risk_eval is not None and not risk_eval.allowed:
            # Risk denied - only shadow trading allowed (if configured)
            if self._config.allow_shadow_if_risk_denied:
                initial_state = ExecutionState.SHADOW_ONLY
            else:
                initial_state = ExecutionState.RISK_REJECTED
        else:
            # Risk approved or not evaluated - waiting for user
            initial_state = ExecutionState.WAITING_FOR_USER
        
        # Get adjusted order from risk engine if available
        adjusted_order = None
        if risk_eval is not None and risk_eval.adjusted_order is not None:
            adjusted_order = risk_eval.adjusted_order
        
        # Create the session
        session = ExecutionSession(
            id=session_id,
            setup_id=setup.id,
            ki_evaluation_id=ki_eval.id if ki_eval else None,
            risk_result_id=None,  # RiskEvaluationResult doesn't have an id field
            state=initial_state,
            created_at=now,
            last_update=now,
            proposed_order=proposed_order,
            adjusted_order=adjusted_order,
            comment=risk_eval.reason if risk_eval else None,
            meta={
                'setup_kind': setup.setup_kind.value if isinstance(setup.setup_kind, Enum) else str(setup.setup_kind),
                'direction': setup.direction,
                'reference_price': setup.reference_price,
                'breakout_type': (
                    setup.breakout.signal_type.value
                    if setup.breakout and setup.breakout.signal_type
                    else None
                ),
            },
        )
        
        # Store session
        self._sessions[session_id] = session
        
        logger.debug(
            "Trade proposal session created",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": setup.id,
                    "initial_state": initial_state.value,
                    "proposed_size": float(proposed_order.size),
                    "proposed_sl": float(proposed_order.stop_loss) if proposed_order.stop_loss else None,
                    "proposed_tp": float(proposed_order.take_profit) if proposed_order.take_profit else None,
                    "adjusted_size": float(adjusted_order.size) if adjusted_order else None,
                    "risk_comment": risk_eval.reason if risk_eval else None,
                }
            }
        )
        
        return session

    def confirm_live_trade(self, session_id: str) -> ExecutedTrade:
        """
        Confirm and execute a live trade.
        
        User clicks 'Trade ausführen' - the order is placed with the broker.
        
        Args:
            session_id: ID of the ExecutionSession.
            
        Returns:
            ExecutedTrade: The executed trade record.
            
        Raises:
            ExecutionError: If trade cannot be executed.
        """
        session = self._get_session(session_id)
        
        logger.debug(
            "Live trade confirmation started",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": session.setup_id,
                    "current_state": session.state.value,
                }
            }
        )
        
        # Validate state
        if session.state != ExecutionState.WAITING_FOR_USER:
            logger.debug(
                "Live trade confirmation failed: invalid state",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "current_state": session.state.value,
                        "expected_state": "WAITING_FOR_USER",
                        "error": "INVALID_STATE",
                    }
                }
            )
            raise ExecutionError(
                f"Cannot execute live trade: session is in state {session.state.value}. "
                f"Expected WAITING_FOR_USER.",
                code="INVALID_STATE",
            )
        
        # Require broker service for live trades
        if self._broker is None:
            logger.debug(
                "Live trade confirmation failed: no broker",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "error": "NO_BROKER",
                    }
                }
            )
            raise ExecutionError(
                "Broker service not configured for live trades.",
                code="NO_BROKER",
            )
        
        # Transition to USER_ACCEPTED
        session.transition_to(ExecutionState.USER_ACCEPTED)
        
        # Get the effective order
        order = session.get_effective_order()
        
        logger.debug(
            "Placing order with broker",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "epic": order.epic,
                    "direction": order.direction.value if hasattr(order.direction, 'value') else str(order.direction),
                    "size": float(order.size),
                    "stop_loss": float(order.stop_loss) if order.stop_loss else None,
                    "take_profit": float(order.take_profit) if order.take_profit else None,
                }
            }
        )
        
        # Place the order with the broker
        try:
            result = self._broker.place_order(order)
        except BrokerError as e:
            # Revert state on error
            session.state = ExecutionState.WAITING_FOR_USER
            logger.debug(
                "Broker error during order placement",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "error": "BROKER_ERROR",
                        "error_message": str(e),
                        "error_code": e.code if hasattr(e, 'code') else None,
                    }
                }
            )
            raise ExecutionError(
                f"Broker error: {str(e)}",
                code=e.code if hasattr(e, 'code') else "BROKER_ERROR",
                details=e.details if hasattr(e, 'details') else {},
            )
        
        if not result.success:
            # Revert state on failure
            session.state = ExecutionState.WAITING_FOR_USER
            logger.debug(
                "Order rejected by broker",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "error": "ORDER_REJECTED",
                        "reason": result.reason,
                        "deal_reference": result.deal_reference,
                    }
                }
            )
            raise ExecutionError(
                f"Order rejected: {result.reason}",
                code="ORDER_REJECTED",
                details={'deal_reference': result.deal_reference},
            )
        
        # Get entry price from market or broker
        entry_price = self._get_entry_price(order.epic)
        
        # Create ExecutedTrade
        now = datetime.now(timezone.utc)
        trade_id = str(uuid.uuid4())
        
        trade = ExecutedTrade(
            id=trade_id,
            created_at=now,
            setup_id=session.setup_id,
            ki_evaluation_id=session.ki_evaluation_id,
            risk_evaluation_id=session.risk_result_id,
            broker_deal_id=result.deal_id,
            broker_order_id=result.deal_reference,
            epic=order.epic,
            direction=self._order_to_trade_direction(order.direction),
            size=order.size,
            entry_price=entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=TradeStatus.OPEN,
            opened_at=now,
            currency=order.currency,
            meta=session.meta,
        )
        
        # Update session
        session.trade_id = trade_id
        session.is_shadow = False
        session.transition_to(ExecutionState.LIVE_TRADE_OPEN)
        
        # Persist to Weaviate
        self._weaviate.store_trade(trade)
        
        logger.debug(
            "Live trade executed successfully",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "trade_id": trade_id,
                    "setup_id": session.setup_id,
                    "epic": order.epic,
                    "direction": trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction),
                    "size": float(order.size),
                    "entry_price": float(entry_price),
                    "stop_loss": float(order.stop_loss) if order.stop_loss else None,
                    "take_profit": float(order.take_profit) if order.take_profit else None,
                    "broker_deal_id": result.deal_id,
                    "status": "OPEN",
                }
            }
        )
        
        return trade

    def confirm_shadow_trade(self, session_id: str) -> ShadowTrade:
        """
        Confirm a shadow trade.
        
        User clicks 'Nur Schatten-Trade' or trade was risk-denied.
        The trade is simulated without broker execution.
        
        Args:
            session_id: ID of the ExecutionSession.
            
        Returns:
            ShadowTrade: The simulated trade record.
            
        Raises:
            ExecutionError: If shadow trade cannot be created.
        """
        session = self._get_session(session_id)
        
        logger.debug(
            "Shadow trade confirmation started",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": session.setup_id,
                    "current_state": session.state.value,
                }
            }
        )
        
        # Validate state
        if not session.state.allows_user_action():
            logger.debug(
                "Shadow trade confirmation failed: invalid state",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "current_state": session.state.value,
                        "error": "INVALID_STATE",
                    }
                }
            )
            raise ExecutionError(
                f"Cannot create shadow trade: session is in state {session.state.value}. "
                f"Expected WAITING_FOR_USER or SHADOW_ONLY.",
                code="INVALID_STATE",
            )
        
        # Transition to USER_SHADOW
        session.transition_to(ExecutionState.USER_SHADOW)
        
        # Get the effective order
        order = session.get_effective_order()
        
        # Get entry price (from broker if available, otherwise from order context)
        entry_price = self._get_entry_price_for_shadow(order.epic)
        
        # Determine skip reason
        skip_reason = None
        if session.comment:
            skip_reason = session.comment
        
        # Create ShadowTrade
        now = datetime.now(timezone.utc)
        trade_id = str(uuid.uuid4())
        
        shadow_trade = ShadowTrade(
            id=trade_id,
            created_at=now,
            setup_id=session.setup_id,
            ki_evaluation_id=session.ki_evaluation_id,
            risk_evaluation_id=session.risk_result_id,
            epic=order.epic,
            direction=self._order_to_trade_direction(order.direction),
            size=order.size,
            entry_price=entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=TradeStatus.OPEN,
            opened_at=now,
            skip_reason=skip_reason,
            meta=session.meta,
        )
        
        # Update session
        session.trade_id = trade_id
        session.is_shadow = True
        session.transition_to(ExecutionState.SHADOW_TRADE_OPEN)
        
        # Persist to Weaviate
        self._weaviate.store_shadow_trade(shadow_trade)
        
        logger.debug(
            "Shadow trade created successfully",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "trade_id": trade_id,
                    "setup_id": session.setup_id,
                    "epic": order.epic,
                    "direction": shadow_trade.direction.value if hasattr(shadow_trade.direction, 'value') else str(shadow_trade.direction),
                    "size": float(order.size),
                    "entry_price": float(entry_price),
                    "stop_loss": float(order.stop_loss) if order.stop_loss else None,
                    "take_profit": float(order.take_profit) if order.take_profit else None,
                    "skip_reason": skip_reason,
                    "is_shadow": True,
                    "status": "OPEN",
                }
            }
        )
        
        return shadow_trade

    def reject_trade(self, session_id: str) -> None:
        """
        Reject a trade proposal.
        
        User clicks 'Verwerfen' - the signal is discarded.
        
        Args:
            session_id: ID of the ExecutionSession.
            
        Raises:
            ExecutionError: If session cannot be rejected.
        """
        session = self._get_session(session_id)
        
        logger.debug(
            "Trade rejection started",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": session.setup_id,
                    "current_state": session.state.value,
                }
            }
        )
        
        # Validate state
        if not session.state.allows_user_action():
            logger.debug(
                "Trade rejection failed: invalid state",
                extra={
                    "execution_data": {
                        "session_id": session_id,
                        "current_state": session.state.value,
                        "error": "INVALID_STATE",
                    }
                }
            )
            raise ExecutionError(
                f"Cannot reject trade: session is in state {session.state.value}. "
                f"Expected WAITING_FOR_USER or SHADOW_ONLY.",
                code="INVALID_STATE",
            )
        
        # Transition to USER_REJECTED
        session.transition_to(ExecutionState.USER_REJECTED)
        
        # Transition to DROPPED
        session.transition_to(ExecutionState.DROPPED)
        
        logger.debug(
            "Trade rejected successfully",
            extra={
                "execution_data": {
                    "session_id": session_id,
                    "setup_id": session.setup_id,
                    "final_state": "DROPPED",
                }
            }
        )

    def get_session(self, session_id: str) -> Optional[ExecutionSession]:
        """
        Get an ExecutionSession by ID.
        
        Args:
            session_id: ID of the session.
            
        Returns:
            ExecutionSession if found, None otherwise.
        """
        return self._sessions.get(session_id)

    def get_all_sessions(self) -> list[ExecutionSession]:
        """
        Get all sessions including terminal ones.
        
        Returns:
            List of all ExecutionSessions.
        """
        return list(self._sessions.values())

    def get_active_sessions(self) -> list[ExecutionSession]:
        """
        Get all active (non-terminal) sessions.
        
        Returns:
            List of active ExecutionSessions.
        """
        return [
            s for s in self._sessions.values()
            if not s.state.is_terminal()
        ]

    def get_open_trades(self) -> list[ExecutionSession]:
        """
        Get all sessions with open trades.
        
        Returns:
            List of sessions with open live or shadow trades.
        """
        return [
            s for s in self._sessions.values()
            if s.state.is_trade_open()
        ]

    # =========================================================================
    # Private helper methods
    # =========================================================================

    def _get_session(self, session_id: str) -> ExecutionSession:
        """Get session or raise error."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ExecutionError(
                f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
        return session

    def _build_order_from_signals(
        self,
        setup: SetupCandidate,
        ki_eval: Optional[KiEvaluationResult],
    ) -> OrderRequest:
        """
        Build an OrderRequest from setup and KI evaluation signals.
        
        Args:
            setup: SetupCandidate from Strategy Engine.
            ki_eval: KiEvaluationResult from KI Layer (optional).
            
        Returns:
            OrderRequest: The constructed order.
        """
        # Determine direction
        direction = OrderDirection.BUY if setup.direction == "LONG" else OrderDirection.SELL
        
        # Get values from KI evaluation if available, otherwise use defaults
        if ki_eval is not None and ki_eval.is_tradeable():
            params = ki_eval.get_trade_parameters()
            if params:
                size = Decimal(str(params.get('size', 1.0)))
                stop_loss = Decimal(str(params.get('sl'))) if params.get('sl') else None
                take_profit = Decimal(str(params.get('tp'))) if params.get('tp') else None
            else:
                size = Decimal('1.0')
                stop_loss = None
                take_profit = None
        else:
            # Default values
            size = Decimal('1.0')
            stop_loss = None
            take_profit = None
        
        return OrderRequest(
            epic=setup.epic,
            direction=direction,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            currency=self._config.default_currency,
        )

    def _get_entry_price(self, epic: str) -> Decimal:
        """
        Get entry price from broker.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Decimal: Entry price.
        """
        if self._broker is not None:
            try:
                price = self._broker.get_symbol_price(epic)
                return price.mid_price
            except Exception as e:
                logger.warning(f"Failed to get price for {epic}: {e}")
        
        # Fallback to a placeholder (should not happen in production)
        logger.warning(f"Using placeholder price for {epic}")
        return Decimal('0.00')

    def _get_entry_price_for_shadow(self, epic: str) -> Decimal:
        """
        Get entry price for shadow trade.
        
        Uses broker if available, otherwise uses a placeholder.
        
        Args:
            epic: Market identifier.
            
        Returns:
            Decimal: Entry price.
        """
        # Try to get real price from broker
        if self._broker is not None:
            try:
                price = self._broker.get_symbol_price(epic)
                return price.mid_price
            except Exception as e:
                logger.warning(f"Failed to get price for shadow trade {epic}: {e}")
        
        # Fallback to a placeholder
        return Decimal('0.00')

    def _order_to_trade_direction(self, order_direction: OrderDirection) -> TradeDirection:
        """Convert OrderDirection to TradeDirection."""
        if order_direction == OrderDirection.BUY:
            return TradeDirection.LONG
        return TradeDirection.SHORT
