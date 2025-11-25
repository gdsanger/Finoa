"""
Strategy Engine module for Finoa.

Provides the Strategy Engine for identifying potential trading setups
based on market data and configurable strategies.
"""

from .models import (
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

from .strategy_engine import StrategyEngine

__all__ = [
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
]
