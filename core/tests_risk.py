"""
Tests for the Risk Engine module.

These tests cover the data models, configuration, and risk evaluation logic
for the Risk Engine v1.0.
"""
from datetime import datetime, timezone, timedelta, time
from decimal import Decimal
from django.test import TestCase

from core.services.risk import (
    RiskConfig,
    RiskEvaluationResult,
    RiskEngine,
)
from core.services.broker.models import (
    AccountState,
    Position,
    OrderRequest,
    OrderType,
    OrderDirection,
)
from core.services.strategy.models import (
    SetupCandidate,
    SetupKind,
    SessionPhase,
    BreakoutContext,
    EiaContext,
)


class RiskConfigTest(TestCase):
    """Tests for RiskConfig dataclass."""

    def test_default_config(self):
        """Test default RiskConfig creation."""
        config = RiskConfig()
        
        self.assertEqual(config.max_risk_per_trade_percent, Decimal('1.0'))
        self.assertEqual(config.max_daily_loss_percent, Decimal('3.0'))
        self.assertEqual(config.max_weekly_loss_percent, Decimal('6.0'))
        self.assertEqual(config.max_open_positions, 1)
        self.assertFalse(config.allow_countertrend)
        self.assertEqual(config.max_position_size, Decimal('5.0'))
        self.assertEqual(config.sl_min_ticks, 5)
        self.assertEqual(config.tp_min_ticks, 5)
        self.assertEqual(config.deny_eia_window_minutes, 5)
        self.assertEqual(config.deny_friday_after, '21:00')
        self.assertTrue(config.deny_overnight)

    def test_config_from_dict(self):
        """Test RiskConfig creation from dictionary."""
        data = {
            'max_risk_per_trade_percent': 2.0,
            'max_daily_loss_percent': 5.0,
            'max_weekly_loss_percent': 10.0,
            'max_open_positions': 2,
            'allow_countertrend': True,
            'max_position_size': 10.0,
            'sl_min_ticks': 10,
            'tp_min_ticks': 10,
            'deny_eia_window_minutes': 10,
            'deny_friday_after': '20:00',
            'deny_overnight': False,
            'tick_size': 0.02,
            'tick_value': 20.0,
        }
        
        config = RiskConfig.from_dict(data)
        
        self.assertEqual(config.max_risk_per_trade_percent, Decimal('2.0'))
        self.assertEqual(config.max_daily_loss_percent, Decimal('5.0'))
        self.assertEqual(config.max_open_positions, 2)
        self.assertTrue(config.allow_countertrend)
        self.assertEqual(config.sl_min_ticks, 10)
        self.assertEqual(config.deny_friday_after, '20:00')
        self.assertFalse(config.deny_overnight)
        self.assertEqual(config.tick_size, Decimal('0.02'))

    def test_config_to_dict(self):
        """Test RiskConfig serialization to dictionary."""
        config = RiskConfig()
        data = config.to_dict()
        
        self.assertEqual(data['max_risk_per_trade_percent'], 1.0)
        self.assertEqual(data['max_open_positions'], 1)
        self.assertFalse(data['allow_countertrend'])
        self.assertIn('sl_min_ticks', data)
        self.assertIn('deny_eia_window_minutes', data)

    def test_config_from_yaml_string(self):
        """Test RiskConfig creation from YAML string."""
        yaml_string = """
max_risk_per_trade_percent: 1.5
max_daily_loss_percent: 4.0
max_weekly_loss_percent: 8.0
max_open_positions: 1
allow_countertrend: false
max_position_size: 3.0
sl_min_ticks: 8
tp_min_ticks: 8
deny_eia_window_minutes: 10
deny_friday_after: "21:00"
deny_overnight: true
"""
        config = RiskConfig.from_yaml_string(yaml_string)
        
        self.assertEqual(config.max_risk_per_trade_percent, Decimal('1.5'))
        self.assertEqual(config.max_daily_loss_percent, Decimal('4.0'))
        self.assertEqual(config.max_position_size, Decimal('3.0'))
        self.assertEqual(config.sl_min_ticks, 8)
        self.assertEqual(config.deny_eia_window_minutes, 10)

    def test_config_to_yaml(self):
        """Test RiskConfig serialization to YAML string."""
        config = RiskConfig()
        yaml_str = config.to_yaml()
        
        self.assertIn('max_risk_per_trade_percent', yaml_str)
        self.assertIn('max_open_positions', yaml_str)
        self.assertIn('deny_friday_after', yaml_str)

    def test_get_friday_cutoff_time(self):
        """Test parsing Friday cutoff time."""
        config = RiskConfig(deny_friday_after='21:00')
        cutoff = config.get_friday_cutoff_time()
        
        self.assertEqual(cutoff, time(21, 0))
        
        config2 = RiskConfig(deny_friday_after='20:30')
        cutoff2 = config2.get_friday_cutoff_time()
        
        self.assertEqual(cutoff2, time(20, 30))

    def test_decimal_conversion(self):
        """Test that numeric values are converted to Decimal."""
        config = RiskConfig(
            max_risk_per_trade_percent=1.5,  # float
            max_position_size="3.0",  # string
        )
        
        self.assertIsInstance(config.max_risk_per_trade_percent, Decimal)
        self.assertIsInstance(config.max_position_size, Decimal)


class RiskEvaluationResultTest(TestCase):
    """Tests for RiskEvaluationResult dataclass."""

    def test_result_creation_allowed(self):
        """Test creating an allowed result."""
        result = RiskEvaluationResult(
            allowed=True,
            reason="Trade meets all risk requirements",
        )
        
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "Trade meets all risk requirements")
        self.assertIsNone(result.adjusted_order)
        self.assertEqual(result.violations, [])

    def test_result_creation_denied(self):
        """Test creating a denied result."""
        result = RiskEvaluationResult(
            allowed=False,
            reason="SL distance too large → risk > 1% of equity",
            violations=["SL distance too large"],
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("SL distance", result.reason)
        self.assertEqual(len(result.violations), 1)

    def test_result_to_dict(self):
        """Test RiskEvaluationResult serialization."""
        result = RiskEvaluationResult(
            allowed=False,
            reason="Test reason",
            violations=["violation1", "violation2"],
            risk_metrics={'max_risk': 100.0},
        )
        
        data = result.to_dict()
        
        self.assertFalse(data['allowed'])
        self.assertEqual(data['reason'], "Test reason")
        self.assertEqual(len(data['violations']), 2)
        self.assertEqual(data['risk_metrics']['max_risk'], 100.0)

    def test_result_to_json(self):
        """Test RiskEvaluationResult JSON serialization."""
        result = RiskEvaluationResult(
            allowed=True,
            reason="Allowed",
        )
        
        json_str = result.to_json()
        
        self.assertIn('"allowed": true', json_str)
        self.assertIn('"reason": "Allowed"', json_str)


class RiskEngineTest(TestCase):
    """Tests for RiskEngine class."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RiskConfig()
        self.engine = RiskEngine(self.config)
        
        # Create a standard account state
        self.account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            margin_used=Decimal("0.00"),
            margin_available=Decimal("10000.00"),
            currency="EUR",
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
        
        # Create a standard order request that fits within risk limits
        # SL at 75.40 = 10 ticks from 75.50
        # Risk per contract = 10 * 10 = 100
        # Max risk = 1% of 10000 = 100
        # Max size from risk = 100 / 100 = 1.0 (exactly fits)
        self.order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.40"),  # 10 ticks from 75.50 reference
            take_profit=Decimal("76.50"),
        )

    def test_trade_allowed_basic(self):
        """Test that a valid trade is allowed."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)  # Wednesday
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "Trade meets all risk requirements")

    def test_trade_denied_too_many_positions(self):
        """Test that trade is denied when max positions reached."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Create an existing position
        existing_position = Position(
            position_id="POS1",
            deal_id="DEAL1",
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude Oil",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            open_price=Decimal("74.00"),
            current_price=Decimal("75.00"),
            unrealized_pnl=Decimal("100.00"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[existing_position],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Max open positions", result.reason)

    def test_trade_denied_friday_evening(self):
        """Test that trade is denied on Friday evening."""
        # Friday at 22:00 CET
        now = datetime(2025, 1, 17, 22, 0, tzinfo=timezone.utc)  # Friday
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Friday", result.reason)

    def test_trade_denied_weekend(self):
        """Test that trade is denied on weekend."""
        # Saturday
        now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Weekend", result.reason)

    def test_trade_denied_eia_window(self):
        """Test that breakout trade is denied during EIA window."""
        now = datetime(2025, 1, 15, 15, 32, tzinfo=timezone.utc)
        eia_time = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
            eia_timestamp=eia_time,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("EIA window", result.reason)

    def test_eia_setup_allowed_during_eia_window(self):
        """Test that EIA setups are allowed during EIA window."""
        now = datetime(2025, 1, 15, 15, 32, tzinfo=timezone.utc)
        eia_time = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        
        # Create an EIA reversion setup
        eia_setup = SetupCandidate(
            id="eia-setup-123",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=75.50,
            direction="LONG",
            eia=EiaContext(
                eia_timestamp=eia_time,
                first_impulse_direction="SHORT",
            ),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=eia_setup,
            order=self.order,
            now=now,
            eia_timestamp=eia_time,
        )
        
        self.assertTrue(result.allowed)

    def test_trade_denied_daily_loss_limit(self):
        """Test that trade is denied when daily loss limit exceeded."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Daily PnL = -4% (exceeds 3% limit)
        daily_pnl = Decimal('-400.00')  # -4% of 10000
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
            daily_pnl=daily_pnl,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Daily loss limit", result.reason)

    def test_trade_denied_weekly_loss_limit(self):
        """Test that trade is denied when weekly loss limit exceeded."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Weekly PnL = -7% (exceeds 6% limit)
        weekly_pnl = Decimal('-700.00')  # -7% of 10000
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
            weekly_pnl=weekly_pnl,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Weekly loss limit", result.reason)

    def test_trade_denied_countertrend(self):
        """Test that countertrend trade is denied when not allowed."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Setup is LONG but trend is SHORT
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
            trend_direction="SHORT",
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Countertrend", result.reason)

    def test_countertrend_allowed_when_configured(self):
        """Test that countertrend trade is allowed when configured."""
        config = RiskConfig(allow_countertrend=True)
        engine = RiskEngine(config)
        
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        result = engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
            trend_direction="SHORT",
        )
        
        self.assertTrue(result.allowed)

    def test_eia_setup_exempt_from_countertrend(self):
        """Test that EIA setups are exempt from countertrend rule."""
        now = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        eia_setup = SetupCandidate(
            id="eia-setup-456",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=75.50,
            direction="LONG",
            eia=EiaContext(
                eia_timestamp=datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc),
                first_impulse_direction="SHORT",
            ),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=eia_setup,
            order=self.order,
            now=now,
            trend_direction="SHORT",  # Against trend but should be allowed
        )
        
        self.assertTrue(result.allowed)

    def test_trade_denied_no_stop_loss(self):
        """Test that trade is denied when stop loss is missing."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        order_no_sl = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=None,
            take_profit=Decimal("76.50"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=order_no_sl,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("Stop loss is required", result.reason)

    def test_trade_denied_sl_too_close(self):
        """Test that trade is denied when SL is too close."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # SL only 2 ticks away (min is 5)
        order_tight_sl = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.48"),  # 2 ticks from 75.50
            take_profit=Decimal("76.50"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=order_tight_sl,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("SL distance", result.reason)
        self.assertIn("below minimum", result.reason)

    def test_trade_adjusted_position_size_for_risk(self):
        """Test that position size is adjusted to fit 1% risk rule."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Large position with wide SL would exceed risk
        # Risk config: 1% of 10000 = 100 EUR max risk
        # SL 100 ticks away at tick value 10 = 1000 EUR risk per contract
        # Should adjust to 0.1 contract
        large_order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("2.0"),  # Large size
            order_type=OrderType.MARKET,
            stop_loss=Decimal("74.50"),  # 100 ticks from 75.50
            take_profit=Decimal("77.00"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=large_order,
            now=now,
        )
        
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.adjusted_order)
        self.assertLess(result.adjusted_order.size, large_order.size)
        self.assertIn("reduced", result.reason)

    def test_trade_denied_sl_too_large_cannot_adjust(self):
        """Test that trade is denied when SL is too large to adjust."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Very wide SL - would require <0.1 lot size
        # 1000 ticks at tick value 10 = 10000 per contract
        # 1% risk = 100 / 10000 = 0.01 lots (too small)
        order_wide_sl = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("65.50"),  # 1000 ticks from 75.50
            take_profit=Decimal("85.00"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=order_wide_sl,
            now=now,
        )
        
        self.assertFalse(result.allowed)
        self.assertIn("SL distance too large", result.reason)

    def test_trade_denied_position_size_too_large(self):
        """Test that position size exceeding limit is adjusted to fit risk."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Max position size is 5.0, but risk limit may be stricter
        # With SL at 75.45 (5 ticks from 75.50), risk per contract = 5 * 10 = 50
        # Max risk = 1% of 10000 = 100
        # Max size from risk = 100 / 50 = 2.0
        # So position should be adjusted to 2.0, not 5.0
        large_order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("10.0"),  # Exceeds max 5.0
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.45"),  # 5 ticks from 75.50
            take_profit=Decimal("75.60"),
        )
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=large_order,
            now=now,
        )
        
        # Should be allowed with adjusted size
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.adjusted_order)
        # Size is limited by risk rule: max_risk / (ticks * tick_value) = 100 / 50 = 2.0
        self.assertEqual(result.adjusted_order.size, Decimal("2.0"))

    def test_position_size_capped_to_max_when_risk_allows(self):
        """Test that position size is capped to max when risk allows more."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # With SL at 75.45 (5 ticks from 75.50), risk per contract = 5 * 10 = 50
        # Max risk = 1% of 10000 = 100
        # Max size from risk = 100 / 50 = 2.0
        # BUT: Let's use a larger account so risk limit allows more
        large_account = AccountState(
            account_id="TEST456",
            account_name="Large Account",
            balance=Decimal("100000.00"),
            available=Decimal("80000.00"),
            equity=Decimal("100000.00"),
            currency="EUR",
        )
        
        # With large account:
        # Max risk = 1% of 100000 = 1000
        # SL at 75.45 (5 ticks from 75.50), risk per contract = 5 * 10 = 50
        # Max size from risk = 1000 / 50 = 20.0
        # But max_position_size = 5.0, so should be capped to 5.0
        large_order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("20.0"),  # Exceeds max 5.0
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.45"),  # 5 ticks from 75.50 (min allowed)
            take_profit=Decimal("75.60"),
        )
        
        result = self.engine.evaluate(
            account=large_account,
            positions=[],
            setup=self.setup,
            order=large_order,
            now=now,
        )
        
        # Should be allowed with adjusted size
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.adjusted_order)
        # Size is limited by max_position_size since risk allows 20.0
        self.assertEqual(result.adjusted_order.size, Decimal("5.0"))

    def test_risk_metrics_calculated(self):
        """Test that risk metrics are calculated and returned."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        result = self.engine.evaluate(
            account=self.account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        self.assertIn('max_risk_amount', result.risk_metrics)
        self.assertIn('equity', result.risk_metrics)
        self.assertEqual(result.risk_metrics['equity'], 10000.0)
        self.assertEqual(result.risk_metrics['max_risk_amount'], 100.0)  # 1% of 10000

    def test_calculate_position_size(self):
        """Test position size calculation."""
        entry = Decimal("75.50")
        sl = Decimal("75.00")  # 50 ticks
        
        size = self.engine.calculate_position_size(
            account=self.account,
            entry_price=entry,
            stop_loss_price=sl,
        )
        
        # Max risk = 1% of 10000 = 100
        # SL = 50 ticks, tick_value = 10
        # Risk per contract = 50 * 10 = 500
        # Size = 100 / 500 = 0.2
        self.assertEqual(size, Decimal("0.2"))

    def test_calculate_position_size_limited_by_max(self):
        """Test that position size is limited by max_position_size."""
        entry = Decimal("75.50")
        sl = Decimal("75.49")  # Only 1 tick (very tight)
        
        size = self.engine.calculate_position_size(
            account=self.account,
            entry_price=entry,
            stop_loss_price=sl,
        )
        
        # Without limit: 100 / (1 * 10) = 10
        # With limit: max is 5.0
        self.assertEqual(size, Decimal("5.0"))


class RiskEngineIntegrationTest(TestCase):
    """Integration tests for RiskEngine."""

    def test_full_workflow_breakout_allowed(self):
        """Test a complete breakout trade evaluation workflow."""
        config = RiskConfig(
            max_risk_per_trade_percent=Decimal('1.0'),
            max_open_positions=1,
            sl_min_ticks=5,
        )
        engine = RiskEngine(config)
        
        account = AccountState(
            account_id="LIVE123",
            account_name="Live Account",
            balance=Decimal("50000.00"),
            available=Decimal("45000.00"),
            equity=Decimal("50000.00"),
            currency="EUR",
        )
        
        setup = SetupCandidate(
            id="breakout-001",
            created_at=datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc),
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
        
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.00"),  # 50 ticks
            take_profit=Decimal("76.50"),
        )
        
        now = datetime(2025, 1, 15, 9, 5, tzinfo=timezone.utc)  # Wednesday
        
        result = engine.evaluate(
            account=account,
            positions=[],
            setup=setup,
            order=order,
            now=now,
            trend_direction="LONG",
        )
        
        self.assertTrue(result.allowed)
        self.assertEqual(len(result.violations), 0)
        self.assertIn('potential_loss', result.risk_metrics)

    def test_full_workflow_eia_reversion(self):
        """Test EIA reversion trade evaluation."""
        config = RiskConfig()
        engine = RiskEngine(config)
        
        account = AccountState(
            account_id="LIVE456",
            account_name="Live Account",
            balance=Decimal("25000.00"),
            available=Decimal("22000.00"),
            equity=Decimal("25000.00"),
            currency="EUR",
        )
        
        eia_time = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        now = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        setup = SetupCandidate(
            id="eia-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=74.50,
            direction="LONG",
            eia=EiaContext(
                eia_timestamp=eia_time,
                first_impulse_direction="SHORT",
                impulse_range_high=75.50,
                impulse_range_low=74.00,
            ),
        )
        
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("0.5"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("73.50"),  # 100 ticks
            take_profit=Decimal("75.50"),
        )
        
        result = engine.evaluate(
            account=account,
            positions=[],
            setup=setup,
            order=order,
            now=now,
            eia_timestamp=eia_time,
            trend_direction="SHORT",  # EIA exempt from countertrend
        )
        
        self.assertTrue(result.allowed)

    def test_multiple_violations_returns_first(self):
        """Test that multiple violations return the first as reason."""
        config = RiskConfig()
        engine = RiskEngine(config)
        
        account = AccountState(
            account_id="TEST",
            account_name="Test",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        
        setup = SetupCandidate(
            id="test-001",
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        
        order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=None,  # Missing SL
        )
        
        # Weekend + missing SL + loss limit exceeded
        now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)  # Saturday
        
        result = engine.evaluate(
            account=account,
            positions=[],
            setup=setup,
            order=order,
            now=now,
            daily_pnl=Decimal("-500"),  # Exceeds limit
        )
        
        self.assertFalse(result.allowed)
        # First violation should be time-based (weekend)
        self.assertIn("Weekend", result.reason)
        # All violations should be tracked
        self.assertGreater(len(result.violations), 1)


class RiskEngineDebugLoggingTest(TestCase):
    """Tests for Risk Engine debug logging."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RiskConfig()
        self.engine = RiskEngine(self.config)
        
        self.account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            margin_used=Decimal("0.00"),
            margin_available=Decimal("10000.00"),
            currency="EUR",
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
        
        self.order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.40"),
            take_profit=Decimal("76.50"),
        )

    def test_evaluate_logs_debug_on_allowed(self):
        """Test that debug logging is called when trade is allowed."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=self.order,
                now=now,
            )
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that evaluation result is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('risk' in str(c).lower() for c in calls))

    def test_evaluate_logs_debug_on_denied(self):
        """Test that warning logging is called when trade is denied."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)  # Saturday
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=self.order,
                now=now,
            )
            
            # Should have debug calls for initial evaluation
            self.assertTrue(mock_logger.debug.called)
            
            # Should have info/warning calls for violations
            self.assertTrue(mock_logger.info.called or mock_logger.warning.called)
            
            # Trade should be denied
            self.assertFalse(result.allowed)
            
            # Check that denial is logged at warning level
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            self.assertTrue(any('denied' in str(c).lower() for c in warning_calls))

    def test_evaluate_logs_all_violations(self):
        """Test that all violations are logged."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)  # Saturday
        
        order_no_sl = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=None,  # Missing SL
            take_profit=Decimal("76.50"),
        )
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=order_no_sl,
                now=now,
                daily_pnl=Decimal("-500"),
            )
            
            # Should have multiple info calls for multiple violations
            self.assertTrue(mock_logger.info.called)
            self.assertGreater(mock_logger.info.call_count, 1)
            
            # Should have warning call for final denial
            self.assertTrue(mock_logger.warning.called)

    def test_evaluate_logs_adjusted_order(self):
        """Test that position size adjustment is logged."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Large order that needs adjustment
        large_order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("2.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("74.50"),  # 100 ticks
            take_profit=Decimal("77.00"),
        )
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.account,
                positions=[],
                setup=self.setup,
                order=large_order,
                now=now,
            )
            
            # Should have debug calls for adjustment
            self.assertTrue(mock_logger.debug.called)
            
            # Trade should be allowed with adjusted order
            self.assertTrue(result.allowed)
            self.assertIsNotNone(result.adjusted_order)
            
            # Check that adjustment is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('adjusted' in str(c).lower() or 'reduced' in str(c).lower() for c in calls))


class RiskEngineZeroEquityTest(TestCase):
    """Tests for Risk Engine handling of zero equity edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RiskConfig()
        self.engine = RiskEngine(self.config)
        
        # Create an account with zero equity
        self.zero_equity_account = AccountState(
            account_id="ZERO_EQUITY",
            account_name="Zero Equity Account",
            balance=Decimal("0.00"),
            available=Decimal("0.00"),
            equity=Decimal("0.00"),
            margin_used=Decimal("0.00"),
            margin_available=Decimal("0.00"),
            currency="USDT",
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
        
        self.order = OrderRequest(
            epic="CC.D.CL.UNC.IP",
            direction=OrderDirection.BUY,
            size=Decimal("1.0"),
            order_type=OrderType.MARKET,
            stop_loss=Decimal("75.40"),
            take_profit=Decimal("76.50"),
        )

    def test_trade_denied_zero_equity(self):
        """Test that trade is denied when account equity is zero."""
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        result = self.engine.evaluate(
            account=self.zero_equity_account,
            positions=[],
            setup=self.setup,
            order=self.order,
            now=now,
        )
        
        # Trade should be denied due to zero equity
        self.assertFalse(result.allowed)
        # Should have a violation related to risk or SL distance
        self.assertGreater(len(result.violations), 0)
        # Verify risk metrics include equity = 0
        self.assertEqual(result.risk_metrics.get('equity'), 0.0)
        self.assertEqual(result.risk_metrics.get('max_risk_amount'), 0.0)

    def test_zero_equity_logs_warning(self):
        """Test that zero equity triggers a warning log."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.zero_equity_account,
                positions=[],
                setup=self.setup,
                order=self.order,
                now=now,
            )
            
            # Should have a warning call for zero equity
            self.assertTrue(mock_logger.warning.called)
            
            # Check that zero equity warning is logged
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            self.assertTrue(any('zero' in str(c).lower() or 'negative' in str(c).lower() for c in warning_calls))

    def test_zero_equity_logs_account_state(self):
        """Test that account state is logged for debugging."""
        from unittest.mock import patch
        
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        with patch('core.services.risk.risk_engine.logger') as mock_logger:
            result = self.engine.evaluate(
                account=self.zero_equity_account,
                positions=[],
                setup=self.setup,
                order=self.order,
                now=now,
            )
            
            # Should have debug calls logging account state
            self.assertTrue(mock_logger.debug.called)
            
            # Check that account state is logged
            debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('account' in str(c).lower() for c in debug_calls))
