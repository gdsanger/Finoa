"""
ReflectionResult model for Fiona KI Layer.

Represents the result from GPT reflection/validation of LocalLLMResult.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Any


@dataclass
class ReflectionResult:
    """
    Result from GPT reflection/validation of a LocalLLMResult.
    
    The GPT reflection layer (GPT-4.1 / GPT-4o) validates and potentially
    corrects the local LLM's analysis:
    - Checks the local LLM recommendation
    - Identifies contradictions/errors
    - Corrects parameters if needed
    - Generates a confidence score
    - Provides additional reasoning
    
    Attributes:
        id: Unique identifier for the result.
        created_at: Timestamp when result was generated.
        setup_id: Reference to the evaluated SetupCandidate.
        local_llm_result_id: Reference to the LocalLLMResult being validated.
        corrected_direction: Corrected trade direction (if different from local LLM).
        corrected_sl: Corrected stop loss price.
        corrected_tp: Corrected take profit price.
        corrected_size: Corrected position size.
        reason: Textual explanation of the validation.
        confidence: Confidence score (0-100%).
        raw_json: Raw JSON response from GPT.
        model: GPT model used.
        tokens_used: Number of tokens consumed.
        latency_ms: Response latency in milliseconds.
        agrees_with_local: Whether GPT agrees with local LLM recommendation.
        corrections_made: List of corrections made.
    """
    id: str
    created_at: datetime
    setup_id: str
    local_llm_result_id: str
    corrected_direction: Optional[Literal["LONG", "SHORT", "NO_TRADE"]] = None
    corrected_sl: Optional[float] = None
    corrected_tp: Optional[float] = None
    corrected_size: Optional[float] = None
    reason: Optional[str] = None
    confidence: float = 0.0  # 0-100%
    raw_json: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    tokens_used: int = 0
    latency_ms: int = 0
    agrees_with_local: bool = True
    corrections_made: Optional[list[str]] = None

    def __post_init__(self):
        """Ensure optional values are initialized."""
        if self.raw_json is None:
            self.raw_json = {}
        if self.corrections_made is None:
            self.corrections_made = []

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
            'local_llm_result_id': self.local_llm_result_id,
            'corrected_direction': self.corrected_direction,
            'corrected_sl': self.corrected_sl,
            'corrected_tp': self.corrected_tp,
            'corrected_size': self.corrected_size,
            'reason': self.reason,
            'confidence': self.confidence,
            'raw_json': self.raw_json,
            'model': self.model,
            'tokens_used': self.tokens_used,
            'latency_ms': self.latency_ms,
            'agrees_with_local': self.agrees_with_local,
            'corrections_made': self.corrections_made,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ReflectionResult':
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
            local_llm_result_id=data['local_llm_result_id'],
            corrected_direction=data.get('corrected_direction'),
            corrected_sl=data.get('corrected_sl'),
            corrected_tp=data.get('corrected_tp'),
            corrected_size=data.get('corrected_size'),
            reason=data.get('reason'),
            confidence=data.get('confidence', 0.0),
            raw_json=data.get('raw_json', {}),
            model=data.get('model'),
            tokens_used=data.get('tokens_used', 0),
            latency_ms=data.get('latency_ms', 0),
            agrees_with_local=data.get('agrees_with_local', True),
            corrections_made=data.get('corrections_made', []),
        )

    @property
    def signal_strength(self) -> str:
        """
        Determine signal strength based on confidence score.
        
        Returns:
            str: Signal strength classification.
        """
        if self.confidence >= 80:
            return "strong_signal"
        elif self.confidence >= 60:
            return "weak_signal"
        else:
            return "no_trade"

    def has_corrections(self) -> bool:
        """
        Check if this reflection made any corrections.
        
        Returns:
            bool: True if any corrections were made.
        """
        return len(self.corrections_made) > 0 if self.corrections_made else False
