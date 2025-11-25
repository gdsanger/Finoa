"""
Fiona KI Layer v1.0

Two-stage AI pipeline for evaluating SetupCandidates:
1. LocalLLMEvaluator - Initial evaluation using local LLM (Gemma/Qwen/Llama)
2. GPTReflectionEvaluator - Validation using GPT-4.1/4o
3. KiOrchestrator - Combines both for final decision

The AI does NOT decide whether to trade - that decision rests with
the Risk Engine and the user.
"""

from .orchestrator import KiOrchestrator
from .local_evaluator import LocalLLMEvaluator
from .reflection_evaluator import GPTReflectionEvaluator
from .models import LocalLLMResult, ReflectionResult, KiEvaluationResult

__all__ = [
    'KiOrchestrator',
    'LocalLLMEvaluator',
    'GPTReflectionEvaluator',
    'LocalLLMResult',
    'ReflectionResult',
    'KiEvaluationResult',
]
