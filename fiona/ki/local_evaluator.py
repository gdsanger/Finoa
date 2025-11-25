"""
LocalLLMEvaluator for Fiona KI Layer.

Performs initial evaluation of SetupCandidates using a local LLM
(Gemma 2 12B / Qwen 14B / Llama).
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models.llm_result import LocalLLMResult


# Path to prompt template
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "local_llm_prompt.txt"


class LocalLLMEvaluator:
    """
    Evaluator using local LLM for initial setup analysis.
    
    The LocalLLMEvaluator:
    - Interprets market structure
    - Recognizes trend direction
    - Evaluates breakout or EIA setups
    - Calculates sensible SL/TP/Size values
    - Formulates textual reasoning
    - Produces clean JSON output
    
    Example:
        >>> evaluator = LocalLLMEvaluator()
        >>> result = evaluator.evaluate(setup_candidate)
        >>> print(result.direction, result.sl, result.tp)
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        model: str = "gemma2:12b",
        provider: str = "LOCAL",
    ):
        """
        Initialize the LocalLLMEvaluator.
        
        Args:
            llm_client: Optional LLM client for API calls.
                       If None, will use KIGate integration.
            model: Model name to use (default: gemma2:12b).
            provider: LLM provider name.
        """
        self._llm_client = llm_client
        self._model = model
        self._provider = provider
        self._prompt_template = self._load_prompt_template()
    
    def _load_prompt_template(self) -> str:
        """Load the prompt template from file."""
        if PROMPT_TEMPLATE_PATH.exists():
            return PROMPT_TEMPLATE_PATH.read_text(encoding='utf-8')
        
        # Fallback inline template
        return """Analyze the following trading setup and provide your evaluation as JSON:
Setup: {epic} - {setup_kind} - {phase}
Reference Price: {reference_price}
Direction: {direction}

Respond with JSON only: {{"direction": "LONG"|"SHORT"|"NO_TRADE", "sl": float, "tp": float, "size": float, "reason": "string", "quality_flags": {{}}}}"""

    def _format_breakout_context(self, setup: Any) -> str:
        """Format breakout context for prompt."""
        if not hasattr(setup, 'breakout') or setup.breakout is None:
            return "Nicht verfügbar"
        
        breakout = setup.breakout
        return f"""- Range High: {breakout.range_high}
- Range Low: {breakout.range_low}
- Range Height: {breakout.range_height}
- Trigger Price: {breakout.trigger_price}
- Breakout Direction: {breakout.direction}
- ATR: {breakout.atr or 'N/A'}
- VWAP: {breakout.vwap or 'N/A'}
- Volume Spike: {breakout.volume_spike or 'N/A'}"""

    def _format_eia_context(self, setup: Any) -> str:
        """Format EIA context for prompt."""
        if not hasattr(setup, 'eia') or setup.eia is None:
            return "Nicht verfügbar"
        
        eia = setup.eia
        return f"""- EIA Timestamp: {eia.eia_timestamp}
- First Impulse Direction: {eia.first_impulse_direction or 'N/A'}
- Impulse Range High: {eia.impulse_range_high or 'N/A'}
- Impulse Range Low: {eia.impulse_range_low or 'N/A'}
- ATR: {eia.atr or 'N/A'}"""

    def _format_quality_flags(self, setup: Any) -> str:
        """Format quality flags for prompt."""
        if not hasattr(setup, 'quality_flags') or not setup.quality_flags:
            return "Keine zusätzlichen Flags"
        
        return json.dumps(setup.quality_flags, indent=2)

    def _format_atr_info(self, setup: Any) -> str:
        """Extract and format ATR info from setup."""
        atr = None
        
        if hasattr(setup, 'breakout') and setup.breakout and setup.breakout.atr:
            atr = setup.breakout.atr
        elif hasattr(setup, 'eia') and setup.eia and setup.eia.atr:
            atr = setup.eia.atr
        
        if atr is None:
            return "ATR nicht verfügbar"
        
        return f"ATR: {atr}"

    def _build_prompt(self, setup: Any) -> str:
        """
        Build the full prompt for the LLM.
        
        Args:
            setup: SetupCandidate to evaluate.
            
        Returns:
            str: Formatted prompt.
        """
        # Get setup_kind value (handle enum)
        setup_kind = setup.setup_kind
        if hasattr(setup_kind, 'value'):
            setup_kind = setup_kind.value
        
        # Get phase value (handle enum)
        phase = setup.phase
        if hasattr(phase, 'value'):
            phase = phase.value
        
        return self._prompt_template.format(
            epic=setup.epic,
            setup_kind=setup_kind,
            phase=phase,
            reference_price=setup.reference_price,
            direction=setup.direction,
            breakout_context=self._format_breakout_context(setup),
            eia_context=self._format_eia_context(setup),
            quality_flags=self._format_quality_flags(setup),
            atr_info=self._format_atr_info(setup),
        )

    def _parse_llm_response(self, response_text: str) -> dict[str, Any]:
        """
        Parse LLM response into structured data.
        
        Args:
            response_text: Raw text response from LLM.
            
        Returns:
            dict: Parsed JSON data.
        """
        # Try to extract JSON from response
        text = response_text.strip()
        
        # Handle markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Return empty dict on parse failure
            return {
                "direction": None,
                "sl": None,
                "tp": None,
                "size": None,
                "reason": f"JSON parse error: {text[:200]}",
                "quality_flags": {},
            }

    def _call_llm(self, prompt: str) -> tuple[str, int, int]:
        """
        Call the LLM with the given prompt.
        
        Args:
            prompt: The prompt to send.
            
        Returns:
            tuple: (response_text, tokens_used, latency_ms)
        """
        start_time = time.time()
        
        if self._llm_client is not None:
            # Use provided client
            try:
                response = self._llm_client(prompt)
                latency_ms = int((time.time() - start_time) * 1000)
                return response.get('text', ''), response.get('tokens', 0), latency_ms
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                return json.dumps({"direction": None, "reason": f"LLM error: {str(e)}"}), 0, latency_ms
        
        # Try to use KIGate if available
        try:
            from core.services.kigate_client import execute_agent, KIGateResponse
            
            response: KIGateResponse = execute_agent(
                prompt=prompt,
                model=self._model,
                temperature=0.3,  # Lower temperature for more deterministic output
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            if response.success and response.data:
                result_text = response.data.get('result', '')
                tokens = response.data.get('tokens_used', 0)
                return result_text, tokens, latency_ms
            else:
                error = response.error or "Unknown error"
                return json.dumps({"direction": None, "reason": f"KIGate error: {error}"}), 0, latency_ms
                
        except ImportError:
            # KIGate not available - return mock response for testing
            latency_ms = int((time.time() - start_time) * 1000)
            mock_response = {
                "direction": "NO_TRADE",
                "sl": None,
                "tp": None,
                "size": None,
                "reason": "LLM client not available",
                "quality_flags": {},
            }
            return json.dumps(mock_response), 0, latency_ms
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return json.dumps({"direction": None, "reason": f"Error: {str(e)}"}), 0, latency_ms

    def evaluate(self, setup: Any) -> LocalLLMResult:
        """
        Evaluate a SetupCandidate using the local LLM.
        
        Args:
            setup: SetupCandidate to evaluate.
            
        Returns:
            LocalLLMResult: Evaluation result.
        """
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Build prompt and call LLM
        prompt = self._build_prompt(setup)
        response_text, tokens_used, latency_ms = self._call_llm(prompt)
        
        # Parse response
        parsed = self._parse_llm_response(response_text)
        
        # Build result
        return LocalLLMResult(
            id=result_id,
            created_at=now,
            setup_id=setup.id,
            direction=parsed.get('direction'),
            sl=parsed.get('sl'),
            tp=parsed.get('tp'),
            size=parsed.get('size'),
            reason=parsed.get('reason'),
            quality_flags=parsed.get('quality_flags', {}),
            raw_json=parsed,
            model=self._model,
            provider=self._provider,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )

    def evaluate_with_mock(self, setup: Any, mock_response: dict[str, Any]) -> LocalLLMResult:
        """
        Evaluate with a mocked LLM response (for testing).
        
        Args:
            setup: SetupCandidate to evaluate.
            mock_response: Mock response dict.
            
        Returns:
            LocalLLMResult: Evaluation result with mock data.
        """
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        return LocalLLMResult(
            id=result_id,
            created_at=now,
            setup_id=setup.id,
            direction=mock_response.get('direction'),
            sl=mock_response.get('sl'),
            tp=mock_response.get('tp'),
            size=mock_response.get('size'),
            reason=mock_response.get('reason'),
            quality_flags=mock_response.get('quality_flags', {}),
            raw_json=mock_response,
            model=self._model,
            provider=self._provider,
            tokens_used=0,
            latency_ms=0,
        )
