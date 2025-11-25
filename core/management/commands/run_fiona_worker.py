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
            help='Market EPIC to trade (default: CC.D.CL.UNC.IP for WTI Crude)'
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
        verbose = options['verbose']
        dry_run = options['dry_run']
        run_once = options['once']
        max_iterations = options['max_iterations']
        
        # Configure logging
        if verbose:
            logging.getLogger('core').setLevel(logging.DEBUG)
            logging.getLogger(__name__).setLevel(logging.DEBUG)
        
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Fiona Worker v1.0 - Starting"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
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
                    self._run_cycle(epic, shadow_only, dry_run)
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

    def _run_cycle(self, epic: str, shadow_only: bool, dry_run: bool) -> None:
        """Run one cycle of the worker loop."""
        now = datetime.now(timezone.utc)
        
        # 1. Determine session phase
        phase = self.market_state_provider.get_phase(now)
        self.stdout.write(f"\n[{now.strftime('%H:%M:%S')} UTC] Phase: {phase.value}")
        
        # 2. Update candle cache with current price
        try:
            self.market_state_provider.update_candle_from_price(epic)
        except Exception as e:
            logger.warning(f"Failed to update candle: {e}")
        
        # 3. Get current price for logging
        try:
            price = self.broker_service.get_symbol_price(epic)
            self.stdout.write(
                f"  Price: {price.bid}/{price.ask} (spread: {price.spread})"
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Could not get price: {e}"))
        
        # 4. Skip if not in tradeable phase
        if phase in [SessionPhase.FRIDAY_LATE, SessionPhase.OTHER]:
            self.stdout.write("  → Phase not tradeable, skipping strategy evaluation")
            return
        
        # 5. Run Strategy Engine
        self.stdout.write("  → Running Strategy Engine...")
        try:
            setups = self.strategy_engine.evaluate(epic, now)
            self.stdout.write(f"    Found {len(setups)} setup(s)")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Strategy error: {e}"))
            logger.exception("Strategy evaluation failed")
            return
        
        if not setups:
            self.stdout.write("  → No setups found")
            return
        
        # 6. Process each setup
        for setup in setups:
            self._process_setup(setup, shadow_only, dry_run, now)

    def _process_setup(self, setup, shadow_only: bool, dry_run: bool, now: datetime) -> None:
        """Process a single setup through risk and execution."""
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
