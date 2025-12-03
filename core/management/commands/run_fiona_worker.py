"""
Fiona Background Worker v1.1 - Multi-Broker Support.

Management command for running the Fiona trading system background worker.
Continuously fetches market data, runs strategy analysis, evaluates risk,
and executes trades (real or shadow).

Supports multiple brokers (IG, MEXC) with automatic broker selection per asset.

Usage:
    python manage.py run_fiona_worker
    python manage.py run_fiona_worker --interval 60 --shadow-only
    python manage.py run_fiona_worker --epic CC.D.CL.UNC.IP --verbose
"""
import logging
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from django.core.management.base import BaseCommand

from core.services.broker import (
    BrokerService,
    IGMarketStateProvider,
    BrokerError,
    AuthenticationError,
    BrokerRegistry,
    SessionTimesConfig,
)
from trading.models import WorkerStatus, AssetDiagnostics, AssetPriceStatus, PriceSnapshot
from core.services.strategy import (
    StrategyEngine,
    StrategyConfig,
    SessionPhase,
)
from core.services.risk import RiskEngine
from core.services.risk.models import RiskConfig
from core.services.execution import ExecutionService
from core.services.execution.models import ExecutionConfig
from core.services.weaviate import WeaviateService
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class AssetCycleResult:
    """Result of a single asset cycle execution."""
    setups_found: int = 0
    bid_price: Optional[Decimal] = None
    ask_price: Optional[Decimal] = None
    spread: Optional[Decimal] = None
    status_message: Optional[str] = None


class GracefulShutdown:
    """Handler for graceful shutdown on SIGINT/SIGTERM."""
    
    def __init__(self):
        self.should_stop = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
    
    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.should_stop = True


class Command(BaseCommand):
    help = 'Run the Fiona trading system background worker'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.broker_registry: Optional[BrokerRegistry] = None
        self.market_state_provider: Optional[IGMarketStateProvider] = None
        self.strategy_engine: Optional[StrategyEngine] = None
        self.risk_engine: Optional[RiskEngine] = None
        self.execution_service: Optional[ExecutionService] = None
        self.weaviate_service: Optional[WeaviateService] = None
        self.shutdown_handler: Optional[GracefulShutdown] = None
        self._last_price_snapshot_cleanup: Optional[datetime] = None
        # Track intra-phase highs/lows per epic using observed mid prices.
        # Broker-provided daily low values would otherwise bleed into later phases
        # (e.g., using the Asia low for London or US ranges).
        self._phase_range_tracker: dict[str, dict[str, float]] = {}

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Polling interval in seconds (default: 60)'
        )
        parser.add_argument(
            '--shadow-only',
            action='store_true',
            help='Run in shadow trading mode only (no real trades)'
        )
        parser.add_argument(
            '--epic',
            type=str,
            default='CC.D.CL.UNC.IP',
            help='Market EPIC to trade (default: CC.D.CL.UNC.IP for WTI Crude). Ignored if --multi-asset is used.'
        )
        parser.add_argument(
            '--multi-asset',
            action='store_true',
            help='Process all active assets from the database instead of a single EPIC'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose logging'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dry run mode - do not execute any trades'
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run once and exit (useful for testing)'
        )
        parser.add_argument(
            '--max-iterations',
            type=int,
            default=0,
            help='Maximum number of iterations (0 = unlimited)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        shadow_only = options['shadow_only']
        epic = options['epic']
        multi_asset = options['multi_asset']
        verbose = options['verbose']
        dry_run = options['dry_run']
        run_once = options['once']
        max_iterations = options['max_iterations']
        
        # Configure logging
        if verbose:
            logging.getLogger('core').setLevel(logging.DEBUG)
            logging.getLogger(__name__).setLevel(logging.DEBUG)
        
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Fiona Worker v1.1 - Multi-Asset Support"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        if multi_asset:
            self.stdout.write("Mode: Multi-Asset (from database)")
        else:
            self.stdout.write(f"Epic: {epic}")
        self.stdout.write(f"Interval: {interval}s")
        self.stdout.write(f"Shadow Only: {shadow_only}")
        self.stdout.write(f"Dry Run: {dry_run}")
        self.stdout.write("")
        
        # Set up graceful shutdown
        self.shutdown_handler = GracefulShutdown()
        
        try:
            # Initialize all services
            self._initialize_services(epic, shadow_only)
            
            # Main loop
            iteration = 0
            while not self.shutdown_handler.should_stop:
                iteration += 1
                
                if max_iterations > 0 and iteration > max_iterations:
                    self.stdout.write(f"Reached max iterations ({max_iterations}), stopping.")
                    break
                
                try:
                    if multi_asset:
                        self._run_multi_asset_cycle(shadow_only, dry_run, interval)
                    else:
                        self._run_cycle(epic, shadow_only, dry_run, interval)
                except BrokerError as e:
                    self.stdout.write(self.style.ERROR(f"Broker error: {e}"))
                    logger.exception("Broker error in main loop")
                    # Try to reconnect
                    self._try_reconnect()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error in cycle: {e}"))
                    logger.exception("Unexpected error in main loop")
                
                if run_once:
                    self.stdout.write("Single run completed, exiting.")
                    break
                
                if not self.shutdown_handler.should_stop:
                    self.stdout.write(f"Sleeping for {interval}s...")
                    time.sleep(interval)
            
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nShutdown requested via keyboard"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Fatal error: {e}"))
            logger.exception("Fatal error in worker")
            sys.exit(1)
        finally:
            self._cleanup()
        
        self.stdout.write(self.style.SUCCESS("\nFiona Worker stopped cleanly."))

    def _initialize_services(self, epic: str, shadow_only: bool) -> None:
        """Initialize all required services."""
        self.stdout.write("Initializing services...")
        
        # 1. Create Broker Registry (manages multiple broker services)
        self.stdout.write("  → Creating Broker Registry...")
        try:
            self.broker_registry = BrokerRegistry()
            self.stdout.write(self.style.SUCCESS("    ✓ Broker Registry created"))
        except Exception as e:
            raise RuntimeError(f"Failed to create Broker Registry: {e}")
        
        # 2. Initialize default IG Broker for backward compatibility
        # (will be replaced by per-asset broker selection in multi-asset mode)
        self.stdout.write("  → Connecting to default broker (IG)...")
        try:
            default_broker = self.broker_registry.get_ig_broker()
            self.stdout.write(self.style.SUCCESS("    ✓ Connected to IG"))
        except AuthenticationError as e:
            logger.warning(f"IG authentication failed: {e}")
            self.stdout.write(self.style.WARNING(f"    ⚠ IG authentication failed: {e}"))
            default_broker = None
        except Exception as e:
            logger.warning(f"Failed to connect to IG: {e}")
            self.stdout.write(self.style.WARNING(f"    ⚠ Failed to connect to IG: {e}"))
            default_broker = None
        
        # 3. Get account state to verify connection (if broker available)
        if default_broker:
            try:
                account = default_broker.get_account_state()
                self.stdout.write(f"    Account: {account.account_name}")
                self.stdout.write(f"    Balance: {account.balance} {account.currency}")
                self.stdout.write(f"    Available: {account.available} {account.currency}")
            except Exception as e:
                logger.warning(f"Could not get account state: {e}")
        
        # 4. Create Market State Provider (with broker registry for multi-broker support)
        self.stdout.write("  → Creating Market State Provider...")
        self.market_state_provider = IGMarketStateProvider(
            broker_service=default_broker,
            eia_timestamp=None,  # Can be set later if needed
            broker_registry=self.broker_registry,
        )
        self.stdout.write(self.style.SUCCESS("    ✓ Market State Provider created"))
        
        # 5. Load Strategy Config
        self.stdout.write("  → Loading Strategy Config...")
        strategy_config = StrategyConfig(
            default_epic=epic,
            tick_size=0.01,  # Default for WTI Crude
        )
        self.stdout.write(self.style.SUCCESS("    ✓ Strategy Config loaded"))
        
        # 6. Create Strategy Engine
        self.stdout.write("  → Creating Strategy Engine...")
        self.strategy_engine = StrategyEngine(
            market_state=self.market_state_provider,
            config=strategy_config,
        )
        self.stdout.write(self.style.SUCCESS("    ✓ Strategy Engine created"))
        
        # 7. Load Risk Config
        self.stdout.write("  → Loading Risk Config...")
        risk_config = RiskConfig()  # Use defaults
        self.stdout.write(self.style.SUCCESS("    ✓ Risk Config loaded"))
        
        # 8. Create Risk Engine
        self.stdout.write("  → Creating Risk Engine...")
        self.risk_engine = RiskEngine(config=risk_config)
        self.stdout.write(self.style.SUCCESS("    ✓ Risk Engine created"))
        
        # 9. Create Weaviate Service
        self.stdout.write("  → Creating Weaviate Service...")
        self.weaviate_service = WeaviateService()  # Uses in-memory by default
        self.stdout.write(self.style.SUCCESS("    ✓ Weaviate Service created"))
        
        # 10. Create Execution Service
        # Note: ExecutionService now gets broker per-asset via BrokerRegistry
        self.stdout.write("  → Creating Execution Service...")
        execution_config = ExecutionConfig(
            allow_shadow_if_risk_denied=True,
        )
        self.execution_service = ExecutionService(
            broker_service=None,  # Will use per-asset broker selection
            weaviate_service=self.weaviate_service,
            config=execution_config,
            broker_registry=self.broker_registry,
            shadow_only=shadow_only,
        )
        self.stdout.write(self.style.SUCCESS("    ✓ Execution Service created"))
        
        self.stdout.write(self.style.SUCCESS("\n✓ All services initialized successfully!"))
        self.stdout.write("")

    def _run_cycle(self, epic: str, shadow_only: bool, dry_run: bool, worker_interval: int = 60) -> None:
        """Run one cycle of the worker loop (legacy single-asset mode)."""
        now = datetime.now(timezone.utc)
        
        # Initialize status tracking variables
        bid_price = None
        ask_price = None
        spread = None
        setup_count = 0
        diagnostic_message = ''
        diagnostic_criteria = []
        
        # 1. Determine session phase
        phase = self.market_state_provider.get_phase(now)
        self.stdout.write(f"\n[{now.strftime('%H:%M:%S')} UTC] Phase: {phase.value}")
        
        # 2. Update candle cache with current price
        try:
            self.market_state_provider.update_candle_from_price(epic)
        except Exception as e:
            logger.warning(f"Failed to update candle: {e}")
        
        # 3. Get current price for logging (using default IG broker for legacy mode)
        price = None
        try:
            default_broker = self.broker_registry.get_ig_broker()
            price = default_broker.get_symbol_price(epic)
            bid_price = price.bid
            ask_price = price.ask
            spread = price.spread
            self.stdout.write(
                f"  Price: {price.bid}/{price.ask} (spread: {price.spread})"
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Could not get price: {e}"))
            diagnostic_message = f"Could not get price: {e}"
        
        # 4. Skip if not in tradeable phase
        if phase in [SessionPhase.FRIDAY_LATE, SessionPhase.OTHER]:
            self.stdout.write("  → Phase not tradeable, skipping strategy evaluation")
            diagnostic_message = f"Phase {phase.value} not tradeable, skipping strategy evaluation"
            diagnostic_criteria = [
                {"name": "Session Phase", "passed": True, "detail": f"Current phase: {phase.value}"},
                {"name": "Phase is tradeable", "passed": False, "detail": f"{phase.value} is not a tradeable phase"},
            ]
            self._update_worker_status(
                now, phase, epic, setup_count, bid_price, ask_price, spread,
                diagnostic_message, diagnostic_criteria, worker_interval
            )
            return
        
        # 5. Run Strategy Engine with diagnostics
        self.stdout.write("  → Running Strategy Engine...")
        try:
            eval_result = self.strategy_engine.evaluate_with_diagnostics(epic, now)
            setups = eval_result.setups
            setup_count = len(setups)
            diagnostic_message = eval_result.summary
            diagnostic_criteria = eval_result.to_criteria_list()
            self.stdout.write(f"    Found {len(setups)} setup(s)")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Strategy error: {e}"))
            logger.exception("Strategy evaluation failed")
            diagnostic_message = f"Strategy evaluation error: {e}"
            diagnostic_criteria = [
                {"name": "Strategy evaluation", "passed": False, "detail": str(e)},
            ]
            self._update_worker_status(
                now, phase, epic, setup_count, bid_price, ask_price, spread,
                diagnostic_message, diagnostic_criteria, worker_interval
            )
            return
        
        if not setups:
            self.stdout.write("  → No setups found")
            self._update_worker_status(
                now, phase, epic, setup_count, bid_price, ask_price, spread,
                diagnostic_message, diagnostic_criteria, worker_interval
            )
            return
        
        # Setups found - update status with success message
        self._update_worker_status(
            now, phase, epic, setup_count, bid_price, ask_price, spread,
            diagnostic_message, diagnostic_criteria, worker_interval
        )
        
        # 6. Process each setup
        for setup in setups:
            # Legacy mode doesn't use AssetDiagnostics, pass None
            self._process_setup(setup, shadow_only, dry_run, now, diagnostics=None)
    
    def _run_multi_asset_cycle(self, shadow_only: bool, dry_run: bool, worker_interval: int = 60) -> None:
        """
        Run one cycle processing all active assets from the database.
        
        This method iterates over all TradingAssets marked as active and
        runs the strategy evaluation for each one using asset-specific configurations.
        """
        from trading.models import TradingAsset
        
        now = datetime.now(timezone.utc)
        
        # Load all active assets
        active_assets = TradingAsset.objects.filter(is_active=True).prefetch_related(
            'breakout_config', 'event_configs'
        )
        
        asset_count = active_assets.count()
        if asset_count == 0:
            self.stdout.write(self.style.WARNING(
                f"\n[{now.strftime('%H:%M:%S')} UTC] No active assets found in database"
            ))
            self._update_worker_status(
                now=now,
                phase=SessionPhase.OTHER,
                epic='N/A',
                setup_count=0,
                bid_price=None,
                ask_price=None,
                spread=None,
                diagnostic_message='No active assets configured in database',
                diagnostic_criteria=[{
                    'name': 'Active Assets',
                    'passed': False,
                    'detail': 'Please configure at least one active asset in the UI'
                }],
                worker_interval=worker_interval,
            )
            return
        
        self.stdout.write(f"\n[{now.strftime('%H:%M:%S')} UTC] Processing {asset_count} active asset(s)")
        
        total_setups = 0
        processed_epics = []
        # Track price from first asset with valid prices for WorkerStatus
        last_bid_price = None
        last_ask_price = None
        last_spread = None
        
        # Process each active asset
        for asset in active_assets:
            self.stdout.write(f"\n  📈 Asset: {asset.name} ({asset.symbol})")
            self.stdout.write(f"     EPIC: {asset.epic}")
            
            try:
                # Get asset-specific strategy config
                strategy_config = asset.get_strategy_config()
                
                # Create a new strategy engine with this asset's config
                asset_strategy_engine = StrategyEngine(
                    market_state=self.market_state_provider,
                    config=strategy_config,
                )
                
                # Run cycle for this asset
                cycle_result = self._run_asset_cycle(
                    asset=asset,
                    strategy_engine=asset_strategy_engine,
                    shadow_only=shadow_only,
                    dry_run=dry_run,
                    now=now,
                )
                
                total_setups += cycle_result.setups_found
                processed_epics.append(asset.epic)
                
                # Use price from first asset with valid prices
                if last_bid_price is None and cycle_result.bid_price is not None:
                    last_bid_price = cycle_result.bid_price
                    last_ask_price = cycle_result.ask_price
                    last_spread = cycle_result.spread
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     ✗ Error processing asset: {e}"))
                logger.exception(f"Error processing asset {asset.epic}")
        
        # Update worker status with summary including price from first asset
        phase = self.market_state_provider.get_phase(now)
        self._update_worker_status(
            now=now,
            phase=phase,
            epic=f"{asset_count} assets",  # Show count instead of single epic
            setup_count=total_setups,
            bid_price=last_bid_price,
            ask_price=last_ask_price,
            spread=last_spread,
            diagnostic_message=f"Processed {asset_count} assets: {', '.join(processed_epics)}",
            diagnostic_criteria=[{
                'name': f'Active Assets ({asset_count})',
                'passed': True,
                'detail': ', '.join(processed_epics)
            }],
            worker_interval=worker_interval,
        )
        
        # Clean up old price snapshots periodically (once per hour) to keep database lean
        # Retain 2 hours of data (enough for the 60-minute chart display)
        self._maybe_cleanup_old_price_snapshots(now)
    
    def _maybe_cleanup_old_price_snapshots(self, now: datetime) -> None:
        """
        Clean up old price snapshots if an hour has passed since last cleanup.
        
        This avoids running cleanup on every cycle which could be inefficient
        as the number of assets grows.
        """
        # Run cleanup at most once per hour
        if (self._last_price_snapshot_cleanup is None or
                (now - self._last_price_snapshot_cleanup) >= timedelta(hours=1)):
            try:
                deleted = PriceSnapshot.cleanup_old_snapshots(hours=2)
                self._last_price_snapshot_cleanup = now
                if deleted > 0:
                    logger.debug(f"Cleaned up {deleted} old price snapshots")
            except Exception as e:
                logger.warning(f"Failed to clean up old price snapshots: {e}")
    
    def _run_asset_cycle(
        self,
        asset,
        strategy_engine: StrategyEngine,
        shadow_only: bool,
        dry_run: bool,
        now: datetime
    ) -> AssetCycleResult:
        """
        Run strategy evaluation for a single asset.
        
        This method uses the asset's broker configuration to get market data
        from the correct broker (IG or MEXC). It also handles range building
        and persistence when in range-building phases.
        
        Args:
            asset: TradingAsset instance
            strategy_engine: Strategy engine configured for this asset
            shadow_only: Whether to only create shadow trades
            dry_run: Whether to skip trade execution
            now: Current timestamp
            
        Returns:
            AssetCycleResult with setups found and price information
        """
        from trading.models import AssetSessionPhaseConfig
        
        epic = asset.epic
        broker_symbol = asset.effective_broker_symbol
        result = AssetCycleResult()
        result.status_message = "Starting asset cycle"
        
        # Get the broker service for this asset
        try:
            asset_broker = self.broker_registry.get_broker_for_asset(asset)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"     Could not get broker for {asset.broker}: {e}"))
            logger.exception(f"Failed to get broker for asset {epic}")
            return result
        
        # Set current asset for range persistence (Acceptance Criteria #2)
        self.market_state_provider.set_current_asset(asset)
        
        try:
            # 1. Configure session times from asset's Sessions & Phases configuration
            # Pre-fetch all phase configs for this asset to avoid N+1 queries
            phase_configs_by_phase = {}
            try:
                phase_configs = list(AssetSessionPhaseConfig.get_enabled_phases_for_asset(asset))
                phase_configs_by_phase = {pc.phase: pc for pc in phase_configs}
                
                # Build session times from phase configs
                session_times_kwargs = {}
                for pc in phase_configs:
                    if pc.phase == 'ASIA_RANGE':
                        session_times_kwargs['asia_start'] = pc.start_time_utc
                        session_times_kwargs['asia_end'] = pc.end_time_utc
                    elif pc.phase == 'LONDON_CORE':
                        session_times_kwargs['london_core_start'] = pc.start_time_utc
                        session_times_kwargs['london_core_end'] = pc.end_time_utc
                    elif pc.phase == 'PRE_US_RANGE':
                        session_times_kwargs['pre_us_start'] = pc.start_time_utc
                        session_times_kwargs['pre_us_end'] = pc.end_time_utc
                    elif pc.phase == 'US_CORE_TRADING':
                        session_times_kwargs['us_core_trading_start'] = pc.start_time_utc
                        session_times_kwargs['us_core_trading_end'] = pc.end_time_utc
                        session_times_kwargs['us_core_trading_enabled'] = pc.enabled
                
                if session_times_kwargs:
                    session_times = SessionTimesConfig.from_time_strings(**session_times_kwargs)
                    self.market_state_provider.set_session_times(session_times)
                else:
                    # Fallback to breakout config if no session phase configs exist
                    logger.debug(f"No AssetSessionPhaseConfig found for {epic}, falling back to AssetBreakoutConfig")
                    try:
                        breakout_cfg = asset.breakout_config
                        session_times = SessionTimesConfig.from_time_strings(
                            asia_start=getattr(breakout_cfg, 'asia_range_start', '00:00'),
                            asia_end=getattr(breakout_cfg, 'asia_range_end', '08:00'),
                            pre_us_start=getattr(breakout_cfg, 'pre_us_start', '13:00'),
                            pre_us_end=getattr(breakout_cfg, 'pre_us_end', '15:00'),
                            us_core_trading_start=getattr(breakout_cfg, 'us_core_trading_start', '15:00'),
                            us_core_trading_end=getattr(breakout_cfg, 'us_core_trading_end', '22:00'),
                            us_core_trading_enabled=getattr(breakout_cfg, 'us_core_trading_enabled', True),
                        )
                        self.market_state_provider.set_session_times(session_times)
                    except Exception:
                        logger.debug(f"No AssetBreakoutConfig found for {epic}, using default session times")
                        self.market_state_provider.set_session_times(SessionTimesConfig())
            except Exception as e:
                logger.debug(f"Using default session times for {epic}: {e}")
                # Use default session times if no configuration exists
                self.market_state_provider.set_session_times(SessionTimesConfig())
            
            # 2. Determine session phase (now using asset-specific times)
            phase = self.market_state_provider.get_phase(now)
            self.stdout.write(f"     Phase: {phase.value}")
            
            # 3. Update candle cache with current price
            # The provider automatically uses the correct broker via BrokerRegistry
            # when current_asset is set (done above via set_current_asset)
            try:
                self.market_state_provider.update_candle_from_price()
            except Exception as e:
                logger.warning(f"Failed to update candle for {broker_symbol}: {e}")
            
            # 4. Get current price for logging and range building
            # Use asset-specific broker and broker_symbol
            current_price = None
            try:
                price = asset_broker.get_symbol_price(broker_symbol)
                current_price = price
                # Store price in result for WorkerStatus update
                result.bid_price = Decimal(str(price.bid)) if price.bid is not None else None
                result.ask_price = Decimal(str(price.ask)) if price.ask is not None else None
                result.spread = Decimal(str(price.spread)) if price.spread is not None else None
                self.stdout.write(f"     Price: {price.bid}/{price.ask} (via {asset.broker})")

                # Record price snapshot for Breakout Distance Chart
                # Calculate mid price from bid/ask (price.bid and price.ask are already Decimal)
                if price.bid is not None and price.ask is not None:
                    try:
                        price_mid = (price.bid + price.ask) / 2
                        PriceSnapshot.record_snapshot(
                            asset=asset,
                            price_mid=price_mid,
                            price_bid=price.bid,
                            price_ask=price.ask,
                        )
                    except Exception as snapshot_error:
                        # Don't let price snapshot failures break the trading workflow
                        logger.warning(f"Failed to record price snapshot for {epic}: {snapshot_error}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"     Could not get price: {e}"))
                result.status_message = f"Could not get price: {e}"
            
            # 5. Build and persist range if in a range-building phase
            range_built_phase = self._build_range_for_phase(asset, epic, phase, phase_configs_by_phase, current_price, now)
            
            # 6. Skip if not in tradeable phase - check using is_trading_phase flag
            # Use pre-fetched phase configs to avoid additional DB query
            is_tradeable = False
            phase_config = phase_configs_by_phase.get(phase.value)
            if phase_config:
                is_tradeable = phase_config.is_trading_phase
            else:
                # Fallback to legacy behavior for phases not in config (e.g., FRIDAY_LATE, OTHER)
                # These phases are not tradeable by default
                if phase in [SessionPhase.FRIDAY_LATE, SessionPhase.OTHER]:
                    is_tradeable = False
                else:
                    # For other phases without config, log a warning and don't trade
                    logger.debug(f"No phase config for {phase.value} on {epic}, using fallback (not tradeable)")
                    is_tradeable = False
            
            if not is_tradeable:
                self.stdout.write("     → Phase not tradeable, skipping")
                # Still update diagnostics for non-tradeable phases
                self._update_asset_diagnostics(
                    asset=asset,
                    now=now,
                    phase=phase,
                    setups_found=0,
                    candles_evaluated=1,  # At least one cycle was run
                    range_built_phase=range_built_phase,
                )
                result.status_message = f"Phase {phase.value} not tradeable"
                return result
            
            # 7. Run Strategy Engine
            try:
                setups = strategy_engine.evaluate(epic, now)
                result.setups_found = len(setups)
                self.stdout.write(f"     Found {len(setups)} setup(s)")
                result.status_message = strategy_engine.last_status_message or result.status_message
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     Strategy error: {e}"))
                logger.exception(f"Strategy evaluation failed for {epic}")
                result.status_message = f"Strategy evaluation failed: {e}"
                # Update diagnostics even on strategy error
                self._update_asset_diagnostics(
                    asset=asset,
                    now=now,
                    phase=phase,
                    setups_found=0,
                    candles_evaluated=1,
                    range_built_phase=range_built_phase,
                )
                return result
            
            # Update diagnostics with the results
            diagnostics = self._update_asset_diagnostics(
                asset=asset,
                now=now,
                phase=phase,
                setups_found=len(setups),
                candles_evaluated=1,
                range_built_phase=range_built_phase,
                setups_discarded=strategy_engine.last_discarded_count,
            )

            if not setups:
                result.status_message = strategy_engine.last_status_message or result.status_message or "No setups generated"
                return result

            # 8. Process each setup
            for setup in setups:
                self._process_setup(setup, shadow_only, dry_run, now, trading_asset=asset, diagnostics=diagnostics)
            
            # Save diagnostics after processing all setups to persist risk engine counters
            if diagnostics:
                try:
                    diagnostics.save()
                except Exception as e:
                    logger.warning(f"Failed to save diagnostics after setup processing: {e}")

            result.status_message = strategy_engine.last_status_message or result.status_message
            return result

        finally:
            status_message = result.status_message or "No status available"
            try:
                AssetPriceStatus.update_price(
                    asset=asset,
                    bid_price=result.bid_price,
                    ask_price=result.ask_price,
                    spread=result.spread,
                    status_message=status_message,
                )
            except Exception as price_status_error:
                logger.warning(f"Failed to persist price status for {epic}: {price_status_error}")
            # Clear current asset after processing
            self.market_state_provider.clear_current_asset()

    def _build_range_for_phase(
        self,
        asset,
        epic: str,
        phase: SessionPhase,
        phase_configs: dict,
        current_price,
        now: datetime
    ) -> str:
        """
        Build and persist range data for the current phase.
        
        If the current phase is a range-building phase (ASIA_RANGE, LONDON_CORE, PRE_US_RANGE),
        this method will update the range high/low from the current price and persist it.
        
        This ensures ranges are captured even during the range-building period,
        not just at the end.
        
        Args:
            asset: TradingAsset instance
            epic: Market EPIC
            phase: Current session phase
            phase_configs: Dict of phase configs by phase name
            current_price: Current SymbolPrice (or None)
            now: Current timestamp
            
        Returns:
            str: Phase name for which range was built ('asia', 'london', 'pre_us'), or None if no range built
        """
        if current_price is None:
            return None
        
        # Get phase config to check if this is a range-building phase
        phase_config = phase_configs.get(phase.value)
        is_range_build = False
        
        if phase_config:
            is_range_build = phase_config.is_range_build_phase
        else:
            # Fallback: these phases are range-building phases by default
            is_range_build = phase in [
                SessionPhase.ASIA_RANGE,
                SessionPhase.LONDON_CORE,
                SessionPhase.PRE_US_RANGE,
            ]
        
        if not is_range_build:
            return None
        
        # Use mid price to build per-phase ranges. Broker-provided high/low values
        # are daily extremes and would keep the Asia low for all following phases.
        mid_price = None
        try:
            mid_price = float(current_price.mid_price)
        except Exception:
            mid_price = None

        if mid_price is None:
            try:
                if current_price.bid is not None and current_price.ask is not None:
                    mid_price = float((current_price.bid + current_price.ask) / 2)
            except Exception:
                mid_price = None

        if mid_price is None:
            logger.debug(f"No mid price for {epic}, skipping range build")
            return None

        tracker = self._phase_range_tracker.get(epic, {})
        if tracker.get("phase") != phase:
            tracker = {"phase": phase, "high": mid_price, "low": mid_price}
        else:
            tracker["high"] = max(tracker.get("high", mid_price), mid_price)
            tracker["low"] = min(tracker.get("low", mid_price), mid_price)

        self._phase_range_tracker[epic] = tracker
        high = tracker["high"]
        low = tracker["low"]
        
        # Get ATR for context
        atr = self.market_state_provider.get_atr(epic, '1h', 14)
        
        # Get candle count
        candle_count = self.market_state_provider.get_candle_count_for_epic(epic)
        
        # Set the range based on current phase
        # Note: The set_*_range methods will persist to database
        if phase == SessionPhase.ASIA_RANGE:
            self.market_state_provider.set_asia_range(
                epic=epic,
                high=high,
                low=low,
                start_time=None,  # Will use now
                end_time=now,
                candle_count=candle_count,
                atr=atr,
            )
            return 'asia'
        elif phase == SessionPhase.LONDON_CORE:
            self.market_state_provider.set_london_core_range(
                epic=epic,
                high=high,
                low=low,
                start_time=None,
                end_time=now,
                candle_count=candle_count,
                atr=atr,
            )
            return 'london'
        elif phase == SessionPhase.PRE_US_RANGE:
            self.market_state_provider.set_pre_us_range(
                epic=epic,
                high=high,
                low=low,
                start_time=None,
                end_time=now,
                candle_count=candle_count,
                atr=atr,
            )
            return 'pre_us'
        
        return None
    
    def _update_worker_status(
        self,
        now: datetime,
        phase,
        epic: str,
        setup_count: int,
        bid_price,
        ask_price,
        spread,
        diagnostic_message: str,
        diagnostic_criteria: list = None,
        worker_interval: int = 60
    ) -> None:
        """Update the worker status in the database."""
        try:
            from decimal import Decimal
            WorkerStatus.update_status(
                last_run_at=now,
                phase=phase.value if hasattr(phase, 'value') else str(phase),
                epic=epic,
                setup_count=setup_count,
                bid_price=Decimal(str(bid_price)) if bid_price is not None else None,
                ask_price=Decimal(str(ask_price)) if ask_price is not None else None,
                spread=Decimal(str(spread)) if spread is not None else None,
                diagnostic_message=diagnostic_message,
                diagnostic_criteria=diagnostic_criteria or [],
                worker_interval=worker_interval,
            )
        except Exception as e:
            logger.warning(f"Failed to update worker status: {e}")

    def _update_asset_diagnostics(
        self,
        asset,
        now: datetime,
        phase,
        setups_found: int = 0,
        candles_evaluated: int = 0,
        range_built_phase: str = None,
        setups_discarded: int = 0,
    ) -> AssetDiagnostics:
        """
        Update or create AssetDiagnostics record for the current time window.
        
        This method creates diagnostic records that can be queried by the
        Trading Diagnostics UI to understand why (not) trading is happening.
        
        Args:
            asset: TradingAsset instance
            now: Current timestamp
            phase: Current session phase
            setups_found: Number of setups generated
            candles_evaluated: Number of candles evaluated
            range_built_phase: Phase for which a range was built (e.g., 'asia', 'london', 'pre_us', 'us_core')
            setups_discarded: Number of setups discarded by strategy filters
            
        Returns:
            AssetDiagnostics: The updated or created diagnostics record
        """
        try:
            # Use 1-hour windows for diagnostics aggregation
            window_start = now.replace(minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(hours=1)
            
            # Get or create diagnostics record for this window
            diagnostics = AssetDiagnostics.get_or_create_for_window(
                asset=asset,
                window_start=window_start,
                window_end=window_end,
            )
            
            # Update current phase and trading mode
            # Phase is expected to be a SessionPhase enum, extract value
            diagnostics.current_phase = phase.value
            diagnostics.trading_mode = asset.trading_mode
            diagnostics.last_cycle_at = now
            
            # Update counters
            diagnostics.candles_evaluated += candles_evaluated
            diagnostics.setups_generated_total += setups_found
            diagnostics.setups_discarded_strategy += setups_discarded
            
            # Update range built counters if applicable
            # Map phase names to field names
            range_field_map = {
                'asia': 'ranges_built_asia',
                'london': 'ranges_built_london',
                'pre_us': 'ranges_built_pre_us',
                'us_core': 'ranges_built_us_core',
            }
            if range_built_phase and range_built_phase in range_field_map:
                field_name = range_field_map[range_built_phase]
                setattr(diagnostics, field_name, getattr(diagnostics, field_name) + 1)
            
            diagnostics.save()
            return diagnostics
            
        except Exception as e:
            logger.warning(f"Failed to update asset diagnostics for {asset.symbol}: {e}")
            return None

    def _process_setup(self, setup, shadow_only: bool, dry_run: bool, now: datetime, trading_asset=None, diagnostics=None) -> None:
        """Process a single setup through risk and execution.
        
        Args:
            setup: SetupCandidate from Strategy Engine
            shadow_only: Whether to only create shadow trades
            dry_run: Whether to skip trade execution
            now: Current timestamp
            trading_asset: Optional TradingAsset model instance for linking signals
            diagnostics: Optional AssetDiagnostics instance for tracking metrics
        """
        self.stdout.write(
            f"\n  Setup: {setup.setup_kind.value} {setup.direction} @ {setup.reference_price}"
        )

        breakout_type = None
        if getattr(setup, 'breakout', None) and setup.breakout.signal_type:
            breakout_type = setup.breakout.signal_type.value
            self.stdout.write(
                f"    Breakout Type: {breakout_type} → Entry Direction: {setup.direction}"
            )
            logger.info(
                "Processing breakout setup",
                extra={
                    "worker_data": {
                        "setup_id": setup.id,
                        "breakout_type": breakout_type,
                        "direction": setup.direction,
                        "phase": getattr(setup, 'phase', None).value if getattr(setup, 'phase', None) else None,
                    }
                },
            )

        # Store setup in Weaviate
        try:
            self.weaviate_service.store_setup(setup)
            self.stdout.write("    ✓ Setup stored")
        except Exception as e:
            logger.warning(f"Failed to store setup: {e}")
        
        # Get the broker for this asset
        try:
            if trading_asset:
                asset_broker = self.broker_registry.get_broker_for_asset(trading_asset)
                broker_symbol = trading_asset.effective_broker_symbol
            else:
                # Fallback to IG broker for legacy mode
                asset_broker = self.broker_registry.get_ig_broker()
                broker_symbol = setup.epic
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Failed to get broker: {e}"))
            return
        
        # Get account state for risk evaluation
        try:
            account = asset_broker.get_account_state()
            positions = asset_broker.get_open_positions()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Failed to get account state: {e}"))
            return
        
        # Build a basic order request for risk evaluation
        from core.services.broker.models import OrderRequest, OrderDirection
        
        direction = OrderDirection.BUY if setup.direction == "LONG" else OrderDirection.SELL
        
        # Calculate basic SL/TP from ATR or default
        atr = self.market_state_provider.get_atr(setup.epic, '1h', 14)
        if atr is None:
            atr = 0.50  # Default for oil
        
        sl_distance = atr * 1.5
        tp_distance = atr * 2.0
        
        if setup.direction == "LONG":
            stop_loss = Decimal(str(setup.reference_price - sl_distance))
            take_profit = Decimal(str(setup.reference_price + tp_distance))
        else:
            stop_loss = Decimal(str(setup.reference_price + sl_distance))
            take_profit = Decimal(str(setup.reference_price - tp_distance))
        
        # Use broker_symbol for the order
        order = OrderRequest(
            epic=broker_symbol,
            direction=direction,
            size=Decimal('1.0'),
            stop_loss=stop_loss,
            take_profit=take_profit,
            currency='EUR',
        )
        
        # Run Risk Engine
        self.stdout.write("    → Evaluating risk...")
        try:
            risk_result = self.risk_engine.evaluate(
                account=account,
                positions=positions,
                setup=setup,
                order=order,
                now=now,
            )
            
            # Update diagnostics for risk engine evaluation
            if diagnostics:
                diagnostics.setups_evaluated_by_risk += 1
                
                if risk_result.allowed:
                    diagnostics.setups_approved_by_risk += 1
                else:
                    diagnostics.setups_rejected_by_risk += 1
                
                # Track rejection reasons if any
                if not risk_result.allowed and risk_result.violations:
                    for violation in risk_result.violations:
                        # Extract reason code if it matches pattern
                        if violation.startswith('RISK_'):
                            diagnostics.increment_risk_reason(violation.split(':')[0].strip())
            
            if risk_result.allowed:
                self.stdout.write(self.style.SUCCESS(f"    ✓ Risk approved: {risk_result.reason}"))
            else:
                self.stdout.write(self.style.WARNING(f"    ✗ Risk denied: {risk_result.reason}"))
                for violation in risk_result.violations:
                    self.stdout.write(f"      - {violation}")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Risk evaluation failed: {e}"))
            logger.exception("Risk evaluation failed")
            return
        
        if dry_run:
            self.stdout.write("    [DRY RUN] Would process trade, but skipping")
            return
        
        # Create execution session
        self.stdout.write("    → Creating execution session...")
        try:
            session = self.execution_service.propose_trade(
                setup=setup,
                ki_eval=None,  # No KI evaluation in v1.0
                risk_eval=risk_result,
            )
            self.stdout.write(f"    Session created: {session.state.value}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Failed to create session: {e}"))
            return
        
        # Execute based on risk result and mode
        if shadow_only or not risk_result.allowed:
            # Execute as shadow trade
            self.stdout.write("    → Executing shadow trade...")
            try:
                shadow_trade = self.execution_service.confirm_shadow_trade(session.id)
                self.stdout.write(self.style.SUCCESS(f"    ✓ Shadow trade created: {shadow_trade.id}"))
                self.stdout.write(f"      Entry: {shadow_trade.entry_price}")
                self.stdout.write(f"      SL: {shadow_trade.stop_loss}")
                self.stdout.write(f"      TP: {shadow_trade.take_profit}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    Shadow trade failed: {e}"))
        else:
            # Execute as real trade
            self.stdout.write("    → Executing REAL trade...")
            try:
                trade = self.execution_service.confirm_live_trade(session.id)
                self.stdout.write(self.style.SUCCESS(f"    ✓ Trade executed: {trade.id}"))
                self.stdout.write(f"      Deal ID: {trade.broker_deal_id}")
                self.stdout.write(f"      Entry: {trade.entry_price}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    Trade execution failed: {e}"))
                # Fall back to shadow trade
                self.stdout.write("    → Falling back to shadow trade...")
                try:
                    shadow_trade = self.execution_service.confirm_shadow_trade(session.id)
                    self.stdout.write(f"    ✓ Shadow trade created: {shadow_trade.id}")
                except Exception as se:
                    self.stdout.write(self.style.ERROR(f"    Shadow trade also failed: {se}"))

    def _try_reconnect(self) -> None:
        """Try to reconnect to all brokers after an error."""
        self.stdout.write(self.style.WARNING("Attempting to reconnect to brokers..."))
        
        try:
            # Clear and reinitialize all broker connections
            if self.broker_registry:
                self.broker_registry.clear()
            
            # Wait a bit before reconnecting
            time.sleep(5)
            
            # Reconnect to default IG broker
            self.broker_registry.get_ig_broker()
            self.stdout.write(self.style.SUCCESS("Reconnected successfully!"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Reconnection failed: {e}"))
            raise

    def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        self.stdout.write("\nCleaning up...")
        
        if self.broker_registry:
            try:
                self.broker_registry.disconnect_all()
                self.stdout.write("  ✓ Disconnected from all brokers")
            except Exception as e:
                logger.warning(f"Error disconnecting brokers: {e}")
        
        self.stdout.write("  ✓ Cleanup complete")
