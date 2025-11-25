"""
DTO (Data Transfer Object) models for the Fiona API layer.

These models represent the API response objects, providing a clear
contract between the backend and frontend.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Literal


@dataclass
class KiInfoDTO:
    """
    KI evaluation info for signal summary.
    
    Attributes:
        finalDirection: Final trade direction from KI.
        finalSl: Final stop loss level.
        finalTp: Final take profit level.
        finalSize: Final position size.
        confidence: Confidence score (0-100).
    """
    finalDirection: Optional[str] = None
    finalSl: Optional[float] = None
    finalTp: Optional[float] = None
    finalSize: Optional[float] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'finalDirection': self.finalDirection,
            'finalSl': self.finalSl,
            'finalTp': self.finalTp,
            'finalSize': self.finalSize,
            'confidence': self.confidence,
        }


@dataclass
class RiskInfoDTO:
    """
    Risk evaluation info for signal summary.
    
    Attributes:
        allowed: Whether the trade is allowed by risk engine.
        reason: Explanation of the risk decision.
    """
    allowed: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'allowed': self.allowed,
            'reason': self.reason,
        }


@dataclass
class AdjustedOrderDTO:
    """
    Adjusted order from risk engine.
    
    Attributes:
        epic: Market identifier.
        direction: Order direction (BUY/SELL).
        orderType: Order type (MARKET, LIMIT, etc.).
        size: Position size.
        level: Order level (for limit orders).
        stopLevel: Stop loss level.
        limitLevel: Take profit level.
    """
    epic: str
    direction: str
    orderType: str = "MARKET"
    size: float = 1.0
    level: Optional[float] = None
    stopLevel: Optional[float] = None
    limitLevel: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'epic': self.epic,
            'direction': self.direction,
            'orderType': self.orderType,
            'size': self.size,
            'level': self.level,
            'stopLevel': self.stopLevel,
            'limitLevel': self.limitLevel,
        }


@dataclass
class RiskEvaluationDTO:
    """
    Full risk evaluation for signal detail.
    
    Attributes:
        allowed: Whether the trade is allowed.
        reason: Explanation of the risk decision.
        adjustedOrder: Adjusted order if risk engine modified it.
    """
    allowed: bool = True
    reason: str = ""
    adjustedOrder: Optional[AdjustedOrderDTO] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'allowed': self.allowed,
            'reason': self.reason,
            'adjustedOrder': self.adjustedOrder.to_dict() if self.adjustedOrder else None,
        }


@dataclass
class ExecutionStateDTO:
    """
    Execution state for signal detail.
    
    Attributes:
        status: Current execution status.
        executionSessionId: ID of the execution session.
    """
    status: str = "WAITING_FOR_USER"
    executionSessionId: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'status': self.status,
            'executionSessionId': self.executionSessionId,
        }


@dataclass
class SignalSummaryDTO:
    """
    Summary DTO for GET /api/signals response.
    
    Provides a concise overview of a signal including KI and risk info.
    
    Attributes:
        id: Signal UUID.
        epic: Market identifier (e.g., 'OIL', 'CL').
        setupKind: Type of setup (BREAKOUT, EIA_REVERSION, EIA_TRENDDAY).
        phase: Session phase (LONDON_CORE, US_CORE, etc.).
        createdAt: ISO timestamp when signal was created.
        direction: Trade direction (LONG/SHORT).
        referencePrice: Reference price at signal creation.
        ki: KI evaluation summary.
        risk: Risk evaluation summary.
    """
    id: str
    epic: str
    setupKind: str
    phase: str
    createdAt: str  # ISO format
    direction: str
    referencePrice: float
    ki: KiInfoDTO
    risk: RiskInfoDTO

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'epic': self.epic,
            'setupKind': self.setupKind,
            'phase': self.phase,
            'createdAt': self.createdAt,
            'direction': self.direction,
            'referencePrice': self.referencePrice,
            'ki': self.ki.to_dict(),
            'risk': self.risk.to_dict(),
        }


@dataclass
class SignalDetailDTO:
    """
    Detail DTO for GET /api/signals/{id} response.
    
    Provides full details of a signal including setup, KI, risk, and execution state.
    
    Attributes:
        id: Signal UUID.
        epic: Market identifier.
        setupKind: Type of setup.
        phase: Session phase.
        createdAt: ISO timestamp.
        setup: Full SetupCandidate data.
        kiEvaluation: Full KI evaluation result.
        riskEvaluation: Full risk evaluation result.
        executionState: Current execution state.
    """
    id: str
    epic: str
    setupKind: str
    phase: str
    createdAt: str
    setup: dict  # Serialized SetupCandidate
    kiEvaluation: Optional[dict] = None  # Serialized KiEvaluationResult
    riskEvaluation: Optional[RiskEvaluationDTO] = None
    executionState: Optional[ExecutionStateDTO] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'epic': self.epic,
            'setupKind': self.setupKind,
            'phase': self.phase,
            'createdAt': self.createdAt,
            'setup': self.setup,
            'kiEvaluation': self.kiEvaluation,
            'riskEvaluation': self.riskEvaluation.to_dict() if self.riskEvaluation else None,
            'executionState': self.executionState.to_dict() if self.executionState else None,
        }


@dataclass
class TradeHistoryDTO:
    """
    DTO for GET /api/trades response items.
    
    Represents a trade in the history view.
    
    Attributes:
        id: Trade UUID.
        epic: Market identifier.
        direction: Trade direction (LONG/SHORT).
        size: Position size.
        entryPrice: Entry price.
        exitPrice: Exit price (if closed).
        openedAt: ISO timestamp when trade was opened.
        closedAt: ISO timestamp when trade was closed.
        realizedPnl: Realized profit/loss.
        isShadow: Whether this is a shadow trade.
        exitReason: Reason for trade exit.
    """
    id: str
    epic: str
    direction: str
    size: float
    entryPrice: float
    exitPrice: Optional[float] = None
    openedAt: str = ""
    closedAt: Optional[str] = None
    realizedPnl: Optional[float] = None
    isShadow: bool = False
    exitReason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'epic': self.epic,
            'direction': self.direction,
            'size': self.size,
            'entryPrice': self.entryPrice,
            'exitPrice': self.exitPrice,
            'openedAt': self.openedAt,
            'closedAt': self.closedAt,
            'realizedPnl': self.realizedPnl,
            'isShadow': self.isShadow,
            'exitReason': self.exitReason,
        }


@dataclass
class TradeActionResponse:
    """
    Response DTO for trade action endpoints.
    
    Used for POST /api/trade/live, /api/trade/shadow, /api/trade/reject.
    
    Attributes:
        success: Whether the action was successful.
        message: Success message.
        error: Error message if not successful.
        tradeId: Trade ID if created.
        shadowTradeId: Shadow trade ID if created.
    """
    success: bool
    message: str = ""
    error: Optional[str] = None
    tradeId: Optional[str] = None
    shadowTradeId: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            'success': self.success,
        }
        if self.success:
            if self.message:
                result['message'] = self.message
            if self.tradeId:
                result['tradeId'] = self.tradeId
            if self.shadowTradeId:
                result['shadowTradeId'] = self.shadowTradeId
        else:
            if self.error:
                result['error'] = self.error
        return result


@dataclass
class TradeRequestDTO:
    """
    Request DTO for trade action endpoints.
    
    Attributes:
        signalId: ID of the signal to act on.
        reason: Optional reason (for reject action).
    """
    signalId: str
    reason: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'TradeRequestDTO':
        """Create instance from dictionary."""
        return cls(
            signalId=data.get('signalId', ''),
            reason=data.get('reason'),
        )
