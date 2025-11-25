"""
Fiona Backend API Layer v1.0

This module provides the HTTP/JSON API layer for Fiona trading system.
It encapsulates all core processes behind a clear interface that can be
used by the frontend (UI/UX).

Pipeline:
    MarketData → Strategy → KI → Risk → Execution → Weaviate

The API v1.0 serves primarily the manual trading workflow.
"""

from .services import SignalService, TradeService
from .dtos import (
    SignalSummaryDTO,
    SignalDetailDTO,
    TradeHistoryDTO,
    TradeActionResponse,
)

__all__ = [
    'SignalService',
    'TradeService',
    'SignalSummaryDTO',
    'SignalDetailDTO',
    'TradeHistoryDTO',
    'TradeActionResponse',
]
