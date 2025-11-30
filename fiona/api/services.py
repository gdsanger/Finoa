"""
Service layer for the Fiona API.

These services provide the business logic for the API endpoints,
aggregating data from Strategy, KI, Risk, and Execution layers.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Literal, Union
import logging

from core.services.execution import ExecutionService, ExecutionState
from core.services.execution.execution_service import ExecutionError
from core.services.execution.models import ExecutionSession
from core.services.weaviate.weaviate_service import WeaviateService, QueryFilter
from core.services.weaviate.models import ExecutedTrade, ShadowTrade, TradeStatus
from core.services.strategy.models import SetupCandidate
from core.services.risk.models import RiskEvaluationResult
from core.services.broker.models import OrderRequest
from fiona.ki.models.ki_evaluation_result import KiEvaluationResult

from .dtos import (
    SignalSummaryDTO,
    SignalDetailDTO,
    TradeHistoryDTO,
    TradeActionResponse,
    KiInfoDTO,
    RiskInfoDTO,
    RiskEvaluationDTO,
    ExecutionStateDTO,
    AdjustedOrderDTO,
)


logger = logging.getLogger(__name__)


class SignalService:
    """
    Service for managing trading signals in the API layer.
    
    Aggregates data from:
    - ExecutionService (sessions)
    - SetupCandidates (strategy)
    - KiEvaluationResults (KI layer)
    - RiskEvaluationResults (risk engine)
    
    Example:
        >>> service = SignalService(execution_service, weaviate_service)
        >>> signals = service.list_signals()
        >>> detail = service.get_signal_detail('signal-uuid')
    """

    def __init__(
        self,
        execution_service: Optional[ExecutionService] = None,
        weaviate_service: Optional[WeaviateService] = None,
    ):
        """
        Initialize the SignalService.
        
        Args:
            execution_service: ExecutionService for session management.
            weaviate_service: WeaviateService for data persistence.
        """
        self._execution = execution_service or ExecutionService()
        self._weaviate = weaviate_service or WeaviateService()
        
        # In-memory cache for signal data (maps signal_id to aggregated data)
        self._signal_cache: dict[str, dict] = {}

    def list_signals(
        self,
        include_dropped: bool = False,
        include_exited: bool = False,
    ) -> List[SignalSummaryDTO]:
        """
        List all active signals/execution sessions.
        
        Returns signals that are:
        - Not yet dropped/rejected
        - Either waiting for user action or have open trades
        
        Args:
            include_dropped: Include dropped/rejected signals.
            include_exited: Include signals with exited trades.
            
        Returns:
            List[SignalSummaryDTO]: List of signal summaries.
        """
        signals = []
        
        # Get all sessions from execution service using public method
        all_sessions = self._execution.get_all_sessions()
        
        for session in all_sessions:
            # Filter based on state
            if not include_dropped and session.state == ExecutionState.DROPPED:
                continue
            if not include_exited and session.state == ExecutionState.EXITED:
                continue
            
            # Build signal summary from session
            signal = self._build_signal_summary(session)
            if signal:
                signals.append(signal)
        
        return signals

    def get_signal_detail(self, signal_id: str) -> Optional[SignalDetailDTO]:
        """
        Get full details for a specific signal.
        
        Args:
            signal_id: UUID of the signal/session.
            
        Returns:
            SignalDetailDTO if found, None otherwise.
        """
        # Try to find session by ID
        session = self._execution.get_session(signal_id)
        if session is None:
            return None
        
        return self._build_signal_detail(session)

    def register_signal(
        self,
        setup: SetupCandidate,
        ki_eval: Optional[KiEvaluationResult] = None,
        risk_eval: Optional[RiskEvaluationResult] = None,
    ) -> SignalSummaryDTO:
        """
        Register a new signal from the pipeline.
        
        Creates an ExecutionSession and returns the signal summary.
        
        Args:
            setup: SetupCandidate from strategy engine.
            ki_eval: KiEvaluationResult from KI layer.
            risk_eval: RiskEvaluationResult from risk engine.
            
        Returns:
            SignalSummaryDTO: The created signal summary.
        """
        # Create execution session
        session = self._execution.propose_trade(setup, ki_eval, risk_eval)
        
        # Cache the signal data for later retrieval
        self._signal_cache[session.id] = {
            'setup': setup,
            'ki_eval': ki_eval,
            'risk_eval': risk_eval,
        }
        
        return self._build_signal_summary(session)

    def _build_signal_summary(self, session: ExecutionSession) -> Optional[SignalSummaryDTO]:
        """Build a SignalSummaryDTO from an ExecutionSession."""
        # Get cached data or load from weaviate
        cached = self._signal_cache.get(session.id, {})
        
        setup = cached.get('setup')
        ki_eval = cached.get('ki_eval')
        risk_eval = cached.get('risk_eval')
        
        # Try to load setup from weaviate if not cached
        if setup is None:
            setup = self._weaviate.get_setup(session.setup_id)
            if setup is None:
                # Create minimal setup from session data
                meta = session.meta or {}
                setup = SetupCandidate(
                    id=session.setup_id,
                    created_at=session.created_at,
                    epic=session.proposed_order.epic if session.proposed_order else 'UNKNOWN',
                    setup_kind=meta.get('setup_kind', 'BREAKOUT'),
                    phase=meta.get('phase', 'OTHER'),
                    reference_price=meta.get('reference_price', 0.0),
                    direction=meta.get('direction', 'LONG'),
                )
        
        # Build KI info
        ki_info = KiInfoDTO()
        if ki_eval:
            ki_info = KiInfoDTO(
                finalDirection=ki_eval.final_direction,
                finalSl=ki_eval.final_sl,
                finalTp=ki_eval.final_tp,
                finalSize=ki_eval.final_size,
                confidence=ki_eval.reflection_score,
            )
        
        # Build risk info
        risk_info = RiskInfoDTO(allowed=True, reason="")
        if risk_eval:
            risk_info = RiskInfoDTO(
                allowed=risk_eval.allowed,
                reason=risk_eval.reason,
            )
        elif session.state == ExecutionState.SHADOW_ONLY:
            risk_info = RiskInfoDTO(
                allowed=False,
                reason=session.comment or "Risk denied",
            )
        
        # Format created_at as ISO string
        created_at = session.created_at.isoformat() if session.created_at else datetime.now(timezone.utc).isoformat()
        
        # Get setup kind as string
        setup_kind = setup.setup_kind.value if hasattr(setup.setup_kind, 'value') else str(setup.setup_kind)
        phase = setup.phase.value if hasattr(setup.phase, 'value') else str(setup.phase)
        breakout_type = None
        if getattr(setup, 'breakout', None) and setup.breakout.signal_type:
            breakout_type = setup.breakout.signal_type.value
        elif session.meta:
            breakout_type = session.meta.get('breakout_type')

        return SignalSummaryDTO(
            id=session.id,
            epic=setup.epic,
            setupKind=setup_kind,
            phase=phase,
            createdAt=created_at,
            direction=setup.direction,
            referencePrice=float(setup.reference_price),
            breakoutType=breakout_type,
            ki=ki_info,
            risk=risk_info,
        )

    def _build_signal_detail(self, session: ExecutionSession) -> SignalDetailDTO:
        """Build a SignalDetailDTO from an ExecutionSession."""
        # Get cached data
        cached = self._signal_cache.get(session.id, {})
        
        setup = cached.get('setup')
        ki_eval = cached.get('ki_eval')
        risk_eval = cached.get('risk_eval')
        
        # Try to load setup from weaviate if not cached
        if setup is None:
            setup = self._weaviate.get_setup(session.setup_id)
            if setup is None:
                # Create minimal setup from session data
                meta = session.meta or {}
                setup = SetupCandidate(
                    id=session.setup_id,
                    created_at=session.created_at,
                    epic=session.proposed_order.epic if session.proposed_order else 'UNKNOWN',
                    setup_kind=meta.get('setup_kind', 'BREAKOUT'),
                    phase=meta.get('phase', 'OTHER'),
                    reference_price=meta.get('reference_price', 0.0),
                    direction=meta.get('direction', 'LONG'),
                )
        
        # Format created_at as ISO string
        created_at = session.created_at.isoformat() if session.created_at else datetime.now(timezone.utc).isoformat()
        
        # Get setup kind as string
        setup_kind = setup.setup_kind.value if hasattr(setup.setup_kind, 'value') else str(setup.setup_kind)
        phase = setup.phase.value if hasattr(setup.phase, 'value') else str(setup.phase)
        breakout_type = None
        if getattr(setup, 'breakout', None) and setup.breakout.signal_type:
            breakout_type = setup.breakout.signal_type.value
        elif session.meta:
            breakout_type = session.meta.get('breakout_type')

        # Build risk evaluation DTO
        risk_evaluation_dto = None
        if risk_eval:
            adjusted_order_dto = None
            if risk_eval.adjusted_order:
                order = risk_eval.adjusted_order
                adjusted_order_dto = AdjustedOrderDTO(
                    epic=order.epic,
                    direction=order.direction.value if hasattr(order.direction, 'value') else str(order.direction),
                    orderType=order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type),
                    size=float(order.size),
                    level=float(order.limit_price) if order.limit_price else None,
                    stopLevel=float(order.stop_loss) if order.stop_loss else None,
                    limitLevel=float(order.take_profit) if order.take_profit else None,
                )
            
            risk_evaluation_dto = RiskEvaluationDTO(
                allowed=risk_eval.allowed,
                reason=risk_eval.reason,
                adjustedOrder=adjusted_order_dto,
            )
        elif session.state == ExecutionState.SHADOW_ONLY:
            risk_evaluation_dto = RiskEvaluationDTO(
                allowed=False,
                reason=session.comment or "Risk denied",
            )
        else:
            risk_evaluation_dto = RiskEvaluationDTO(allowed=True, reason="Risk approved")
        
        # Build execution state DTO
        execution_state_dto = ExecutionStateDTO(
            status=session.state.value,
            executionSessionId=session.id,
        )
        
        return SignalDetailDTO(
            id=session.id,
            epic=setup.epic,
            setupKind=setup_kind,
            phase=phase,
            createdAt=created_at,
            breakoutType=breakout_type,
            setup=setup.to_dict(),
            kiEvaluation=ki_eval.to_dict() if ki_eval else None,
            riskEvaluation=risk_evaluation_dto,
            executionState=execution_state_dto,
        )


class TradeService:
    """
    Service for executing trade actions via the API.
    
    Handles:
    - Live trade execution
    - Shadow trade execution
    - Signal rejection
    - Trade history queries
    
    Example:
        >>> service = TradeService(execution_service, weaviate_service)
        >>> result = service.execute_live_trade('signal-uuid')
        >>> if result.success:
        ...     print(f"Trade opened: {result.tradeId}")
    """

    def __init__(
        self,
        execution_service: Optional[ExecutionService] = None,
        weaviate_service: Optional[WeaviateService] = None,
    ):
        """
        Initialize the TradeService.
        
        Args:
            execution_service: ExecutionService for trade execution.
            weaviate_service: WeaviateService for data persistence.
        """
        self._execution = execution_service or ExecutionService()
        self._weaviate = weaviate_service or WeaviateService()

    def execute_live_trade(self, signal_id: str) -> TradeActionResponse:
        """
        Execute a live trade for a signal.
        
        Args:
            signal_id: UUID of the signal/session.
            
        Returns:
            TradeActionResponse: Result of the trade action.
        """
        try:
            trade = self._execution.confirm_live_trade(signal_id)
            return TradeActionResponse(
                success=True,
                message="Live trade opened successfully.",
                tradeId=trade.id,
            )
        except ExecutionError as e:
            logger.error(f"Failed to execute live trade: {e}")
            return TradeActionResponse(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Unexpected error executing live trade: {e}")
            return TradeActionResponse(
                success=False,
                error=f"Unexpected error: {str(e)}",
            )

    def execute_shadow_trade(self, signal_id: str) -> TradeActionResponse:
        """
        Execute a shadow trade for a signal.
        
        Args:
            signal_id: UUID of the signal/session.
            
        Returns:
            TradeActionResponse: Result of the trade action.
        """
        try:
            shadow = self._execution.confirm_shadow_trade(signal_id)
            return TradeActionResponse(
                success=True,
                message="Shadow trade started.",
                shadowTradeId=shadow.id,
            )
        except ExecutionError as e:
            logger.error(f"Failed to execute shadow trade: {e}")
            return TradeActionResponse(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Unexpected error executing shadow trade: {e}")
            return TradeActionResponse(
                success=False,
                error=f"Unexpected error: {str(e)}",
            )

    def reject_signal(self, signal_id: str, reason: Optional[str] = None) -> TradeActionResponse:
        """
        Reject/dismiss a signal.
        
        Args:
            signal_id: UUID of the signal/session.
            reason: Optional reason for rejection.
            
        Returns:
            TradeActionResponse: Result of the action.
        """
        try:
            self._execution.reject_trade(signal_id)
            return TradeActionResponse(
                success=True,
                message="Signal rejected.",
            )
        except ExecutionError as e:
            logger.error(f"Failed to reject signal: {e}")
            return TradeActionResponse(
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Unexpected error rejecting signal: {e}")
            return TradeActionResponse(
                success=False,
                error=f"Unexpected error: {str(e)}",
            )

    def get_trade_history(
        self,
        trade_type: Literal['live', 'shadow', 'all'] = 'all',
        limit: int = 50,
    ) -> List[TradeHistoryDTO]:
        """
        Get trade history.
        
        Args:
            trade_type: Filter by trade type ('live', 'shadow', 'all').
            limit: Maximum number of results.
            
        Returns:
            List[TradeHistoryDTO]: List of trade history items.
        """
        trades = []
        query_filter = QueryFilter(limit=limit)
        
        # Query live trades
        if trade_type in ('live', 'all'):
            live_trades = self._weaviate.query_trades(query_filter)
            for trade in live_trades:
                trades.append(self._build_trade_history_dto(trade, is_shadow=False))
        
        # Query shadow trades
        if trade_type in ('shadow', 'all'):
            shadow_trades = self._weaviate.query_shadow_trades(query_filter)
            for shadow in shadow_trades:
                trades.append(self._build_trade_history_dto(shadow, is_shadow=True))
        
        # Sort by opened_at descending
        trades.sort(key=lambda t: t.openedAt, reverse=True)
        
        # Apply limit
        return trades[:limit]

    def _build_trade_history_dto(
        self,
        trade: Union[ExecutedTrade, ShadowTrade],
        is_shadow: bool,
    ) -> TradeHistoryDTO:
        """Build a TradeHistoryDTO from a trade object."""
        opened_at = ""
        if trade.opened_at:
            opened_at = trade.opened_at.isoformat()
        elif trade.created_at:
            opened_at = trade.created_at.isoformat()
        
        closed_at = None
        if trade.closed_at:
            closed_at = trade.closed_at.isoformat()
        
        # Get realized PnL
        realized_pnl = None
        if is_shadow:
            if hasattr(trade, 'theoretical_pnl') and trade.theoretical_pnl is not None:
                realized_pnl = float(trade.theoretical_pnl)
        else:
            if hasattr(trade, 'pnl') and trade.pnl is not None:
                realized_pnl = float(trade.pnl)
        
        # Get direction as string
        direction = trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction)
        
        return TradeHistoryDTO(
            id=trade.id,
            epic=trade.epic,
            direction=direction,
            size=float(trade.size),
            entryPrice=float(trade.entry_price),
            exitPrice=float(trade.exit_price) if trade.exit_price else None,
            openedAt=opened_at,
            closedAt=closed_at,
            realizedPnl=realized_pnl,
            isShadow=is_shadow,
            exitReason=trade.exit_reason,
        )
