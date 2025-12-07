"""Tests for candle storage fixes.

Tests to verify:
1. Only one candle per minute is stored in Redis
2. Gaps are filled with zero-volume candles
3. Open/Close values are correct (open=first price, close=last price)
"""
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import MagicMock, patch

from core.services.broker.kraken_broker_service import KrakenBrokerService, KrakenBrokerConfig
from core.services.broker.models import Candle1m
from core.services.market_data.candle_models import Candle
from core.services.market_data.redis_candle_store import RedisCandleStore


class TestRedisCandleStoreDuplicatePrevention(TestCase):
    """Test that Redis candle store prevents duplicate candles per minute."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = RedisCandleStore()
        # Use in-memory fallback for tests
        self.store._redis_client = None
        self.store._connected = False
    
    def test_append_candle_replaces_duplicate_timestamp(self):
        """Test that appending a candle with the same timestamp replaces the old one."""
        asset_id = "TEST_ASSET"
        timeframe = "1m"
        
        # Create first candle
        ts = int(datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        candle1 = Candle(
            timestamp=ts,
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=1000.0,
            trade_count=10,
        )
        
        # Append first candle
        self.store.append_candle(asset_id, timeframe, candle1)
        
        # Create second candle with SAME timestamp but different values
        candle2 = Candle(
            timestamp=ts,
            open=100.0,
            high=106.0,
            low=98.0,
            close=103.0,
            volume=1500.0,
            trade_count=15,
        )
        
        # Append second candle (should replace first)
        self.store.append_candle(asset_id, timeframe, candle2)
        
        # Load candles
        candles = self.store.load_candles(asset_id, timeframe)
        
        # Should only have ONE candle with the updated values
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].timestamp, ts)
        self.assertEqual(candles[0].high, 106.0)
        self.assertEqual(candles[0].low, 98.0)
        self.assertEqual(candles[0].close, 103.0)
        self.assertEqual(candles[0].volume, 1500.0)
        self.assertEqual(candles[0].trade_count, 15)
    
    def test_append_candles_batch_replaces_duplicates(self):
        """Test that batch append replaces duplicate timestamps."""
        asset_id = "TEST_ASSET"
        timeframe = "1m"
        
        # Create first set of candles
        ts1 = int(datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        ts2 = int(datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc).timestamp())
        
        candles1 = [
            Candle(timestamp=ts1, open=100.0, high=105.0, low=99.0, close=102.0, volume=1000.0),
            Candle(timestamp=ts2, open=102.0, high=107.0, low=101.0, close=105.0, volume=1200.0),
        ]
        
        self.store.append_candles(asset_id, timeframe, candles1)
        
        # Create second set with duplicate timestamp (ts1)
        candles2 = [
            Candle(timestamp=ts1, open=100.0, high=108.0, low=97.0, close=104.0, volume=1500.0),
        ]
        
        self.store.append_candles(asset_id, timeframe, candles2)
        
        # Load all candles
        candles = self.store.load_candles(asset_id, timeframe)
        
        # Should have 2 candles total (ts1 replaced, ts2 unchanged)
        self.assertEqual(len(candles), 2)
        
        # Find ts1 candle
        ts1_candle = next(c for c in candles if c.timestamp == ts1)
        self.assertEqual(ts1_candle.high, 108.0)
        self.assertEqual(ts1_candle.low, 97.0)
        self.assertEqual(ts1_candle.close, 104.0)
        self.assertEqual(ts1_candle.volume, 1500.0)


class TestKrakenCandleOpenCloseCorrectness(TestCase):
    """Test that open/close values are assigned correctly."""
    
    def setUp(self):
        """Set up test fixtures."""
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        self.service = KrakenBrokerService(config)
        self.service._connected = True
        self.service._session = MagicMock()
        self.service._candle_store_enabled = False
    
    def test_open_is_first_close_is_last_price(self):
        """Test that open=first price and close=last price in a minute."""
        from django.utils import timezone as dj_timezone
        
        base_time = dj_timezone.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        
        # Trade 1 at beginning of minute: price=100
        self.service._update_candle("PI_XBTUSD", 100.0, 1.0, base_time.replace(second=5))
        
        # Trade 2 in middle: price=105
        self.service._update_candle("PI_XBTUSD", 105.0, 1.0, base_time.replace(second=30))
        
        # Trade 3 at end: price=98
        self.service._update_candle("PI_XBTUSD", 98.0, 1.0, base_time.replace(second=55))
        
        # Get current candle
        current = self.service._current_candle.get("PI_XBTUSD")
        
        # Verify: open should be first price (100), close should be last price (98)
        self.assertIsNotNone(current)
        self.assertEqual(current["open"], 100.0, "Open should be first trade price")
        self.assertEqual(current["close"], 98.0, "Close should be last trade price")
        self.assertEqual(current["high"], 105.0)
        self.assertEqual(current["low"], 98.0)
    
    def test_single_trade_open_equals_close(self):
        """Test that with a single trade, open=close."""
        from django.utils import timezone as dj_timezone
        
        base_time = dj_timezone.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        
        # Only one trade
        self.service._update_candle("PI_XBTUSD", 100.0, 1.0, base_time.replace(second=30))
        
        # Get current candle
        current = self.service._current_candle.get("PI_XBTUSD")
        
        # With single trade, open and close should be the same
        self.assertIsNotNone(current)
        self.assertEqual(current["open"], 100.0)
        self.assertEqual(current["close"], 100.0)
        self.assertEqual(current["high"], 100.0)
        self.assertEqual(current["low"], 100.0)


class TestKrakenCandleGapFilling(TestCase):
    """Test that gaps in candle data are filled with zero-volume candles."""
    
    def setUp(self):
        """Set up test fixtures."""
        config = KrakenBrokerConfig(
            api_key="test-key",
            api_secret="test-secret",
            default_symbol="PI_XBTUSD",
            use_demo=True,
        )
        
        self.service = KrakenBrokerService(config)
        self.service._connected = True
        self.service._session = MagicMock()
        self.service._candle_store_enabled = False
    
    def test_fill_candle_gaps_with_zero_volume(self):
        """Test that gaps are filled with zero-volume candles."""
        from django.utils import timezone as dj_timezone
        
        base_time = dj_timezone.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        
        # Create candles with gaps
        candles = [
            Candle1m(
                symbol="PI_XBTUSD",
                time=base_time,
                open=100.0,
                high=105.0,
                low=99.0,
                close=102.0,
                volume=1000.0,
                trade_count=10,
            ),
            # Gap of 2 minutes
            Candle1m(
                symbol="PI_XBTUSD",
                time=base_time + timedelta(minutes=3),
                open=102.0,
                high=108.0,
                low=101.0,
                close=106.0,
                volume=1200.0,
                trade_count=12,
            ),
        ]
        
        # Fill gaps
        filled = self.service._fill_candle_gaps(candles, "PI_XBTUSD")
        
        # Should have 4 candles total (original 2 + 2 gap candles)
        self.assertEqual(len(filled), 4)
        
        # Verify gap candles
        gap1 = filled[1]
        self.assertEqual(gap1.time, base_time + timedelta(minutes=1))
        self.assertEqual(gap1.open, 102.0, "Gap candle should use last known close")
        self.assertEqual(gap1.close, 102.0)
        self.assertEqual(gap1.high, 102.0)
        self.assertEqual(gap1.low, 102.0)
        self.assertEqual(gap1.volume, 0.0, "Gap candle should have zero volume")
        self.assertEqual(gap1.trade_count, 0)
        
        gap2 = filled[2]
        self.assertEqual(gap2.time, base_time + timedelta(minutes=2))
        self.assertEqual(gap2.volume, 0.0)
        self.assertEqual(gap2.trade_count, 0)
    
    def test_no_gaps_no_filling(self):
        """Test that consecutive candles are not modified."""
        from django.utils import timezone as dj_timezone
        
        base_time = dj_timezone.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        
        # Create consecutive candles (no gaps)
        candles = [
            Candle1m(
                symbol="PI_XBTUSD",
                time=base_time,
                open=100.0,
                high=105.0,
                low=99.0,
                close=102.0,
                volume=1000.0,
                trade_count=10,
            ),
            Candle1m(
                symbol="PI_XBTUSD",
                time=base_time + timedelta(minutes=1),
                open=102.0,
                high=108.0,
                low=101.0,
                close=106.0,
                volume=1200.0,
                trade_count=12,
            ),
        ]
        
        # Fill gaps (should not add any)
        filled = self.service._fill_candle_gaps(candles, "PI_XBTUSD")
        
        # Should have same 2 candles
        self.assertEqual(len(filled), 2)
        self.assertEqual(filled[0].time, base_time)
        self.assertEqual(filled[1].time, base_time + timedelta(minutes=1))
