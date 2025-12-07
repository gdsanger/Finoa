"""
Tests for the Kraken Market Data Worker management command.

Tests cover asset processing, exception handling, and data fetching logic.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, Mock
from io import StringIO

from django.test import TestCase
from django.core.management import call_command

from core.services.broker.kraken_broker_service import KrakenBrokerService
from core.services.broker.models import Candle1m
from trading.models import TradingAsset
from core.management.commands.run_kraken_market_data_worker import (
    KrakenMarketDataWorker,
)


class KrakenMarketDataWorkerTest(TestCase):
    """Tests for KrakenMarketDataWorker."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock broker
        self.mock_broker = MagicMock(spec=KrakenBrokerService)
        self.mock_broker.is_candle_store_enabled.return_value = True
        self.mock_broker.store_candle_to_redis = Mock()
        
        # Create test assets
        self.asset1 = TradingAsset.objects.create(
            symbol="BTC/USD",
            epic="PI_XBTUSD",
            broker_symbol="PI_XBTUSD",
            name="Bitcoin",
            broker=TradingAsset.BrokerKind.KRAKEN,
            is_active=True,
            tick_size=0.5,
        )
        
        self.asset2 = TradingAsset.objects.create(
            symbol="ETH/USD",
            epic="PI_ETHUSD",
            broker_symbol="PI_ETHUSD",
            name="Ethereum",
            broker=TradingAsset.BrokerKind.KRAKEN,
            is_active=True,
            tick_size=0.05,
        )
        
        # Create sample candles (mimicking Charts API response - no trade_count)
        now = datetime.now(timezone.utc)
        self.sample_candles = [
            Candle1m(
                symbol="PI_XBTUSD",
                time=now - timedelta(hours=1, minutes=i),
                open=50000.0 + i,
                high=50100.0 + i,
                low=49900.0 + i,
                close=50050.0 + i,
                volume=100.0,
                trade_count=0,  # Charts API doesn't provide trade count
            )
            for i in range(5)
        ]

    def test_process_asset_fetches_12_hours(self):
        """Test that _process_asset fetches 12 hours of candle data with mark tick_type."""
        # Mock the fetch_candles_from_charts_api method
        self.mock_broker.fetch_candles_from_charts_api.return_value = self.sample_candles
        
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1])
        worker._process_asset(self.asset1)
        
        # Verify that fetch_candles_from_charts_api was called
        self.mock_broker.fetch_candles_from_charts_api.assert_called_once()
        call_args = self.mock_broker.fetch_candles_from_charts_api.call_args
        
        # Verify symbol parameter
        self.assertEqual(call_args.kwargs['symbol'], 'PI_XBTUSD')
        self.assertEqual(call_args.kwargs['resolution'], '1m')
        # Verify tick_type is 'mark'
        self.assertEqual(call_args.kwargs['tick_type'], 'mark')
        
        # Verify time window is 12 hours
        from_ts = call_args.kwargs['from_timestamp']
        to_ts = call_args.kwargs['to_timestamp']
        time_diff_hours = (to_ts - from_ts) / (1000 * 60 * 60)  # Convert ms to hours
        self.assertAlmostEqual(time_diff_hours, 12.0, delta=0.1)

    def test_process_all_assets_despite_exception(self):
        """Test that exceptions in one asset don't stop processing other assets."""
        # Make the first asset fail but second succeed
        def side_effect(symbol, **kwargs):
            if symbol == "PI_XBTUSD":
                raise Exception("API error for BTC")
            return self.sample_candles
        
        self.mock_broker.fetch_candles_from_charts_api.side_effect = side_effect
        
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1, self.asset2])
        
        # Process both assets
        worker._process_asset(self.asset1)
        worker._process_asset(self.asset2)
        
        # Verify both assets were attempted
        self.assertEqual(
            self.mock_broker.fetch_candles_from_charts_api.call_count, 2
        )
        
        # Verify second asset processed successfully
        # (candles were stored for the second asset)
        store_calls = self.mock_broker.store_candle_to_redis.call_args_list
        # Should have stored candles for ETH but not BTC
        self.assertGreater(len(store_calls), 0)

    def test_process_asset_stores_candles_in_redis(self):
        """Test that fetched candles are stored in Redis."""
        self.mock_broker.fetch_candles_from_charts_api.return_value = self.sample_candles
        
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1])
        worker._process_asset(self.asset1)
        
        # Verify all candles were stored
        self.assertEqual(
            self.mock_broker.store_candle_to_redis.call_count,
            len(self.sample_candles)
        )

    def test_process_asset_handles_no_candles(self):
        """Test that _process_asset handles empty candle response gracefully."""
        self.mock_broker.fetch_candles_from_charts_api.return_value = []
        
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1])
        
        # Should not raise an exception
        try:
            worker._process_asset(self.asset1)
        except Exception as e:
            self.fail(f"_process_asset raised exception with empty candles: {e}")
        
        # Verify fetch was called but no storage happened
        self.mock_broker.fetch_candles_from_charts_api.assert_called_once()
        self.mock_broker.store_candle_to_redis.assert_not_called()

    def test_process_asset_exception_handling(self):
        """Test that exceptions in _process_asset are caught and logged."""
        # Make the broker raise an exception during storage
        self.mock_broker.fetch_candles_from_charts_api.return_value = self.sample_candles
        self.mock_broker.store_candle_to_redis.side_effect = Exception("Redis error")
        
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1])
        
        # Should not raise an exception (it should be caught)
        try:
            worker._process_asset(self.asset1)
        except Exception as e:
            self.fail(f"_process_asset raised exception instead of catching it: {e}")
    
    def test_subsequent_run_fetches_only_newest_candle(self):
        """Test that subsequent runs only fetch and store the newest candle."""
        # First run - establish last_ts
        self.mock_broker.fetch_candles_from_charts_api.return_value = self.sample_candles
        worker = KrakenMarketDataWorker(self.mock_broker, [self.asset1])
        worker._process_asset(self.asset1)
        
        # Reset mock
        self.mock_broker.reset_mock()
        
        # Second run - should fetch recent data and only store newest
        now = datetime.now(timezone.utc)
        new_candle = Candle1m(
            symbol="PI_XBTUSD",
            time=now,
            open=51000.0,
            high=51100.0,
            low=50900.0,
            close=51050.0,
            volume=150.0,
            trade_count=0,  # Charts API doesn't provide trade count
        )
        self.mock_broker.fetch_candles_from_charts_api.return_value = [new_candle]
        
        worker._process_asset(self.asset1)
        
        # Verify fetch was called with shorter time window (5 minutes)
        call_args = self.mock_broker.fetch_candles_from_charts_api.call_args
        from_ts = call_args.kwargs['from_timestamp']
        to_ts = call_args.kwargs['to_timestamp']
        time_diff_minutes = (to_ts - from_ts) / (1000 * 60)  # Convert ms to minutes
        self.assertAlmostEqual(time_diff_minutes, 5.0, delta=0.5)
        
        # Verify only one candle was stored (the newest)
        self.mock_broker.store_candle_to_redis.assert_called_once()
        stored_candle = self.mock_broker.store_candle_to_redis.call_args[0][1]
        self.assertEqual(stored_candle.time, new_candle.time)


class KrakenMarketDataWorkerCommandTest(TestCase):
    """Tests for the run_kraken_market_data_worker management command."""

    @patch('core.management.commands.run_kraken_market_data_worker.BrokerRegistry')
    @patch('core.management.commands.run_kraken_market_data_worker.KrakenMarketDataWorker')
    def test_command_with_no_active_assets(self, mock_worker_class, mock_registry_class):
        """Test command behavior when no active Kraken assets are configured."""
        out = StringIO()
        call_command('run_kraken_market_data_worker', stdout=out)
        
        # Should print warning and exit without creating worker
        output = out.getvalue()
        self.assertIn("No active Kraken assets", output)
        mock_worker_class.assert_not_called()

    @patch('core.management.commands.run_kraken_market_data_worker.BrokerRegistry')
    @patch('core.management.commands.run_kraken_market_data_worker.KrakenMarketDataWorker')
    def test_command_creates_worker_with_active_assets(self, mock_worker_class, mock_registry_class):
        """Test command creates worker when active assets exist."""
        # Create a test asset
        TradingAsset.objects.create(
            symbol="BTC/USD",
            epic="PI_XBTUSD",
            broker_symbol="PI_XBTUSD",
            name="Bitcoin",
            broker=TradingAsset.BrokerKind.KRAKEN,
            is_active=True,
            tick_size=0.5,
        )
        
        # Mock broker registry
        mock_broker = MagicMock(spec=KrakenBrokerService)
        mock_registry = MagicMock()
        mock_registry.get_kraken_broker.return_value = mock_broker
        mock_registry_class.return_value = mock_registry
        
        # Mock worker to prevent actual execution
        mock_worker = MagicMock()
        mock_worker_class.return_value = mock_worker
        
        # Prevent the worker from actually running
        mock_worker.run.side_effect = KeyboardInterrupt()
        
        out = StringIO()
        try:
            call_command('run_kraken_market_data_worker', stdout=out)
        except KeyboardInterrupt:
            pass
        
        # Verify worker was created with the asset and broker
        mock_worker_class.assert_called_once()
        args = mock_worker_class.call_args
        assets = args[0][1]  # Second argument is the assets list
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].symbol, "BTC/USD")
