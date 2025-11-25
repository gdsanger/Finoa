"""
Weaviate Core Services module for Fiona.

Provides the central persistence layer for Fiona based on Weaviate:
- Storage of all relevant objects (SetupCandidates, LocalLLMResults, etc.)
- Retrieval services for analyses
- Separation between Operational Storage and Historical Storage
- Versioned schemas & stable interfaces
"""

from .models import (
    LocalLLMResult,
    ReflectionResult,
    KiEvaluationResult,
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
)

from .weaviate_service import WeaviateService

__all__ = [
    # Data models
    'LocalLLMResult',
    'ReflectionResult',
    'KiEvaluationResult',
    'ExecutedTrade',
    'ShadowTrade',
    'MarketSnapshot',
    # Service
    'WeaviateService',
]
