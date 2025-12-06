"""Kraken Market Data Worker.

Streams Kraken trade data via WebSocket, aggregates 1m candles, persists them
to Redis/in-memory caches via :class:`KrakenBrokerService`, and builds
session-phase ranges for breakout trading.

Only active Kraken assets are processed. Session times are taken from each
asset's :class:`~trading.models.AssetSessionPhaseConfig` so that range
boundaries match the asset configuration (e.g., Asia 00:00-08:00 UTC).
"""
from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from core.services.broker.config import BrokerRegistry
from core.services.broker.kraken_broker_service import KrakenBrokerService
from core.services.broker.models import Candle1m
from core.services.strategy.models import SessionPhase
from trading.models import AssetSessionPhaseConfig, BreakoutRange, TradingAsset

logger = logging.getLogger(__name__)


@dataclass
class RangeState:
    """Tracks an in-progress session range for an asset."""

    phase: SessionPhase
    start_time: datetime
    high: float
    low: float
    candle_count: int = 0
    last_candle_end: Optional[datetime] = None


class GracefulShutdown:
    """Signal handler to allow clean shutdown of the worker."""

    def __init__(self) -> None:
        self.should_stop = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame) -> None:  # pragma: no cover - signal hook
        logger.info("Received signal %s, stopping Kraken market data worker", signum)
        self.should_stop = True


class AssetPhaseResolver:
    """Resolve the configured session phase for a timestamp."""

    def __init__(self, asset: TradingAsset, phase_configs: Iterable[AssetSessionPhaseConfig]):
        self.asset = asset
        self.phase_configs: Dict[str, AssetSessionPhaseConfig] = {
            cfg.phase: cfg for cfg in phase_configs if cfg.enabled
        }

    @staticmethod
    def _to_minutes(time_str: str) -> int:
        hour, minute = time_str.split(":")
        return int(hour) * 60 + int(minute)

    def resolve(self, ts: datetime) -> Optional[SessionPhase]:
        """Return the configured phase (if any) for the given timestamp."""

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        current_minutes = ts.hour * 60 + ts.minute

        for cfg in self.phase_configs.values():
            try:
                start_min = self._to_minutes(cfg.start_time_utc)
                end_min = self._to_minutes(cfg.end_time_utc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Invalid time config for %s %s: %s", self.asset.symbol, cfg.phase, exc)
                continue

            in_window = False
            if start_min <= end_min:
                in_window = start_min <= current_minutes < end_min
            else:
                # Phase wraps around midnight
                in_window = current_minutes >= start_min or current_minutes < end_min

            if in_window:
                try:
                    return SessionPhase(cfg.phase)
                except ValueError:
                    logger.debug("Unknown session phase %s for %s", cfg.phase, self.asset.symbol)
                    return None

        return None

    def is_range_phase(self, phase: SessionPhase) -> bool:
        cfg = self.phase_configs.get(phase.value)
        return bool(cfg and cfg.is_range_build_phase)


class KrakenMarketDataWorker:
    """Aggregates Kraken trades into 1m candles and session ranges."""

    def __init__(self, broker: KrakenBrokerService, assets: List[TradingAsset]):
        self.broker = broker
        self.assets = assets
        self.shutdown = GracefulShutdown()
        self._phase_resolvers: Dict[int, AssetPhaseResolver] = {}
        self._range_state: Dict[int, RangeState] = {}
        self._last_candle_ts: Dict[int, datetime] = {}
        self._next_range_persist_ts: float = time.monotonic()

        for asset in assets:
            configs = AssetSessionPhaseConfig.get_enabled_phases_for_asset(asset)
            self._phase_resolvers[asset.id] = AssetPhaseResolver(asset, configs)

    def _get_symbol(self, asset: TradingAsset) -> str:
        return asset.broker_symbol or asset.epic

    def _finalize_range(self, asset: TradingAsset, state: RangeState) -> None:
        self._persist_range_snapshot(asset, state)
        self._range_state.pop(asset.id, None)

    def _persist_range_snapshot(self, asset: TradingAsset, state: RangeState) -> None:
        if state.candle_count == 0:
            return

        end_time = state.last_candle_end or state.start_time
        try:
            with transaction.atomic():
                BreakoutRange.save_range_snapshot(
                    asset=asset,
                    phase=state.phase.value,
                    start_time=state.start_time,
                    end_time=end_time,
                    high=state.high,
                    low=state.low,
                    tick_size=float(asset.tick_size),
                    candle_count=state.candle_count,
                    atr=None,
                    is_valid=True,
                )
            logger.info(
                "Persisted %s range for %s: high=%.5f low=%.5f candles=%s",
                state.phase.value,
                asset.symbol,
                state.high,
                state.low,
                state.candle_count,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist range for %s (%s): %s",
                asset.symbol,
                state.phase.value,
                exc,
            )

    def _handle_candle(self, asset: TradingAsset, candle: Candle1m) -> None:
        resolver = self._phase_resolvers[asset.id]
        phase = resolver.resolve(candle.time)

        if phase is None or not resolver.is_range_phase(phase):
            # End any open range if we left the window
            self._range_state.pop(asset.id, None)
            return

        current = self._range_state.get(asset.id)
        candle_end = candle.time + timedelta(minutes=1)

        if current is None or current.phase != phase:
            if current is not None:
                self._range_state.pop(asset.id, None)
            self._range_state[asset.id] = RangeState(
                phase=phase,
                start_time=candle.time,
                high=candle.high,
                low=candle.low,
                candle_count=1,
                last_candle_end=candle_end,
            )
            return

        current.high = max(current.high, candle.high)
        current.low = min(current.low, candle.low)
        current.candle_count += 1
        current.last_candle_end = candle_end

    def _persist_active_ranges(self) -> None:
        for asset_id, state in self._range_state.items():
            asset = next((a for a in self.assets if a.id == asset_id), None)
            if asset is None:
                continue
            self._persist_range_snapshot(asset, state)

    def _process_asset(self, asset: TradingAsset) -> None:
        symbol = self._get_symbol(asset)
        last_ts = self._last_candle_ts.get(asset.id)

        candles = self.broker.get_candles_1m(symbol=symbol, hours=6)
        new_candles = [c for c in candles if last_ts is None or c.time > last_ts]

        if not new_candles:
            return

        new_candles.sort(key=lambda c: c.time)
        for candle in new_candles:
            self._handle_candle(asset, candle)

        self._last_candle_ts[asset.id] = new_candles[-1].time

    def _finalize_all(self) -> None:
        for asset_id, state in list(self._range_state.items()):
            asset = next((a for a in self.assets if a.id == asset_id), None)
            if asset is None:
                continue
            self._finalize_range(asset, state)
        self._range_state.clear()

    def run(self, interval_seconds: int = 5) -> None:
        symbols = [self._get_symbol(asset) for asset in self.assets]
        logger.info("Starting Kraken price stream for assets: %s", ", ".join(symbols))
        self.broker.start_price_stream(symbols)

        persist_interval = 60

        while not self.shutdown.should_stop:
            for asset in self.assets:
                self._process_asset(asset)
            now = time.monotonic()
            if now >= self._next_range_persist_ts:
                self._persist_active_ranges()
                self._next_range_persist_ts = now + persist_interval
            time.sleep(interval_seconds)

        self._finalize_all()


class Command(BaseCommand):
    help = "Run Kraken market data worker (WebSocket trade feed → 1m candles + ranges)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--interval",
            type=int,
            default=5,
            help="Polling interval for new candles in seconds (default: 5)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]

        assets = list(
            TradingAsset.objects.filter(
                is_active=True,
                broker=TradingAsset.BrokerKind.KRAKEN,
            )
        )

        if not assets:
            self.stdout.write(self.style.WARNING("No active Kraken assets configured."))
            return

        registry = BrokerRegistry()
        broker = registry.get_kraken_broker()

        worker = KrakenMarketDataWorker(broker, assets)
        self.stdout.write(self.style.SUCCESS("Kraken market data worker started."))
        try:
            worker.run(interval_seconds=interval)
        finally:
            self.stdout.write(self.style.WARNING("Kraken market data worker stopped."))
