"""
LocalLLMResult model for Fiona KI Layer.

Represents the result from local LLM evaluation of a SetupCandidate.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, Any


@dataclass
class LocalLLMResult:
    """
    Result from local LLM analysis of a SetupCandidate.
    
    The local LLM (Gemma 2 12B / Qwen 14B / Llama) performs the initial
    evaluation, including:
    - Market structure interpretation
    - Trend direction recognition
    - Breakout/EIA setup evaluation
    - SL/TP/Size calculation
    - Textual reasoning
    
    Attributes:
        id: Unique identifier for the result.
        created_at: Timestamp when result was generated.
        setup_id: Reference to the evaluated SetupCandidate.
        direction: Suggested trade direction (LONG/SHORT/NO_TRADE).
        sl: Suggested stop loss price.
        tp: Suggested take profit price.
        size: Suggested position size.
        reason: Textual explanation of the evaluation.
        quality_flags: Additional quality indicators.
        raw_json: Raw JSON response from the LLM.
        model: Model name used for evaluation.
        provider: LLM provider used.
        tokens_used: Number of tokens consumed.
        latency_ms: Response latency in milliseconds.
    """
    id: str
    created_at: datetime
    setup_id: str
    direction: Optional[Literal["LONG", "SHORT", "NO_TRADE"]] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    size: Optional[float] = None
    reason: Optional[str] = None
    quality_flags: Optional[dict[str, Any]] = None
    raw_json: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    tokens_used: int = 0
    latency_ms: int = 0

    def __post_init__(self):
        """Ensure optional dicts are initialized."""
        if self.quality_flags is None:
            self.quality_flags = {}
        if self.raw_json is None:
            self.raw_json = {}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'setup_id': self.setup_id,
            'direction': self.direction,
            'sl': self.sl,
            'tp': self.tp,
            'size': self.size,
            'reason': self.reason,
            'quality_flags': self.quality_flags,
            'raw_json': self.raw_json,
            'model': self.model,
            'provider': self.provider,
            'tokens_used': self.tokens_used,
            'latency_ms': self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'LocalLLMResult':
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
        
        return cls(
            id=data['id'],
            created_at=created_at,
            setup_id=data['setup_id'],
            direction=data.get('direction'),
            sl=data.get('sl'),
            tp=data.get('tp'),
            size=data.get('size'),
            reason=data.get('reason'),
            quality_flags=data.get('quality_flags', {}),
            raw_json=data.get('raw_json', {}),
            model=data.get('model'),
            provider=data.get('provider'),
            tokens_used=data.get('tokens_used', 0),
            latency_ms=data.get('latency_ms', 0),
        )

    def is_valid_trade_signal(self) -> bool:
        """
        Check if this result represents a valid trade signal.
        
        Returns:
            bool: True if direction is LONG or SHORT with required parameters.
        """
        if self.direction not in ("LONG", "SHORT"):
            return False
        return self.sl is not None and self.tp is not None

    @property
    def risk_reward_ratio(self) -> Optional[float]:
        """
        Calculate risk/reward ratio if possible.
        
        Returns:
            Optional[float]: Risk/reward ratio or None if not calculable.
        """
        if self.sl is None or self.tp is None:
            return None
        
        # Need reference price to calculate - this would typically come from SetupCandidate
        return None
