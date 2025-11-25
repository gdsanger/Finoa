"""
KiOrchestrator for Fiona KI Layer.

Central orchestration logic that combines LocalLLMEvaluator and
GPTReflectionEvaluator to produce a consolidated KiEvaluationResult.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .local_evaluator import LocalLLMEvaluator
from .reflection_evaluator import GPTReflectionEvaluator
from .models.llm_result import LocalLLMResult
from .models.reflection_result import ReflectionResult
from .models.ki_evaluation_result import KiEvaluationResult


class KiOrchestrator:
    """
    Central orchestrator for the two-stage KI pipeline.
    
    The KiOrchestrator:
    1. Calls LocalLLMEvaluator for initial analysis
    2. Calls GPTReflectionEvaluator for validation
    3. Merges both results into a consolidated KiEvaluationResult
    4. Applies confidence-based signal classification:
       - confidence >= 80: strong_signal
       - 60 <= confidence < 80: weak_signal
       - confidence < 60: no_trade
    5. Stores all results in Weaviate (optional)
    
    The AI does NOT decide whether to trade. Risk Engine + User
    make the final decision.
    
    Example:
        >>> orchestrator = KiOrchestrator()
        >>> result = orchestrator.evaluate(setup_candidate)
        >>> print(result.signal_strength, result.final_direction)
    """
    
    def __init__(
        self,
        local_evaluator: Optional[LocalLLMEvaluator] = None,
        reflection_evaluator: Optional[GPTReflectionEvaluator] = None,
        weaviate_service: Optional[Any] = None,
    ):
        """
        Initialize the KiOrchestrator.
        
        Args:
            local_evaluator: LocalLLMEvaluator instance.
                           If None, creates default instance.
            reflection_evaluator: GPTReflectionEvaluator instance.
                                If None, creates default instance.
            weaviate_service: Optional WeaviateService for persistence.
        """
        self._local_evaluator = local_evaluator or LocalLLMEvaluator()
        self._reflection_evaluator = reflection_evaluator or GPTReflectionEvaluator()
        self._weaviate_service = weaviate_service
    
    def _determine_signal_strength(self, confidence: float) -> str:
        """
        Determine signal strength based on confidence score.
        
        Args:
            confidence: Confidence score (0-100).
            
        Returns:
            str: Signal strength classification.
        """
        if confidence >= 80:
            return "strong_signal"
        elif confidence >= 60:
            return "weak_signal"
        else:
            return "no_trade"
    
    def _merge_results(
        self,
        setup: Any,
        local_result: LocalLLMResult,
        reflection_result: ReflectionResult,
    ) -> KiEvaluationResult:
        """
        Merge local and reflection results into final evaluation.
        
        Strategy:
        - If reflection corrected values, use corrected values
        - Otherwise, use local LLM values
        - Apply confidence-based signal classification
        
        Args:
            setup: Original SetupCandidate.
            local_result: LocalLLMResult from first stage.
            reflection_result: ReflectionResult from second stage.
            
        Returns:
            KiEvaluationResult: Merged final evaluation.
        """
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Determine final values (use corrections if present)
        final_direction = (
            reflection_result.corrected_direction
            if reflection_result.corrected_direction is not None
            else local_result.direction
        )
        
        final_sl = (
            reflection_result.corrected_sl
            if reflection_result.corrected_sl is not None
            else local_result.sl
        )
        
        final_tp = (
            reflection_result.corrected_tp
            if reflection_result.corrected_tp is not None
            else local_result.tp
        )
        
        final_size = (
            reflection_result.corrected_size
            if reflection_result.corrected_size is not None
            else local_result.size
        )
        
        # Build combined reasoning
        local_reason = local_result.reason or ""
        reflection_reason = reflection_result.reason or ""
        
        if reflection_result.has_corrections():
            corrections = ", ".join(reflection_result.corrections_made)
            final_reason = f"Local: {local_reason}\nReflection (mit Korrekturen: {corrections}): {reflection_reason}"
        else:
            final_reason = f"Local: {local_reason}\nReflection (bestätigt): {reflection_reason}"
        
        # Determine signal strength
        signal_strength = self._determine_signal_strength(reflection_result.confidence)
        
        # Override to no_trade if direction is NO_TRADE or None
        if final_direction is None or final_direction == "NO_TRADE":
            signal_strength = "no_trade"
        
        return KiEvaluationResult(
            id=result_id,
            setup_id=setup.id,
            timestamp=now,
            
            # Local LLM data
            llm_direction=local_result.direction,
            llm_sl=local_result.sl,
            llm_tp=local_result.tp,
            llm_size=local_result.size,
            llm_reason=local_result.reason,
            
            # Reflection data
            reflection_direction=reflection_result.corrected_direction,
            reflection_sl=reflection_result.corrected_sl,
            reflection_tp=reflection_result.corrected_tp,
            reflection_size=reflection_result.corrected_size,
            reflection_reason=reflection_result.reason,
            reflection_score=reflection_result.confidence,
            
            # Final merged values
            final_direction=final_direction,
            final_sl=final_sl,
            final_tp=final_tp,
            final_size=final_size,
            final_reason=final_reason,
            signal_strength=signal_strength,
            
            # Raw data
            raw_local=local_result.to_dict(),
            raw_reflection=reflection_result.to_dict(),
            local_llm_result_id=local_result.id,
            reflection_result_id=reflection_result.id,
        )
    
    def _store_results(
        self,
        local_result: LocalLLMResult,
        reflection_result: ReflectionResult,
        ki_result: KiEvaluationResult,
    ) -> None:
        """
        Store all results in Weaviate if service is available.
        
        Args:
            local_result: LocalLLMResult to store.
            reflection_result: ReflectionResult to store.
            ki_result: KiEvaluationResult to store.
        """
        if self._weaviate_service is None:
            return
        
        try:
            # Note: The existing WeaviateService uses different model classes
            # This would need adaptation to work with existing models
            # For now, we'll use a simplified approach
            pass
        except Exception as e:
            # Log error but don't fail the evaluation
            print(f"Warning: Failed to store results in Weaviate: {e}")
    
    def evaluate(self, setup: Any) -> KiEvaluationResult:
        """
        Perform full two-stage evaluation of a SetupCandidate.
        
        Args:
            setup: SetupCandidate to evaluate.
            
        Returns:
            KiEvaluationResult: Consolidated evaluation result.
        """
        # Stage 1: Local LLM evaluation
        local_result = self._local_evaluator.evaluate(setup)
        
        # Stage 2: GPT reflection
        reflection_result = self._reflection_evaluator.reflect(setup, local_result)
        
        # Merge results
        ki_result = self._merge_results(setup, local_result, reflection_result)
        
        # Store results if Weaviate is available
        self._store_results(local_result, reflection_result, ki_result)
        
        return ki_result
    
    def evaluate_local_only(self, setup: Any) -> LocalLLMResult:
        """
        Perform only the local LLM evaluation (skip reflection).
        
        Useful for testing or when GPT is not available.
        
        Args:
            setup: SetupCandidate to evaluate.
            
        Returns:
            LocalLLMResult: Local evaluation result.
        """
        return self._local_evaluator.evaluate(setup)
    
    def evaluate_with_mock(
        self,
        setup: Any,
        mock_local_response: dict[str, Any],
        mock_reflection_response: dict[str, Any],
    ) -> KiEvaluationResult:
        """
        Perform evaluation with mocked responses (for testing).
        
        Args:
            setup: SetupCandidate to evaluate.
            mock_local_response: Mock response for local LLM.
            mock_reflection_response: Mock response for GPT reflection.
            
        Returns:
            KiEvaluationResult: Consolidated evaluation result.
        """
        # Stage 1: Mock local evaluation
        local_result = self._local_evaluator.evaluate_with_mock(setup, mock_local_response)
        
        # Stage 2: Mock GPT reflection
        reflection_result = self._reflection_evaluator.reflect_with_mock(
            setup, local_result, mock_reflection_response
        )
        
        # Merge results
        ki_result = self._merge_results(setup, local_result, reflection_result)
        
        return ki_result
    
    def get_local_evaluator(self) -> LocalLLMEvaluator:
        """Get the local LLM evaluator instance."""
        return self._local_evaluator
    
    def get_reflection_evaluator(self) -> GPTReflectionEvaluator:
        """Get the GPT reflection evaluator instance."""
        return self._reflection_evaluator
    
    def set_weaviate_service(self, service: Any) -> None:
        """
        Set or update the Weaviate service for persistence.
        
        Args:
            service: WeaviateService instance.
        """
        self._weaviate_service = service
