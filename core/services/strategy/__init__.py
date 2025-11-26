"""
Strategy Engine module for Fiona.

Provides the Strategy Engine for identifying potential trading setups
based on market data and configurable strategies.
"""

from .models import (
    SCHEMA_VERSION,
    SetupKind,
    SessionPhase,
    BreakoutContext,
    EiaContext,
    Candle,
    SetupCandidate,
)

from .config import (
    StrategyConfig,
    BreakoutConfig,
    EiaConfig,
    AsiaRangeConfig,
    UsCoreConfig,
)

from .providers import (
    MarketStateProvider,
    BaseMarketStateProvider,
)

from .strategy_engine import (
    StrategyEngine,
    DiagnosticCriterion,
    EvaluationResult,
)

from .diagnostics import (
    PricePosition,
    BreakoutStatus,
    RangeValidation,
    BreakoutRangeDiagnostics,
    BreakoutRangeDiagnosticService,
)

__all__ = [
    # Constants
    'SCHEMA_VERSION',
    # Data models
    'SetupKind',
    'SessionPhase',
    'BreakoutContext',
    'EiaContext',
    'Candle',
    'SetupCandidate',
    # Configuration
    'StrategyConfig',
    'BreakoutConfig',
    'EiaConfig',
    'AsiaRangeConfig',
    'UsCoreConfig',
    # Providers
    'MarketStateProvider',
    'BaseMarketStateProvider',
    # Engine
    'StrategyEngine',
    # Diagnostics
    'PricePosition',
    'BreakoutStatus',
    'RangeValidation',
    'BreakoutRangeDiagnostics',
    'BreakoutRangeDiagnosticService',
    'DiagnosticCriterion',
    'EvaluationResult',
]
