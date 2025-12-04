"""
Tests for the Strategy Engine module.

These tests cover the data models, configuration, and strategy logic
for breakout and EIA setups.
"""
from datetime import datetime, timezone
from decimal import Decimal
from django.test import TestCase

from core.services.strategy import (
    SetupKind,
    SessionPhase,
    BreakoutContext,
    EiaContext,
    Candle,
    SetupCandidate,
    StrategyConfig,
    BreakoutConfig,
    EiaConfig,
    AsiaRangeConfig,
    UsCoreConfig,
    MarketStateProvider,
    BaseMarketStateProvider,
    StrategyEngine,
    DiagnosticCriterion,
    EvaluationResult,
)


class SetupKindEnumTest(TestCase):
    """Tests for SetupKind enum."""

    def test_setup_kind_values(self):
        """Test SetupKind enum values."""
        self.assertEqual(SetupKind.BREAKOUT.value, "BREAKOUT")
        self.assertEqual(SetupKind.EIA_REVERSION.value, "EIA_REVERSION")
        self.assertEqual(SetupKind.EIA_TRENDDAY.value, "EIA_TRENDDAY")

    def test_setup_kind_is_string_subclass(self):
        """Test that SetupKind is a string subclass for JSON serialization."""
        self.assertIsInstance(SetupKind.BREAKOUT, str)


class SessionPhaseEnumTest(TestCase):
    """Tests for SessionPhase enum."""

    def test_session_phase_values(self):
        """Test SessionPhase enum values."""
        self.assertEqual(SessionPhase.ASIA_RANGE.value, "ASIA_RANGE")
        self.assertEqual(SessionPhase.LONDON_CORE.value, "LONDON_CORE")
        self.assertEqual(SessionPhase.PRE_US_RANGE.value, "PRE_US_RANGE")
        self.assertEqual(SessionPhase.US_CORE_TRADING.value, "US_CORE_TRADING")
        self.assertEqual(SessionPhase.US_CORE.value, "US_CORE")
        self.assertEqual(SessionPhase.EIA_PRE.value, "EIA_PRE")
        self.assertEqual(SessionPhase.EIA_POST.value, "EIA_POST")
        self.assertEqual(SessionPhase.FRIDAY_LATE.value, "FRIDAY_LATE")
        self.assertEqual(SessionPhase.OTHER.value, "OTHER")


class BreakoutContextTest(TestCase):
    """Tests for BreakoutContext dataclass."""

    def test_breakout_context_creation(self):
        """Test BreakoutContext dataclass creation."""
        context = BreakoutContext(
            range_high=75.50,
            range_low=74.50,
            range_height=1.00,
            trigger_price=75.60,
            direction="LONG",
            atr=0.50,
            vwap=75.00,
            volume_spike=True,
        )
        
        self.assertEqual(context.range_high, 75.50)
        self.assertEqual(context.range_low, 74.50)
        self.assertEqual(context.range_height, 1.00)
        self.assertEqual(context.trigger_price, 75.60)
        self.assertEqual(context.direction, "LONG")
        self.assertEqual(context.atr, 0.50)
        self.assertTrue(context.volume_spike)

    def test_breakout_context_to_dict(self):
        """Test BreakoutContext to_dict serialization."""
        context = BreakoutContext(
            range_high=75.50,
            range_low=74.50,
            range_height=1.00,
            trigger_price=75.60,
            direction="LONG",
        )
        
        data = context.to_dict()
        
        self.assertEqual(data['range_high'], 75.50)
        self.assertEqual(data['direction'], "LONG")
        self.assertIsNone(data['atr'])


class EiaContextTest(TestCase):
    """Tests for EiaContext dataclass."""

    def test_eia_context_creation(self):
        """Test EiaContext dataclass creation."""
        ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        context = EiaContext(
            eia_timestamp=ts,
            first_impulse_direction="SHORT",
            impulse_range_high=75.50,
            impulse_range_low=74.00,
            atr=0.50,
        )
        
        self.assertEqual(context.eia_timestamp, ts)
        self.assertEqual(context.first_impulse_direction, "SHORT")
        self.assertEqual(context.impulse_range_high, 75.50)
        self.assertEqual(context.atr, 0.50)

    def test_eia_context_to_dict(self):
        """Test EiaContext to_dict serialization."""
        ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        context = EiaContext(
            eia_timestamp=ts,
            first_impulse_direction="LONG",
        )
        
        data = context.to_dict()
        
        self.assertIn('2025-01-15', data['eia_timestamp'])
        self.assertEqual(data['first_impulse_direction'], "LONG")


class CandleTest(TestCase):
    """Tests for Candle dataclass."""

    def test_candle_creation(self):
        """Test Candle dataclass creation."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        candle = Candle(
            timestamp=ts,
            open=75.00,
            high=75.50,
            low=74.50,
            close=75.40,
            volume=1000.0,
        )
        
        self.assertEqual(candle.open, 75.00)
        self.assertEqual(candle.high, 75.50)
        self.assertEqual(candle.low, 74.50)
        self.assertEqual(candle.close, 75.40)
        self.assertEqual(candle.volume, 1000.0)

    def test_candle_body_properties(self):
        """Test Candle body property calculations."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Bullish candle
        bullish = Candle(ts, open=74.50, high=75.50, low=74.00, close=75.00)
        self.assertEqual(bullish.body_high, 75.00)
        self.assertEqual(bullish.body_low, 74.50)
        self.assertEqual(bullish.body_size, 0.50)
        self.assertTrue(bullish.is_bullish)
        self.assertFalse(bullish.is_bearish)
        
        # Bearish candle
        bearish = Candle(ts, open=75.00, high=75.50, low=74.00, close=74.50)
        self.assertEqual(bearish.body_high, 75.00)
        self.assertEqual(bearish.body_low, 74.50)
        self.assertEqual(bearish.body_size, 0.50)
        self.assertFalse(bearish.is_bullish)
        self.assertTrue(bearish.is_bearish)

    def test_candle_to_dict(self):
        """Test Candle to_dict serialization."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        candle = Candle(ts, open=75.00, high=75.50, low=74.50, close=75.40)
        
        data = candle.to_dict()
        
        self.assertIn('2025-01-15', data['timestamp'])
        self.assertEqual(data['open'], 75.00)
        self.assertEqual(data['close'], 75.40)


class SetupCandidateTest(TestCase):
    """Tests for SetupCandidate dataclass."""

    def test_setup_candidate_breakout(self):
        """Test SetupCandidate creation for breakout."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        breakout = BreakoutContext(
            range_high=75.50,
            range_low=74.50,
            range_height=1.00,
            trigger_price=75.60,
            direction="LONG",
        )
        
        candidate = SetupCandidate(
            id="test-123",
            created_at=ts,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.60,
            direction="LONG",
            breakout=breakout,
            quality_flags={"clean_range": True},
        )
        
        self.assertEqual(candidate.id, "test-123")
        self.assertEqual(candidate.setup_kind, SetupKind.BREAKOUT)
        self.assertEqual(candidate.direction, "LONG")
        self.assertIsNotNone(candidate.breakout)
        self.assertIsNone(candidate.eia)

    def test_setup_candidate_eia(self):
        """Test SetupCandidate creation for EIA setup."""
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        eia = EiaContext(
            eia_timestamp=eia_ts,
            first_impulse_direction="SHORT",
            impulse_range_high=75.50,
            impulse_range_low=74.00,
        )
        
        candidate = SetupCandidate(
            id="test-456",
            created_at=ts,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=74.50,
            direction="LONG",
            eia=eia,
        )
        
        self.assertEqual(candidate.setup_kind, SetupKind.EIA_REVERSION)
        self.assertEqual(candidate.direction, "LONG")
        self.assertIsNone(candidate.breakout)
        self.assertIsNotNone(candidate.eia)

    def test_setup_candidate_to_dict(self):
        """Test SetupCandidate to_dict serialization."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        candidate = SetupCandidate(
            id="test-789",
            created_at=ts,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.60,
            direction="LONG",
        )
        
        data = candidate.to_dict()
        
        self.assertEqual(data['id'], "test-789")
        self.assertEqual(data['setup_kind'], "BREAKOUT")
        self.assertEqual(data['phase'], "LONDON_CORE")
        self.assertEqual(data['direction'], "LONG")


class StrategyConfigTest(TestCase):
    """Tests for StrategyConfig."""

    def test_default_config(self):
        """Test default StrategyConfig creation."""
        config = StrategyConfig()
        
        self.assertEqual(config.breakout.asia_range.start, "00:00")
        self.assertEqual(config.breakout.asia_range.end, "08:00")
        self.assertEqual(config.breakout.asia_range.min_range_ticks, 10)
        self.assertEqual(config.eia.impulse_window_minutes, 3)
        self.assertEqual(config.default_epic, "CC.D.CL.UNC.IP")

    def test_config_from_dict(self):
        """Test StrategyConfig creation from dictionary."""
        data = {
            'breakout': {
                'asia_range': {
                    'start': '01:00',
                    'end': '09:00',
                    'min_range_ticks': 15,
                },
                'us_core': {
                    'pre_us_start': '14:00',
                    'min_range_ticks': 20,
                },
            },
            'eia': {
                'impulse_window_minutes': 5,
                'reversion_min_retrace_fraction': 0.6,
            },
            'tick_size': 0.02,
        }
        
        config = StrategyConfig.from_dict(data)
        
        self.assertEqual(config.breakout.asia_range.start, '01:00')
        self.assertEqual(config.breakout.asia_range.min_range_ticks, 15)
        self.assertEqual(config.breakout.us_core.pre_us_start, '14:00')
        self.assertEqual(config.eia.impulse_window_minutes, 5)
        self.assertEqual(config.tick_size, 0.02)

    def test_config_to_dict(self):
        """Test StrategyConfig to_dict serialization."""
        config = StrategyConfig()
        data = config.to_dict()
        
        self.assertIn('breakout', data)
        self.assertIn('eia', data)
        self.assertIn('asia_range', data['breakout'])
        self.assertEqual(data['breakout']['asia_range']['start'], '00:00')


class DummyMarketStateProvider(BaseMarketStateProvider):
    """Dummy implementation of MarketStateProvider for testing."""

    def __init__(
        self,
        phase: SessionPhase = SessionPhase.OTHER,
        candles: list[Candle] = None,
        asia_range: tuple[float, float] = None,
        london_core_range: tuple[float, float] = None,
        pre_us_range: tuple[float, float] = None,
        eia_timestamp: datetime = None,
        atr: float = None,
        tradeable: bool | None = None,
    ):
        self._phase = phase
        self._candles = candles or []
        self._asia_range = asia_range
        self._london_core_range = london_core_range
        self._pre_us_range = pre_us_range
        self._eia_timestamp = eia_timestamp
        self._atr = atr
        self._tradeable = tradeable

    def get_phase(self, ts: datetime) -> SessionPhase:
        return self._phase

    def get_recent_candles(
        self,
        epic: str,
        timeframe: str,
        limit: int,
        closed_only: bool = False,
    ) -> list[Candle]:
        return self._candles[:limit]

    def get_asia_range(self, epic: str) -> tuple[float, float] | None:
        return self._asia_range

    def get_london_core_range(self, epic: str) -> tuple[float, float] | None:
        return self._london_core_range

    def get_pre_us_range(self, epic: str) -> tuple[float, float] | None:
        return self._pre_us_range

    def get_eia_timestamp(self) -> datetime | None:
        return self._eia_timestamp

    def is_phase_tradeable(self, phase: SessionPhase) -> bool:
        if self._tradeable is not None:
            return self._tradeable

        tradeable_phases = {
            SessionPhase.LONDON_CORE,
            SessionPhase.US_CORE_TRADING,
            SessionPhase.US_CORE,
            SessionPhase.EIA_POST,
        }
        return phase in tradeable_phases

    def get_atr(
        self,
        epic: str,
        timeframe: str,
        period: int
    ) -> float | None:
        return self._atr


class StrategyEngineBreakoutTest(TestCase):
    """Tests for StrategyEngine breakout logic."""

    def test_no_setup_when_phase_other(self):
        """Test that no setups are generated when phase is OTHER."""
        provider = DummyMarketStateProvider(phase=SessionPhase.OTHER)
        engine = StrategyEngine(provider)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)

    def test_asia_breakout_long(self):
        """Test Asia range breakout LONG setup."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a bullish breakout candle with body >= 50% of range
        # Range is 0.20 (75.20 - 75.00), so min body is 0.10
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.30,
            low=75.10,
            close=75.28,  # Above Asia high (75.20), body = 0.13
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),  # 0.20 range = 20 ticks at 0.01
            atr=0.50,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].setup_kind, SetupKind.BREAKOUT)
        self.assertEqual(candidates[0].direction, "LONG")
        self.assertEqual(candidates[0].phase, SessionPhase.LONDON_CORE)
        self.assertIsNotNone(candidates[0].breakout)
        self.assertEqual(candidates[0].breakout.range_high, 75.20)

    def test_asia_breakout_short(self):
        """Test Asia range breakout SHORT setup."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a bearish breakout candle with body >= 50% of range
        # Range is 0.20 (75.20 - 75.00), so min body is 0.10
        candle = Candle(
            timestamp=ts,
            open=75.05,
            high=75.10,
            low=74.90,
            close=74.93,  # Below Asia low (75.00), body = 0.12
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),  # 0.20 range = 20 ticks
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].direction, "SHORT")

    def test_no_breakout_when_range_too_small(self):
        """Test that no breakout is generated when range is too small."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        candle = Candle(
            timestamp=ts,
            open=75.03,
            high=75.05,
            low=75.01,
            close=75.04,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.03, 75.00),  # Only 0.03 = 3 ticks, below min 10
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)

    def test_no_breakout_when_candle_body_too_small(self):
        """Test that no breakout is generated when candle body is too small."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Candle with tiny body (doji-like)
        candle = Candle(
            timestamp=ts,
            open=75.51,
            high=75.60,
            low=75.40,
            close=75.52,  # Very small body
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.50, 74.50),  # 1.00 range
        )
        config = StrategyConfig()
        config.breakout.asia_range.min_breakout_body_fraction = 0.5
        
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)

    def test_us_core_breakout(self):
        """Test US Core breakout setup."""
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)

        # Create a bullish breakout candle with body >= 50% of range
        # Range is 0.20 (75.20 - 75.00), so min body is 0.10
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.30,
            low=75.10,
            close=75.28,  # Above range high (75.20), body = 0.13
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE,
            candles=[candle],
            pre_us_range=(75.20, 75.00),  # 0.20 range = 20 ticks
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].setup_kind, SetupKind.BREAKOUT)
        self.assertEqual(candidates[0].phase, SessionPhase.US_CORE)

    def test_us_core_breakout_reports_price_position(self):
        """When price leaves the range without a valid signal, status reflects position."""
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)

        # Bullish candle that dips below the range low (invalid SHORT breakout)
        candle = Candle(
            timestamp=ts,
            open=138.50,
            high=139.00,
            low=137.90,  # Below range low
            close=138.80,  # Bullish close keeps breakout invalid for SHORT
        )

        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE_TRADING,
            candles=[candle],
            pre_us_range=(140.15, 138.18),
        )
        engine = StrategyEngine(provider)

        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)

        self.assertEqual(len(candidates), 0)
        self.assertEqual(
            engine.last_status_message,
            "Breakout rejected: SHORT validation failed - Bearish breakout required "
            "but candle closed higher than it opened (open 138.5000 < close 138.8000) "
            "[US diagnostics breakout evaluation]; US breakout evaluation: price below range; "
            "Phase US_CORE_TRADING is tradeable but no valid setups found",
        )

    def test_pre_us_breakout_uses_london_core_range(self):
        """Pre-US breakout should evaluate against London Core range (previous phase)."""
        ts = datetime(2025, 1, 15, 13, 0, tzinfo=timezone.utc)

        candle = Candle(
            timestamp=ts,
            open=139.40,
            high=139.50,
            low=138.90,  # Below London Core low
            close=139.10,  # Below London Core low but body too small for breakout
        )

        provider = DummyMarketStateProvider(
            phase=SessionPhase.PRE_US_RANGE,
            candles=[candle],
            london_core_range=(140.00, 139.20),
            pre_us_range=(150.00, 145.00),  # Decoy range; should not be used
        )
        engine = StrategyEngine(provider)

        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)

        self.assertEqual(len(candidates), 0)
        self.assertEqual(
            engine.last_status_message,
            "Breakout rejected: SHORT validation failed - Candle body 0.3000 below minimum "
            "0.4000 (50% of range) [US diagnostics breakout evaluation]; "
            "US breakout evaluation: price below range; "
            "Phase PRE_US_RANGE is tradeable but no valid setups found",
        )


class StrategyEngineEiaTest(TestCase):
    """Tests for StrategyEngine EIA logic."""

    def test_eia_reversion_after_long_impulse(self):
        """Test EIA reversion setup after LONG impulse."""
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        # Create impulse candles (LONG)
        impulse_candles = [
            Candle(datetime(2025, 1, 15, 15, 30), open=74.00, high=74.50, low=73.90, close=74.40),
            Candle(datetime(2025, 1, 15, 15, 31), open=74.40, high=75.00, low=74.30, close=74.90),
            Candle(datetime(2025, 1, 15, 15, 32), open=74.90, high=75.50, low=74.80, close=75.40),
        ]
        
        # Create reversion candle (bearish, retracing)
        reversion_candle = Candle(
            datetime(2025, 1, 15, 15, 33),
            open=75.30,
            high=75.40,
            low=74.50,
            close=74.60,  # Significant retrace
        )
        
        all_candles = impulse_candles + [reversion_candle]
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=all_candles,
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should find EIA_REVERSION with SHORT direction
        reversion_candidates = [c for c in candidates if c.setup_kind == SetupKind.EIA_REVERSION]
        self.assertEqual(len(reversion_candidates), 1)
        self.assertEqual(reversion_candidates[0].direction, "SHORT")

    def test_eia_reversion_after_short_impulse(self):
        """Test EIA reversion setup after SHORT impulse."""
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        # Create impulse candles (SHORT)
        impulse_candles = [
            Candle(datetime(2025, 1, 15, 15, 30), open=75.00, high=75.10, low=74.60, close=74.70),
            Candle(datetime(2025, 1, 15, 15, 31), open=74.70, high=74.80, low=74.30, close=74.40),
            Candle(datetime(2025, 1, 15, 15, 32), open=74.40, high=74.50, low=74.00, close=74.10),
        ]
        
        # Create reversion candle (bullish, retracing)
        reversion_candle = Candle(
            datetime(2025, 1, 15, 15, 33),
            open=74.20,
            high=74.80,
            low=74.10,
            close=74.70,  # Significant retrace upward
        )
        
        all_candles = impulse_candles + [reversion_candle]
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=all_candles,
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should find EIA_REVERSION with LONG direction
        reversion_candidates = [c for c in candidates if c.setup_kind == SetupKind.EIA_REVERSION]
        self.assertEqual(len(reversion_candidates), 1)
        self.assertEqual(reversion_candidates[0].direction, "LONG")

    def test_eia_trendday_long(self):
        """Test EIA trend day setup with LONG continuation."""
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 37, tzinfo=timezone.utc)
        
        # Create impulse candles (LONG)
        impulse_candles = [
            Candle(datetime(2025, 1, 15, 15, 30), open=74.00, high=74.50, low=73.90, close=74.40),
            Candle(datetime(2025, 1, 15, 15, 31), open=74.40, high=75.00, low=74.30, close=74.90),
            Candle(datetime(2025, 1, 15, 15, 32), open=74.90, high=75.50, low=74.80, close=75.40),
        ]
        
        # Create follow candles with higher highs and higher lows
        follow_candles = [
            Candle(datetime(2025, 1, 15, 15, 33), open=75.40, high=75.60, low=75.30, close=75.55),
            Candle(datetime(2025, 1, 15, 15, 34), open=75.55, high=75.75, low=75.45, close=75.70),
            Candle(datetime(2025, 1, 15, 15, 35), open=75.70, high=75.90, low=75.60, close=75.85),
        ]
        
        all_candles = impulse_candles + follow_candles
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=all_candles,
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should find EIA_TRENDDAY with LONG direction
        trendday_candidates = [c for c in candidates if c.setup_kind == SetupKind.EIA_TRENDDAY]
        self.assertEqual(len(trendday_candidates), 1)
        self.assertEqual(trendday_candidates[0].direction, "LONG")

    def test_eia_trendday_short(self):
        """Test EIA trend day setup with SHORT continuation."""
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 37, tzinfo=timezone.utc)
        
        # Create impulse candles (SHORT)
        impulse_candles = [
            Candle(datetime(2025, 1, 15, 15, 30), open=75.00, high=75.10, low=74.60, close=74.70),
            Candle(datetime(2025, 1, 15, 15, 31), open=74.70, high=74.80, low=74.30, close=74.40),
            Candle(datetime(2025, 1, 15, 15, 32), open=74.40, high=74.50, low=74.00, close=74.10),
        ]
        
        # Create follow candles with lower lows and lower highs
        follow_candles = [
            Candle(datetime(2025, 1, 15, 15, 33), open=74.10, high=74.05, low=73.90, close=73.95),
            Candle(datetime(2025, 1, 15, 15, 34), open=73.95, high=73.90, low=73.75, close=73.80),
            Candle(datetime(2025, 1, 15, 15, 35), open=73.80, high=73.75, low=73.60, close=73.65),
        ]
        
        all_candles = impulse_candles + follow_candles
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=all_candles,
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should find EIA_TRENDDAY with SHORT direction
        trendday_candidates = [c for c in candidates if c.setup_kind == SetupKind.EIA_TRENDDAY]
        self.assertEqual(len(trendday_candidates), 1)
        self.assertEqual(trendday_candidates[0].direction, "SHORT")

    def test_no_eia_setup_without_eia_timestamp(self):
        """Test that no EIA setups are generated without EIA timestamp."""
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=[],
            eia_timestamp=None,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)


class StrategyEngineIntegrationTest(TestCase):
    """Integration tests for StrategyEngine."""

    def test_multiple_candidates_filtered(self):
        """Test that duplicate candidates are filtered."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create multiple breakout candles with proper body size
        # Range is 0.20, min body is 0.10
        # The engine uses the last candle, so make sure it has proper body
        candles = [
            Candle(ts, open=75.10, high=75.25, low=75.05, close=75.22),  # body = 0.12
            Candle(ts, open=75.15, high=75.35, low=75.10, close=75.30),  # body = 0.15, above high
        ]
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=candles,
            asia_range=(75.20, 75.00),  # 0.20 range = 20 ticks
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should only have one LONG breakout candidate
        breakout_long = [c for c in candidates if c.setup_kind == SetupKind.BREAKOUT and c.direction == "LONG"]
        self.assertEqual(len(breakout_long), 1)

    def test_config_affects_evaluation(self):
        """Test that configuration affects evaluation."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a valid breakout candle with proper body size
        # Range is 0.20 (75.50 - 75.30), min body is 0.10
        candle = Candle(
            timestamp=ts,
            open=75.45,
            high=75.65,
            low=75.40,
            close=75.58,  # Above range high (75.50), body = 0.13
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.50, 75.30),  # 0.20 range = 20 ticks
        )
        
        # Default config (min 10 ticks) should allow breakout
        engine1 = StrategyEngine(provider)
        candidates1 = engine1.evaluate("CC.D.CL.UNC.IP", ts)
        self.assertEqual(len(candidates1), 1)
        
        # Config with min 50 ticks should reject
        config = StrategyConfig()
        config.breakout.asia_range.min_range_ticks = 50
        engine2 = StrategyEngine(provider, config)
        candidates2 = engine2.evaluate("CC.D.CL.UNC.IP", ts)
        self.assertEqual(len(candidates2), 0)


class BreakoutRangeDiagnosticsTest(TestCase):
    """Tests for BreakoutRangeDiagnostics dataclass."""
    
    def test_diagnostics_to_dict(self):
        """Test BreakoutRangeDiagnostics to_dict serialization."""
        from core.services.strategy import (
            BreakoutRangeDiagnostics,
            PricePosition,
            BreakoutStatus,
            RangeValidation,
            SessionPhase,
        )
        
        diagnostics = BreakoutRangeDiagnostics(
            range_type="Asia Range",
            range_period_start="00:00",
            range_period_end="08:00",
            range_high=75.50,
            range_low=74.50,
            range_height=1.00,
            range_height_ticks=100,
            current_price=75.60,
            price_position=PricePosition.ABOVE,
            breakout_status=BreakoutStatus.VALID_BREAKOUT,
            potential_direction="LONG",
            range_validation=RangeValidation.VALID,
            current_phase=SessionPhase.LONDON_CORE,
            diagnostic_message="Valid LONG breakout!",
            detailed_explanation="A valid breakout detected.",
        )
        
        data = diagnostics.to_dict()
        
        self.assertEqual(data['range_type'], "Asia Range")
        self.assertEqual(data['range_data']['high'], 75.50)
        self.assertEqual(data['range_data']['low'], 74.50)
        self.assertEqual(data['current_market']['price'], 75.60)
        self.assertEqual(data['current_market']['position'], "ABOVE")
        self.assertEqual(data['breakout_status']['status'], "VALID_BREAKOUT")
        self.assertEqual(data['validation']['range_validation'], "VALID")
        self.assertEqual(data['current_phase'], "LONDON_CORE")


class BreakoutRangeDiagnosticServiceTest(TestCase):
    """Tests for BreakoutRangeDiagnosticService."""
    
    def test_placeholder(self):
        """Placeholder test - BreakoutRangeDiagnosticService tests are incomplete."""
        # The tests in this class require BreakoutRangeDiagnosticService which is not
        # fully implemented. This placeholder ensures the test file is valid Python.
        pass


class StrategyEngineDiagnosticsTest(TestCase):
    """Tests for StrategyEngine evaluate_with_diagnostics method."""

    def test_diagnostics_non_tradeable_phase(self):
        """Test diagnostics when phase is not tradeable."""
        provider = DummyMarketStateProvider(phase=SessionPhase.OTHER)
        engine = StrategyEngine(provider)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertIsInstance(result, EvaluationResult)
        self.assertEqual(len(result.setups), 0)
        self.assertGreater(len(result.criteria), 0)
        
        # Should have phase info criterion
        phase_criteria = [c for c in result.criteria if 'phase' in c.name.lower()]
        self.assertGreater(len(phase_criteria), 0)
        
        # One should show that phase is not tradeable
        not_tradeable = [c for c in result.criteria if not c.passed and 'tradeable' in c.name.lower()]
        self.assertGreater(len(not_tradeable), 0)

    def test_diagnostics_asia_breakout(self):
        """Test diagnostics for Asia breakout evaluation."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            RangeValidation,
        )
        
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a bullish breakout candle
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.30,
            low=75.10,
            close=75.28,  # Above Asia high (75.20)
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            asia_range=None,
        )
        service = BreakoutRangeDiagnosticService(provider)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(diagnostics.range_type, "Asia Range")
        self.assertEqual(diagnostics.range_validation, RangeValidation.NOT_AVAILABLE)
        # Check for presence of "No" and "available" in the message
        self.assertIn("No", diagnostics.diagnostic_message)
        self.assertIn("available", diagnostics.diagnostic_message.lower())
    
    def test_asia_range_diagnostics_valid_range(self):
        """Test diagnostics with valid Asia range data."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            RangeValidation,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            asia_range=(75.20, 75.00),  # 0.20 range = 20 ticks
        )
        service = BreakoutRangeDiagnosticService(provider)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(diagnostics.range_type, "Asia Range")
        self.assertEqual(diagnostics.range_high, 75.20)
        self.assertEqual(diagnostics.range_low, 75.00)
        self.assertAlmostEqual(diagnostics.range_height, 0.20, places=5)
        self.assertEqual(diagnostics.range_height_ticks, 20)
        self.assertEqual(diagnostics.range_validation, RangeValidation.VALID)
    
    def test_asia_range_diagnostics_range_too_small(self):
        """Test diagnostics when range is too small."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            StrategyConfig,
            RangeValidation,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            asia_range=(75.05, 75.00),  # 0.05 range = 5 ticks (below min 10)
        )
        config = StrategyConfig()
        config.breakout.asia_range.min_range_ticks = 10
        service = BreakoutRangeDiagnosticService(provider, config)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(diagnostics.range_validation, RangeValidation.TOO_SMALL)
        self.assertIn("below", diagnostics.diagnostic_message.lower())
    
    def test_asia_range_diagnostics_price_position(self):
        """Test diagnostics shows correct price position."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            PricePosition,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            asia_range=(75.20, 75.00),
        )
        service = BreakoutRangeDiagnosticService(provider)
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Price above range
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts, current_price=75.30)
        self.assertEqual(diagnostics.price_position, PricePosition.ABOVE)
        
        # Price inside range
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts, current_price=75.10)
        self.assertEqual(diagnostics.price_position, PricePosition.INSIDE)
        
        # Price below range
        diagnostics = service.get_asia_range_diagnostics("CC.D.CL.UNC.IP", ts, current_price=74.90)
        self.assertEqual(diagnostics.price_position, PricePosition.BELOW)

    def test_diagnostics_no_asia_range(self):
        """Test diagnostics when Asia range is not available."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[],
            asia_range=None,  # No Asia range
        )
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(result.setups), 0)
        
        # Should have a failed criterion about Asia Range availability
        failed_criteria = [c for c in result.criteria if not c.passed]
        self.assertGreater(len(failed_criteria), 0)

    def test_diagnostics_price_within_range(self):
        """Test diagnostics when price is within range (no breakout)."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a candle within the range
        candle = Candle(
            timestamp=ts,
            open=75.08,
            high=75.12,
            low=75.05,
            close=75.10,  # Within Asia range (75.00 - 75.20)
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
        )
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(result.setups), 0)
        
        # Should have a criterion about price not breaking range
        breakout_criteria = [c for c in result.criteria if 'breakout' in c.name.lower() or 'broke' in c.name.lower()]
        self.assertGreater(len(breakout_criteria), 0)
        
        # At least one should fail
        failed_breakout = [c for c in breakout_criteria if not c.passed]
        self.assertGreater(len(failed_breakout), 0)
    
    def test_pre_us_range_diagnostics(self):
        """Test Pre-US range diagnostics."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            RangeValidation,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE,
            pre_us_range=(76.00, 75.50),  # 0.50 range = 50 ticks
        )
        service = BreakoutRangeDiagnosticService(provider)
        
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)
        diagnostics = service.get_pre_us_range_diagnostics("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(diagnostics.range_type, "Pre-US Range")
        self.assertEqual(diagnostics.range_high, 76.00)
        self.assertEqual(diagnostics.range_low, 75.50)
        self.assertEqual(diagnostics.range_validation, RangeValidation.VALID)
    
    def test_diagnostics_breakout_status_detection(self):
        """Test that breakout status is correctly detected."""
        from core.services.strategy import (
            BreakoutRangeDiagnosticService,
            BreakoutStatus,
        )
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        # Create a bullish breakout candle with body >= 50% of range
        # Range is 0.20 (75.20 - 75.00), so min body is 0.10
        breakout_candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.35,
            low=75.10,
            close=75.30,  # Above range high (75.20), body = 0.15
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[breakout_candle],
            asia_range=(75.20, 75.00),  # 0.20 range = 20 ticks
        )
        service = BreakoutRangeDiagnosticService(provider)
        
        diagnostics = service.get_asia_range_diagnostics(
            "CC.D.CL.UNC.IP", ts, current_price=75.30
        )
        
        self.assertEqual(diagnostics.breakout_status, BreakoutStatus.VALID_BREAKOUT)
        self.assertEqual(diagnostics.potential_direction, "LONG")

    def test_criteria_to_dict_conversion(self):
        """Test that criteria can be converted to dict for JSON serialization."""
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(phase=SessionPhase.OTHER)
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        criteria_list = result.to_criteria_list()
        
        self.assertIsInstance(criteria_list, list)
        self.assertGreater(len(criteria_list), 0)
        
        for criterion_dict in criteria_list:
            self.assertIsInstance(criterion_dict, dict)
            self.assertIn('name', criterion_dict)
            self.assertIn('passed', criterion_dict)
            self.assertIn('detail', criterion_dict)
            self.assertIsInstance(criterion_dict['passed'], bool)

    def test_diagnostic_criterion_dataclass(self):
        """Test DiagnosticCriterion dataclass."""
        criterion = DiagnosticCriterion(
            name="Test Criterion",
            passed=True,
            detail="Test detail",
        )
        
        self.assertEqual(criterion.name, "Test Criterion")
        self.assertTrue(criterion.passed)
        self.assertEqual(criterion.detail, "Test detail")
        
        as_dict = criterion.to_dict()
        self.assertEqual(as_dict['name'], "Test Criterion")
        self.assertTrue(as_dict['passed'])
        self.assertEqual(as_dict['detail'], "Test detail")


class UsCoreTradinSessionTest(TestCase):
    """Tests for the new US Core Trading session feature (PRE_US_RANGE and US_CORE_TRADING)."""
    
    def test_pre_us_range_is_not_tradeable(self):
        """Test that PRE_US_RANGE phase does not generate setups."""
        ts = datetime(2025, 1, 15, 13, 30, tzinfo=timezone.utc)
        
        # Create a valid breakout candle
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.35,
            low=75.10,
            close=75.30,  # Above range high
        )
        
        # PRE_US_RANGE should NOT generate setups
        provider = DummyMarketStateProvider(
            phase=SessionPhase.PRE_US_RANGE,
            candles=[candle],
            pre_us_range=(75.20, 75.00),  # 0.20 range = 20 ticks
            atr=0.50,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)

        # No setups in PRE_US_RANGE phase - it's range formation only
        self.assertEqual(len(candidates), 0)

    def test_pre_us_range_can_be_tradeable_via_config(self):
        """PRE_US_RANGE should generate setups when explicitly marked tradeable."""
        ts = datetime(2025, 1, 15, 13, 30, tzinfo=timezone.utc)

        candle = Candle(
            timestamp=ts,
            open=75.18,
            high=75.55,
            low=75.12,
            close=75.42,
        )

        provider = DummyMarketStateProvider(
            phase=SessionPhase.PRE_US_RANGE,
            candles=[candle],
            pre_us_range=(75.20, 75.00),
            atr=0.50,
            tradeable=True,
        )

        engine = StrategyEngine(provider)
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)

        self.assertGreaterEqual(len(candidates), 1)
        for candidate in candidates:
            self.assertEqual(candidate.phase, SessionPhase.PRE_US_RANGE)
    
    def test_pre_us_range_diagnostics(self):
        """Test that PRE_US_RANGE phase shows informative diagnostics."""
        ts = datetime(2025, 1, 15, 13, 30, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.PRE_US_RANGE,
            candles=[],
            pre_us_range=(75.20, 75.00),
        )
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        # No setups in PRE_US_RANGE
        self.assertEqual(len(result.setups), 0)
        
        # Summary should indicate range collection
        self.assertIn("PRE_US_RANGE", result.summary)
        self.assertIn("range", result.summary.lower())
    
    def test_us_core_trading_generates_setups(self):
        """Test that US_CORE_TRADING phase generates setups correctly."""
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)
        
        # Create a bullish breakout candle with body >= 50% of range
        # Range is 0.20 (75.20 - 75.00), so min body is 0.10
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.35,
            low=75.10,
            close=75.30,  # Above range high (75.20), body = 0.15
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE_TRADING,
            candles=[candle],
            pre_us_range=(75.20, 75.00),  # 0.20 range = 20 ticks
            atr=0.50,
        )
        engine = StrategyEngine(provider)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # US_CORE_TRADING should generate setups
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].setup_kind, SetupKind.BREAKOUT)
        self.assertEqual(candidates[0].direction, "LONG")
        self.assertEqual(candidates[0].phase, SessionPhase.US_CORE_TRADING)
    
    def test_us_core_trading_diagnostics(self):
        """Test that US_CORE_TRADING phase shows as tradeable."""
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE_TRADING,
            candles=[],
            pre_us_range=(75.20, 75.00),
        )
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        # Phase should be shown as tradeable
        tradeable_criteria = [c for c in result.criteria if 'tradeable' in c.name.lower()]
        self.assertGreater(len(tradeable_criteria), 0)
        
        # The tradeable criterion should pass for US_CORE_TRADING
        tradeable_criterion = tradeable_criteria[0]
        self.assertTrue(tradeable_criterion.passed)
    
    def test_us_core_trading_with_eia_post_overlap(self):
        """Test that EIA_POST takes priority when overlapping with US_CORE_TRADING times."""
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        # EIA_POST should take priority over US_CORE_TRADING
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,  # EIA takes priority
            candles=[],
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", ts)
        
        # EIA_POST is tradeable
        tradeable_criteria = [c for c in result.criteria if 'tradeable' in c.name.lower()]
        self.assertGreater(len(tradeable_criteria), 0)
        tradeable_criterion = tradeable_criteria[0]
        self.assertTrue(tradeable_criterion.passed)
    
    def test_session_phase_enum_has_new_phases(self):
        """Test that SessionPhase enum includes the new phases."""
        # Verify PRE_US_RANGE exists
        self.assertEqual(SessionPhase.PRE_US_RANGE.value, "PRE_US_RANGE")
        
        # Verify US_CORE_TRADING exists
        self.assertEqual(SessionPhase.US_CORE_TRADING.value, "US_CORE_TRADING")
        
        # Verify backwards compatibility (US_CORE still exists)
        self.assertEqual(SessionPhase.US_CORE.value, "US_CORE")


class StrategyEngineDebugLoggingTest(TestCase):
    """Tests for Strategy Engine debug logging."""

    def test_evaluate_logs_debug_on_setup_found(self):
        """Test that debug logging is called when a setup is found."""
        import logging
        from unittest.mock import patch
        
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Create a bullish breakout candle with body >= 50% of range
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.30,
            low=75.10,
            close=75.28,
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        engine = StrategyEngine(provider)
        
        with patch('core.services.strategy.strategy_engine.logger') as mock_logger:
            candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check that setup_found is logged
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('setup' in str(c).lower() for c in calls))

    def test_evaluate_logs_debug_on_no_setup(self):
        """Test that debug logging is called when no setup is found."""
        import logging
        from unittest.mock import patch
        
        ts = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        provider = DummyMarketStateProvider(phase=SessionPhase.OTHER)
        engine = StrategyEngine(provider)
        
        with patch('core.services.strategy.strategy_engine.logger') as mock_logger:
            candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Should return no candidates
            self.assertEqual(len(candidates), 0)

    def test_asia_breakout_logs_range_validation(self):
        """Test that Asia breakout logs range validation details."""
        import logging
        from unittest.mock import patch
        
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Too small range
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[],
            asia_range=(75.03, 75.00),  # Only 3 ticks
        )
        engine = StrategyEngine(provider)
        
        with patch('core.services.strategy.strategy_engine.logger') as mock_logger:
            candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check for range validation logging
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            # Should log either about range size or about the evaluation
            self.assertTrue(len(calls) > 0)

    def test_eia_evaluation_logs_impulse_analysis(self):
        """Test that EIA evaluation logs impulse analysis details."""
        import logging
        from unittest.mock import patch
        
        eia_ts = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
        ts = datetime(2025, 1, 15, 15, 35, tzinfo=timezone.utc)
        
        # Create impulse candles (LONG)
        impulse_candles = [
            Candle(datetime(2025, 1, 15, 15, 30), open=74.00, high=74.50, low=73.90, close=74.40),
            Candle(datetime(2025, 1, 15, 15, 31), open=74.40, high=75.00, low=74.30, close=74.90),
            Candle(datetime(2025, 1, 15, 15, 32), open=74.90, high=75.50, low=74.80, close=75.40),
        ]
        
        reversion_candle = Candle(
            datetime(2025, 1, 15, 15, 33),
            open=75.30,
            high=75.40,
            low=74.50,
            close=74.60,
        )
        
        all_candles = impulse_candles + [reversion_candle]
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.EIA_POST,
            candles=all_candles,
            eia_timestamp=eia_ts,
        )
        engine = StrategyEngine(provider)
        
        with patch('core.services.strategy.strategy_engine.logger') as mock_logger:
            candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
            
            # Should have debug calls
            self.assertTrue(mock_logger.debug.called)
            
            # Check for EIA-related logging
            calls = [str(c) for c in mock_logger.debug.call_args_list]
            self.assertTrue(any('eia' in str(c).lower() for c in calls))


class StrategyEngineCandleDistanceTest(TestCase):
    """Tests for max_candle_distance_ticks breakout filter."""

    def test_long_breakout_passes_within_max_distance(self):
        """Test LONG breakout passes when candle low is within max distance from range high."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle high breaks above range high (75.30)
        # Candle low is 75.15, which is 0.05 (5 ticks) from range high (75.20)
        # This should pass with max_candle_distance_ticks = 10
        candle = Candle(
            timestamp=ts,
            open=75.15,
            high=75.30,
            low=75.15,
            close=75.28,  # Body = 0.13 (13 ticks), >= 50% of range (10 ticks)
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 10 (default)
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 10
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].direction, "LONG")

    def test_long_breakout_rejected_exceeds_max_distance(self):
        """Test LONG breakout rejected when candle low is too far from range high."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle high breaks above range high (75.40)
        # Candle low is 75.05, which is 0.15 (15 ticks) from range high (75.20)
        # This should fail with max_candle_distance_ticks = 10
        candle = Candle(
            timestamp=ts,
            open=75.10,
            high=75.40,
            low=75.05,
            close=75.35,  # Body = 0.25 (25 ticks), >= 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 10
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 10
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)

    def test_short_breakout_passes_within_max_distance(self):
        """Test SHORT breakout passes when candle high is within max distance from range low."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle low breaks below range low (74.90)
        # Candle high is 74.95, which is 0.05 (5 ticks) from range low (75.00)
        # This should pass with max_candle_distance_ticks = 10
        candle = Candle(
            timestamp=ts,
            open=74.95,
            high=74.95,
            low=74.90,
            close=74.83,  # Body = 0.12 (12 ticks), >= 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 10
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 10
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].direction, "SHORT")

    def test_short_breakout_rejected_exceeds_max_distance(self):
        """Test SHORT breakout rejected when candle high is too far from range low."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle low breaks below range low (74.70)
        # Candle high is 74.85, which is 0.15 (15 ticks) from range low (75.00)
        # This should fail with max_candle_distance_ticks = 10
        candle = Candle(
            timestamp=ts,
            open=74.80,
            high=74.85,
            low=74.70,
            close=74.72,  # Body = 0.08, but more than 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 10
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 10
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 0)

    def test_configurable_max_distance(self):
        """Test that max_candle_distance_ticks is configurable."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle low is 75.00, which is 0.20 (20 ticks) from range high (75.20)
        candle = Candle(
            timestamp=ts,
            open=75.05,
            high=75.40,
            low=75.00,
            close=75.35,  # Body = 0.30, >= 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Test with max_candle_distance_ticks = 10 (should reject)
        config1 = StrategyConfig()
        config1.breakout.max_candle_distance_ticks = 10
        engine1 = StrategyEngine(provider, config1)
        candidates1 = engine1.evaluate("CC.D.CL.UNC.IP", ts)
        self.assertEqual(len(candidates1), 0)
        
        # Test with max_candle_distance_ticks = 25 (should accept)
        config2 = StrategyConfig()
        config2.breakout.max_candle_distance_ticks = 25
        engine2 = StrategyEngine(provider, config2)
        candidates2 = engine2.evaluate("CC.D.CL.UNC.IP", ts)
        self.assertEqual(len(candidates2), 1)

    def test_us_core_breakout_with_max_distance(self):
        """Test US Core Trading breakout with max_candle_distance_ticks filter."""
        ts = datetime(2025, 1, 15, 16, 0, tzinfo=timezone.utc)
        
        # Pre-US Range: 74.50 - 74.70 (20 ticks)
        # Candle breaks above with low at 74.62 (0.08 = 8 ticks from range high)
        # Should pass with default max_candle_distance_ticks = 10
        candle = Candle(
            timestamp=ts,
            open=74.65,
            high=74.80,
            low=74.62,
            close=74.78,  # Body = 0.13 >= 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.US_CORE_TRADING,
            candles=[candle],
            pre_us_range=(74.70, 74.50),
            atr=0.50,
        )
        
        engine = StrategyEngine(provider)
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].direction, "LONG")

    def test_zero_max_distance_allows_exact_boundary(self):
        """Test that max_candle_distance_ticks = 0 allows candles exactly at boundary."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle breaks above with low exactly at range high (0 ticks distance)
        # This should be allowed with max_distance = 0
        candle = Candle(
            timestamp=ts,
            open=75.20,
            high=75.30,
            low=75.20,  # Exactly at range high (0 ticks)
            close=75.28,  # Body = 0.08 < 50% of range (0.10)
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 0
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 0
        # Reduce min_body_fraction so we test distance, not body size
        config.breakout.asia_range.min_breakout_body_fraction = 0.3
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should pass because candle low is exactly at range high (0 ticks away)
        self.assertEqual(len(candidates), 1)

    def test_zero_max_distance_rejects_any_distance(self):
        """Test that max_candle_distance_ticks = 0 rejects any distance > 0."""
        ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        
        # Range: 75.00 - 75.20 (20 ticks)
        # Candle breaks above with low at 75.19 (0.01 = 1 tick from range high)
        # This should be rejected with max_distance = 0
        candle = Candle(
            timestamp=ts,
            open=75.20,
            high=75.30,
            low=75.19,  # 1 tick below range high
            close=75.28,  # Body = 0.08 < 50% of range
        )
        
        provider = DummyMarketStateProvider(
            phase=SessionPhase.LONDON_CORE,
            candles=[candle],
            asia_range=(75.20, 75.00),
            atr=0.50,
        )
        
        # Configure with max_candle_distance_ticks = 0
        config = StrategyConfig()
        config.breakout.max_candle_distance_ticks = 0
        # Reduce min_body_fraction so we test distance, not body size
        config.breakout.asia_range.min_breakout_body_fraction = 0.3
        engine = StrategyEngine(provider, config)
        
        candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)
        
        # Should be rejected because candle low is 1 tick away from range high
        self.assertEqual(len(candidates), 0)
