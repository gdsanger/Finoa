"""
Fiona Background Worker v1.0 - IG Market Integration.

Management command for running the Fiona trading system background worker.
Continuously fetches market data, runs strategy analysis, evaluates risk,
and executes trades (real or shadow).

Usage:
    python manage.py run_fiona_worker
    python manage.py run_fiona_worker --interval 60 --shadow-only
    python manage.py run_fiona_worker --epic CC.D.CL.UNC.IP --verbose
"""
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from django.core.management.base import BaseCommand

from core.models import IgBrokerConfig
from core.services.broker import (
    IgBrokerService,
    IGMarketStateProvider,
    BrokerError,
    AuthenticationError,
    create_ig_broker_service,
)
from trading.models import WorkerStatus
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


logger = logging.getLogger(__name__)


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
        self.broker_service: Optional[IgBrokerService] = None
        self.market_state_provider: Optional[IGMarketStateProvider] = None
        self.strategy_engine: Optional[StrategyEngine] = None
        self.risk_engine: Optional[RiskEngine] = None
        self.execution_service: Optional[ExecutionService] = None
        self.weaviate_service: Optional[WeaviateService] = None
        self.shutdown_handler: Optional[GracefulShutdown] = None

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
        
        # 1. Create IG Broker Service
        self.stdout.write("  → Creating IG Broker Service...")
        try:
            self.broker_service = create_ig_broker_service()
            self.stdout.write(self.style.SUCCESS("    ✓ IG Broker Service created"))
        except Exception as e:
            raise RuntimeError(f"Failed to create IG Broker Service: {e}")
        
        # 2. Connect to broker
        self.stdout.write("  → Connecting to IG...")
        try:
            self.broker_service.connect()
            self.stdout.write(self.style.SUCCESS("    ✓ Connected to IG"))
        except AuthenticationError as e:
            raise RuntimeError(f"IG authentication failed: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to IG: {e}")
        
        # 3. Get account state to verify connection
        try:
            account = self.broker_service.get_account_state()
            self.stdout.write(f"    Account: {account.account_name}")
            self.stdout.write(f"    Balance: {account.balance} {account.currency}")
            self.stdout.write(f"    Available: {account.available} {account.currency}")
        except Exception as e:
            logger.warning(f"Could not get account state: {e}")
        
        # 4. Create Market State Provider
        self.stdout.write("  → Creating Market State Provider...")
        self.market_state_provider = IGMarketStateProvider(
            broker_service=self.broker_service,
            eia_timestamp=None,  # Can be set later if needed
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
        self.stdout.write("  → Creating Execution Service...")
        execution_config = ExecutionConfig(
            allow_shadow_if_risk_denied=True,
        )
        # In shadow-only mode, don't pass broker to prevent real trades
        broker_for_execution = None if shadow_only else self.broker_service
        self.execution_service = ExecutionService(
            broker_service=broker_for_execution,
            weaviate_service=self.weaviate_service,
            config=execution_config,
        )
        self.stdout.write(self.style.SUCCESS("    ✓ Execution Service created"))
        
        self.stdout.write(self.style.SUCCESS("\n✓ All services initialized successfully!"))
        self.stdout.write("")

    def _run_cycle(self, epic: str, shadow_only: bool, dry_run: bool, worker_interval: int = 60) -> None:
        """Run one cycle of the worker loop."""
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
        
        # 3. Get current price for logging
        price = None
        try:
            price = self.broker_service.get_symbol_price(epic)
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
            self._process_setup(setup, shadow_only, dry_run, now)
    
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
                setups_found = self._run_asset_cycle(
                    asset=asset,
                    strategy_engine=asset_strategy_engine,
                    shadow_only=shadow_only,
                    dry_run=dry_run,
                    now=now,
                )
                
                total_setups += setups_found
                processed_epics.append(asset.epic)
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     ✗ Error processing asset: {e}"))
                logger.exception(f"Error processing asset {asset.epic}")
        
        # Update worker status with summary
        phase = self.market_state_provider.get_phase(now)
        self._update_worker_status(
            now=now,
            phase=phase,
            epic=f"{asset_count} assets",  # Show count instead of single epic
            setup_count=total_setups,
            bid_price=None,
            ask_price=None,
            spread=None,
            diagnostic_message=f"Processed {asset_count} assets: {', '.join(processed_epics)}",
            diagnostic_criteria=[{
                'name': f'Active Assets ({asset_count})',
                'passed': True,
                'detail': ', '.join(processed_epics)
            }],
            worker_interval=worker_interval,
        )
    
    def _run_asset_cycle(
        self,
        asset,
        strategy_engine: StrategyEngine,
        shadow_only: bool,
        dry_run: bool,
        now: datetime
    ) -> int:
        """
        Run strategy evaluation for a single asset.
        
        Args:
            asset: TradingAsset instance
            strategy_engine: Strategy engine configured for this asset
            shadow_only: Whether to only create shadow trades
            dry_run: Whether to skip trade execution
            now: Current timestamp
            
        Returns:
            Number of setups found
        """
        epic = asset.epic
        
        # 1. Determine session phase
        phase = self.market_state_provider.get_phase(now)
        self.stdout.write(f"     Phase: {phase.value}")
        
        # 2. Update candle cache with current price
        try:
            self.market_state_provider.update_candle_from_price(epic)
        except Exception as e:
            logger.warning(f"Failed to update candle for {epic}: {e}")
        
        # 3. Get current price for logging
        try:
            price = self.broker_service.get_symbol_price(epic)
            self.stdout.write(f"     Price: {price.bid}/{price.ask}")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"     Could not get price: {e}"))
        
        # 4. Skip if not in tradeable phase
        if phase in [SessionPhase.FRIDAY_LATE, SessionPhase.OTHER]:
            self.stdout.write("     → Phase not tradeable, skipping")
            return 0
        
        # 5. Run Strategy Engine
        try:
            setups = strategy_engine.evaluate(epic, now)
            self.stdout.write(f"     Found {len(setups)} setup(s)")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"     Strategy error: {e}"))
            logger.exception(f"Strategy evaluation failed for {epic}")
            return 0
        
        if not setups:
            return 0
        
        # 6. Process each setup
        for setup in setups:
            self._process_setup(setup, shadow_only, dry_run, now, trading_asset=asset)
        
        return len(setups)
    
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

    def _process_setup(self, setup, shadow_only: bool, dry_run: bool, now: datetime, trading_asset=None) -> None:
        """Process a single setup through risk and execution.
        
        Args:
            setup: SetupCandidate from Strategy Engine
            shadow_only: Whether to only create shadow trades
            dry_run: Whether to skip trade execution
            now: Current timestamp
            trading_asset: Optional TradingAsset model instance for linking signals
        """
        self.stdout.write(
            f"\n  Setup: {setup.setup_kind.value} {setup.direction} @ {setup.reference_price}"
        )
        
        # Store setup in Weaviate
        try:
            self.weaviate_service.store_setup(setup)
            self.stdout.write("    ✓ Setup stored")
        except Exception as e:
            logger.warning(f"Failed to store setup: {e}")
        
        # Get account state for risk evaluation
        try:
            account = self.broker_service.get_account_state()
            positions = self.broker_service.get_open_positions()
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
        
        order = OrderRequest(
            epic=setup.epic,
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
        """Try to reconnect to the broker after an error."""
        self.stdout.write(self.style.WARNING("Attempting to reconnect to broker..."))
        
        try:
            # Disconnect first if connected
            if self.broker_service:
                try:
                    self.broker_service.disconnect()
                except Exception:
                    pass
            
            # Wait a bit before reconnecting
            time.sleep(5)
            
            # Reconnect
            self.broker_service.connect()
            self.stdout.write(self.style.SUCCESS("Reconnected successfully!"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Reconnection failed: {e}"))
            raise

    def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        self.stdout.write("\nCleaning up...")
        
        if self.broker_service:
            try:
                self.broker_service.disconnect()
                self.stdout.write("  ✓ Disconnected from broker")
            except Exception as e:
                logger.warning(f"Error disconnecting broker: {e}")
        
        self.stdout.write("  ✓ Cleanup complete")
