"""
Data models for Weaviate persistence layer.

These models represent the complete pipeline for Fiona:
Setup → KI → Reflexion → Entscheidung → Trade → Nachbetrachtung

All objects support serialization with schema versioning for future upgrades.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional, Union
import json

# Current schema version for all models
SCHEMA_VERSION = "1.0"


class TradeStatus(str, Enum):
    """Status of a trade."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"


class TradeDirection(str, Enum):
    """Direction of a trade."""
    LONG = "LONG"
    SHORT = "SHORT"


class LLMProvider(str, Enum):
    """LLM provider used for analysis."""
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    LOCAL = "LOCAL"
    KIGATE = "KIGATE"


@dataclass
class LocalLLMResult:
    """
    Result from a Local LLM analysis of a setup candidate.
    
    Represents the AI evaluation of a trading setup, including
    recommendations and confidence scores.
    
    Attributes:
        id: Unique identifier for the result.
        created_at: Timestamp when the result was generated.
        setup_id: Reference to the analyzed SetupCandidate.
        provider: LLM provider used.
        model: Model name/version used.
        prompt: The prompt sent to the LLM.
        response: Raw response from the LLM.
        recommendation: Extracted recommendation (BUY/SELL/HOLD).
        confidence: Confidence score (0.0 to 1.0).
        reasoning: Explanation of the recommendation.
        tokens_used: Number of tokens consumed.
        latency_ms: Response latency in milliseconds.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    setup_id: str
    provider: LLMProvider
    model: str
    prompt: str
    response: str
    recommendation: Optional[Literal["BUY", "SELL", "HOLD"]] = None
    confidence: float = 0.0
    reasoning: Optional[str] = None
    tokens_used: int = 0
    latency_ms: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'provider': self.provider.value if isinstance(self.provider, LLMProvider) else self.provider,
            'model': self.model,
            'prompt': self.prompt,
            'response': self.response,
            'recommendation': self.recommendation,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'tokens_used': self.tokens_used,
            'latency_ms': self.latency_ms,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LocalLLMResult':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            LocalLLMResult: New instance.
        """
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        provider = data.get('provider')
        if isinstance(provider, str):
            provider = LLMProvider(provider)
        
        return cls(
            id=data['id'],
            created_at=created_at,
            setup_id=data['setup_id'],
            provider=provider,
            model=data['model'],
            prompt=data['prompt'],
            response=data['response'],
            recommendation=data.get('recommendation'),
            confidence=data.get('confidence', 0.0),
            reasoning=data.get('reasoning'),
            tokens_used=data.get('tokens_used', 0),
            latency_ms=data.get('latency_ms', 0),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class ReflectionResult:
    """
    Result from a reflection/analysis of a trade or trading decision.
    
    Used for post-trade analysis and learning from past decisions.
    
    Attributes:
        id: Unique identifier for the reflection.
        created_at: Timestamp when the reflection was created.
        setup_id: Reference to the original SetupCandidate.
        trade_id: Reference to the executed trade (if any).
        llm_result_id: Reference to the LLM result that influenced the decision.
        reflection_type: Type of reflection (PRE_TRADE, POST_TRADE, REVIEW).
        outcome: Outcome assessment (POSITIVE, NEGATIVE, NEUTRAL).
        lessons_learned: Key takeaways from the trade.
        improvements: Suggested improvements for future trades.
        confidence_adjustment: Adjustment to future confidence scores.
        notes: Additional notes or observations.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    setup_id: str
    reflection_type: Literal["PRE_TRADE", "POST_TRADE", "REVIEW"]
    outcome: Optional[Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]] = None
    trade_id: Optional[str] = None
    llm_result_id: Optional[str] = None
    lessons_learned: Optional[list[str]] = None
    improvements: Optional[list[str]] = None
    confidence_adjustment: float = 0.0
    notes: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure lists are initialized."""
        if self.lessons_learned is None:
            self.lessons_learned = []
        if self.improvements is None:
            self.improvements = []

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'trade_id': self.trade_id,
            'llm_result_id': self.llm_result_id,
            'reflection_type': self.reflection_type,
            'outcome': self.outcome,
            'lessons_learned': self.lessons_learned,
            'improvements': self.improvements,
            'confidence_adjustment': self.confidence_adjustment,
            'notes': self.notes,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ReflectionResult':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            ReflectionResult: New instance.
        """
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        return cls(
            id=data['id'],
            created_at=created_at,
            setup_id=data['setup_id'],
            trade_id=data.get('trade_id'),
            llm_result_id=data.get('llm_result_id'),
            reflection_type=data['reflection_type'],
            outcome=data.get('outcome'),
            lessons_learned=data.get('lessons_learned', []),
            improvements=data.get('improvements', []),
            confidence_adjustment=data.get('confidence_adjustment', 0.0),
            notes=data.get('notes'),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class KiEvaluationResult:
    """
    Aggregated KI evaluation result combining multiple analysis sources.
    
    This represents the final decision-making output combining
    LLM analysis, strategy signals, and risk assessment.
    
    Attributes:
        id: Unique identifier for the evaluation.
        created_at: Timestamp when the evaluation was made.
        setup_id: Reference to the SetupCandidate.
        llm_result_ids: References to LocalLLMResults used.
        final_decision: The final trading decision (EXECUTE, SKIP, WAIT).
        decision_confidence: Overall confidence in the decision (0.0 to 1.0).
        risk_score: Calculated risk score (0.0 to 1.0).
        position_size_suggestion: Suggested position size.
        entry_price_target: Suggested entry price.
        stop_loss_target: Suggested stop loss level.
        take_profit_target: Suggested take profit level.
        factors: Contributing factors to the decision.
        warnings: Any warnings or concerns.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    setup_id: str
    final_decision: Literal["EXECUTE", "SKIP", "WAIT"]
    decision_confidence: float = 0.0
    risk_score: float = 0.0
    llm_result_ids: Optional[list[str]] = None
    position_size_suggestion: Optional[float] = None
    entry_price_target: Optional[float] = None
    stop_loss_target: Optional[float] = None
    take_profit_target: Optional[float] = None
    factors: Optional[dict[str, Any]] = None
    warnings: Optional[list[str]] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure lists are initialized."""
        if self.llm_result_ids is None:
            self.llm_result_ids = []
        if self.warnings is None:
            self.warnings = []
        if self.factors is None:
            self.factors = {}

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'llm_result_ids': self.llm_result_ids,
            'final_decision': self.final_decision,
            'decision_confidence': self.decision_confidence,
            'risk_score': self.risk_score,
            'position_size_suggestion': self.position_size_suggestion,
            'entry_price_target': self.entry_price_target,
            'stop_loss_target': self.stop_loss_target,
            'take_profit_target': self.take_profit_target,
            'factors': self.factors,
            'warnings': self.warnings,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'KiEvaluationResult':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            KiEvaluationResult: New instance.
        """
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        return cls(
            id=data['id'],
            created_at=created_at,
            setup_id=data['setup_id'],
            llm_result_ids=data.get('llm_result_ids', []),
            final_decision=data['final_decision'],
            decision_confidence=data.get('decision_confidence', 0.0),
            risk_score=data.get('risk_score', 0.0),
            position_size_suggestion=data.get('position_size_suggestion'),
            entry_price_target=data.get('entry_price_target'),
            stop_loss_target=data.get('stop_loss_target'),
            take_profit_target=data.get('take_profit_target'),
            factors=data.get('factors', {}),
            warnings=data.get('warnings', []),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class ExecutedTrade:
    """
    Represents an actually executed trade with full lifecycle data.
    
    Attributes:
        id: Unique identifier for the trade.
        created_at: Timestamp when the trade was created.
        setup_id: Reference to the SetupCandidate that triggered the trade.
        ki_evaluation_id: Reference to the KiEvaluationResult.
        broker_deal_id: Deal ID from the broker.
        epic: Market identifier.
        direction: Trade direction (LONG/SHORT).
        size: Position size.
        entry_price: Actual entry price.
        exit_price: Actual exit price (when closed).
        stop_loss: Stop loss level.
        take_profit: Take profit level.
        status: Current trade status.
        opened_at: Timestamp when trade was opened.
        closed_at: Timestamp when trade was closed.
        pnl: Profit/loss.
        pnl_percent: Profit/loss percentage.
        fees: Trading fees.
        currency: Trade currency.
        market_snapshot_ids: References to MarketSnapshots.
        notes: Additional notes.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    setup_id: str
    epic: str
    direction: TradeDirection
    size: Decimal
    entry_price: Decimal
    status: TradeStatus
    ki_evaluation_id: Optional[str] = None
    broker_deal_id: Optional[str] = None
    exit_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    pnl: Optional[Decimal] = None
    pnl_percent: Optional[float] = None
    fees: Decimal = Decimal('0.00')
    currency: str = 'EUR'
    market_snapshot_ids: Optional[list[str]] = None
    notes: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure proper types and initialize lists."""
        if self.market_snapshot_ids is None:
            self.market_snapshot_ids = []
        
        # Ensure Decimal types
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))
        if not isinstance(self.entry_price, Decimal):
            self.entry_price = Decimal(str(self.entry_price))
        if self.exit_price is not None and not isinstance(self.exit_price, Decimal):
            self.exit_price = Decimal(str(self.exit_price))
        if self.stop_loss is not None and not isinstance(self.stop_loss, Decimal):
            self.stop_loss = Decimal(str(self.stop_loss))
        if self.take_profit is not None and not isinstance(self.take_profit, Decimal):
            self.take_profit = Decimal(str(self.take_profit))
        if self.pnl is not None and not isinstance(self.pnl, Decimal):
            self.pnl = Decimal(str(self.pnl))
        if not isinstance(self.fees, Decimal):
            self.fees = Decimal(str(self.fees))
        
        # Ensure enum types
        if isinstance(self.direction, str):
            self.direction = TradeDirection(self.direction)
        if isinstance(self.status, str):
            self.status = TradeStatus(self.status)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'ki_evaluation_id': self.ki_evaluation_id,
            'broker_deal_id': self.broker_deal_id,
            'epic': self.epic,
            'direction': self.direction.value if isinstance(self.direction, TradeDirection) else self.direction,
            'size': float(self.size),
            'entry_price': float(self.entry_price),
            'exit_price': float(self.exit_price) if self.exit_price is not None else None,
            'stop_loss': float(self.stop_loss) if self.stop_loss is not None else None,
            'take_profit': float(self.take_profit) if self.take_profit is not None else None,
            'status': self.status.value if isinstance(self.status, TradeStatus) else self.status,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'pnl': float(self.pnl) if self.pnl is not None else None,
            'pnl_percent': self.pnl_percent,
            'fees': float(self.fees),
            'currency': self.currency,
            'market_snapshot_ids': self.market_snapshot_ids,
            'notes': self.notes,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutedTrade':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            ExecutedTrade: New instance.
        """
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)
        
        return cls(
            id=data['id'],
            created_at=parse_datetime(data.get('created_at')),
            setup_id=data['setup_id'],
            ki_evaluation_id=data.get('ki_evaluation_id'),
            broker_deal_id=data.get('broker_deal_id'),
            epic=data['epic'],
            direction=data['direction'],
            size=Decimal(str(data['size'])),
            entry_price=Decimal(str(data['entry_price'])),
            exit_price=Decimal(str(data['exit_price'])) if data.get('exit_price') is not None else None,
            stop_loss=Decimal(str(data['stop_loss'])) if data.get('stop_loss') is not None else None,
            take_profit=Decimal(str(data['take_profit'])) if data.get('take_profit') is not None else None,
            status=data['status'],
            opened_at=parse_datetime(data.get('opened_at')),
            closed_at=parse_datetime(data.get('closed_at')),
            pnl=Decimal(str(data['pnl'])) if data.get('pnl') is not None else None,
            pnl_percent=data.get('pnl_percent'),
            fees=Decimal(str(data.get('fees', '0.00'))),
            currency=data.get('currency', 'EUR'),
            market_snapshot_ids=data.get('market_snapshot_ids', []),
            notes=data.get('notes'),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class ShadowTrade:
    """
    Represents a simulated/paper trade for strategy validation.
    
    Shadow trades are not executed on the broker but tracked
    as if they were real for performance analysis.
    
    Attributes:
        id: Unique identifier for the shadow trade.
        created_at: Timestamp when the shadow trade was created.
        setup_id: Reference to the SetupCandidate.
        ki_evaluation_id: Reference to the KiEvaluationResult.
        epic: Market identifier.
        direction: Trade direction (LONG/SHORT).
        size: Hypothetical position size.
        entry_price: Hypothetical entry price.
        exit_price: Hypothetical exit price (when closed).
        stop_loss: Stop loss level.
        take_profit: Take profit level.
        status: Current trade status.
        opened_at: Timestamp when trade was "opened".
        closed_at: Timestamp when trade was "closed".
        theoretical_pnl: Theoretical profit/loss.
        theoretical_pnl_percent: Theoretical profit/loss percentage.
        skip_reason: Reason why this was not executed (if applicable).
        market_snapshot_ids: References to MarketSnapshots.
        notes: Additional notes.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    setup_id: str
    epic: str
    direction: TradeDirection
    size: Decimal
    entry_price: Decimal
    status: TradeStatus
    ki_evaluation_id: Optional[str] = None
    exit_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    theoretical_pnl: Optional[Decimal] = None
    theoretical_pnl_percent: Optional[float] = None
    skip_reason: Optional[str] = None
    market_snapshot_ids: Optional[list[str]] = None
    notes: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure proper types and initialize lists."""
        if self.market_snapshot_ids is None:
            self.market_snapshot_ids = []
        
        # Ensure Decimal types
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))
        if not isinstance(self.entry_price, Decimal):
            self.entry_price = Decimal(str(self.entry_price))
        if self.exit_price is not None and not isinstance(self.exit_price, Decimal):
            self.exit_price = Decimal(str(self.exit_price))
        if self.stop_loss is not None and not isinstance(self.stop_loss, Decimal):
            self.stop_loss = Decimal(str(self.stop_loss))
        if self.take_profit is not None and not isinstance(self.take_profit, Decimal):
            self.take_profit = Decimal(str(self.take_profit))
        if self.theoretical_pnl is not None and not isinstance(self.theoretical_pnl, Decimal):
            self.theoretical_pnl = Decimal(str(self.theoretical_pnl))
        
        # Ensure enum types
        if isinstance(self.direction, str):
            self.direction = TradeDirection(self.direction)
        if isinstance(self.status, str):
            self.status = TradeStatus(self.status)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'ki_evaluation_id': self.ki_evaluation_id,
            'epic': self.epic,
            'direction': self.direction.value if isinstance(self.direction, TradeDirection) else self.direction,
            'size': float(self.size),
            'entry_price': float(self.entry_price),
            'exit_price': float(self.exit_price) if self.exit_price is not None else None,
            'stop_loss': float(self.stop_loss) if self.stop_loss is not None else None,
            'take_profit': float(self.take_profit) if self.take_profit is not None else None,
            'status': self.status.value if isinstance(self.status, TradeStatus) else self.status,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'theoretical_pnl': float(self.theoretical_pnl) if self.theoretical_pnl is not None else None,
            'theoretical_pnl_percent': self.theoretical_pnl_percent,
            'skip_reason': self.skip_reason,
            'market_snapshot_ids': self.market_snapshot_ids,
            'notes': self.notes,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ShadowTrade':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            ShadowTrade: New instance.
        """
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)
        
        return cls(
            id=data['id'],
            created_at=parse_datetime(data.get('created_at')),
            setup_id=data['setup_id'],
            ki_evaluation_id=data.get('ki_evaluation_id'),
            epic=data['epic'],
            direction=data['direction'],
            size=Decimal(str(data['size'])),
            entry_price=Decimal(str(data['entry_price'])),
            exit_price=Decimal(str(data['exit_price'])) if data.get('exit_price') is not None else None,
            stop_loss=Decimal(str(data['stop_loss'])) if data.get('stop_loss') is not None else None,
            take_profit=Decimal(str(data['take_profit'])) if data.get('take_profit') is not None else None,
            status=data['status'],
            opened_at=parse_datetime(data.get('opened_at')),
            closed_at=parse_datetime(data.get('closed_at')),
            theoretical_pnl=Decimal(str(data['theoretical_pnl'])) if data.get('theoretical_pnl') is not None else None,
            theoretical_pnl_percent=data.get('theoretical_pnl_percent'),
            skip_reason=data.get('skip_reason'),
            market_snapshot_ids=data.get('market_snapshot_ids', []),
            notes=data.get('notes'),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class MarketSnapshot:
    """
    Represents a point-in-time snapshot of market conditions.
    
    Used for recording market state at key moments (trade entry/exit,
    setup detection, etc.) for later analysis.
    
    Attributes:
        id: Unique identifier for the snapshot.
        created_at: Timestamp when the snapshot was taken.
        epic: Market identifier.
        bid: Bid price.
        ask: Ask price.
        spread: Current spread.
        high: Day high.
        low: Day low.
        volume: Current volume (if available).
        atr: Average True Range.
        vwap: Volume Weighted Average Price.
        trend_direction: Current trend direction.
        volatility_level: Volatility assessment.
        session_phase: Current trading session phase.
        additional_indicators: Additional technical indicators.
        notes: Additional notes.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    epic: str
    bid: Decimal
    ask: Decimal
    spread: Decimal
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    volume: Optional[float] = None
    atr: Optional[float] = None
    vwap: Optional[float] = None
    trend_direction: Optional[Literal["UP", "DOWN", "SIDEWAYS"]] = None
    volatility_level: Optional[Literal["LOW", "NORMAL", "HIGH", "EXTREME"]] = None
    session_phase: Optional[str] = None
    additional_indicators: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure proper types."""
        if self.additional_indicators is None:
            self.additional_indicators = {}
        
        # Ensure Decimal types
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

    @property
    def mid_price(self) -> Decimal:
        """Calculate mid price between bid and ask."""
        return (self.bid + self.ask) / 2

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'epic': self.epic,
            'bid': float(self.bid),
            'ask': float(self.ask),
            'spread': float(self.spread),
            'mid_price': float(self.mid_price),
            'high': float(self.high) if self.high is not None else None,
            'low': float(self.low) if self.low is not None else None,
            'volume': self.volume,
            'atr': self.atr,
            'vwap': self.vwap,
            'trend_direction': self.trend_direction,
            'volatility_level': self.volatility_level,
            'session_phase': self.session_phase,
            'additional_indicators': self.additional_indicators,
            'notes': self.notes,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'MarketSnapshot':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            MarketSnapshot: New instance.
        """
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        return cls(
            id=data['id'],
            created_at=created_at,
            epic=data['epic'],
            bid=Decimal(str(data['bid'])),
            ask=Decimal(str(data['ask'])),
            spread=Decimal(str(data['spread'])),
            high=Decimal(str(data['high'])) if data.get('high') is not None else None,
            low=Decimal(str(data['low'])) if data.get('low') is not None else None,
            volume=data.get('volume'),
            atr=data.get('atr'),
            vwap=data.get('vwap'),
            trend_direction=data.get('trend_direction'),
            volatility_level=data.get('volatility_level'),
            session_phase=data.get('session_phase'),
            additional_indicators=data.get('additional_indicators', {}),
            notes=data.get('notes'),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )
