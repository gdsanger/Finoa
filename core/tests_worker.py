"""
Tests for the Fiona Worker management command.

Tests cover initialization, main loop, and graceful shutdown.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock, Mock
from io import StringIO

from django.test import TestCase
from django.core.management import call_command

from core.models import IgBrokerConfig
from core.services.broker import (
    IgBrokerService,
    IGMarketStateProvider,
    AccountState,
    SymbolPrice,
    Position,
)
from core.services.strategy import (
    SessionPhase,
    SetupCandidate,
    SetupKind,
    StrategyEngine,
    StrategyConfig,
)
from core.services.risk import RiskEngine, RiskConfig
from core.services.risk.models import RiskEvaluationResult
from core.services.execution import ExecutionService
from core.services.weaviate import WeaviateService


class IGMarketStateProviderTest(TestCase):
    """Tests for IGMarketStateProvider."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_broker = MagicMock(spec=IgBrokerService)
        
        # Mock symbol price
        self.mock_price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude",
            bid=Decimal("75.50"),
            ask=Decimal("75.55"),
            spread=Decimal("0.05"),
            high=Decimal("76.00"),
            low=Decimal("74.00"),
        )
        self.mock_broker.get_symbol_price.return_value = self.mock_price

    def test_provider_initialization(self):
        """Test provider initializes correctly."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        self.assertIsNotNone(provider)

    def test_get_phase_asia_range(self):
        """Test phase detection for Asia session."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 03:00 UTC on a Tuesday
        ts = datetime(2024, 1, 9, 3, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.ASIA_RANGE)

    def test_get_phase_london_core(self):
        """Test phase detection for London Core session."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 09:00 UTC on a Tuesday
        ts = datetime(2024, 1, 9, 9, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.LONDON_CORE)

    def test_get_phase_pre_us_range(self):
        """Test phase detection for Pre-US Range session."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 13:30 UTC on a Tuesday should be PRE_US_RANGE
        ts = datetime(2024, 1, 9, 13, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.PRE_US_RANGE)

    def test_get_phase_us_core_trading(self):
        """Test phase detection for US Core Trading session."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 15:00 UTC on a Tuesday should be US_CORE_TRADING
        ts = datetime(2024, 1, 9, 15, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 20:00 UTC on a Tuesday should also be US_CORE_TRADING
        ts = datetime(2024, 1, 9, 20, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)

    def test_get_phase_us_core(self):
        """Test phase detection for deprecated US Core session (backwards compat)."""
        from core.services.broker import SessionTimesConfig
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Configure to use the deprecated US_CORE (disable US_CORE_TRADING)
        session_times = SessionTimesConfig.from_time_strings(
            us_core_trading_enabled=False,
            us_core_start="14:00",
            us_core_end="17:00",
        )
        provider.set_session_times(session_times)
        
        # 15:00 UTC on a Tuesday should be US_CORE
        ts = datetime(2024, 1, 9, 15, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.US_CORE)

    def test_get_phase_friday_late(self):
        """Test phase detection for Friday late."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 22:00 UTC on a Friday
        ts = datetime(2024, 1, 12, 22, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.FRIDAY_LATE)

    def test_get_phase_weekend(self):
        """Test phase detection for weekend."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Saturday
        ts = datetime(2024, 1, 13, 12, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.OTHER)

    def test_get_phase_eia_pre(self):
        """Test phase detection for EIA pre-release window."""
        eia_time = datetime(2024, 1, 10, 15, 30, 0, tzinfo=timezone.utc)
        provider = IGMarketStateProvider(
            broker_service=self.mock_broker,
            eia_timestamp=eia_time,
        )
        
        # 2 minutes before EIA
        ts = eia_time - timedelta(minutes=2)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.EIA_PRE)

    def test_get_phase_eia_post(self):
        """Test phase detection for EIA post-release window."""
        eia_time = datetime(2024, 1, 10, 15, 30, 0, tzinfo=timezone.utc)
        provider = IGMarketStateProvider(
            broker_service=self.mock_broker,
            eia_timestamp=eia_time,
        )
        
        # 10 minutes after EIA
        ts = eia_time + timedelta(minutes=10)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.EIA_POST)

    def test_get_recent_candles(self):
        """Test getting recent candles."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        candles = provider.get_recent_candles("CC.D.CL.UNC.IP", "1m", 10)
        
        self.assertIsInstance(candles, list)
        # Should have at least 1 candle from current price
        self.assertGreaterEqual(len(candles), 1)

    def test_get_daily_high_low(self):
        """Test getting daily high/low."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        result = provider.get_daily_high_low("CC.D.CL.UNC.IP")
        
        self.assertIsNotNone(result)
        self.assertEqual(result, (76.0, 74.0))

    def test_set_and_get_asia_range(self):
        """Test setting and getting Asia range."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Initially None
        self.assertIsNone(provider.get_asia_range("CC.D.CL.UNC.IP"))
        
        # Set range
        provider.set_asia_range("CC.D.CL.UNC.IP", 75.50, 74.50)
        
        # Get range
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        self.assertEqual(result, (75.50, 74.50))

    def test_set_and_get_pre_us_range(self):
        """Test setting and getting pre-US range."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Initially None
        self.assertIsNone(provider.get_pre_us_range("CC.D.CL.UNC.IP"))
        
        # Set range
        provider.set_pre_us_range("CC.D.CL.UNC.IP", 76.00, 75.00)
        
        # Get range
        result = provider.get_pre_us_range("CC.D.CL.UNC.IP")
        self.assertEqual(result, (76.00, 75.00))

    def test_get_eia_timestamp(self):
        """Test getting EIA timestamp."""
        eia_time = datetime(2024, 1, 10, 15, 30, 0, tzinfo=timezone.utc)
        provider = IGMarketStateProvider(
            broker_service=self.mock_broker,
            eia_timestamp=eia_time,
        )
        
        self.assertEqual(provider.get_eia_timestamp(), eia_time)

    def test_set_eia_timestamp(self):
        """Test setting EIA timestamp."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        self.assertIsNone(provider.get_eia_timestamp())
        
        eia_time = datetime(2024, 1, 10, 15, 30, 0, tzinfo=timezone.utc)
        provider.set_eia_timestamp(eia_time)
        
        self.assertEqual(provider.get_eia_timestamp(), eia_time)

    def test_clear_session_caches(self):
        """Test clearing session caches."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Set some ranges
        provider.set_asia_range("CC.D.CL.UNC.IP", 75.50, 74.50)
        provider.set_pre_us_range("CC.D.CL.UNC.IP", 76.00, 75.00)
        
        # Clear caches
        provider.clear_session_caches()
        
        # Verify cleared
        self.assertIsNone(provider.get_asia_range("CC.D.CL.UNC.IP"))
        self.assertIsNone(provider.get_pre_us_range("CC.D.CL.UNC.IP"))

    def test_configurable_us_core_trading_session_times(self):
        """Test that US Core Trading session times can be configured."""
        from core.services.broker import SessionTimesConfig
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Configure US Core Trading to 16:00 - 20:00 UTC
        session_times = SessionTimesConfig.from_time_strings(
            us_core_trading_start="16:00",
            us_core_trading_end="20:00",
        )
        provider.set_session_times(session_times)
        
        # 15:30 UTC on a Tuesday should be OTHER (not in trading window)
        ts = datetime(2024, 1, 9, 15, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertNotEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 16:30 UTC on a Tuesday should be US_CORE_TRADING
        ts = datetime(2024, 1, 9, 16, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
    
    def test_default_session_times_new_phases(self):
        """Test that default session times include PRE_US_RANGE and US_CORE_TRADING."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # 13:30 UTC should be PRE_US_RANGE with default config
        ts = datetime(2024, 1, 9, 13, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.PRE_US_RANGE)
        
        # 15:00 UTC should be US_CORE_TRADING with default config
        ts = datetime(2024, 1, 9, 15, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 21:00 UTC should be US_CORE_TRADING with default config
        ts = datetime(2024, 1, 9, 21, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 22:00 UTC should be OTHER with default config
        ts = datetime(2024, 1, 9, 22, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.OTHER)
    
    def test_session_times_with_minutes(self):
        """Test session times with minute-level precision."""
        from core.services.broker import SessionTimesConfig
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Configure Pre-US to 13:30 - 15:30 and US Core Trading to 15:30 - 21:30 UTC
        session_times = SessionTimesConfig.from_time_strings(
            pre_us_start="13:30",
            pre_us_end="15:30",
            us_core_trading_start="15:30",
            us_core_trading_end="21:30",
        )
        provider.set_session_times(session_times)
        
        # 13:29 UTC should be OTHER
        ts = datetime(2024, 1, 9, 13, 29, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertNotEqual(phase, SessionPhase.PRE_US_RANGE)
        
        # 13:30 UTC should be PRE_US_RANGE
        ts = datetime(2024, 1, 9, 13, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.PRE_US_RANGE)
        
        # 15:29 UTC should be PRE_US_RANGE
        ts = datetime(2024, 1, 9, 15, 29, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.PRE_US_RANGE)
        
        # 15:30 UTC should be US_CORE_TRADING
        ts = datetime(2024, 1, 9, 15, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 21:29 UTC should be US_CORE_TRADING
        ts = datetime(2024, 1, 9, 21, 29, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)
        
        # 21:30 UTC should be OTHER
        ts = datetime(2024, 1, 9, 21, 30, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        self.assertEqual(phase, SessionPhase.OTHER)


class FionaWorkerCommandTest(TestCase):
    """Tests for the run_fiona_worker management command."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test broker config
        IgBrokerConfig.objects.create(
            name="Test IG Config",
            api_key="test-api-key",
            username="test-user",
            password="test-pass",
            account_type="DEMO",
            is_active=True,
        )

    @patch('core.management.commands.run_fiona_worker.create_ig_broker_service')
    def test_command_dry_run_once(self, mock_create_broker):
        """Test command with dry run and once options."""
        # Set up mock broker
        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.is_connected.return_value = True
        
        mock_account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        mock_broker.get_account_state.return_value = mock_account
        mock_broker.get_open_positions.return_value = []
        
        mock_price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude",
            bid=Decimal("75.50"),
            ask=Decimal("75.55"),
            spread=Decimal("0.05"),
        )
        mock_broker.get_symbol_price.return_value = mock_price
        
        mock_create_broker.return_value = mock_broker
        
        out = StringIO()
        call_command(
            'run_fiona_worker',
            '--once',
            '--dry-run',
            stdout=out,
        )
        
        output = out.getvalue()
        
        # Verify command ran
        self.assertIn("Fiona Worker v1.1", output)
        self.assertIn("Single run completed", output)
        
        # Verify broker was connected
        mock_broker.connect.assert_called_once()
        mock_broker.disconnect.assert_called_once()

    @patch('core.management.commands.run_fiona_worker.create_ig_broker_service')
    def test_command_shadow_only_mode(self, mock_create_broker):
        """Test command in shadow-only mode."""
        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.is_connected.return_value = True
        
        mock_account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        mock_broker.get_account_state.return_value = mock_account
        mock_broker.get_open_positions.return_value = []
        
        mock_price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude",
            bid=Decimal("75.50"),
            ask=Decimal("75.55"),
            spread=Decimal("0.05"),
        )
        mock_broker.get_symbol_price.return_value = mock_price
        
        mock_create_broker.return_value = mock_broker
        
        out = StringIO()
        call_command(
            'run_fiona_worker',
            '--once',
            '--shadow-only',
            stdout=out,
        )
        
        output = out.getvalue()
        
        self.assertIn("Shadow Only: True", output)

    @patch('core.management.commands.run_fiona_worker.create_ig_broker_service')
    def test_command_max_iterations(self, mock_create_broker):
        """Test command with max iterations limit."""
        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.is_connected.return_value = True
        
        mock_account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        mock_broker.get_account_state.return_value = mock_account
        mock_broker.get_open_positions.return_value = []
        
        mock_price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude",
            bid=Decimal("75.50"),
            ask=Decimal("75.55"),
            spread=Decimal("0.05"),
        )
        mock_broker.get_symbol_price.return_value = mock_price
        
        mock_create_broker.return_value = mock_broker
        
        out = StringIO()
        call_command(
            'run_fiona_worker',
            '--max-iterations', '2',
            '--interval', '0',
            stdout=out,
        )
        
        output = out.getvalue()
        
        self.assertIn("Reached max iterations (2)", output)

    @patch('core.management.commands.run_fiona_worker.create_ig_broker_service')
    def test_command_custom_epic(self, mock_create_broker):
        """Test command with custom epic."""
        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.is_connected.return_value = True
        
        mock_account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        mock_broker.get_account_state.return_value = mock_account
        mock_broker.get_open_positions.return_value = []
        
        mock_price = SymbolPrice(
            epic="IX.D.DAX.DAILY.IP",
            market_name="Germany 40",
            bid=Decimal("17500.00"),
            ask=Decimal("17501.00"),
            spread=Decimal("1.00"),
        )
        mock_broker.get_symbol_price.return_value = mock_price
        
        mock_create_broker.return_value = mock_broker
        
        out = StringIO()
        call_command(
            'run_fiona_worker',
            '--once',
            '--epic', 'IX.D.DAX.DAILY.IP',
            stdout=out,
        )
        
        output = out.getvalue()
        
        self.assertIn("Epic: IX.D.DAX.DAILY.IP", output)


class WorkerIntegrationTest(TestCase):
    """Integration tests for worker components."""

    def test_full_workflow_with_mocks(self):
        """Test full workflow with mocked services."""
        # Create mock broker
        mock_broker = MagicMock(spec=IgBrokerService)
        mock_broker.is_connected.return_value = True
        
        mock_account = AccountState(
            account_id="TEST123",
            account_name="Test Account",
            balance=Decimal("10000.00"),
            available=Decimal("8000.00"),
            equity=Decimal("10000.00"),
            currency="EUR",
        )
        mock_broker.get_account_state.return_value = mock_account
        mock_broker.get_open_positions.return_value = []
        
        mock_price = SymbolPrice(
            epic="CC.D.CL.UNC.IP",
            market_name="WTI Crude",
            bid=Decimal("75.50"),
            ask=Decimal("75.55"),
            spread=Decimal("0.05"),
            high=Decimal("76.00"),
            low=Decimal("74.00"),
        )
        mock_broker.get_symbol_price.return_value = mock_price
        
        # Create market state provider
        provider = IGMarketStateProvider(broker_service=mock_broker)
        
        # Create strategy engine
        config = StrategyConfig()
        engine = StrategyEngine(market_state=provider, config=config)
        
        # Create risk engine
        risk_config = RiskConfig()
        risk_engine = RiskEngine(config=risk_config)
        
        # Create weaviate service (in-memory)
        weaviate = WeaviateService()
        
        # Create execution service (shadow only)
        execution = ExecutionService(
            broker_service=None,  # No broker = shadow only
            weaviate_service=weaviate,
        )
        
        # Simulate a cycle
        now = datetime(2024, 1, 9, 9, 30, 0, tzinfo=timezone.utc)  # London Core
        
        # Get phase
        phase = provider.get_phase(now)
        self.assertEqual(phase, SessionPhase.LONDON_CORE)
        
        # Update candles
        provider.update_candle_from_price("CC.D.CL.UNC.IP")
        
        # Run strategy (may not find setups without proper range data)
        setups = engine.evaluate("CC.D.CL.UNC.IP", now)
        
        # Verify we got a list (may be empty)
        self.assertIsInstance(setups, list)
