"""
Execution Layer for Fiona trading system.

The Execution Layer handles:
- Signal orchestration from Strategy Engine, KI Layer, and Risk Engine
- Manual trade execution with user confirmation
- Shadow trading for risk-denied or user-selected simulations
- Trade lifecycle tracking and persistence
"""

from .models import (
    ExecutionState,
    ExecutionSession,
    ExecutionConfig,
)
from .execution_service import ExecutionService
from .shadow_trader_service import ShadowTraderService

__all__ = [
    # Models
    'ExecutionState',
    'ExecutionSession',
    'ExecutionConfig',
    # Services
    'ExecutionService',
    'ShadowTraderService',
]
