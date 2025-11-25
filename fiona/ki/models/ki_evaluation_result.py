"""
KiEvaluationResult model for Fiona KI Layer.

Represents the consolidated result from the KI orchestrator.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Any


@dataclass
class KiEvaluationResult:
    """
    Consolidated KI evaluation result from the orchestrator.
    
    The KiOrchestrator combines LocalLLMResult and ReflectionResult
    to produce a final, merged evaluation with:
    - Local LLM evaluation data
    - GPT reflection data
    - Final merged parameters
    - Signal strength classification
    
    The AI does NOT decide whether to trade - Risk Engine + User make
    the final decision.
    
    Attributes:
        id: Unique identifier for the evaluation.
        setup_id: Reference to the evaluated SetupCandidate.
        timestamp: Timestamp when evaluation was created.
        
        # Local LLM evaluation
        llm_direction: Direction from local LLM.
        llm_sl: Stop loss from local LLM.
        llm_tp: Take profit from local LLM.
        llm_size: Position size from local LLM.
        llm_reason: Reasoning from local LLM.
        
        # GPT reflection
        reflection_direction: Direction from GPT reflection.
        reflection_sl: Stop loss from GPT reflection.
        reflection_tp: Take profit from GPT reflection.
        reflection_size: Position size from GPT reflection.
        reflection_reason: Reasoning from GPT reflection.
        reflection_score: Confidence score from reflection (0-100).
        
        # Final merged values
        final_direction: Final trade direction.
        final_sl: Final stop loss.
        final_tp: Final take profit.
        final_size: Final position size.
        final_reason: Final combined reasoning.
        signal_strength: Signal strength (strong_signal/weak_signal/no_trade).
        
        # Raw data
        raw_local: Raw LocalLLMResult dict.
        raw_reflection: Raw ReflectionResult dict.
        local_llm_result_id: Reference to LocalLLMResult.
        reflection_result_id: Reference to ReflectionResult.
    """
    id: str
    setup_id: str
    timestamp: datetime

    # Local LLM evaluation
    llm_direction: Optional[Literal["LONG", "SHORT", "NO_TRADE"]] = None
    llm_sl: Optional[float] = None
    llm_tp: Optional[float] = None
    llm_size: Optional[float] = None
    llm_reason: Optional[str] = None

    # GPT reflection
    reflection_direction: Optional[Literal["LONG", "SHORT", "NO_TRADE"]] = None
    reflection_sl: Optional[float] = None
    reflection_tp: Optional[float] = None
    reflection_size: Optional[float] = None
    reflection_reason: Optional[str] = None
    reflection_score: float = 0.0

    # Final merged values
    final_direction: Optional[Literal["LONG", "SHORT", "NO_TRADE"]] = None
    final_sl: Optional[float] = None
    final_tp: Optional[float] = None
    final_size: Optional[float] = None
    final_reason: Optional[str] = None
    signal_strength: Literal["strong_signal", "weak_signal", "no_trade"] = "no_trade"

    # Raw data references
    raw_local: Optional[dict[str, Any]] = None
    raw_reflection: Optional[dict[str, Any]] = None
    local_llm_result_id: Optional[str] = None
    reflection_result_id: Optional[str] = None

    def __post_init__(self):
        """Ensure optional dicts are initialized."""
        if self.raw_local is None:
            self.raw_local = {}
        if self.raw_reflection is None:
            self.raw_reflection = {}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        return {
            'id': self.id,
            'setup_id': self.setup_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            
            # Local LLM
            'llm_direction': self.llm_direction,
            'llm_sl': self.llm_sl,
            'llm_tp': self.llm_tp,
            'llm_size': self.llm_size,
            'llm_reason': self.llm_reason,
            
            # Reflection
            'reflection_direction': self.reflection_direction,
            'reflection_sl': self.reflection_sl,
            'reflection_tp': self.reflection_tp,
            'reflection_size': self.reflection_size,
            'reflection_reason': self.reflection_reason,
            'reflection_score': self.reflection_score,
            
            # Final
            'final_direction': self.final_direction,
            'final_sl': self.final_sl,
            'final_tp': self.final_tp,
            'final_size': self.final_size,
            'final_reason': self.final_reason,
            'signal_strength': self.signal_strength,
            
            # Raw
            'raw_local': self.raw_local,
            'raw_reflection': self.raw_reflection,
            'local_llm_result_id': self.local_llm_result_id,
            'reflection_result_id': self.reflection_result_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'KiEvaluationResult':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            KiEvaluationResult: New instance.
        """
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        
        return cls(
            id=data['id'],
            setup_id=data['setup_id'],
            timestamp=timestamp,
            
            # Local LLM
            llm_direction=data.get('llm_direction'),
            llm_sl=data.get('llm_sl'),
            llm_tp=data.get('llm_tp'),
            llm_size=data.get('llm_size'),
            llm_reason=data.get('llm_reason'),
            
            # Reflection
            reflection_direction=data.get('reflection_direction'),
            reflection_sl=data.get('reflection_sl'),
            reflection_tp=data.get('reflection_tp'),
            reflection_size=data.get('reflection_size'),
            reflection_reason=data.get('reflection_reason'),
            reflection_score=data.get('reflection_score', 0.0),
            
            # Final
            final_direction=data.get('final_direction'),
            final_sl=data.get('final_sl'),
            final_tp=data.get('final_tp'),
            final_size=data.get('final_size'),
            final_reason=data.get('final_reason'),
            signal_strength=data.get('signal_strength', 'no_trade'),
            
            # Raw
            raw_local=data.get('raw_local', {}),
            raw_reflection=data.get('raw_reflection', {}),
            local_llm_result_id=data.get('local_llm_result_id'),
            reflection_result_id=data.get('reflection_result_id'),
        )

    def is_tradeable(self) -> bool:
        """
        Check if this evaluation suggests a tradeable signal.
        
        Note: This is advisory only. Risk Engine + User make final decision.
        
        Returns:
            bool: True if signal_strength is not 'no_trade'.
        """
        return self.signal_strength != "no_trade"

    def get_trade_parameters(self) -> Optional[dict[str, Any]]:
        """
        Get final trade parameters if tradeable.
        
        Returns:
            Optional[dict]: Trade parameters or None if not tradeable.
        """
        if not self.is_tradeable():
            return None
        
        return {
            'direction': self.final_direction,
            'sl': self.final_sl,
            'tp': self.final_tp,
            'size': self.final_size,
            'signal_strength': self.signal_strength,
            'confidence': self.reflection_score,
        }
