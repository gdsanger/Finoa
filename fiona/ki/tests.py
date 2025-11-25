"""
Tests for Fiona KI Layer.

Tests for:
- LocalLLMResult model
- ReflectionResult model  
- KiEvaluationResult model
- LocalLLMEvaluator
- GPTReflectionEvaluator
- KiOrchestrator
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from fiona.ki.models import LocalLLMResult, ReflectionResult, KiEvaluationResult
from fiona.ki.local_evaluator import LocalLLMEvaluator
from fiona.ki.reflection_evaluator import GPTReflectionEvaluator
from fiona.ki.orchestrator import KiOrchestrator

# Import SetupCandidate and related models from core
from core.services.strategy.models import (
    SetupCandidate,
    SetupKind,
    SessionPhase,
    BreakoutContext,
    EiaContext,
)


class LocalLLMResultModelTest(TestCase):
    """Tests for LocalLLMResult model."""
    
    def test_local_llm_result_creation(self):
        """Test basic LocalLLMResult creation."""
        now = datetime.now(timezone.utc)
        result = LocalLLMResult(
            id="llm-001",
            created_at=now,
            setup_id="setup-001",
            direction="LONG",
            sl=74.50,
            tp=77.50,
            size=1.0,
            reason="Strong breakout pattern",
            quality_flags={"trend_strength": 85},
            model="gemma2:12b",
            provider="LOCAL",
        )
        
        self.assertEqual(result.id, "llm-001")
        self.assertEqual(result.direction, "LONG")
        self.assertEqual(result.sl, 74.50)
        self.assertEqual(result.tp, 77.50)
        self.assertEqual(result.size, 1.0)
        self.assertTrue(result.is_valid_trade_signal())
    
    def test_local_llm_result_to_dict(self):
        """Test LocalLLMResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = LocalLLMResult(
            id="llm-002",
            created_at=now,
            setup_id="setup-002",
            direction="SHORT",
            sl=78.00,
            tp=75.00,
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "llm-002")
        self.assertEqual(data['direction'], "SHORT")
        self.assertEqual(data['sl'], 78.00)
        self.assertEqual(data['tp'], 75.00)
    
    def test_local_llm_result_from_dict(self):
        """Test LocalLLMResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "llm-003",
            'created_at': now.isoformat(),
            'setup_id': "setup-003",
            'direction': "LONG",
            'sl': 74.00,
            'tp': 78.00,
            'size': 0.5,
            'reason': "Test reason",
            'quality_flags': {"test": True},
        }
        
        result = LocalLLMResult.from_dict(data)
        
        self.assertEqual(result.id, "llm-003")
        self.assertEqual(result.direction, "LONG")
        self.assertEqual(result.sl, 74.00)
        self.assertTrue(result.is_valid_trade_signal())
    
    def test_local_llm_result_invalid_signal(self):
        """Test is_valid_trade_signal() with invalid data."""
        result = LocalLLMResult(
            id="llm-004",
            created_at=datetime.now(timezone.utc),
            setup_id="setup-004",
            direction="NO_TRADE",
        )
        
        self.assertFalse(result.is_valid_trade_signal())
        
        # Also test with missing SL/TP
        result2 = LocalLLMResult(
            id="llm-005",
            created_at=datetime.now(timezone.utc),
            setup_id="setup-005",
            direction="LONG",
            sl=74.00,
            tp=None,  # Missing TP
        )
        
        self.assertFalse(result2.is_valid_trade_signal())


class ReflectionResultModelTest(TestCase):
    """Tests for ReflectionResult model."""
    
    def test_reflection_result_creation(self):
        """Test basic ReflectionResult creation."""
        now = datetime.now(timezone.utc)
        result = ReflectionResult(
            id="ref-001",
            created_at=now,
            setup_id="setup-001",
            local_llm_result_id="llm-001",
            corrected_direction=None,
            corrected_sl=None,
            corrected_tp=None,
            reason="Analysis confirmed",
            confidence=85.0,
            agrees_with_local=True,
            corrections_made=[],
        )
        
        self.assertEqual(result.id, "ref-001")
        self.assertEqual(result.confidence, 85.0)
        self.assertTrue(result.agrees_with_local)
        self.assertEqual(result.signal_strength, "strong_signal")
    
    def test_reflection_result_signal_strength(self):
        """Test signal strength classification."""
        now = datetime.now(timezone.utc)
        
        # Strong signal (>= 80)
        strong = ReflectionResult(
            id="ref-strong",
            created_at=now,
            setup_id="setup-001",
            local_llm_result_id="llm-001",
            confidence=80.0,
        )
        self.assertEqual(strong.signal_strength, "strong_signal")
        
        # Weak signal (60-79)
        weak = ReflectionResult(
            id="ref-weak",
            created_at=now,
            setup_id="setup-002",
            local_llm_result_id="llm-002",
            confidence=65.0,
        )
        self.assertEqual(weak.signal_strength, "weak_signal")
        
        # No trade (< 60)
        no_trade = ReflectionResult(
            id="ref-no-trade",
            created_at=now,
            setup_id="setup-003",
            local_llm_result_id="llm-003",
            confidence=50.0,
        )
        self.assertEqual(no_trade.signal_strength, "no_trade")
    
    def test_reflection_result_to_dict(self):
        """Test ReflectionResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = ReflectionResult(
            id="ref-002",
            created_at=now,
            setup_id="setup-002",
            local_llm_result_id="llm-002",
            corrected_direction="SHORT",
            corrected_sl=78.50,
            confidence=75.0,
            corrections_made=["Corrected direction"],
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "ref-002")
        self.assertEqual(data['corrected_direction'], "SHORT")
        self.assertEqual(data['corrected_sl'], 78.50)
        self.assertEqual(data['confidence'], 75.0)
        self.assertEqual(len(data['corrections_made']), 1)
    
    def test_reflection_result_from_dict(self):
        """Test ReflectionResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "ref-003",
            'created_at': now.isoformat(),
            'setup_id': "setup-003",
            'local_llm_result_id': "llm-003",
            'corrected_direction': None,
            'confidence': 90.0,
            'agrees_with_local': True,
            'corrections_made': [],
        }
        
        result = ReflectionResult.from_dict(data)
        
        self.assertEqual(result.id, "ref-003")
        self.assertEqual(result.confidence, 90.0)
        self.assertTrue(result.agrees_with_local)
    
    def test_reflection_result_has_corrections(self):
        """Test has_corrections() method."""
        now = datetime.now(timezone.utc)
        
        # No corrections
        no_corrections = ReflectionResult(
            id="ref-no-corr",
            created_at=now,
            setup_id="setup-001",
            local_llm_result_id="llm-001",
            corrections_made=[],
        )
        self.assertFalse(no_corrections.has_corrections())
        
        # With corrections
        with_corrections = ReflectionResult(
            id="ref-with-corr",
            created_at=now,
            setup_id="setup-002",
            local_llm_result_id="llm-002",
            corrections_made=["Adjusted SL", "Adjusted TP"],
        )
        self.assertTrue(with_corrections.has_corrections())


class KiEvaluationResultModelTest(TestCase):
    """Tests for KiEvaluationResult model."""
    
    def test_ki_evaluation_result_creation(self):
        """Test basic KiEvaluationResult creation."""
        now = datetime.now(timezone.utc)
        result = KiEvaluationResult(
            id="ki-001",
            setup_id="setup-001",
            timestamp=now,
            llm_direction="LONG",
            llm_sl=74.50,
            llm_tp=77.50,
            llm_size=1.0,
            reflection_score=85.0,
            final_direction="LONG",
            final_sl=74.50,
            final_tp=77.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )
        
        self.assertEqual(result.id, "ki-001")
        self.assertEqual(result.final_direction, "LONG")
        self.assertEqual(result.signal_strength, "strong_signal")
        self.assertTrue(result.is_tradeable())
    
    def test_ki_evaluation_result_to_dict(self):
        """Test KiEvaluationResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = KiEvaluationResult(
            id="ki-002",
            setup_id="setup-002",
            timestamp=now,
            llm_direction="SHORT",
            final_direction="SHORT",
            final_sl=78.00,
            final_tp=75.00,
            signal_strength="weak_signal",
            reflection_score=70.0,
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "ki-002")
        self.assertEqual(data['final_direction'], "SHORT")
        self.assertEqual(data['signal_strength'], "weak_signal")
    
    def test_ki_evaluation_result_from_dict(self):
        """Test KiEvaluationResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "ki-003",
            'setup_id': "setup-003",
            'timestamp': now.isoformat(),
            'llm_direction': "LONG",
            'final_direction': "LONG",
            'final_sl': 74.00,
            'final_tp': 78.00,
            'signal_strength': "strong_signal",
            'reflection_score': 85.0,
        }
        
        result = KiEvaluationResult.from_dict(data)
        
        self.assertEqual(result.id, "ki-003")
        self.assertEqual(result.final_direction, "LONG")
        self.assertTrue(result.is_tradeable())
    
    def test_ki_evaluation_result_is_tradeable(self):
        """Test is_tradeable() method."""
        now = datetime.now(timezone.utc)
        
        # Tradeable
        tradeable = KiEvaluationResult(
            id="ki-tradeable",
            setup_id="setup-001",
            timestamp=now,
            signal_strength="strong_signal",
        )
        self.assertTrue(tradeable.is_tradeable())
        
        # Not tradeable
        not_tradeable = KiEvaluationResult(
            id="ki-not-tradeable",
            setup_id="setup-002",
            timestamp=now,
            signal_strength="no_trade",
        )
        self.assertFalse(not_tradeable.is_tradeable())
    
    def test_ki_evaluation_result_get_trade_parameters(self):
        """Test get_trade_parameters() method."""
        now = datetime.now(timezone.utc)
        
        # With tradeable signal
        result = KiEvaluationResult(
            id="ki-params",
            setup_id="setup-001",
            timestamp=now,
            final_direction="LONG",
            final_sl=74.50,
            final_tp=77.50,
            final_size=1.0,
            signal_strength="strong_signal",
            reflection_score=85.0,
        )
        
        params = result.get_trade_parameters()
        
        self.assertIsNotNone(params)
        self.assertEqual(params['direction'], "LONG")
        self.assertEqual(params['sl'], 74.50)
        self.assertEqual(params['tp'], 77.50)
        self.assertEqual(params['confidence'], 85.0)
        
        # Without tradeable signal
        no_trade = KiEvaluationResult(
            id="ki-no-params",
            setup_id="setup-002",
            timestamp=now,
            signal_strength="no_trade",
        )
        
        self.assertIsNone(no_trade.get_trade_parameters())


class LocalLLMEvaluatorTest(TestCase):
    """Tests for LocalLLMEvaluator."""
    
    def _create_test_setup(self) -> SetupCandidate:
        """Create a test SetupCandidate."""
        now = datetime.now(timezone.utc)
        breakout = BreakoutContext(
            range_high=77.00,
            range_low=75.00,
            range_height=2.00,
            trigger_price=77.10,
            direction="LONG",
            atr=0.45,
        )
        
        return SetupCandidate(
            id="setup-test-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=77.10,
            direction="LONG",
            breakout=breakout,
        )
    
    def test_local_evaluator_creation(self):
        """Test LocalLLMEvaluator instantiation."""
        evaluator = LocalLLMEvaluator()
        
        self.assertIsNotNone(evaluator)
        self.assertEqual(evaluator._model, "gemma2:12b")
        self.assertEqual(evaluator._provider, "LOCAL")
        self.assertEqual(evaluator._agent_name, "trading-evaluation-agent")
    
    def test_local_evaluator_custom_params(self):
        """Test LocalLLMEvaluator with custom parameters."""
        mock_client = MagicMock()
        evaluator = LocalLLMEvaluator(
            llm_client=mock_client,
            model="qwen:14b",
            provider="QWEN",
        )
        
        self.assertEqual(evaluator._model, "qwen:14b")
        self.assertEqual(evaluator._provider, "QWEN")
    
    def test_local_evaluator_custom_agent_name(self):
        """Test LocalLLMEvaluator with custom agent name."""
        evaluator = LocalLLMEvaluator(
            model="llama:7b",
            provider="ollama",
            agent_name="custom-trading-agent",
        )
        
        self.assertEqual(evaluator._agent_name, "custom-trading-agent")
        self.assertEqual(evaluator._model, "llama:7b")
        self.assertEqual(evaluator._provider, "ollama")
    
    def test_local_evaluator_evaluate_with_mock(self):
        """Test evaluate_with_mock() method."""
        evaluator = LocalLLMEvaluator()
        setup = self._create_test_setup()
        
        mock_response = {
            "direction": "LONG",
            "sl": 75.00,
            "tp": 79.00,
            "size": 1.0,
            "reason": "Strong breakout above range",
            "quality_flags": {"trend_strength": 80},
        }
        
        result = evaluator.evaluate_with_mock(setup, mock_response)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, "LONG")
        self.assertEqual(result.sl, 75.00)
        self.assertEqual(result.tp, 79.00)
        self.assertEqual(result.setup_id, "setup-test-001")
        self.assertTrue(result.is_valid_trade_signal())
    
    def test_local_evaluator_build_prompt(self):
        """Test prompt building."""
        evaluator = LocalLLMEvaluator()
        setup = self._create_test_setup()
        
        prompt = evaluator._build_prompt(setup)
        
        self.assertIn("CC.D.CL.UNC.IP", prompt)
        self.assertIn("BREAKOUT", prompt)
        self.assertIn("LONDON_CORE", prompt)
        self.assertIn("77.1", str(prompt))  # Float renders as 77.1, not 77.10
    
    def test_local_evaluator_build_prompt_kigate_format(self):
        """Test that prompt follows KIGate message format."""
        evaluator = LocalLLMEvaluator()
        setup = self._create_test_setup()
        
        prompt = evaluator._build_prompt(setup)
        
        # Verify KIGate message format sections
        self.assertIn("## Setup-Daten", prompt)
        self.assertIn("- Epic:", prompt)
        self.assertIn("- Setup-Art:", prompt)
        self.assertIn("- Marktphase:", prompt)
        self.assertIn("- Referenzpreis:", prompt)
        self.assertIn("- Aktuelle Richtung:", prompt)
        self.assertIn("## Breakout-Kontext (falls vorhanden)", prompt)
        self.assertIn("## EIA-Kontext (falls vorhanden)", prompt)
        self.assertIn("## Qualitäts-Flags", prompt)
        self.assertIn("## ATR/Range-Informationen", prompt)
    
    def test_local_evaluator_parse_json_response(self):
        """Test JSON response parsing."""
        evaluator = LocalLLMEvaluator()
        
        # Test with clean JSON
        clean_json = '{"direction": "LONG", "sl": 74.50, "tp": 77.50, "size": 1.0, "reason": "Test"}'
        parsed = evaluator._parse_llm_response(clean_json)
        self.assertEqual(parsed['direction'], "LONG")
        self.assertEqual(parsed['sl'], 74.50)
        
        # Test with markdown code blocks
        markdown_json = '''```json
{"direction": "SHORT", "sl": 78.00, "tp": 75.00}
```'''
        parsed = evaluator._parse_llm_response(markdown_json)
        self.assertEqual(parsed['direction'], "SHORT")
    
    @patch('fiona.ki.local_evaluator._execute_agent')
    @patch('fiona.ki.local_evaluator._kigate_available', True)
    def test_local_evaluator_kigate_integration(self, mock_execute_agent):
        """Test KIGate integration with trading-evaluation-agent."""
        # Mock KIGate response
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.data = {
            'result': '{"direction": "LONG", "sl": 75.00, "tp": 79.00, "size": 1.0, "reason": "Strong breakout"}',
            'tokens_used': 150,
        }
        mock_execute_agent.return_value = mock_response
        
        evaluator = LocalLLMEvaluator()
        setup = self._create_test_setup()
        
        result = evaluator.evaluate(setup)
        
        # Verify execute_agent was called with correct parameters
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        
        self.assertEqual(call_kwargs['agent_name'], 'trading-evaluation-agent')
        self.assertEqual(call_kwargs['model'], 'gemma2:12b')
        self.assertEqual(call_kwargs['provider'], 'LOCAL')
        self.assertEqual(call_kwargs['temperature'], 0.3)
        self.assertIn('## Setup-Daten', call_kwargs['prompt'])
        
        # Verify result
        self.assertEqual(result.direction, "LONG")
        self.assertEqual(result.sl, 75.00)
        self.assertEqual(result.tp, 79.00)


class GPTReflectionEvaluatorTest(TestCase):
    """Tests for GPTReflectionEvaluator."""
    
    def _create_test_setup(self) -> SetupCandidate:
        """Create a test SetupCandidate."""
        now = datetime.now(timezone.utc)
        return SetupCandidate(
            id="setup-ref-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.US_CORE,
            reference_price=76.50,
            direction="LONG",
        )
    
    def _create_test_local_result(self, setup_id: str) -> LocalLLMResult:
        """Create a test LocalLLMResult."""
        return LocalLLMResult(
            id="llm-ref-001",
            created_at=datetime.now(timezone.utc),
            setup_id=setup_id,
            direction="LONG",
            sl=75.50,
            tp=78.50,
            size=1.0,
            reason="Breakout confirmed",
        )
    
    def test_reflection_evaluator_creation(self):
        """Test GPTReflectionEvaluator instantiation."""
        evaluator = GPTReflectionEvaluator()
        
        self.assertIsNotNone(evaluator)
        self.assertEqual(evaluator._model, "gpt-4o")
    
    def test_reflection_evaluator_custom_model(self):
        """Test GPTReflectionEvaluator with custom model."""
        evaluator = GPTReflectionEvaluator(model="gpt-4-1106-preview")
        
        self.assertEqual(evaluator._model, "gpt-4-1106-preview")
    
    def test_reflection_evaluator_reflect_with_mock(self):
        """Test reflect_with_mock() method."""
        evaluator = GPTReflectionEvaluator()
        setup = self._create_test_setup()
        local_result = self._create_test_local_result(setup.id)
        
        mock_response = {
            "corrected_direction": None,
            "corrected_sl": None,
            "corrected_tp": None,
            "reason": "Analysis confirmed, parameters appropriate",
            "confidence": 85.0,
            "agrees_with_local": True,
            "corrections_made": [],
        }
        
        result = evaluator.reflect_with_mock(setup, local_result, mock_response)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.confidence, 85.0)
        self.assertTrue(result.agrees_with_local)
        self.assertEqual(result.signal_strength, "strong_signal")
        self.assertFalse(result.has_corrections())
    
    def test_reflection_evaluator_with_corrections(self):
        """Test reflection with corrections."""
        evaluator = GPTReflectionEvaluator()
        setup = self._create_test_setup()
        local_result = self._create_test_local_result(setup.id)
        
        mock_response = {
            "corrected_direction": None,
            "corrected_sl": 76.00,  # Tighter SL
            "corrected_tp": 79.00,  # Extended TP
            "reason": "SL too wide, TP could be extended",
            "confidence": 75.0,
            "agrees_with_local": False,
            "corrections_made": ["Adjusted SL to be tighter", "Extended TP target"],
        }
        
        result = evaluator.reflect_with_mock(setup, local_result, mock_response)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.corrected_sl, 76.00)
        self.assertEqual(result.corrected_tp, 79.00)
        self.assertFalse(result.agrees_with_local)
        self.assertTrue(result.has_corrections())
        self.assertEqual(result.signal_strength, "weak_signal")

    def test_reflection_evaluator_kigate_config(self):
        """Test GPTReflectionEvaluator with custom KIGate configuration."""
        evaluator = GPTReflectionEvaluator(
            agent_name="custom-agent",
            provider="claude",
            user_id="custom-user"
        )
        
        self.assertEqual(evaluator._agent_name, "custom-agent")
        self.assertEqual(evaluator._provider, "claude")
        self.assertEqual(evaluator._user_id, "custom-user")
        self.assertEqual(evaluator._model, "gpt-4o")  # Default model
    
    def test_reflection_evaluator_default_kigate_config(self):
        """Test GPTReflectionEvaluator default KIGate configuration."""
        from fiona.ki.reflection_evaluator import (
            KIGATE_AGENT_NAME,
            KIGATE_PROVIDER,
            KIGATE_USER_ID
        )
        
        evaluator = GPTReflectionEvaluator()
        
        self.assertEqual(evaluator._agent_name, KIGATE_AGENT_NAME)
        self.assertEqual(evaluator._provider, KIGATE_PROVIDER)
        self.assertEqual(evaluator._user_id, KIGATE_USER_ID)
        self.assertEqual(KIGATE_AGENT_NAME, "trading-reflection-agent")
        self.assertEqual(KIGATE_PROVIDER, "openai")
    
    def test_reflection_evaluator_parse_json_response(self):
        """Test JSON response parsing."""
        evaluator = GPTReflectionEvaluator()
        
        # Test with clean JSON
        clean_json = '{"corrected_direction": null, "confidence": 85, "agrees_with_local": true}'
        parsed = evaluator._parse_gpt_response(clean_json)
        self.assertIsNone(parsed['corrected_direction'])
        self.assertEqual(parsed['confidence'], 85)
        self.assertTrue(parsed['agrees_with_local'])
        
        # Test with markdown code blocks
        markdown_json = '''```json
{"corrected_direction": "SHORT", "corrected_sl": 78.00, "confidence": 75}
```'''
        parsed = evaluator._parse_gpt_response(markdown_json)
        self.assertEqual(parsed['corrected_direction'], "SHORT")
        self.assertEqual(parsed['corrected_sl'], 78.00)
        self.assertEqual(parsed['confidence'], 75)
    
    def test_reflection_evaluator_build_prompt(self):
        """Test prompt building for KIGate."""
        evaluator = GPTReflectionEvaluator()
        setup = self._create_test_setup()
        local_result = self._create_test_local_result(setup.id)
        
        prompt = evaluator._build_prompt(setup, local_result)
        
        # Verify prompt contains expected elements
        self.assertIn("CC.D.CL.UNC.IP", prompt)  # Epic
        self.assertIn("BREAKOUT", prompt)  # Setup kind
        self.assertIn("LONG", prompt)  # Direction
        self.assertIn("75.5", str(prompt))  # SL value


class KiOrchestratorTest(TestCase):
    """Tests for KiOrchestrator."""
    
    def _create_test_setup(self) -> SetupCandidate:
        """Create a test SetupCandidate."""
        now = datetime.now(timezone.utc)
        breakout = BreakoutContext(
            range_high=77.00,
            range_low=75.00,
            range_height=2.00,
            trigger_price=77.10,
            direction="LONG",
            atr=0.45,
        )
        
        return SetupCandidate(
            id="setup-orch-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=77.10,
            direction="LONG",
            breakout=breakout,
        )
    
    def test_orchestrator_creation(self):
        """Test KiOrchestrator instantiation."""
        orchestrator = KiOrchestrator()
        
        self.assertIsNotNone(orchestrator)
        self.assertIsNotNone(orchestrator.get_local_evaluator())
        self.assertIsNotNone(orchestrator.get_reflection_evaluator())
    
    def test_orchestrator_custom_evaluators(self):
        """Test KiOrchestrator with custom evaluators."""
        local_eval = LocalLLMEvaluator(model="qwen:14b")
        reflection_eval = GPTReflectionEvaluator(model="gpt-4-1106-preview")
        
        orchestrator = KiOrchestrator(
            local_evaluator=local_eval,
            reflection_evaluator=reflection_eval,
        )
        
        self.assertEqual(orchestrator.get_local_evaluator()._model, "qwen:14b")
        self.assertEqual(orchestrator.get_reflection_evaluator()._model, "gpt-4-1106-preview")
    
    def test_orchestrator_evaluate_with_mock_strong_signal(self):
        """Test full evaluation with mocked responses - strong signal."""
        orchestrator = KiOrchestrator()
        setup = self._create_test_setup()
        
        mock_local = {
            "direction": "LONG",
            "sl": 75.00,
            "tp": 79.00,
            "size": 1.0,
            "reason": "Strong breakout above range",
            "quality_flags": {"trend_strength": 85},
        }
        
        mock_reflection = {
            "corrected_direction": None,
            "corrected_sl": None,
            "corrected_tp": None,
            "reason": "Analysis confirmed",
            "confidence": 85.0,
            "agrees_with_local": True,
            "corrections_made": [],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.final_direction, "LONG")
        self.assertEqual(result.final_sl, 75.00)
        self.assertEqual(result.final_tp, 79.00)
        self.assertEqual(result.signal_strength, "strong_signal")
        self.assertTrue(result.is_tradeable())
    
    def test_orchestrator_evaluate_with_mock_weak_signal(self):
        """Test full evaluation with mocked responses - weak signal."""
        orchestrator = KiOrchestrator()
        setup = self._create_test_setup()
        
        mock_local = {
            "direction": "LONG",
            "sl": 75.00,
            "tp": 78.00,
            "size": 1.0,
            "reason": "Possible breakout",
        }
        
        mock_reflection = {
            "corrected_direction": None,
            "corrected_sl": 75.50,  # Correction
            "corrected_tp": None,
            "reason": "SL should be tighter",
            "confidence": 70.0,  # Between 60-80
            "agrees_with_local": False,
            "corrections_made": ["Adjusted SL"],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        self.assertEqual(result.signal_strength, "weak_signal")
        self.assertEqual(result.final_sl, 75.50)  # Uses corrected value
        self.assertEqual(result.final_tp, 78.00)  # Uses local value
        self.assertTrue(result.is_tradeable())
    
    def test_orchestrator_evaluate_with_mock_no_trade(self):
        """Test full evaluation with mocked responses - no trade."""
        orchestrator = KiOrchestrator()
        setup = self._create_test_setup()
        
        mock_local = {
            "direction": "LONG",
            "sl": 75.00,
            "tp": 78.00,
            "size": 1.0,
            "reason": "Weak setup",
        }
        
        mock_reflection = {
            "corrected_direction": "NO_TRADE",
            "reason": "Setup too risky, low confidence",
            "confidence": 45.0,  # Below 60
            "agrees_with_local": False,
            "corrections_made": ["Changed to NO_TRADE"],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        self.assertEqual(result.signal_strength, "no_trade")
        self.assertEqual(result.final_direction, "NO_TRADE")
        self.assertFalse(result.is_tradeable())
    
    def test_orchestrator_signal_strength_classification(self):
        """Test signal strength classification logic."""
        orchestrator = KiOrchestrator()
        
        # Test boundary conditions
        self.assertEqual(orchestrator._determine_signal_strength(100), "strong_signal")
        self.assertEqual(orchestrator._determine_signal_strength(80), "strong_signal")
        self.assertEqual(orchestrator._determine_signal_strength(79.9), "weak_signal")
        self.assertEqual(orchestrator._determine_signal_strength(60), "weak_signal")
        self.assertEqual(orchestrator._determine_signal_strength(59.9), "no_trade")
        self.assertEqual(orchestrator._determine_signal_strength(0), "no_trade")
    
    def test_orchestrator_merge_with_corrections(self):
        """Test that corrections are properly merged."""
        orchestrator = KiOrchestrator()
        setup = self._create_test_setup()
        
        mock_local = {
            "direction": "LONG",
            "sl": 74.00,
            "tp": 78.00,
            "size": 1.5,
            "reason": "Initial analysis",
        }
        
        mock_reflection = {
            "corrected_direction": None,  # No change
            "corrected_sl": 75.00,  # Tighter SL
            "corrected_tp": 79.00,  # Extended TP
            "corrected_size": 1.0,  # Reduced size
            "reason": "Adjusted risk parameters",
            "confidence": 82.0,
            "corrections_made": ["SL", "TP", "Size"],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        # Final values should use corrections where present
        self.assertEqual(result.final_direction, "LONG")  # From local
        self.assertEqual(result.final_sl, 75.00)  # Corrected
        self.assertEqual(result.final_tp, 79.00)  # Corrected
        self.assertEqual(result.final_size, 1.0)  # Corrected
        
        # Local values should be preserved
        self.assertEqual(result.llm_direction, "LONG")
        self.assertEqual(result.llm_sl, 74.00)
        self.assertEqual(result.llm_tp, 78.00)
        self.assertEqual(result.llm_size, 1.5)
        
        # Reflection values should be stored
        self.assertEqual(result.reflection_sl, 75.00)
        self.assertEqual(result.reflection_tp, 79.00)
        self.assertEqual(result.reflection_size, 1.0)


class KiOrchestratorIntegrationTest(TestCase):
    """Integration tests for KiOrchestrator pipeline."""
    
    def _create_eia_setup(self) -> SetupCandidate:
        """Create an EIA setup for testing."""
        now = datetime.now(timezone.utc)
        eia = EiaContext(
            eia_timestamp=now,
            first_impulse_direction="LONG",
            impulse_range_high=78.00,
            impulse_range_low=76.00,
            atr=0.50,
        )
        
        return SetupCandidate(
            id="setup-eia-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=77.50,
            direction="SHORT",
            eia=eia,
        )
    
    def test_full_pipeline_breakout_setup(self):
        """Test full pipeline with breakout setup."""
        orchestrator = KiOrchestrator()
        
        now = datetime.now(timezone.utc)
        breakout = BreakoutContext(
            range_high=77.00,
            range_low=75.00,
            range_height=2.00,
            trigger_price=77.10,
            direction="LONG",
            atr=0.45,
        )
        setup = SetupCandidate(
            id="pipeline-breakout-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=77.10,
            direction="LONG",
            breakout=breakout,
        )
        
        mock_local = {
            "direction": "LONG",
            "sl": 75.00,
            "tp": 79.10,
            "size": 1.0,
            "reason": "Clean breakout above range, ATR-based SL",
            "quality_flags": {"trend_strength": 85, "setup_quality": 80},
        }
        
        mock_reflection = {
            "corrected_direction": None,
            "corrected_sl": None,
            "corrected_tp": None,
            "reason": "Analysis confirmed, good risk/reward",
            "confidence": 88.0,
            "agrees_with_local": True,
            "corrections_made": [],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        # Verify complete result
        self.assertEqual(result.setup_id, "pipeline-breakout-001")
        self.assertEqual(result.final_direction, "LONG")
        self.assertEqual(result.final_sl, 75.00)
        self.assertEqual(result.final_tp, 79.10)
        self.assertEqual(result.signal_strength, "strong_signal")
        self.assertEqual(result.reflection_score, 88.0)
        
        # Verify raw data is preserved
        self.assertIsNotNone(result.raw_local)
        self.assertIsNotNone(result.raw_reflection)
        self.assertEqual(result.raw_local['direction'], "LONG")
        self.assertEqual(result.raw_reflection['confidence'], 88.0)
    
    def test_full_pipeline_eia_setup(self):
        """Test full pipeline with EIA setup."""
        orchestrator = KiOrchestrator()
        setup = self._create_eia_setup()
        
        mock_local = {
            "direction": "SHORT",
            "sl": 78.50,
            "tp": 75.50,
            "size": 0.5,
            "reason": "EIA reversion after impulse exhaustion",
            "quality_flags": {"setup_quality": 75},
        }
        
        mock_reflection = {
            "corrected_direction": None,
            "corrected_sl": 78.25,  # Slightly tighter
            "corrected_tp": None,
            "reason": "SL can be tighter based on impulse high",
            "confidence": 72.0,
            "agrees_with_local": True,
            "corrections_made": ["Adjusted SL"],
        }
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        self.assertEqual(result.setup_id, "setup-eia-001")
        self.assertEqual(result.final_direction, "SHORT")
        self.assertEqual(result.final_sl, 78.25)  # Corrected
        self.assertEqual(result.final_tp, 75.50)  # From local
        self.assertEqual(result.signal_strength, "weak_signal")
    
    def test_roundtrip_serialization(self):
        """Test that results can be serialized and deserialized."""
        orchestrator = KiOrchestrator()
        
        now = datetime.now(timezone.utc)
        setup = SetupCandidate(
            id="roundtrip-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.US_CORE,
            reference_price=76.00,
            direction="LONG",
        )
        
        mock_local = {"direction": "LONG", "sl": 74.50, "tp": 78.00, "size": 1.0}
        mock_reflection = {"confidence": 85.0, "agrees_with_local": True}
        
        result = orchestrator.evaluate_with_mock(setup, mock_local, mock_reflection)
        
        # Serialize and deserialize
        data = result.to_dict()
        restored = KiEvaluationResult.from_dict(data)
        
        self.assertEqual(restored.id, result.id)
        self.assertEqual(restored.setup_id, result.setup_id)
        self.assertEqual(restored.final_direction, result.final_direction)
        self.assertEqual(restored.final_sl, result.final_sl)
        self.assertEqual(restored.signal_strength, result.signal_strength)
