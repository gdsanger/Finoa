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
        self.mock_broker.get_historical_prices.return_value = []

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

    def test_get_phase_crypto_asset_weekend_trading(self):
        """Test that crypto assets can trade on weekends (24/7)."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Create a mock crypto asset
        mock_crypto_asset = MagicMock()
        mock_crypto_asset.is_crypto = True
        mock_crypto_asset.broker = 'MEXC'
        mock_crypto_asset.symbol = 'ETHUSDT'
        mock_crypto_asset.epic = 'ETHUSDT'
        
        provider.set_current_asset(mock_crypto_asset)
        
        # Saturday 14:00 UTC - should return PRE_US_RANGE (not OTHER)
        ts = datetime(2024, 1, 13, 14, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.PRE_US_RANGE)
        
        # Saturday 16:00 UTC - should return US_CORE_TRADING (not OTHER)
        ts = datetime(2024, 1, 13, 16, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)

    def test_get_phase_crypto_asset_friday_late_trading(self):
        """Test that crypto assets can trade during Friday late hours (skip FRIDAY_LATE check)."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Create a mock crypto asset
        mock_crypto_asset = MagicMock()
        mock_crypto_asset.is_crypto = True
        mock_crypto_asset.broker = 'MEXC'
        mock_crypto_asset.symbol = 'ETHUSDT'
        mock_crypto_asset.epic = 'ETHUSDT'
        
        provider.set_current_asset(mock_crypto_asset)
        
        # Friday 21:00 UTC - within US_CORE_TRADING and would be FRIDAY_LATE for IG assets
        # For crypto, should return US_CORE_TRADING (not FRIDAY_LATE)
        ts = datetime(2024, 1, 12, 21, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.US_CORE_TRADING)

    def test_get_phase_ig_asset_weekend_blocked(self):
        """Test that IG assets are blocked on weekends."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Create a mock IG asset
        mock_ig_asset = MagicMock()
        mock_ig_asset.is_crypto = False
        mock_ig_asset.broker = 'IG'
        mock_ig_asset.symbol = 'OIL'
        mock_ig_asset.epic = 'CC.D.CL.UNC.IP'
        
        provider.set_current_asset(mock_ig_asset)
        
        # Saturday 14:00 UTC - should return OTHER
        ts = datetime(2024, 1, 13, 14, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.OTHER)

    def test_get_phase_ig_asset_friday_late_blocked(self):
        """Test that IG assets are blocked during Friday late hours."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Create a mock IG asset
        mock_ig_asset = MagicMock()
        mock_ig_asset.is_crypto = False
        mock_ig_asset.broker = 'IG'
        mock_ig_asset.symbol = 'OIL'
        mock_ig_asset.epic = 'CC.D.CL.UNC.IP'
        
        provider.set_current_asset(mock_ig_asset)
        
        # Friday 22:00 UTC - should return FRIDAY_LATE
        ts = datetime(2024, 1, 12, 22, 0, 0, tzinfo=timezone.utc)
        phase = provider.get_phase(ts)
        
        self.assertEqual(phase, SessionPhase.FRIDAY_LATE)

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

    def test_get_recent_candles_uses_ig_history_when_available(self):
        """Historical IG candles should be used when provided by the broker."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)

        self.mock_broker.get_historical_prices.return_value = [
            {"time": 1, "open": 1.0, "high": 1.5, "low": 0.8, "close": 1.2},
            {"time": 2, "open": 1.2, "high": 2.0, "low": 1.0, "close": 1.8},
        ]

        candles = provider.get_recent_candles("CC.D.CL.UNC.IP", "1m", 1)

        self.mock_broker.get_symbol_price.assert_not_called()
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].high, 2.0)
        self.assertEqual(candles[0].low, 1.0)

    def test_get_recent_candles_trims_to_limit(self):
        """Excess IG candles should be trimmed so only the newest N are used."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)

        self.mock_broker.get_historical_prices.return_value = [
            {"time": 1, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0},
            {"time": 2, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1},
            {"time": 3, "open": 1.2, "high": 1.3, "low": 1.1, "close": 1.2},
        ]

        candles = provider.get_recent_candles("CC.D.CL.UNC.IP", "1m", 2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].timestamp, datetime.fromtimestamp(2, tz=timezone.utc))
        self.assertEqual(candles[1].timestamp, datetime.fromtimestamp(3, tz=timezone.utc))

    def test_get_recent_candles_can_exclude_current_incomplete(self):
        """closed_only flag should drop the currently forming candle from IG history."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)

        candle_1 = datetime(2024, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
        candle_2 = datetime(2024, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
        candle_current = datetime(2024, 1, 1, 0, 3, 0, tzinfo=timezone.utc)

        self.mock_broker.get_historical_prices.return_value = [
            {"time": int(candle_1.timestamp()), "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0},
            {"time": int(candle_2.timestamp()), "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1},
            {"time": int(candle_current.timestamp()), "open": 1.2, "high": 1.5, "low": 1.0, "close": 1.3},
        ]

        with patch(
            "core.services.broker.ig_market_state_provider.datetime",
            wraps=datetime,
        ) as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 0, 3, 30, tzinfo=timezone.utc)
            candles = provider.get_recent_candles("CC.D.CL.UNC.IP", "1m", 1, closed_only=True)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].timestamp, candle_2)

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

    def test_update_candle_from_price_with_broker_registry(self):
        """Test that update_candle_from_price uses the BrokerRegistry to get the correct broker.
        
        This tests the fix for the MEXC/IG broker mixing issue where the provider
        should use the asset-specific broker via BrokerRegistry for candle updates.
        """
        from trading.models import TradingAsset
        
        # Create a default broker (simulating IG)
        default_broker = MagicMock()
        default_broker_price = SymbolPrice(
            epic="IG_EPIC",
            market_name="IG Market",
            bid=Decimal("100.00"),
            ask=Decimal("100.05"),
            spread=Decimal("0.05"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
        )
        default_broker.get_symbol_price.return_value = default_broker_price
        
        # Create an alternate broker (simulating MEXC)
        mexc_broker = MagicMock()
        mexc_price = SymbolPrice(
            epic="ETHUSDT",
            market_name="ETH/USDT",
            bid=Decimal("3000.00"),
            ask=Decimal("3000.10"),
            spread=Decimal("0.10"),
            high=Decimal("3050.00"),
            low=Decimal("2950.00"),
        )
        mexc_broker.get_symbol_price.return_value = mexc_price
        
        # Create a mock BrokerRegistry that returns the MEXC broker
        mock_registry = MagicMock()
        mock_registry.get_broker_for_asset.return_value = mexc_broker
        
        # Create a test asset for MEXC
        asset = TradingAsset.objects.create(
            name="ETH/USDT",
            symbol="ETH/USDT",
            epic="ETHUSDT",
            broker=TradingAsset.BrokerKind.MEXC,
            broker_symbol="ETHUSDT",
            category="crypto",
            tick_size="0.01",
            is_active=True,
        )
        
        # Initialize provider with default broker and registry
        provider = IGMarketStateProvider(
            broker_service=default_broker,
            broker_registry=mock_registry,
        )
        
        # Set the current asset (this tells the provider which asset we're working with)
        provider.set_current_asset(asset)
        
        # Update candle - should automatically use MEXC broker via registry
        provider.update_candle_from_price()
        
        # Verify that the registry was used to get the MEXC broker
        mock_registry.get_broker_for_asset.assert_called_once_with(asset)
        mexc_broker.get_symbol_price.assert_called_once_with("ETHUSDT")
        default_broker.get_symbol_price.assert_not_called()
        
        # Verify the candle was cached correctly
        candles = provider._candle_cache.get("ETHUSDT_1m", [])
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].close, 3000.05)  # mid_price of mexc_price

    def test_update_candle_from_price_default_broker_fallback(self):
        """Test that update_candle_from_price falls back to default broker when no registry/asset is set."""
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Update candle with epic - should use default broker
        provider.update_candle_from_price("CC.D.CL.UNC.IP")
        
        # Verify the default broker was used
        self.mock_broker.get_symbol_price.assert_called_once_with("CC.D.CL.UNC.IP")

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
    
    def test_set_session_times_logs_us_core_trading(self):
        """Test that set_session_times logs US Core Trading times correctly."""
        from core.services.broker import SessionTimesConfig
        import logging
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Configure custom US Core Trading times
        session_times = SessionTimesConfig.from_time_strings(
            us_core_trading_start="15:00",
            us_core_trading_end="22:00",
        )
        
        # Capture log output
        with self.assertLogs('core.services.broker.ig_market_state_provider', level='INFO') as cm:
            provider.set_session_times(session_times)
        
        # Verify log message contains "US Core Trading" not "US Core"
        self.assertTrue(any('US Core Trading 15:00 - 22:00' in log for log in cm.output))


class IGMarketStateProviderDbFallbackTest(TestCase):
    """Tests for IGMarketStateProvider database fallback for ranges."""

    def setUp(self):
        """Set up test fixtures."""
        from trading.models import TradingAsset
        
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
        
        # Create a test asset
        self.asset = TradingAsset.objects.create(
            name="Test Oil",
            symbol="OIL",
            epic="CC.D.CL.UNC.IP",
            category="commodity",
            tick_size="0.01",
            is_active=True,
        )

    def test_asia_range_falls_back_to_database(self):
        """Test that get_asia_range falls back to database when cache is empty."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Associate asset with provider
        provider.set_current_asset(self.asset)
        
        # Initially, cache should be empty
        # Without DB fallback, this would return None
        self.assertIsNone(provider._asia_range_cache.get("CC.D.CL.UNC.IP"))
        
        # Create a range in the database
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=2),
            high=Decimal("75.50"),
            low=Decimal("74.50"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # Now get_asia_range should load from database
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        
        self.assertIsNotNone(result)
        self.assertEqual(result, (75.50, 74.50))
        
        # Verify it was also cached
        self.assertEqual(provider._asia_range_cache.get("CC.D.CL.UNC.IP"), (75.50, 74.50))

    def test_pre_us_range_falls_back_to_database(self):
        """Test that get_pre_us_range falls back to database when cache is empty."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Associate asset with provider
        provider.set_current_asset(self.asset)
        
        # Initially, cache should be empty
        self.assertIsNone(provider._pre_us_range_cache.get("CC.D.CL.UNC.IP"))
        
        # Create a range in the database
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='PRE_US_RANGE',
            start_time=now - timedelta(hours=4),
            end_time=now - timedelta(hours=2),
            high=Decimal("76.00"),
            low=Decimal("75.00"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # Now get_pre_us_range should load from database
        result = provider.get_pre_us_range("CC.D.CL.UNC.IP")
        
        self.assertIsNotNone(result)
        self.assertEqual(result, (76.00, 75.00))
        
        # Verify it was also cached
        self.assertEqual(provider._pre_us_range_cache.get("CC.D.CL.UNC.IP"), (76.00, 75.00))

    def test_london_core_range_falls_back_to_database(self):
        """Test that get_london_core_range falls back to database when cache is empty."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Associate asset with provider
        provider.set_current_asset(self.asset)
        
        # Initially, cache should be empty
        self.assertIsNone(provider._london_core_range_cache.get("CC.D.CL.UNC.IP"))
        
        # Create a range in the database
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='LONDON_CORE',
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(hours=2),
            high=Decimal("75.80"),
            low=Decimal("74.80"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # Now get_london_core_range should load from database
        result = provider.get_london_core_range("CC.D.CL.UNC.IP")
        
        self.assertIsNotNone(result)
        self.assertEqual(result, (75.80, 74.80))
        
        # Verify it was also cached
        self.assertEqual(provider._london_core_range_cache.get("CC.D.CL.UNC.IP"), (75.80, 74.80))

    def test_range_not_loaded_if_too_old(self):
        """Test that ranges older than 24 hours are not loaded from database."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        # Create an old range in the database (25 hours ago)
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=30),
            end_time=now - timedelta(hours=25),  # Ended 25 hours ago
            high=Decimal("75.50"),
            low=Decimal("74.50"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # get_asia_range should not load this old range
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        
        self.assertIsNone(result)

    def test_range_not_loaded_if_invalid(self):
        """Test that invalid ranges are not loaded from database."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        # Create an invalid range
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=2),
            high=Decimal("75.50"),
            low=Decimal("74.50"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=False,  # Invalid!
        )
        
        # get_asia_range should not load this invalid range
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        
        self.assertIsNone(result)

    def test_range_not_loaded_without_current_asset(self):
        """Test that ranges are not loaded if no current asset is set."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        
        # Don't set current asset
        
        # Create a range in the database
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=2),
            high=Decimal("75.50"),
            low=Decimal("74.50"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # get_asia_range should return None because no current asset
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        
        self.assertIsNone(result)

    def test_cache_takes_precedence_over_database(self):
        """Test that cached values are used when available."""
        from trading.models import BreakoutRange
        from datetime import timedelta
        
        provider = IGMarketStateProvider(broker_service=self.mock_broker)
        provider.set_current_asset(self.asset)
        
        # Set cache value directly
        provider._asia_range_cache["CC.D.CL.UNC.IP"] = (80.00, 79.00)
        
        # Create a different range in the database
        now = datetime.now(timezone.utc)
        BreakoutRange.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=2),
            high=Decimal("75.50"),
            low=Decimal("74.50"),
            height_ticks=100,
            height_points=Decimal("1.00"),
            is_valid=True,
        )
        
        # get_asia_range should return cached value, not database
        result = provider.get_asia_range("CC.D.CL.UNC.IP")
        
        self.assertEqual(result, (80.00, 79.00))


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

    @patch('core.services.broker.config.create_ig_broker_service')
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

    @patch('core.services.broker.config.create_ig_broker_service')
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

    @patch('core.services.broker.config.create_ig_broker_service')
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

    @patch('core.services.broker.config.create_ig_broker_service')
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


class SessionPhaseConfigIntegrationTest(TestCase):
    """Integration tests for AssetSessionPhaseConfig and worker behavior."""
    
    def setUp(self):
        """Set up test fixtures."""
        from trading.models import TradingAsset, AssetSessionPhaseConfig
        
        # Create a test asset
        self.asset = TradingAsset.objects.create(
            name="Test Oil",
            symbol="OIL",
            epic="CC.D.CL.UNC.IP",
            category="commodity",
            tick_size="0.01",
            is_active=True,
        )
        
        # Create session phase configs for the asset
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
            is_trading_phase=False,
            enabled=True,
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='PRE_US_RANGE',
            start_time_utc='13:00',
            end_time_utc='15:00',
            is_range_build_phase=True,
            is_trading_phase=False,
            enabled=True,
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='US_CORE_TRADING',
            start_time_utc='15:00',
            end_time_utc='22:00',
            is_range_build_phase=False,
            is_trading_phase=True,
            enabled=True,
        )
    
    def test_session_phase_config_get_phases_for_asset(self):
        """Test getting session phase configs for an asset."""
        from trading.models import AssetSessionPhaseConfig
        
        configs = AssetSessionPhaseConfig.get_phases_for_asset(self.asset)
        
        self.assertEqual(configs.count(), 3)
        
        # Verify US_CORE_TRADING config has correct flags
        us_core_trading = configs.get(phase='US_CORE_TRADING')
        self.assertTrue(us_core_trading.is_trading_phase)
        self.assertFalse(us_core_trading.is_range_build_phase)
        self.assertEqual(us_core_trading.start_time_utc, '15:00')
        self.assertEqual(us_core_trading.end_time_utc, '22:00')
    
    def test_session_phase_config_is_trading_phase_flag(self):
        """Test that is_trading_phase flag is correctly set for trading phases."""
        from trading.models import AssetSessionPhaseConfig
        
        # PRE_US_RANGE should NOT be tradeable
        pre_us = AssetSessionPhaseConfig.objects.get(asset=self.asset, phase='PRE_US_RANGE')
        self.assertFalse(pre_us.is_trading_phase)
        
        # US_CORE_TRADING should be tradeable
        us_trading = AssetSessionPhaseConfig.objects.get(asset=self.asset, phase='US_CORE_TRADING')
        self.assertTrue(us_trading.is_trading_phase)
    
    def test_session_times_config_from_phase_configs(self):
        """Test building SessionTimesConfig from AssetSessionPhaseConfig."""
        from trading.models import AssetSessionPhaseConfig
        from core.services.broker import SessionTimesConfig
        
        configs = AssetSessionPhaseConfig.get_enabled_phases_for_asset(self.asset)
        
        # Build session times from configs
        session_times_kwargs = {}
        for pc in configs:
            if pc.phase == 'ASIA_RANGE':
                session_times_kwargs['asia_start'] = pc.start_time_utc
                session_times_kwargs['asia_end'] = pc.end_time_utc
            elif pc.phase == 'PRE_US_RANGE':
                session_times_kwargs['pre_us_start'] = pc.start_time_utc
                session_times_kwargs['pre_us_end'] = pc.end_time_utc
            elif pc.phase == 'US_CORE_TRADING':
                session_times_kwargs['us_core_trading_start'] = pc.start_time_utc
                session_times_kwargs['us_core_trading_end'] = pc.end_time_utc
                session_times_kwargs['us_core_trading_enabled'] = pc.enabled
        
        session_times = SessionTimesConfig.from_time_strings(**session_times_kwargs)
        
        self.assertEqual(session_times.asia_start, 0)
        self.assertEqual(session_times.asia_end, 8)
        self.assertEqual(session_times.pre_us_start, 13)
        self.assertEqual(session_times.pre_us_end, 15)
        self.assertEqual(session_times.us_core_trading_start, 15)
        self.assertEqual(session_times.us_core_trading_end, 22)
        self.assertTrue(session_times.us_core_trading_enabled)


class WorkerAssetDiagnosticsTest(TestCase):
    """Tests for worker creating AssetDiagnostics records."""
    
    def setUp(self):
        """Set up test fixtures."""
        from trading.models import TradingAsset, AssetSessionPhaseConfig
        
        # Create a test asset
        self.asset = TradingAsset.objects.create(
            name="Test Oil",
            symbol="OIL",
            epic="CC.D.CL.UNC.IP",
            category="commodity",
            tick_size="0.01",
            is_active=True,
            trading_mode='STRICT',
        )
        
        # Create session phase configs for the asset
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='ASIA_RANGE',
            start_time_utc='00:00',
            end_time_utc='08:00',
            is_range_build_phase=True,
            is_trading_phase=False,
            enabled=True,
        )
        AssetSessionPhaseConfig.objects.create(
            asset=self.asset,
            phase='US_CORE_TRADING',
            start_time_utc='15:00',
            end_time_utc='22:00',
            is_range_build_phase=False,
            is_trading_phase=True,
            enabled=True,
        )
    
    def test_update_asset_diagnostics_creates_record(self):
        """Test that _update_asset_diagnostics creates a diagnostics record."""
        from trading.models import AssetDiagnostics
        from core.management.commands.run_fiona_worker import Command
        
        # Create command instance
        cmd = Command()
        
        # Call _update_asset_diagnostics
        now = datetime(2024, 1, 15, 16, 30, 0, tzinfo=timezone.utc)
        cmd._update_asset_diagnostics(
            asset=self.asset,
            now=now,
            phase=SessionPhase.US_CORE_TRADING,
            setups_found=2,
            candles_evaluated=1,
            range_built_phase=None,
        )
        
        # Verify diagnostics record was created
        diagnostics = AssetDiagnostics.objects.filter(asset=self.asset).first()
        self.assertIsNotNone(diagnostics)
        self.assertEqual(diagnostics.setups_generated_total, 2)
        self.assertEqual(diagnostics.candles_evaluated, 1)
        self.assertEqual(diagnostics.current_phase, 'US_CORE_TRADING')
        self.assertEqual(diagnostics.trading_mode, 'STRICT')
        self.assertIsNotNone(diagnostics.last_cycle_at)
    
    def test_update_asset_diagnostics_aggregates_data(self):
        """Test that _update_asset_diagnostics aggregates data within same window."""
        from trading.models import AssetDiagnostics
        from core.management.commands.run_fiona_worker import Command
        
        # Create command instance
        cmd = Command()
        
        # Call twice within the same hour window
        now1 = datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        cmd._update_asset_diagnostics(
            asset=self.asset,
            now=now1,
            phase=SessionPhase.US_CORE_TRADING,
            setups_found=1,
            candles_evaluated=1,
            range_built_phase=None,
        )
        
        now2 = datetime(2024, 1, 15, 16, 30, 0, tzinfo=timezone.utc)
        cmd._update_asset_diagnostics(
            asset=self.asset,
            now=now2,
            phase=SessionPhase.US_CORE_TRADING,
            setups_found=2,
            candles_evaluated=1,
            range_built_phase=None,
        )
        
        # Should have only one record (same window)
        diagnostics_count = AssetDiagnostics.objects.filter(asset=self.asset).count()
        self.assertEqual(diagnostics_count, 1)
        
        # Values should be aggregated
        diagnostics = AssetDiagnostics.objects.filter(asset=self.asset).first()
        self.assertEqual(diagnostics.setups_generated_total, 3)  # 1 + 2
        self.assertEqual(diagnostics.candles_evaluated, 2)  # 1 + 1
    
    def test_update_asset_diagnostics_tracks_range_built(self):
        """Test that _update_asset_diagnostics tracks range built phases."""
        from trading.models import AssetDiagnostics
        from core.management.commands.run_fiona_worker import Command
        
        # Create command instance
        cmd = Command()
        
        # Update with asia range built
        now = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
        cmd._update_asset_diagnostics(
            asset=self.asset,
            now=now,
            phase=SessionPhase.ASIA_RANGE,
            setups_found=0,
            candles_evaluated=1,
            range_built_phase='asia',
        )
        
        diagnostics = AssetDiagnostics.objects.filter(asset=self.asset).first()
        self.assertEqual(diagnostics.ranges_built_asia, 1)
        self.assertEqual(diagnostics.ranges_built_london, 0)
    
    def test_diagnostics_queryable_for_period(self):
        """Test that diagnostics can be queried for a time period."""
        from trading.models import AssetDiagnostics
        from core.management.commands.run_fiona_worker import Command
        
        # Create command instance
        cmd = Command()
        
        # Create diagnostics at different times (4 different hours = 4 different windows)
        for hour in [14, 15, 16, 17]:
            now = datetime(2024, 1, 15, hour, 30, 0, tzinfo=timezone.utc)
            cmd._update_asset_diagnostics(
                asset=self.asset,
                now=now,
                phase=SessionPhase.US_CORE_TRADING,
                setups_found=1,
                candles_evaluated=1,
                range_built_phase=None,
            )
        
        # Query for a window that overlaps only with hours 15 and 16 (not 14 and 17)
        # Window 15:00-16:00 has window_end=16:00, window_start=15:00
        # Window 16:00-17:00 has window_end=17:00, window_start=16:00
        # Query: window_end >= 15:01, window_start <= 16:59 (excludes 14:00-15:00 and 17:00-18:00)
        start = datetime(2024, 1, 15, 15, 1, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 16, 59, 0, tzinfo=timezone.utc)
        
        aggregated = AssetDiagnostics.get_aggregated_for_period(self.asset, start, end)
        
        # Should have 2 records in window (15:00-16:00 and 16:00-17:00)
        self.assertEqual(aggregated['record_count'], 2)
        self.assertEqual(aggregated['counters']['setups']['generated_total'], 2)
        self.assertEqual(aggregated['counters']['candles_evaluated'], 2)
