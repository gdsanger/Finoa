"""
Weaviate Core Services module for Fiona.

Provides the central persistence layer for Fiona based on Weaviate:
- Storage of all relevant objects (SetupCandidates, LocalLLMResults, etc.)
- Retrieval services for analyses
- Separation between Operational Storage and Historical Storage
- Versioned schemas & stable interfaces
"""

from .models import (
    SCHEMA_VERSION,
    LocalLLMResult,
    ReflectionResult,
    KiEvaluationResult,
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
)

from .weaviate_service import WeaviateService, InMemoryWeaviateClient
from .weaviate_client import RealWeaviateClient, get_weaviate_client, WEAVIATE_AVAILABLE

__all__ = [
    # Constants
    'SCHEMA_VERSION',
    'WEAVIATE_AVAILABLE',
    # Data models
    'LocalLLMResult',
    'ReflectionResult',
    'KiEvaluationResult',
    'ExecutedTrade',
    'ShadowTrade',
    'MarketSnapshot',
    # Clients
    'InMemoryWeaviateClient',
    'RealWeaviateClient',
    'get_weaviate_client',
    # Service
    'WeaviateService',
]
