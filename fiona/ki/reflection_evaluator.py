"""
GPTReflectionEvaluator for Fiona KI Layer.

Performs validation and reflection on LocalLLMResult using GPT-4.1/4o.
Uses KIGate API with the 'trading-reflection-agent' for evaluation.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .models.llm_result import LocalLLMResult
from .models.reflection_result import ReflectionResult


# Try to import KIGate client at module level
_kigate_available = False
_execute_agent = None
try:
    from core.services.kigate_client import execute_agent as _execute_agent_import
    _execute_agent = _execute_agent_import
    _kigate_available = True
except ImportError:
    pass


# Path to prompt template
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "reflection_prompt.txt"

# KIGate configuration for trading-reflection-agent
KIGATE_AGENT_NAME = "trading-reflection-agent"
KIGATE_PROVIDER = "openai"
KIGATE_MODEL = "gpt-4o"
KIGATE_USER_ID = "fiona-ki"


class GPTReflectionEvaluator:
    """
    Evaluator using GPT for reflection and validation.
    
    The GPTReflectionEvaluator:
    - Reviews the local LLM's recommendation
    - Identifies contradictions/errors
    - Corrects parameters if needed
    - Generates a confidence score (0-100%)
    - Provides final reasoning
    
    Uses KIGate API with the 'trading-reflection-agent' for evaluation.
    
    Example:
        >>> evaluator = GPTReflectionEvaluator()
        >>> reflection = evaluator.reflect(setup, local_result)
        >>> print(reflection.confidence, reflection.signal_strength)
    """
    
    def __init__(
        self,
        gpt_client: Optional[Any] = None,
        model: str = "gpt-4o",
        agent_name: str = KIGATE_AGENT_NAME,
        provider: str = KIGATE_PROVIDER,
        user_id: str = KIGATE_USER_ID,
    ):
        """
        Initialize the GPTReflectionEvaluator.
        
        Args:
            gpt_client: Optional GPT client for API calls.
                       If None, will use KIGate integration.
            model: GPT model name to use (default: gpt-4o).
            agent_name: KIGate agent name (default: trading-reflection-agent).
            provider: KIGate provider (default: openai).
            user_id: KIGate user ID (default: fiona-ki).
        """
        self._gpt_client = gpt_client
        self._model = model
        self._agent_name = agent_name
        self._provider = provider
        self._user_id = user_id
        self._prompt_template = self._load_prompt_template()
    
    def _load_prompt_template(self) -> str:
        """Load the prompt template from file."""
        if PROMPT_TEMPLATE_PATH.exists():
            return PROMPT_TEMPLATE_PATH.read_text(encoding='utf-8')
        
        # Fallback inline template
        return """Review the following local LLM analysis:
Setup: {epic} - {setup_kind}
Local LLM Direction: {llm_direction}
Local LLM SL: {llm_sl}
Local LLM TP: {llm_tp}

Respond with JSON: {{"corrected_direction": null|"LONG"|"SHORT"|"NO_TRADE", "corrected_sl": null|float, "corrected_tp": null|float, "corrected_size": null|float, "reason": "string", "confidence": 0-100, "agrees_with_local": bool, "corrections_made": []}}"""

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
- ATR: {breakout.atr or 'N/A'}"""

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

    def _build_prompt(self, setup: Any, local_result: LocalLLMResult) -> str:
        """
        Build the reflection prompt.
        
        Args:
            setup: Original SetupCandidate.
            local_result: LocalLLMResult to reflect on.
            
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
            llm_direction=local_result.direction,
            llm_sl=local_result.sl,
            llm_tp=local_result.tp,
            llm_size=local_result.size,
            llm_reason=local_result.reason or "Keine Begründung",
            llm_quality_flags=json.dumps(local_result.quality_flags or {}, indent=2),
        )

    def _parse_gpt_response(self, response_text: str) -> dict[str, Any]:
        """
        Parse GPT response into structured data.
        
        Args:
            response_text: Raw text response from GPT.
            
        Returns:
            dict: Parsed JSON data.
        """
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
            return {
                "corrected_direction": None,
                "corrected_sl": None,
                "corrected_tp": None,
                "corrected_size": None,
                "reason": f"JSON parse error: {text[:200]}",
                "confidence": 0,
                "agrees_with_local": False,
                "corrections_made": ["Parse error"],
            }

    def _call_gpt(self, prompt: str) -> tuple[str, int, int]:
        """
        Call GPT via KIGate with the given prompt.
        
        Uses the trading-reflection-agent via /agent/execute endpoint.
        
        Args:
            prompt: The prompt to send.
            
        Returns:
            tuple: (response_text, tokens_used, latency_ms)
        """
        start_time = time.time()
        
        if self._gpt_client is not None:
            # Use provided client (for testing)
            try:
                response = self._gpt_client(prompt)
                latency_ms = int((time.time() - start_time) * 1000)
                return response.get('text', ''), response.get('tokens', 0), latency_ms
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                return json.dumps({"confidence": 0, "reason": f"GPT error: {str(e)}"}), 0, latency_ms
        
        # Use KIGate if available (module-level import)
        if _kigate_available and _execute_agent is not None:
            try:
                response = _execute_agent(
                    prompt=prompt,
                    agent_name=self._agent_name,
                    provider=self._provider,
                    model=self._model,
                    user_id=self._user_id,
                    temperature=0.3,  # Lower temperature for more deterministic output
                )
                
                latency_ms = int((time.time() - start_time) * 1000)
                
                if response.success and response.data:
                    result_text = response.data.get('result', '')
                    tokens = response.data.get('tokens_used', 0)
                    return result_text, tokens, latency_ms
                else:
                    error = response.error or "Unknown error"
                    return json.dumps({"confidence": 0, "reason": f"KIGate error: {error}"}), 0, latency_ms
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                return json.dumps({"confidence": 0, "reason": f"Error: {str(e)}"}), 0, latency_ms
        
        # KIGate not available - return mock response
        latency_ms = int((time.time() - start_time) * 1000)
        mock_response = {
            "corrected_direction": None,
            "corrected_sl": None,
            "corrected_tp": None,
            "corrected_size": None,
            "reason": "KIGate client not available",
            "confidence": 0,
            "agrees_with_local": True,
            "corrections_made": [],
        }
        return json.dumps(mock_response), 0, latency_ms

    def reflect(self, setup: Any, local_result: LocalLLMResult) -> ReflectionResult:
        """
        Perform reflection on a LocalLLMResult.
        
        Args:
            setup: Original SetupCandidate.
            local_result: LocalLLMResult to reflect on.
            
        Returns:
            ReflectionResult: Reflection/validation result.
        """
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Build prompt and call GPT
        prompt = self._build_prompt(setup, local_result)
        response_text, tokens_used, latency_ms = self._call_gpt(prompt)
        
        # Parse response
        parsed = self._parse_gpt_response(response_text)
        
        # Build result
        return ReflectionResult(
            id=result_id,
            created_at=now,
            setup_id=setup.id,
            local_llm_result_id=local_result.id,
            corrected_direction=parsed.get('corrected_direction'),
            corrected_sl=parsed.get('corrected_sl'),
            corrected_tp=parsed.get('corrected_tp'),
            corrected_size=parsed.get('corrected_size'),
            reason=parsed.get('reason'),
            confidence=parsed.get('confidence', 0),
            raw_json=parsed,
            model=self._model,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            agrees_with_local=parsed.get('agrees_with_local', True),
            corrections_made=parsed.get('corrections_made', []),
        )

    def reflect_with_mock(
        self,
        setup: Any,
        local_result: LocalLLMResult,
        mock_response: dict[str, Any]
    ) -> ReflectionResult:
        """
        Reflect with a mocked GPT response (for testing).
        
        Args:
            setup: Original SetupCandidate.
            local_result: LocalLLMResult to reflect on.
            mock_response: Mock response dict.
            
        Returns:
            ReflectionResult: Reflection result with mock data.
        """
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        return ReflectionResult(
            id=result_id,
            created_at=now,
            setup_id=setup.id,
            local_llm_result_id=local_result.id,
            corrected_direction=mock_response.get('corrected_direction'),
            corrected_sl=mock_response.get('corrected_sl'),
            corrected_tp=mock_response.get('corrected_tp'),
            corrected_size=mock_response.get('corrected_size'),
            reason=mock_response.get('reason'),
            confidence=mock_response.get('confidence', 0),
            raw_json=mock_response,
            model=self._model,
            tokens_used=0,
            latency_ms=0,
            agrees_with_local=mock_response.get('agrees_with_local', True),
            corrections_made=mock_response.get('corrections_made', []),
        )
