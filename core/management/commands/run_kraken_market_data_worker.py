"""Kraken Market Data Worker.

Fetches Kraken 1m candle data from Charts API v1, stores them in Redis,
and builds session-phase ranges for breakout trading.

Uses the public Kraken Charts API endpoint:
https://futures.kraken.com/api/charts/v1/trade/:symbol/1m

Polls once per minute (configurable) to fetch the latest candle data.
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
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from core.services.broker.config import BrokerRegistry
from core.services.broker.kraken_broker_service import KrakenBrokerService
from core.services.broker.models import Candle1m
from core.services.market_data.redis_candle_store import get_candle_store
from core.services.strategy.models import SessionPhase
from trading.models import AssetSessionPhaseConfig, BreakoutRange, TradingAsset

logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_FETCH_INTERVAL_SECONDS = 30  # Poll Charts API once per minute
RANGE_PERSIST_INTERVAL_SECONDS = 30  # Persist range updates once per minute
WORKER_SLEEP_INTERVAL_SECONDS = 3  # Sleep between iterations to avoid busy-waiting
DEFAULT_TICK_SIZE = 0.01  # Default tick size when asset tick_size is 0 or invalid

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
    """Fetches Kraken candles from Charts API and builds session ranges."""

    def __init__(self, broker: KrakenBrokerService, assets: List[TradingAsset]):
        self.broker = broker
        self.assets = assets
        self.shutdown = GracefulShutdown()
        self._phase_resolvers: Dict[int, AssetPhaseResolver] = {}
        self._range_state: Dict[int, RangeState] = {}
        self._last_candle_ts: Dict[int, datetime] = {}
        self._next_range_persist_ts: float = time.monotonic()
        self._next_fetch_ts: float = time.monotonic()

        for asset in assets:
            configs = AssetSessionPhaseConfig.get_enabled_phases_for_asset(asset)
            self._phase_resolvers[asset.id] = AssetPhaseResolver(asset, configs)

    def _get_symbol(self, asset: TradingAsset) -> str:
        return asset.broker_symbol or asset.epic
    
    def _trim_to_720_candles(self, symbol: str) -> None:
        """Ensure Redis contains at most 720 candles (12 hours) for the symbol."""
        try:
            candle_store = get_candle_store()
            
            if not candle_store.is_connected:
                return
            
            redis_client = candle_store._get_redis_client()
            if redis_client:
                key = candle_store._get_key(symbol, '1m')
                count = redis_client.zcard(key)
                if count > 720:
                    # Remove oldest candles to keep exactly 720
                    excess = count - 720
                    redis_client.zpopmin(key, excess)
                    logger.debug("Trimmed %d old candles for %s (keeping 720)", excess, symbol)
        except Exception as exc:
            logger.debug("Failed to trim candles for %s: %s", symbol, exc)

    def _finalize_range(self, asset: TradingAsset, state: RangeState) -> None:
        self._persist_range_snapshot(asset, state)
        self._range_state.pop(asset.id, None)

    def _persist_range_snapshot(self, asset: TradingAsset, state: RangeState) -> None:
        """
        Persist or update the range snapshot in the database.
        
        Updates the existing range record for the current phase if it exists
        (same phase, same date), otherwise creates a new one.
        This ensures we have only one record per phase per day, updated each minute.
        """
        if state.candle_count == 0:
            return

        end_time = state.last_candle_end or state.start_time
        
        # Extract the trading date (UTC) from start_time
        if state.start_time.tzinfo is None:
            start_time_utc = state.start_time.replace(tzinfo=timezone.utc)
        else:
            start_time_utc = state.start_time.astimezone(timezone.utc)
        trading_date = start_time_utc.date()
        
        # Calculate range metrics
        height_points = Decimal(str(state.high)) - Decimal(str(state.low))
        tick_size_decimal = Decimal(str(asset.tick_size)) if asset.tick_size > 0 else Decimal(str(DEFAULT_TICK_SIZE))
        height_ticks = int((height_points / tick_size_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        
        try:
            with transaction.atomic():
                # Try to find an existing range for this phase and date
                # This ensures we update the same record throughout the day
                existing_range = BreakoutRange.objects.filter(
                    asset=asset,
                    phase=state.phase.value,
                    date=trading_date,
                ).first()
                
                if existing_range:
                    # Update existing record with optimized query
                    # Build list of fields that changed
                    update_fields = []
                    
                    # Only update start_time if the new one is earlier (phase started earlier today)
                    if state.start_time < existing_range.start_time:
                        existing_range.start_time = state.start_time
                        update_fields.append('start_time')
                    
                    existing_range.end_time = end_time
                    existing_range.high = Decimal(str(state.high))
                    existing_range.low = Decimal(str(state.low))
                    existing_range.height_ticks = height_ticks
                    existing_range.height_points = height_points
                    existing_range.candle_count = state.candle_count
                    existing_range.is_valid = True
                    
                    update_fields.extend([
                        'end_time', 'high', 'low', 'height_ticks',
                        'height_points', 'candle_count', 'is_valid'
                    ])
                    
                    existing_range.save(update_fields=update_fields)
                    logger.debug(
                        "Updated %s range for %s (date=%s): high=%.5f low=%.5f candles=%s",
                        state.phase.value,
                        asset.symbol,
                        trading_date,
                        state.high,
                        state.low,
                        state.candle_count,
                    )
                else:
                    # Create new record for new phase/date
                    BreakoutRange.objects.create(
                        asset=asset,
                        phase=state.phase.value,
                        date=trading_date,
                        start_time=state.start_time,
                        end_time=end_time,
                        high=Decimal(str(state.high)),
                        low=Decimal(str(state.low)),
                        height_ticks=height_ticks,
                        height_points=height_points,
                        candle_count=state.candle_count,
                        atr=None,
                        valid_flags={},
                        is_valid=True,
                    )
                    logger.info(
                        "Created new %s range for %s (date=%s): high=%.5f low=%.5f candles=%s",
                        state.phase.value,
                        asset.symbol,
                        trading_date,
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
        """
        Fetch candles from Charts API and process them.

        Per asset:
        - First run (no last_ts for this asset yet): fetch last 12 hours (up to 720 candles) and overwrite Redis.
        - Subsequent runs: fetch recent candles and append only candles newer than last_ts.
        """
        try:
            symbol = self._get_symbol(asset)
            last_ts = self._last_candle_ts.get(asset.id)

            now = datetime.now(timezone.utc)

            # Per-asset first run: no last_ts → fetch 12h history
            if last_ts is None:
                from_time = now - timedelta(hours=12)
                first_run = True
                logger.info("First run for %s: fetching 12 hours of candles from Charts API", symbol)
            else:
                # Subsequent runs: small window is enough, we filter by last_ts anyway
                from_time = now - timedelta(minutes=5)
                first_run = False
                logger.info("Subsequent run for %s: fetching recent candles from Charts API", symbol)

            # Fetch candles from Charts API
            try:
                candles = self.broker.fetch_candles_from_charts_api(
                    symbol=symbol,
                    resolution="1m",
                    from_timestamp=int(from_time.timestamp() * 1000),
                    to_timestamp=int(now.timestamp() * 1000),
                    tick_type="trade",  # oder "mark" – wichtig: muss zu deinem Endpoint passen
                )
            except Exception as exc:
                logger.warning("Failed to fetch candles for %s from Charts API: %s", symbol, exc)
                return

            if not candles:
                logger.warning("Charts API returned no candles for %s (from=%s to=%s)", symbol, from_time, now)
                return

            # Sort ascending by time
            candles.sort(key=lambda c: c.time)

            if first_run:
                # Initial load: keep at most 720 candles
                candles_to_store = candles[-720:] if len(candles) > 720 else candles
                logger.info(
                    "Initializing Redis for %s with %d candles (up to 12h history)",
                    symbol,
                    len(candles_to_store),
                )

                if self.broker.is_candle_store_enabled():
                    candle_store = get_candle_store()
                    candle_store.clear(asset_id=symbol, timeframe="1m")

                    for c in candles_to_store:
                        self.broker.store_candle_to_redis(symbol, c)

                for c in candles_to_store:
                    self._handle_candle(asset, c)

                self._last_candle_ts[asset.id] = candles_to_store[-1].time
                logger.info("Initialized %s with %d candles", symbol, len(candles_to_store))
            else:
                # Only candles newer than last_ts
                new_candles = [c for c in candles if c.time > last_ts]

                if not new_candles:
                    logger.info("No new candles for %s (latest known: %s)", symbol, last_ts)
                    return

                logger.info("Processing %d new candles for %s", len(new_candles), symbol)

                if self.broker.is_candle_store_enabled():
                    for c in new_candles:
                        self.broker.store_candle_to_redis(symbol, c)
                    self._trim_to_720_candles(symbol)

                for c in new_candles:
                    self._handle_candle(asset, c)

                self._last_candle_ts[asset.id] = new_candles[-1].time

        except Exception as exc:
            logger.exception("Error processing asset %s: %s", asset.symbol, exc)



    def _finalize_all(self) -> None:
        for asset_id, state in list(self._range_state.items()):
            asset = next((a for a in self.assets if a.id == asset_id), None)
            if asset is None:
                continue
            self._finalize_range(asset, state)
        self._range_state.clear()

    def run(self, interval_seconds: int = DEFAULT_FETCH_INTERVAL_SECONDS) -> None:
        """
        Main worker loop.
        
        Fetches candles from Charts API once per minute, stores them in Redis,
        and updates session ranges.
        
        Args:
            interval_seconds: Polling interval in seconds (default: 60 for once per minute)
        """
        symbols = [self._get_symbol(asset) for asset in self.assets]
        logger.info("Starting Kraken Charts API worker for assets: %s", ", ".join(symbols))
        logger.info("Fetching candles from Charts API every %d seconds", interval_seconds)
      
        # Persist ranges every minute
        persist_interval = RANGE_PERSIST_INTERVAL_SECONDS
        # Fetch candles every minute (or as configured)
        fetch_interval = interval_seconds

        while not self.shutdown.should_stop:
            now = time.monotonic()
            
            # Fetch new candles once per minute
            if now >= self._next_fetch_ts:
                logger.info("Fetching candles for %d assets", len(self.assets))
                for asset in self.assets:
                    logger.info("Processing asset: %s (%s)", asset.symbol, asset.epic)
                    self._process_asset(asset)
                self._next_fetch_ts = now + fetch_interval
            
            # Persist range snapshots once per minute
            if now >= self._next_range_persist_ts:
                self._persist_active_ranges()
                self._next_range_persist_ts = now + persist_interval
            
            # Sleep for a short interval to avoid busy-waiting
            time.sleep(WORKER_SLEEP_INTERVAL_SECONDS)

        self._finalize_all()


class Command(BaseCommand):
    help = "Run Kraken market data worker (Charts API v1 → 1m candles + ranges)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--interval",
            type=int,
            default=DEFAULT_FETCH_INTERVAL_SECONDS,
            help=f"Polling interval for fetching candles from Charts API in seconds (default: {DEFAULT_FETCH_INTERVAL_SECONDS})",
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
