"""
Tests for the Fiona Backend API Layer.

These tests cover:
- DTO models and serialization
- SignalService and TradeService
- API endpoints
- Integration tests for full workflows
"""
from datetime import datetime, timezone
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client
from django.urls import reverse

from core.services.execution import ExecutionService, ExecutionState
from core.services.execution.execution_service import ExecutionError
from core.services.execution.models import ExecutionSession
from core.services.broker.models import (
    OrderRequest,
    OrderResult,
    OrderDirection,
    OrderStatus,
    SymbolPrice,
)
from core.services.strategy.models import (
    SetupCandidate,
    SetupKind,
    SessionPhase,
    BreakoutContext,
)
from core.services.risk.models import RiskEvaluationResult
from core.services.weaviate.weaviate_service import WeaviateService, InMemoryWeaviateClient
from core.services.weaviate.models import (
    ExecutedTrade,
    ShadowTrade,
    TradeDirection,
    TradeStatus,
)
from fiona.ki.models.ki_evaluation_result import KiEvaluationResult

from fiona.api.dtos import (
    SignalSummaryDTO,
    SignalDetailDTO,
    TradeHistoryDTO,
    TradeActionResponse,
    KiInfoDTO,
    RiskInfoDTO,
    RiskEvaluationDTO,
    ExecutionStateDTO,
    AdjustedOrderDTO,
    TradeRequestDTO,
)
from fiona.api.services import SignalService, TradeService
from fiona.api import views


# ============================================================================
# DTO Tests
# ============================================================================

class KiInfoDTOTest(TestCase):
    """Tests for KiInfoDTO."""

    def test_to_dict(self):
        """Test KiInfoDTO serialization."""
        ki_info = KiInfoDTO(
            finalDirection="LONG",
            finalSl=83.70,
            finalTp=85.40,
            finalSize=1.0,
            confidence=86.5,
        )
        
        result = ki_info.to_dict()
        
        self.assertEqual(result['finalDirection'], "LONG")
        self.assertEqual(result['finalSl'], 83.70)
        self.assertEqual(result['finalTp'], 85.40)
        self.assertEqual(result['finalSize'], 1.0)
        self.assertEqual(result['confidence'], 86.5)

    def test_default_values(self):
        """Test default values."""
        ki_info = KiInfoDTO()
        
        self.assertIsNone(ki_info.finalDirection)
        self.assertIsNone(ki_info.finalSl)
        self.assertEqual(ki_info.confidence, 0.0)


class RiskInfoDTOTest(TestCase):
    """Tests for RiskInfoDTO."""

    def test_to_dict(self):
        """Test RiskInfoDTO serialization."""
        risk_info = RiskInfoDTO(
            allowed=True,
            reason="Risk < 1% equity",
        )
        
        result = risk_info.to_dict()
        
        self.assertTrue(result['allowed'])
        self.assertEqual(result['reason'], "Risk < 1% equity")


class SignalSummaryDTOTest(TestCase):
    """Tests for SignalSummaryDTO."""

    def test_to_dict(self):
        """Test SignalSummaryDTO serialization."""
        signal = SignalSummaryDTO(
            id="signal-123",
            epic="OIL",
            setupKind="BREAKOUT",
            phase="LONDON_CORE",
            createdAt="2025-05-01T12:34:56Z",
            direction="LONG",
            referencePrice=84.12,
            ki=KiInfoDTO(
                finalDirection="LONG",
                finalSl=83.70,
                finalTp=85.40,
                finalSize=1.0,
                confidence=86.5,
            ),
            risk=RiskInfoDTO(
                allowed=True,
                reason="Risk < 1% equity",
            ),
        )
        
        result = signal.to_dict()
        
        self.assertEqual(result['id'], "signal-123")
        self.assertEqual(result['epic'], "OIL")
        self.assertEqual(result['setupKind'], "BREAKOUT")
        self.assertEqual(result['phase'], "LONDON_CORE")
        self.assertEqual(result['direction'], "LONG")
        self.assertEqual(result['referencePrice'], 84.12)
        self.assertIn('ki', result)
        self.assertIn('risk', result)
        self.assertEqual(result['ki']['finalDirection'], "LONG")
        self.assertTrue(result['risk']['allowed'])


class TradeActionResponseTest(TestCase):
    """Tests for TradeActionResponse."""

    def test_success_response(self):
        """Test successful response serialization."""
        response = TradeActionResponse(
            success=True,
            message="Live trade opened successfully.",
            tradeId="trade-123",
        )
        
        result = response.to_dict()
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], "Live trade opened successfully.")
        self.assertEqual(result['tradeId'], "trade-123")
        self.assertNotIn('error', result)

    def test_error_response(self):
        """Test error response serialization."""
        response = TradeActionResponse(
            success=False,
            error="Trade not allowed by Risk Engine.",
        )
        
        result = response.to_dict()
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], "Trade not allowed by Risk Engine.")
        self.assertNotIn('message', result)


class TradeRequestDTOTest(TestCase):
    """Tests for TradeRequestDTO."""

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            'signalId': 'signal-123',
            'reason': 'User rejected signal.',
        }
        
        request = TradeRequestDTO.from_dict(data)
        
        self.assertEqual(request.signalId, 'signal-123')
        self.assertEqual(request.reason, 'User rejected signal.')

    def test_from_dict_minimal(self):
        """Test creating with minimal data."""
        data = {'signalId': 'signal-123'}
        
        request = TradeRequestDTO.from_dict(data)
        
        self.assertEqual(request.signalId, 'signal-123')
        self.assertIsNone(request.reason)


# ============================================================================
# SignalService Tests
# ============================================================================

class SignalServiceTest(TestCase):
    """Tests for SignalService."""

    def setUp(self):
        """Set up test fixtures."""
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.execution = ExecutionService(
            broker_service=None,
            weaviate_service=self.weaviate,
        )
        self.service = SignalService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        
        # Create a standard setup candidate
        self.setup = SetupCandidate(
            id="setup-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
            breakout=BreakoutContext(
                range_high=75.50,
                range_low=74.50,
                range_height=1.00,
                trigger_price=75.55,
                direction="LONG",
            ),
        )
        
        # Create a KI evaluation
        self.ki_eval = KiEvaluationResult(
            id="ki-123",
            setup_id="setup-123",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
            reflection_score=86.5,
        )

    def test_register_signal(self):
        """Test registering a new signal."""
        signal = self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        self.assertIsNotNone(signal)
        self.assertEqual(signal.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(signal.setupKind, "BREAKOUT")
        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.ki.finalDirection, "LONG")
        self.assertEqual(signal.ki.confidence, 86.5)
        self.assertTrue(signal.risk.allowed)

    def test_register_signal_risk_denied(self):
        """Test registering a signal with risk denied."""
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Daily loss limit exceeded",
        )
        
        signal = self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
            risk_eval=risk_eval,
        )
        
        self.assertFalse(signal.risk.allowed)
        self.assertIn("loss limit", signal.risk.reason)

    def test_list_signals_empty(self):
        """Test listing signals when none exist."""
        signals = self.service.list_signals()
        
        self.assertEqual(len(signals), 0)

    def test_list_signals(self):
        """Test listing signals."""
        self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        signals = self.service.list_signals()
        
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].direction, "LONG")

    def test_list_signals_excludes_dropped(self):
        """Test that dropped signals are excluded by default."""
        signal = self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        # Reject the signal
        self.execution.reject_trade(signal.id)
        
        signals = self.service.list_signals()
        
        self.assertEqual(len(signals), 0)

    def test_list_signals_include_dropped(self):
        """Test including dropped signals."""
        signal = self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        # Reject the signal
        self.execution.reject_trade(signal.id)
        
        signals = self.service.list_signals(include_dropped=True)
        
        self.assertEqual(len(signals), 1)

    def test_get_signal_detail(self):
        """Test getting signal details."""
        signal = self.service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        detail = self.service.get_signal_detail(signal.id)
        
        self.assertIsNotNone(detail)
        self.assertEqual(detail.id, signal.id)
        self.assertEqual(detail.epic, "CC.D.CL.UNC.IP")
        self.assertIsNotNone(detail.setup)
        self.assertIsNotNone(detail.kiEvaluation)
        self.assertIsNotNone(detail.executionState)
        self.assertEqual(detail.executionState.status, "WAITING_FOR_USER")

    def test_get_signal_detail_not_found(self):
        """Test getting non-existent signal."""
        detail = self.service.get_signal_detail("non-existent")
        
        self.assertIsNone(detail)


# ============================================================================
# TradeService Tests
# ============================================================================

class TradeServiceTest(TestCase):
    """Tests for TradeService."""

    def setUp(self):
        """Set up test fixtures."""
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.execution = ExecutionService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
        )
        self.signal_service = SignalService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        self.trade_service = TradeService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        
        # Create a standard setup
        self.setup = SetupCandidate(
            id="setup-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        self.ki_eval = KiEvaluationResult(
            id="ki-123",
            setup_id="setup-123",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )

    def test_execute_live_trade_success(self):
        """Test successful live trade execution."""
        # Setup broker mock
        self.broker.place_order.return_value = OrderResult(
            success=True,
            deal_id="DEAL-123",
            deal_reference="REF-456",
            status=OrderStatus.OPEN,
        )
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        # Register signal
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        # Execute live trade
        result = self.trade_service.execute_live_trade(signal.id)
        
        self.assertTrue(result.success)
        self.assertIsNotNone(result.tradeId)
        self.assertEqual(result.message, "Live trade opened successfully.")

    def test_execute_live_trade_not_found(self):
        """Test live trade with non-existent signal."""
        result = self.trade_service.execute_live_trade("non-existent")
        
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_execute_shadow_trade_success(self):
        """Test successful shadow trade execution."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        # Register signal
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        # Execute shadow trade
        result = self.trade_service.execute_shadow_trade(signal.id)
        
        self.assertTrue(result.success)
        self.assertIsNotNone(result.shadowTradeId)

    def test_reject_signal_success(self):
        """Test successful signal rejection."""
        # Register signal
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        # Reject signal
        result = self.trade_service.reject_signal(signal.id, reason="Test rejection")
        
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Signal rejected.")

    def test_reject_signal_not_found(self):
        """Test rejecting non-existent signal."""
        result = self.trade_service.reject_signal("non-existent")
        
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_get_trade_history_empty(self):
        """Test getting empty trade history."""
        trades = self.trade_service.get_trade_history()
        
        self.assertEqual(len(trades), 0)

    def test_get_trade_history_with_trades(self):
        """Test getting trade history with trades."""
        # Setup broker mock
        self.broker.place_order.return_value = OrderResult(
            success=True,
            deal_id="DEAL-123",
            status=OrderStatus.OPEN,
        )
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        # Register and execute
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        self.trade_service.execute_live_trade(signal.id)
        
        # Get history
        trades = self.trade_service.get_trade_history(trade_type='live')
        
        self.assertEqual(len(trades), 1)
        self.assertFalse(trades[0].isShadow)


# ============================================================================
# API View Tests
# ============================================================================

class APIViewTest(TestCase):
    """Tests for API views."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        
        # Create mock services
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.execution = ExecutionService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
        )
        self.signal_service = SignalService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        self.trade_service = TradeService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        
        # Set mock services
        views.set_signal_service(self.signal_service)
        views.set_trade_service(self.trade_service)
        
        # Setup broker mock
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        # Create standard test data
        self.setup = SetupCandidate(
            id="setup-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        self.ki_eval = KiEvaluationResult(
            id="ki-123",
            setup_id="setup-123",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
            reflection_score=86.5,
        )

    def tearDown(self):
        """Clean up after tests."""
        # Reset global services
        views._signal_service = None
        views._trade_service = None

    def test_list_signals_empty(self):
        """Test GET /api/signals with no signals."""
        response = self.client.get('/api/signals/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('signals', data)
        self.assertEqual(len(data['signals']), 0)

    def test_list_signals_with_data(self):
        """Test GET /api/signals with signals."""
        # Register a signal
        self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        response = self.client.get('/api/signals/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['signals']), 1)
        self.assertEqual(data['signals'][0]['direction'], 'LONG')
        self.assertIn('ki', data['signals'][0])
        self.assertIn('risk', data['signals'][0])

    def test_get_signal_detail(self):
        """Test GET /api/signals/{id}."""
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        response = self.client.get(f'/api/signals/{signal.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], signal.id)
        self.assertIn('setup', data)
        self.assertIn('kiEvaluation', data)
        self.assertIn('executionState', data)

    def test_get_signal_not_found(self):
        """Test GET /api/signals/{id} with non-existent ID."""
        response = self.client.get('/api/signals/non-existent/')
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn('error', data)

    def test_execute_live_trade_success(self):
        """Test POST /api/trade/live."""
        # Setup broker mock
        self.broker.place_order.return_value = OrderResult(
            success=True,
            deal_id="DEAL-123",
            status=OrderStatus.OPEN,
        )
        
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        response = self.client.post(
            '/api/trade/live/',
            data=json.dumps({'signalId': signal.id}),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('tradeId', data)

    def test_execute_live_trade_missing_signal_id(self):
        """Test POST /api/trade/live without signalId."""
        response = self.client.post(
            '/api/trade/live/',
            data=json.dumps({}),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('error', data)

    def test_execute_shadow_trade_success(self):
        """Test POST /api/trade/shadow."""
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        response = self.client.post(
            '/api/trade/shadow/',
            data=json.dumps({'signalId': signal.id}),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('shadowTradeId', data)

    def test_reject_signal_success(self):
        """Test POST /api/trade/reject."""
        signal = self.signal_service.register_signal(
            setup=self.setup,
            ki_eval=self.ki_eval,
        )
        
        response = self.client.post(
            '/api/trade/reject/',
            data=json.dumps({
                'signalId': signal.id,
                'reason': 'User rejected.',
            }),
            content_type='application/json',
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

    def test_list_trades_empty(self):
        """Test GET /api/trades with no trades."""
        response = self.client.get('/api/trades/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 0)

    def test_list_trades_with_filter(self):
        """Test GET /api/trades with type filter."""
        response = self.client.get('/api/trades/?type=shadow&limit=10')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)


# ============================================================================
# Integration Tests
# ============================================================================

class IntegrationTest(TestCase):
    """Integration tests for the full API workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        
        # Create services
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.execution = ExecutionService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
        )
        self.signal_service = SignalService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        self.trade_service = TradeService(
            execution_service=self.execution,
            weaviate_service=self.weaviate,
        )
        
        # Set mock services
        views.set_signal_service(self.signal_service)
        views.set_trade_service(self.trade_service)
        
        # Setup broker mock
        self.broker.place_order.return_value = OrderResult(
            success=True,
            deal_id="DEAL-123",
            status=OrderStatus.OPEN,
        )
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )

    def tearDown(self):
        """Clean up after tests."""
        views._signal_service = None
        views._trade_service = None

    def test_full_live_trade_workflow(self):
        """Test complete live trade workflow via API."""
        # 1. Register a signal (simulating pipeline output)
        setup = SetupCandidate(
            id="setup-workflow",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        ki_eval = KiEvaluationResult(
            id="ki-workflow",
            setup_id="setup-workflow",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )
        
        risk_eval = RiskEvaluationResult(
            allowed=True,
            reason="Trade meets all requirements",
        )
        
        signal = self.signal_service.register_signal(setup, ki_eval, risk_eval)
        
        # 2. GET /api/signals - should show signal
        response = self.client.get('/api/signals/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['signals']), 1)
        self.assertEqual(data['signals'][0]['id'], signal.id)
        
        # 3. GET /api/signals/{id} - get details
        response = self.client.get(f'/api/signals/{signal.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['executionState']['status'], 'WAITING_FOR_USER')
        
        # 4. POST /api/trade/live - execute trade
        response = self.client.post(
            '/api/trade/live/',
            data=json.dumps({'signalId': signal.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        trade_id = data['tradeId']
        
        # 5. GET /api/signals/{id} - should show LIVE_TRADE_OPEN
        response = self.client.get(f'/api/signals/{signal.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['executionState']['status'], 'LIVE_TRADE_OPEN')
        
        # 6. GET /api/trades - should show the trade
        response = self.client.get('/api/trades/?type=live')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], trade_id)
        self.assertFalse(data[0]['isShadow'])

    def test_full_shadow_trade_workflow(self):
        """Test complete shadow trade workflow via API."""
        # Register a signal with risk denied
        setup = SetupCandidate(
            id="setup-shadow-wf",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        ki_eval = KiEvaluationResult(
            id="ki-shadow-wf",
            setup_id="setup-shadow-wf",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )
        
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Daily loss limit exceeded (3%)",
        )
        
        signal = self.signal_service.register_signal(setup, ki_eval, risk_eval)
        
        # Check signal state
        response = self.client.get(f'/api/signals/{signal.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['executionState']['status'], 'SHADOW_ONLY')
        self.assertFalse(data['riskEvaluation']['allowed'])
        
        # Execute shadow trade
        response = self.client.post(
            '/api/trade/shadow/',
            data=json.dumps({'signalId': signal.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        shadow_trade_id = data['shadowTradeId']
        
        # Verify in history
        response = self.client.get('/api/trades/?type=shadow')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], shadow_trade_id)
        self.assertTrue(data[0]['isShadow'])

    def test_reject_workflow(self):
        """Test complete reject workflow via API."""
        # Register a signal
        setup = SetupCandidate(
            id="setup-reject-wf",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        signal = self.signal_service.register_signal(setup)
        
        # Reject signal
        response = self.client.post(
            '/api/trade/reject/',
            data=json.dumps({
                'signalId': signal.id,
                'reason': 'Not interested in this setup.',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Signal should be dropped (excluded by default)
        response = self.client.get('/api/signals/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['signals']), 0)
        
        # But visible with include_dropped=true
        response = self.client.get('/api/signals/?include_dropped=true')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['signals']), 1)
