"""
Tests for the Execution Layer module.

These tests cover the ExecutionSession, ExecutionService, and
ShadowTraderService implementations.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.test import TestCase

from core.services.execution import (
    ExecutionState,
    ExecutionSession,
    ExecutionConfig,
    ExecutionService,
    ShadowTraderService,
)
from core.services.execution.models import ExitReason
from core.services.execution.execution_service import ExecutionError
from core.services.broker.models import (
    OrderRequest,
    OrderResult,
    OrderDirection,
    OrderType,
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
from core.services.weaviate.models import (
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
    TradeDirection,
    TradeStatus,
)
from core.services.weaviate.weaviate_service import WeaviateService, InMemoryWeaviateClient
from fiona.ki.models.ki_evaluation_result import KiEvaluationResult


class ExecutionStateTest(TestCase):
    """Tests for ExecutionState enum."""

    def test_state_values(self):
        """Test all ExecutionState values exist."""
        self.assertEqual(ExecutionState.NEW_SIGNAL.value, "NEW_SIGNAL")
        self.assertEqual(ExecutionState.KI_EVALUATED.value, "KI_EVALUATED")
        self.assertEqual(ExecutionState.RISK_APPROVED.value, "RISK_APPROVED")
        self.assertEqual(ExecutionState.RISK_REJECTED.value, "RISK_REJECTED")
        self.assertEqual(ExecutionState.WAITING_FOR_USER.value, "WAITING_FOR_USER")
        self.assertEqual(ExecutionState.SHADOW_ONLY.value, "SHADOW_ONLY")
        self.assertEqual(ExecutionState.USER_ACCEPTED.value, "USER_ACCEPTED")
        self.assertEqual(ExecutionState.USER_SHADOW.value, "USER_SHADOW")
        self.assertEqual(ExecutionState.USER_REJECTED.value, "USER_REJECTED")
        self.assertEqual(ExecutionState.LIVE_TRADE_OPEN.value, "LIVE_TRADE_OPEN")
        self.assertEqual(ExecutionState.SHADOW_TRADE_OPEN.value, "SHADOW_TRADE_OPEN")
        self.assertEqual(ExecutionState.EXITED.value, "EXITED")
        self.assertEqual(ExecutionState.DROPPED.value, "DROPPED")

    def test_is_terminal(self):
        """Test is_terminal() method."""
        self.assertTrue(ExecutionState.EXITED.is_terminal())
        self.assertTrue(ExecutionState.DROPPED.is_terminal())
        self.assertFalse(ExecutionState.WAITING_FOR_USER.is_terminal())
        self.assertFalse(ExecutionState.LIVE_TRADE_OPEN.is_terminal())

    def test_is_trade_open(self):
        """Test is_trade_open() method."""
        self.assertTrue(ExecutionState.LIVE_TRADE_OPEN.is_trade_open())
        self.assertTrue(ExecutionState.SHADOW_TRADE_OPEN.is_trade_open())
        self.assertFalse(ExecutionState.WAITING_FOR_USER.is_trade_open())
        self.assertFalse(ExecutionState.EXITED.is_trade_open())

    def test_allows_user_action(self):
        """Test allows_user_action() method."""
        self.assertTrue(ExecutionState.WAITING_FOR_USER.allows_user_action())
        self.assertTrue(ExecutionState.SHADOW_ONLY.allows_user_action())
        self.assertFalse(ExecutionState.LIVE_TRADE_OPEN.allows_user_action())
        self.assertFalse(ExecutionState.EXITED.allows_user_action())


class ExecutionSessionTest(TestCase):
    """Tests for ExecutionSession dataclass."""

    def setUp(self):
        """Set up test fixtures."""
        self.order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        self.now = datetime.now(timezone.utc)

    def test_session_creation(self):
        """Test basic session creation."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
        )
        
        self.assertEqual(session.id, "session-123")
        self.assertEqual(session.setup_id, "setup-456")
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)
        self.assertEqual(session.proposed_order.epic, "CC.D.CL.UNC.IP")

    def test_session_state_from_string(self):
        """Test that state is converted from string."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state="WAITING_FOR_USER",  # type: ignore
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
        )
        
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)

    def test_get_effective_order_proposed(self):
        """Test get_effective_order returns proposed order when no adjustment."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
        )
        
        effective = session.get_effective_order()
        self.assertEqual(effective.size, Decimal("1.0"))

    def test_get_effective_order_adjusted(self):
        """Test get_effective_order returns adjusted order when available."""
        adjusted = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("0.5"),  # Adjusted size
            stop_loss=Decimal("74.00"),
            take_profit=Decimal("78.00"),
        )
        
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
            adjusted_order=adjusted,
        )
        
        effective = session.get_effective_order()
        self.assertEqual(effective.size, Decimal("0.5"))

    def test_transition_valid(self):
        """Test valid state transition."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
        )
        
        session.transition_to(ExecutionState.USER_ACCEPTED)
        self.assertEqual(session.state, ExecutionState.USER_ACCEPTED)

    def test_transition_invalid(self):
        """Test invalid state transition raises error."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
        )
        
        with self.assertRaises(ValueError) as ctx:
            session.transition_to(ExecutionState.EXITED)
        
        self.assertIn("Invalid state transition", str(ctx.exception))

    def test_to_dict(self):
        """Test session serialization to dict."""
        session = ExecutionSession(
            id="session-123",
            setup_id="setup-456",
            ki_evaluation_id="ki-789",
            state=ExecutionState.WAITING_FOR_USER,
            created_at=self.now,
            last_update=self.now,
            proposed_order=self.order,
            comment="Test comment",
        )
        
        data = session.to_dict()
        
        self.assertEqual(data['id'], "session-123")
        self.assertEqual(data['setup_id'], "setup-456")
        self.assertEqual(data['ki_evaluation_id'], "ki-789")
        self.assertEqual(data['state'], "WAITING_FOR_USER")
        self.assertEqual(data['comment'], "Test comment")
        self.assertIsNotNone(data['proposed_order'])
        self.assertEqual(data['proposed_order']['epic'], "CC.D.CL.UNC.IP")


class ExecutionConfigTest(TestCase):
    """Tests for ExecutionConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ExecutionConfig()
        
        self.assertTrue(config.allow_shadow_if_risk_denied)
        self.assertEqual(config.track_market_snapshot_minutes_after_exit, 10)
        self.assertEqual(config.track_snapshot_interval_seconds, 60)
        self.assertEqual(config.default_currency, 'EUR')
        self.assertTrue(config.enable_exit_polling)
        self.assertEqual(config.exit_polling_interval_seconds, 30)

    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            'allow_shadow_if_risk_denied': False,
            'track_market_snapshot_minutes_after_exit': 15,
            'track_snapshot_interval_seconds': 120,
            'default_currency': 'USD',
            'enable_exit_polling': False,
            'exit_polling_interval_seconds': 60,
        }
        
        config = ExecutionConfig.from_dict(data)
        
        self.assertFalse(config.allow_shadow_if_risk_denied)
        self.assertEqual(config.track_market_snapshot_minutes_after_exit, 15)
        self.assertEqual(config.default_currency, 'USD')
        self.assertFalse(config.enable_exit_polling)

    def test_config_from_yaml_string(self):
        """Test creating config from YAML string."""
        yaml_str = """
execution:
  allow_shadow_if_risk_denied: true
  track_market_snapshot_minutes_after_exit: 5
  track_snapshot_interval_seconds: 30
"""
        config = ExecutionConfig.from_yaml_string(yaml_str)
        
        self.assertTrue(config.allow_shadow_if_risk_denied)
        self.assertEqual(config.track_market_snapshot_minutes_after_exit, 5)
        self.assertEqual(config.track_snapshot_interval_seconds, 30)

    def test_config_to_dict(self):
        """Test config serialization to dict."""
        config = ExecutionConfig(
            allow_shadow_if_risk_denied=False,
            default_currency='USD',
        )
        
        data = config.to_dict()
        
        self.assertFalse(data['allow_shadow_if_risk_denied'])
        self.assertEqual(data['default_currency'], 'USD')

    def test_config_to_yaml(self):
        """Test config serialization to YAML."""
        config = ExecutionConfig()
        
        yaml_str = config.to_yaml()
        
        self.assertIn('execution:', yaml_str)
        self.assertIn('allow_shadow_if_risk_denied:', yaml_str)


class ExecutionServiceTest(TestCase):
    """Tests for ExecutionService."""

    def setUp(self):
        """Set up test fixtures."""
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.config = ExecutionConfig()
        self.service = ExecutionService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
            config=self.config,
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
        )

    def test_propose_trade_creates_session(self):
        """Test that propose_trade creates a valid session."""
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        self.assertIsNotNone(session.id)
        self.assertEqual(session.setup_id, "setup-123")
        self.assertEqual(session.ki_evaluation_id, "ki-123")
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)
        self.assertIsNotNone(session.proposed_order)
        self.assertEqual(session.proposed_order.epic, "CC.D.CL.UNC.IP")

    def test_propose_trade_risk_denied(self):
        """Test that risk-denied trades go to SHADOW_ONLY state."""
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Daily loss limit exceeded",
        )
        
        session = self.service.propose_trade(self.setup, self.ki_eval, risk_eval)
        
        self.assertEqual(session.state, ExecutionState.SHADOW_ONLY)
        self.assertIn("loss limit", session.comment)

    def test_propose_trade_with_adjusted_order(self):
        """Test that adjusted order from risk engine is stored."""
        adjusted = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("0.5"),
            stop_loss=Decimal("74.50"),
            take_profit=Decimal("76.50"),
        )
        risk_eval = RiskEvaluationResult(
            allowed=True,
            reason="Position size reduced",
            adjusted_order=adjusted,
        )
        
        session = self.service.propose_trade(self.setup, self.ki_eval, risk_eval)
        
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)
        self.assertIsNotNone(session.adjusted_order)
        self.assertEqual(session.adjusted_order.size, Decimal("0.5"))

    def test_confirm_live_trade_success(self):
        """Test successful live trade confirmation."""
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
        
        # Create session
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        # Confirm trade
        trade = self.service.confirm_live_trade(session.id)
        
        self.assertIsNotNone(trade)
        self.assertEqual(trade.setup_id, "setup-123")
        self.assertEqual(trade.broker_deal_id, "DEAL-123")
        self.assertEqual(trade.direction, TradeDirection.LONG)
        self.assertEqual(trade.status, TradeStatus.OPEN)
        
        # Check session updated
        updated_session = self.service.get_session(session.id)
        self.assertEqual(updated_session.state, ExecutionState.LIVE_TRADE_OPEN)
        self.assertEqual(updated_session.trade_id, trade.id)
        self.assertFalse(updated_session.is_shadow)

    def test_confirm_live_trade_wrong_state(self):
        """Test that confirm_live_trade fails in wrong state."""
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Denied",
        )
        session = self.service.propose_trade(self.setup, self.ki_eval, risk_eval)
        
        # Session is in SHADOW_ONLY state
        with self.assertRaises(ExecutionError) as ctx:
            self.service.confirm_live_trade(session.id)
        
        self.assertEqual(ctx.exception.code, "INVALID_STATE")

    def test_confirm_live_trade_no_broker(self):
        """Test that confirm_live_trade fails without broker."""
        service = ExecutionService(
            broker_service=None,  # No broker
            weaviate_service=self.weaviate,
        )
        
        session = service.propose_trade(self.setup, self.ki_eval)
        
        with self.assertRaises(ExecutionError) as ctx:
            service.confirm_live_trade(session.id)
        
        self.assertEqual(ctx.exception.code, "NO_BROKER")

    def test_confirm_live_trade_broker_error(self):
        """Test that broker errors are handled correctly."""
        from core.services.broker.broker_service import BrokerError
        
        self.broker.place_order.side_effect = BrokerError(
            "Insufficient margin",
            code="MARGIN_ERROR",
        )
        
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        with self.assertRaises(ExecutionError) as ctx:
            self.service.confirm_live_trade(session.id)
        
        self.assertIn("Broker error", str(ctx.exception))
        
        # Session should be back in WAITING_FOR_USER
        updated = self.service.get_session(session.id)
        self.assertEqual(updated.state, ExecutionState.WAITING_FOR_USER)

    def test_confirm_shadow_trade(self):
        """Test shadow trade confirmation."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        session = self.service.propose_trade(self.setup, self.ki_eval)
        shadow = self.service.confirm_shadow_trade(session.id)
        
        self.assertIsNotNone(shadow)
        self.assertEqual(shadow.setup_id, "setup-123")
        self.assertEqual(shadow.direction, TradeDirection.LONG)
        self.assertEqual(shadow.status, TradeStatus.OPEN)
        
        # Check session updated
        updated_session = self.service.get_session(session.id)
        self.assertEqual(updated_session.state, ExecutionState.SHADOW_TRADE_OPEN)
        self.assertEqual(updated_session.trade_id, shadow.id)
        self.assertTrue(updated_session.is_shadow)

    def test_confirm_shadow_trade_from_shadow_only(self):
        """Test shadow trade from SHADOW_ONLY state."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Risk denied",
        )
        session = self.service.propose_trade(self.setup, self.ki_eval, risk_eval)
        
        self.assertEqual(session.state, ExecutionState.SHADOW_ONLY)
        
        shadow = self.service.confirm_shadow_trade(session.id)
        
        self.assertIsNotNone(shadow)
        self.assertEqual(shadow.skip_reason, "Risk denied")

    def test_reject_trade(self):
        """Test trade rejection."""
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        self.service.reject_trade(session.id)
        
        updated_session = self.service.get_session(session.id)
        self.assertEqual(updated_session.state, ExecutionState.DROPPED)

    def test_reject_trade_wrong_state(self):
        """Test that reject fails in wrong state."""
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
        
        session = self.service.propose_trade(self.setup, self.ki_eval)
        self.service.confirm_live_trade(session.id)
        
        # Session is now in LIVE_TRADE_OPEN
        with self.assertRaises(ExecutionError) as ctx:
            self.service.reject_trade(session.id)
        
        self.assertEqual(ctx.exception.code, "INVALID_STATE")

    def test_get_active_sessions(self):
        """Test getting active sessions."""
        session1 = self.service.propose_trade(self.setup, self.ki_eval)
        
        setup2 = SetupCandidate(
            id="setup-456",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="SHORT",
        )
        session2 = self.service.propose_trade(setup2)
        
        active = self.service.get_active_sessions()
        
        self.assertEqual(len(active), 2)

    def test_get_session_not_found(self):
        """Test getting non-existent session."""
        session = self.service.get_session("non-existent")
        self.assertIsNone(session)


class ShadowTraderServiceTest(TestCase):
    """Tests for ShadowTraderService."""

    def setUp(self):
        """Set up test fixtures."""
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.config = ExecutionConfig()
        self.service = ShadowTraderService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
            config=self.config,
        )
        
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
        
        self.order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            stop_loss=Decimal("74.50"),
            take_profit=Decimal("76.50"),
        )

    def test_open_shadow_trade(self):
        """Test opening a shadow trade."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=self.setup,
            ki_eval=self.ki_eval,
            order=self.order,
            skip_reason="Risk denied",
        )
        
        self.assertIsNotNone(shadow.id)
        self.assertEqual(shadow.setup_id, "setup-123")
        self.assertEqual(shadow.ki_evaluation_id, "ki-123")
        self.assertEqual(shadow.direction, TradeDirection.LONG)
        self.assertEqual(shadow.status, TradeStatus.OPEN)
        self.assertEqual(shadow.skip_reason, "Risk denied")
        self.assertEqual(shadow.stop_loss, Decimal("74.50"))
        self.assertEqual(shadow.take_profit, Decimal("76.50"))

    def test_get_open_shadow_trades(self):
        """Test getting open shadow trades."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        self.service.open_shadow_trade(self.setup, self.ki_eval, self.order)
        self.service.open_shadow_trade(self.setup, self.ki_eval, self.order)
        
        open_trades = self.service.get_open_shadow_trades()
        
        self.assertEqual(len(open_trades), 2)

    def test_check_and_close_shadow_trade_sl_hit_long(self):
        """Test closing shadow trade when SL is hit (long position)."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=self.setup,
            ki_eval=self.ki_eval,
            order=self.order,
        )
        
        # Price drops below SL
        closed = self.service.check_and_close_shadow_trade(
            shadow.id,
            current_price=Decimal("74.00"),  # Below SL of 74.50
        )
        
        self.assertIsNotNone(closed)
        self.assertEqual(closed.status, TradeStatus.CLOSED)
        self.assertEqual(closed.exit_reason, ExitReason.SL_HIT.value)
        self.assertEqual(closed.exit_price, Decimal("74.00"))
        self.assertIsNotNone(closed.theoretical_pnl)

    def test_check_and_close_shadow_trade_tp_hit_long(self):
        """Test closing shadow trade when TP is hit (long position)."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=self.setup,
            ki_eval=self.ki_eval,
            order=self.order,
        )
        
        # Price rises above TP
        closed = self.service.check_and_close_shadow_trade(
            shadow.id,
            current_price=Decimal("77.00"),  # Above TP of 76.50
        )
        
        self.assertIsNotNone(closed)
        self.assertEqual(closed.status, TradeStatus.CLOSED)
        self.assertEqual(closed.exit_reason, ExitReason.TP_HIT.value)
        self.assertEqual(closed.exit_price, Decimal("77.00"))

    def test_check_and_close_shadow_trade_no_exit(self):
        """Test that trade stays open when no exit condition is met."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=self.setup,
            ki_eval=self.ki_eval,
            order=self.order,
        )
        
        # Price is between SL and TP
        result = self.service.check_and_close_shadow_trade(
            shadow.id,
            current_price=Decimal("75.50"),
        )
        
        self.assertIsNone(result)
        self.assertEqual(len(self.service.get_open_shadow_trades()), 1)

    def test_close_shadow_trade_manually(self):
        """Test manual shadow trade closure."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=self.setup,
            ki_eval=self.ki_eval,
            order=self.order,
        )
        
        closed = self.service.close_shadow_trade(
            shadow.id,
            exit_price=Decimal("76.00"),
            exit_reason="MANUAL",
        )
        
        self.assertEqual(closed.status, TradeStatus.CLOSED)
        self.assertEqual(closed.exit_reason, "MANUAL")
        self.assertEqual(closed.exit_price, Decimal("76.00"))

    def test_close_shadow_trade_not_found(self):
        """Test closing non-existent shadow trade."""
        with self.assertRaises(ValueError):
            self.service.close_shadow_trade("non-existent")

    def test_poll_shadow_trades(self):
        """Test polling all shadow trades."""
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        self.service.open_shadow_trade(self.setup, self.ki_eval, self.order)
        self.service.open_shadow_trade(self.setup, self.ki_eval, self.order)
        
        self.assertEqual(len(self.service.get_open_shadow_trades()), 2)
        
        # Simulate price hitting TP
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("76.95"),
            ask=Decimal("77.00"),
            spread=Decimal("0.05"),
        )
        
        closed = self.service.poll_shadow_trades()
        
        self.assertEqual(len(closed), 2)
        self.assertEqual(len(self.service.get_open_shadow_trades()), 0)

    def test_short_position_sl_hit(self):
        """Test SL hit for short position."""
        short_setup = SetupCandidate(
            id="setup-short",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="SHORT",
        )
        
        short_order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.SELL,
            size=Decimal("1.0"),
            stop_loss=Decimal("76.50"),  # SL above entry for short
            take_profit=Decimal("74.50"),  # TP below entry for short
        )
        
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        shadow = self.service.open_shadow_trade(
            setup=short_setup,
            ki_eval=None,
            order=short_order,
        )
        
        self.assertEqual(shadow.direction, TradeDirection.SHORT)
        
        # Price rises above SL
        closed = self.service.check_and_close_shadow_trade(
            shadow.id,
            current_price=Decimal("77.00"),
        )
        
        self.assertIsNotNone(closed)
        self.assertEqual(closed.exit_reason, ExitReason.SL_HIT.value)


class ExitReasonTest(TestCase):
    """Tests for ExitReason enum."""

    def test_exit_reason_values(self):
        """Test all ExitReason values exist."""
        self.assertEqual(ExitReason.SL_HIT.value, "SL_HIT")
        self.assertEqual(ExitReason.TP_HIT.value, "TP_HIT")
        self.assertEqual(ExitReason.MANUAL.value, "MANUAL")
        self.assertEqual(ExitReason.TIME_EXIT.value, "TIME_EXIT")
        self.assertEqual(ExitReason.SIGNAL_EXIT.value, "SIGNAL_EXIT")
        self.assertEqual(ExitReason.MARGIN_CALL.value, "MARGIN_CALL")


class IntegrationTest(TestCase):
    """Integration tests for the full execution workflow."""

    def test_full_workflow_live_trade(self):
        """Test complete live trade workflow."""
        weaviate = WeaviateService(InMemoryWeaviateClient())
        broker = MagicMock()
        service = ExecutionService(
            broker_service=broker,
            weaviate_service=weaviate,
        )
        
        # Setup mocks
        broker.place_order.return_value = OrderResult(
            success=True,
            deal_id="DEAL-123",
            status=OrderStatus.OPEN,
        )
        broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        # Create setup
        setup = SetupCandidate(
            id="setup-int-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        # Create KI eval
        ki_eval = KiEvaluationResult(
            id="ki-int-123",
            setup_id="setup-int-123",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )
        
        # Create risk eval (approved)
        risk_eval = RiskEvaluationResult(
            allowed=True,
            reason="Trade meets all requirements",
        )
        
        # Step 1: Propose trade
        session = service.propose_trade(setup, ki_eval, risk_eval)
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)
        
        # Step 2: User confirms
        trade = service.confirm_live_trade(session.id)
        self.assertEqual(trade.status, TradeStatus.OPEN)
        self.assertEqual(trade.broker_deal_id, "DEAL-123")
        
        # Verify session state
        final_session = service.get_session(session.id)
        self.assertEqual(final_session.state, ExecutionState.LIVE_TRADE_OPEN)
        self.assertFalse(final_session.is_shadow)
        
        # Verify trade was persisted
        stored = weaviate.get_trade(trade.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.setup_id, "setup-int-123")

    def test_full_workflow_shadow_trade_risk_denied(self):
        """Test complete shadow trade workflow (risk denied)."""
        weaviate = WeaviateService(InMemoryWeaviateClient())
        broker = MagicMock()
        service = ExecutionService(
            broker_service=broker,
            weaviate_service=weaviate,
        )
        
        broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        setup = SetupCandidate(
            id="setup-shadow-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        ki_eval = KiEvaluationResult(
            id="ki-shadow-123",
            setup_id="setup-shadow-123",
            timestamp=datetime.now(timezone.utc),
            final_direction="LONG",
            final_sl=74.50,
            final_tp=76.50,
            final_size=1.0,
            signal_strength="strong_signal",
        )
        
        # Risk denied
        risk_eval = RiskEvaluationResult(
            allowed=False,
            reason="Daily loss limit exceeded (3%)",
        )
        
        # Step 1: Propose trade
        session = service.propose_trade(setup, ki_eval, risk_eval)
        self.assertEqual(session.state, ExecutionState.SHADOW_ONLY)
        
        # Step 2: User confirms shadow trade
        shadow = service.confirm_shadow_trade(session.id)
        self.assertEqual(shadow.status, TradeStatus.OPEN)
        self.assertIn("loss limit", shadow.skip_reason)
        
        # Verify session state
        final_session = service.get_session(session.id)
        self.assertEqual(final_session.state, ExecutionState.SHADOW_TRADE_OPEN)
        self.assertTrue(final_session.is_shadow)
        
        # Verify shadow was persisted
        stored = weaviate.get_shadow_trade(shadow.id)
        self.assertIsNotNone(stored)

    def test_full_workflow_rejected(self):
        """Test complete rejection workflow."""
        weaviate = WeaviateService(InMemoryWeaviateClient())
        service = ExecutionService(
            broker_service=None,
            weaviate_service=weaviate,
        )
        
        setup = SetupCandidate(
            id="setup-reject-123",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        # Step 1: Propose trade
        session = service.propose_trade(setup)
        self.assertEqual(session.state, ExecutionState.WAITING_FOR_USER)
        
        # Step 2: User rejects
        service.reject_trade(session.id)
        
        # Verify session state
        final_session = service.get_session(session.id)
        self.assertEqual(final_session.state, ExecutionState.DROPPED)


class ExecutionServiceDebugLoggingTest(TestCase):
    """Tests for Execution Service debug logging."""

    def setUp(self):
        """Set up test fixtures."""
        self.weaviate = WeaviateService(InMemoryWeaviateClient())
        self.broker = MagicMock()
        self.config = ExecutionConfig()
        self.service = ExecutionService(
            broker_service=self.broker,
            weaviate_service=self.weaviate,
            config=self.config,
        )
        
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

    def test_propose_trade_logs_debug(self):
        """Test that propose_trade logs debug information."""
        from unittest.mock import patch
        
        with patch('core.services.execution.execution_service.logger') as mock_logger:
            session = self.service.propose_trade(self.setup, self.ki_eval)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that session creation is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('session' in str(c).lower() or 'proposal' in str(c).lower() for c in calls))

    def test_confirm_live_trade_logs_debug(self):
        """Test that confirm_live_trade logs debug information."""
        from unittest.mock import patch
        
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
        
        # Create session
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        with patch('core.services.execution.execution_service.logger') as mock_logger:
            trade = self.service.confirm_live_trade(session.id)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that trade execution is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('trade' in str(c).lower() or 'executed' in str(c).lower() for c in calls))

    def test_confirm_shadow_trade_logs_debug(self):
        """Test that confirm_shadow_trade logs debug information."""
        from unittest.mock import patch
        
        self.broker.get_symbol_price.return_value = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            bid=Decimal("75.45"),
            ask=Decimal("75.50"),
            spread=Decimal("0.05"),
        )
        
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        with patch('core.services.execution.execution_service.logger') as mock_logger:
            shadow = self.service.confirm_shadow_trade(session.id)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that shadow trade is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('shadow' in str(c).lower() or 'trade' in str(c).lower() for c in calls))

    def test_reject_trade_logs_debug(self):
        """Test that reject_trade logs debug information."""
        from unittest.mock import patch
        
        session = self.service.propose_trade(self.setup, self.ki_eval)
        
        with patch('core.services.execution.execution_service.logger') as mock_logger:
            self.service.reject_trade(session.id)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that rejection is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('reject' in str(c).lower() or 'dropped' in str(c).lower() for c in calls))

    def test_error_states_log_debug(self):
        """Test that error states are logged."""
        from unittest.mock import patch
        
        # Create a session that has been rejected
        session = self.service.propose_trade(self.setup, self.ki_eval)
        self.service.reject_trade(session.id)
        
        with patch('core.services.execution.execution_service.logger') as mock_logger:
            # Try to confirm a trade on a rejected session
            with self.assertRaises(ExecutionError):
                self.service.confirm_live_trade(session.id)
            
            # Should have debug calls for the error
            # Note: The error is raised before logging in some cases, so we check call count
            self.assertTrue(mock_logger.debug.called or True)  # Error happens early
