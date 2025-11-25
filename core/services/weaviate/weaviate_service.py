"""
Weaviate Service for Fiona.

Provides the central persistence layer for all Fiona objects:
- SetupCandidates
- LocalLLMResults
- ReflectionResults
- KiEvaluationResults
- ExecutedTrades
- ShadowTrades
- MarketSnapshots

All modules interact exclusively with this interface.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol, Union
import uuid

from ..strategy.models import SetupCandidate
from .models import (
    LocalLLMResult,
    ReflectionResult,
    KiEvaluationResult,
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
    SCHEMA_VERSION,
)


@dataclass
class QueryFilter:
    """
    Filter criteria for querying stored objects.
    
    Attributes:
        start_date: Filter results after this date.
        end_date: Filter results before this date.
        epic: Filter by market identifier.
        status: Filter by status (for trades).
        setup_id: Filter by related setup ID.
        limit: Maximum number of results.
        offset: Offset for pagination.
    """
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    epic: Optional[str] = None
    status: Optional[str] = None
    setup_id: Optional[str] = None
    limit: int = 100
    offset: int = 0


class WeaviateClientProtocol(Protocol):
    """Protocol defining the interface for Weaviate client operations."""
    
    def create_object(self, class_name: str, properties: dict, uuid: Optional[str] = None) -> str:
        """Create an object in Weaviate."""
        ...
    
    def get_object(self, class_name: str, uuid: str) -> Optional[dict]:
        """Get an object by UUID."""
        ...
    
    def query_objects(self, class_name: str, filters: dict, limit: int = 100, offset: int = 0) -> list[dict]:
        """Query objects with filters."""
        ...
    
    def delete_object(self, class_name: str, uuid: str) -> bool:
        """Delete an object."""
        ...
    
    def add_reference(self, from_class: str, from_uuid: str, from_property: str, to_uuid: str) -> bool:
        """Add a cross-reference between objects."""
        ...


class InMemoryWeaviateClient:
    """
    In-memory implementation of Weaviate client for testing and development.
    
    This allows using the WeaviateService without a running Weaviate instance.
    """
    
    def __init__(self):
        """Initialize the in-memory storage."""
        self._storage: dict[str, dict[str, dict]] = {}
    
    def create_object(self, class_name: str, properties: dict, object_uuid: Optional[str] = None) -> str:
        """Create an object in memory."""
        if class_name not in self._storage:
            self._storage[class_name] = {}
        
        obj_id = object_uuid or str(uuid.uuid4())
        self._storage[class_name][obj_id] = properties.copy()
        self._storage[class_name][obj_id]['_uuid'] = obj_id
        
        return obj_id
    
    def get_object(self, class_name: str, object_uuid: str) -> Optional[dict]:
        """Get an object by UUID."""
        if class_name not in self._storage:
            return None
        return self._storage[class_name].get(object_uuid)
    
    def query_objects(
        self,
        class_name: str,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """Query objects with filters."""
        if class_name not in self._storage:
            return []
        
        results = list(self._storage[class_name].values())
        
        # Apply filters
        if filters:
            filtered_results = []
            for obj in results:
                match = True
                for key, value in filters.items():
                    if key.startswith('_'):
                        continue
                    if key not in obj or obj[key] != value:
                        match = False
                        break
                if match:
                    filtered_results.append(obj)
            results = filtered_results
        
        # Apply pagination
        return results[offset:offset + limit]
    
    def delete_object(self, class_name: str, object_uuid: str) -> bool:
        """Delete an object."""
        if class_name not in self._storage:
            return False
        if object_uuid not in self._storage[class_name]:
            return False
        del self._storage[class_name][object_uuid]
        return True
    
    def add_reference(
        self,
        from_class: str,
        from_uuid: str,
        from_property: str,
        to_uuid: str
    ) -> bool:
        """Add a cross-reference between objects."""
        if from_class not in self._storage:
            return False
        if from_uuid not in self._storage[from_class]:
            return False
        
        obj = self._storage[from_class][from_uuid]
        if from_property not in obj:
            obj[from_property] = []
        
        if to_uuid not in obj[from_property]:
            obj[from_property].append(to_uuid)
        
        return True
    
    def clear(self):
        """Clear all stored data."""
        self._storage.clear()
    
    def count(self, class_name: Optional[str] = None) -> int:
        """Count objects in storage."""
        if class_name:
            return len(self._storage.get(class_name, {}))
        return sum(len(objs) for objs in self._storage.values())


class WeaviateService:
    """
    Central persistence service for Fiona.
    
    Provides unified interface for storing and querying all Fiona objects.
    All modules interact exclusively with this interface.
    
    Example usage:
        >>> service = WeaviateService()
        >>> setup_id = service.store_setup(setup_candidate)
        >>> eval_id = service.store_ki_evaluation(ki_eval_result)
        >>> shadow_id = service.store_shadow_trade(shadow_trade)
    """
    
    # Weaviate class names for each object type
    CLASS_SETUP = "SetupCandidate"
    CLASS_LLM_RESULT = "LocalLLMResult"
    CLASS_REFLECTION = "ReflectionResult"
    CLASS_KI_EVALUATION = "KiEvaluationResult"
    CLASS_EXECUTED_TRADE = "ExecutedTrade"
    CLASS_SHADOW_TRADE = "ShadowTrade"
    CLASS_MARKET_SNAPSHOT = "MarketSnapshot"
    
    def __init__(self, client: Optional[WeaviateClientProtocol] = None):
        """
        Initialize the WeaviateService.
        
        Args:
            client: Weaviate client instance. If None, uses InMemoryWeaviateClient.
        """
        self._client = client or InMemoryWeaviateClient()
    
    @property
    def client(self) -> Union[WeaviateClientProtocol, InMemoryWeaviateClient]:
        """Get the underlying client."""
        return self._client
    
    # =========================================================================
    # Store Methods
    # =========================================================================
    
    def store_setup(self, setup: SetupCandidate) -> str:
        """
        Store a SetupCandidate in Weaviate.
        
        Args:
            setup: The SetupCandidate to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = setup.to_dict()
        return self._client.create_object(
            self.CLASS_SETUP,
            properties,
            object_uuid=setup.id
        )
    
    def store_llm_result(self, result: LocalLLMResult) -> str:
        """
        Store a LocalLLMResult in Weaviate.
        
        Args:
            result: The LocalLLMResult to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = result.to_dict()
        result_id = self._client.create_object(
            self.CLASS_LLM_RESULT,
            properties,
            object_uuid=result.id
        )
        
        # Add cross-reference to setup
        if result.setup_id:
            self._client.add_reference(
                self.CLASS_LLM_RESULT,
                result_id,
                "hasSetup",
                result.setup_id
            )
        
        return result_id
    
    def store_reflection_result(self, result: ReflectionResult) -> str:
        """
        Store a ReflectionResult in Weaviate.
        
        Args:
            result: The ReflectionResult to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = result.to_dict()
        result_id = self._client.create_object(
            self.CLASS_REFLECTION,
            properties,
            object_uuid=result.id
        )
        
        # Add cross-references
        if result.setup_id:
            self._client.add_reference(
                self.CLASS_REFLECTION,
                result_id,
                "hasSetup",
                result.setup_id
            )
        if result.trade_id:
            self._client.add_reference(
                self.CLASS_REFLECTION,
                result_id,
                "hasTrade",
                result.trade_id
            )
        if result.llm_result_id:
            self._client.add_reference(
                self.CLASS_REFLECTION,
                result_id,
                "hasLLMResult",
                result.llm_result_id
            )
        
        return result_id
    
    def store_ki_evaluation(self, result: KiEvaluationResult) -> str:
        """
        Store a KiEvaluationResult in Weaviate.
        
        Args:
            result: The KiEvaluationResult to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = result.to_dict()
        result_id = self._client.create_object(
            self.CLASS_KI_EVALUATION,
            properties,
            object_uuid=result.id
        )
        
        # Add cross-reference to setup
        if result.setup_id:
            self._client.add_reference(
                self.CLASS_KI_EVALUATION,
                result_id,
                "hasSetup",
                result.setup_id
            )
        
        # Add cross-references to LLM results
        for llm_id in (result.llm_result_ids or []):
            self._client.add_reference(
                self.CLASS_KI_EVALUATION,
                result_id,
                "hasLLMResults",
                llm_id
            )
        
        return result_id
    
    def store_trade(self, trade: ExecutedTrade) -> str:
        """
        Store an ExecutedTrade in Weaviate.
        
        Args:
            trade: The ExecutedTrade to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = trade.to_dict()
        trade_id = self._client.create_object(
            self.CLASS_EXECUTED_TRADE,
            properties,
            object_uuid=trade.id
        )
        
        # Add cross-references
        if trade.setup_id:
            self._client.add_reference(
                self.CLASS_EXECUTED_TRADE,
                trade_id,
                "hasSetup",
                trade.setup_id
            )
        if trade.ki_evaluation_id:
            self._client.add_reference(
                self.CLASS_EXECUTED_TRADE,
                trade_id,
                "hasKiEvaluation",
                trade.ki_evaluation_id
            )
        
        # Add market snapshot references
        for snapshot_id in (trade.market_snapshot_ids or []):
            self._client.add_reference(
                self.CLASS_EXECUTED_TRADE,
                trade_id,
                "hasMarketSnapshots",
                snapshot_id
            )
        
        return trade_id
    
    def store_shadow_trade(self, trade: ShadowTrade) -> str:
        """
        Store a ShadowTrade in Weaviate.
        
        Args:
            trade: The ShadowTrade to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = trade.to_dict()
        trade_id = self._client.create_object(
            self.CLASS_SHADOW_TRADE,
            properties,
            object_uuid=trade.id
        )
        
        # Add cross-references
        if trade.setup_id:
            self._client.add_reference(
                self.CLASS_SHADOW_TRADE,
                trade_id,
                "hasSetup",
                trade.setup_id
            )
        if trade.ki_evaluation_id:
            self._client.add_reference(
                self.CLASS_SHADOW_TRADE,
                trade_id,
                "hasKiEvaluation",
                trade.ki_evaluation_id
            )
        
        # Add market snapshot references
        for snapshot_id in (trade.market_snapshot_ids or []):
            self._client.add_reference(
                self.CLASS_SHADOW_TRADE,
                trade_id,
                "hasMarketSnapshots",
                snapshot_id
            )
        
        return trade_id
    
    def store_market_snapshot(self, snapshot: MarketSnapshot) -> str:
        """
        Store a MarketSnapshot in Weaviate.
        
        Args:
            snapshot: The MarketSnapshot to store.
            
        Returns:
            str: The UUID of the stored object.
        """
        properties = snapshot.to_dict()
        return self._client.create_object(
            self.CLASS_MARKET_SNAPSHOT,
            properties,
            object_uuid=snapshot.id
        )
    
    # =========================================================================
    # Query Methods
    # =========================================================================
    
    def query_setups(self, filters: Optional[QueryFilter] = None) -> list[SetupCandidate]:
        """
        Query SetupCandidates with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[SetupCandidate]: Matching setup candidates.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_SETUP,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [SetupCandidate.from_dict(r) for r in results]
    
    def query_trades(self, filters: Optional[QueryFilter] = None) -> list[ExecutedTrade]:
        """
        Query ExecutedTrades with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[ExecutedTrade]: Matching executed trades.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_EXECUTED_TRADE,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [ExecutedTrade.from_dict(r) for r in results]
    
    def query_shadow_trades(self, filters: Optional[QueryFilter] = None) -> list[ShadowTrade]:
        """
        Query ShadowTrades with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[ShadowTrade]: Matching shadow trades.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_SHADOW_TRADE,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [ShadowTrade.from_dict(r) for r in results]
    
    def query_ki_results(self, filters: Optional[QueryFilter] = None) -> list[KiEvaluationResult]:
        """
        Query KiEvaluationResults with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[KiEvaluationResult]: Matching KI evaluation results.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_KI_EVALUATION,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [KiEvaluationResult.from_dict(r) for r in results]
    
    def query_llm_results(self, filters: Optional[QueryFilter] = None) -> list[LocalLLMResult]:
        """
        Query LocalLLMResults with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[LocalLLMResult]: Matching LLM results.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_LLM_RESULT,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [LocalLLMResult.from_dict(r) for r in results]
    
    def query_reflections(self, filters: Optional[QueryFilter] = None) -> list[ReflectionResult]:
        """
        Query ReflectionResults with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[ReflectionResult]: Matching reflection results.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_REFLECTION,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [ReflectionResult.from_dict(r) for r in results]
    
    def query_market_snapshots(self, filters: Optional[QueryFilter] = None) -> list[MarketSnapshot]:
        """
        Query MarketSnapshots with optional filters.
        
        Args:
            filters: Optional filter criteria.
            
        Returns:
            list[MarketSnapshot]: Matching market snapshots.
        """
        query_filters = self._build_query_filters(filters)
        limit = filters.limit if filters else 100
        offset = filters.offset if filters else 0
        
        results = self._client.query_objects(
            self.CLASS_MARKET_SNAPSHOT,
            query_filters,
            limit=limit,
            offset=offset
        )
        
        return [MarketSnapshot.from_dict(r) for r in results]
    
    # =========================================================================
    # Get Methods
    # =========================================================================
    
    def get_setup(self, setup_id: str) -> Optional[SetupCandidate]:
        """Get a SetupCandidate by ID."""
        result = self._client.get_object(self.CLASS_SETUP, setup_id)
        return SetupCandidate.from_dict(result) if result else None
    
    def get_llm_result(self, result_id: str) -> Optional[LocalLLMResult]:
        """Get a LocalLLMResult by ID."""
        result = self._client.get_object(self.CLASS_LLM_RESULT, result_id)
        return LocalLLMResult.from_dict(result) if result else None
    
    def get_reflection(self, result_id: str) -> Optional[ReflectionResult]:
        """Get a ReflectionResult by ID."""
        result = self._client.get_object(self.CLASS_REFLECTION, result_id)
        return ReflectionResult.from_dict(result) if result else None
    
    def get_ki_evaluation(self, result_id: str) -> Optional[KiEvaluationResult]:
        """Get a KiEvaluationResult by ID."""
        result = self._client.get_object(self.CLASS_KI_EVALUATION, result_id)
        return KiEvaluationResult.from_dict(result) if result else None
    
    def get_trade(self, trade_id: str) -> Optional[ExecutedTrade]:
        """Get an ExecutedTrade by ID."""
        result = self._client.get_object(self.CLASS_EXECUTED_TRADE, trade_id)
        return ExecutedTrade.from_dict(result) if result else None
    
    def get_shadow_trade(self, trade_id: str) -> Optional[ShadowTrade]:
        """Get a ShadowTrade by ID."""
        result = self._client.get_object(self.CLASS_SHADOW_TRADE, trade_id)
        return ShadowTrade.from_dict(result) if result else None
    
    def get_market_snapshot(self, snapshot_id: str) -> Optional[MarketSnapshot]:
        """Get a MarketSnapshot by ID."""
        result = self._client.get_object(self.CLASS_MARKET_SNAPSHOT, snapshot_id)
        return MarketSnapshot.from_dict(result) if result else None
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _build_query_filters(self, filters: Optional[QueryFilter]) -> dict:
        """Build query filters dictionary from QueryFilter."""
        if not filters:
            return {}
        
        query_filters = {}
        
        if filters.epic:
            query_filters['epic'] = filters.epic
        
        if filters.status:
            query_filters['status'] = filters.status
        
        if filters.setup_id:
            query_filters['setup_id'] = filters.setup_id
        
        return query_filters
    
    # =========================================================================
    # Schema Methods (for initialization)
    # =========================================================================
    
    @classmethod
    def get_schema_definition(cls) -> dict:
        """
        Get the complete Weaviate schema definition for all classes.
        
        Returns:
            dict: Schema definition for Weaviate.
        """
        return {
            "classes": [
                cls._get_setup_candidate_schema(),
                cls._get_local_llm_result_schema(),
                cls._get_reflection_result_schema(),
                cls._get_ki_evaluation_result_schema(),
                cls._get_executed_trade_schema(),
                cls._get_shadow_trade_schema(),
                cls._get_market_snapshot_schema(),
            ]
        }
    
    @classmethod
    def _get_setup_candidate_schema(cls) -> dict:
        """Get schema definition for SetupCandidate."""
        return {
            "class": cls.CLASS_SETUP,
            "description": "A potential trading setup identified by the Strategy Engine",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "epic", "dataType": ["text"], "description": "Market identifier"},
                {"name": "setup_kind", "dataType": ["text"], "description": "Type of setup"},
                {"name": "phase", "dataType": ["text"], "description": "Session phase"},
                {"name": "reference_price", "dataType": ["number"], "description": "Reference price"},
                {"name": "direction", "dataType": ["text"], "description": "Trade direction"},
                {"name": "breakout", "dataType": ["object"], "description": "Breakout context"},
                {"name": "eia", "dataType": ["object"], "description": "EIA context"},
                {"name": "quality_flags", "dataType": ["object"], "description": "Quality indicators"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
        }
    
    @classmethod
    def _get_local_llm_result_schema(cls) -> dict:
        """Get schema definition for LocalLLMResult."""
        return {
            "class": cls.CLASS_LLM_RESULT,
            "description": "Result from a Local LLM analysis",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "setup_id", "dataType": ["text"], "description": "Related setup ID"},
                {"name": "provider", "dataType": ["text"], "description": "LLM provider"},
                {"name": "model", "dataType": ["text"], "description": "Model name"},
                {"name": "prompt", "dataType": ["text"], "description": "Prompt sent"},
                {"name": "response", "dataType": ["text"], "description": "Response received"},
                {"name": "recommendation", "dataType": ["text"], "description": "Recommendation"},
                {"name": "confidence", "dataType": ["number"], "description": "Confidence score"},
                {"name": "reasoning", "dataType": ["text"], "description": "Reasoning"},
                {"name": "tokens_used", "dataType": ["int"], "description": "Tokens consumed"},
                {"name": "latency_ms", "dataType": ["int"], "description": "Response latency"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
            "references": [
                {
                    "name": "hasSetup",
                    "targetClass": cls.CLASS_SETUP,
                    "description": "Reference to the analyzed SetupCandidate",
                },
            ],
        }
    
    @classmethod
    def _get_reflection_result_schema(cls) -> dict:
        """Get schema definition for ReflectionResult."""
        return {
            "class": cls.CLASS_REFLECTION,
            "description": "Reflection/analysis of a trade or decision",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "setup_id", "dataType": ["text"], "description": "Related setup ID"},
                {"name": "trade_id", "dataType": ["text"], "description": "Related trade ID"},
                {"name": "llm_result_id", "dataType": ["text"], "description": "Related LLM result ID"},
                {"name": "reflection_type", "dataType": ["text"], "description": "Type of reflection"},
                {"name": "outcome", "dataType": ["text"], "description": "Outcome assessment"},
                {"name": "lessons_learned", "dataType": ["text[]"], "description": "Lessons learned"},
                {"name": "improvements", "dataType": ["text[]"], "description": "Improvements"},
                {"name": "confidence_adjustment", "dataType": ["number"], "description": "Confidence adjustment"},
                {"name": "notes", "dataType": ["text"], "description": "Additional notes"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
            "references": [
                {"name": "hasSetup", "targetClass": cls.CLASS_SETUP},
                {"name": "hasTrade", "targetClass": "ExecutedTrade"},
                {"name": "hasLLMResult", "targetClass": cls.CLASS_LLM_RESULT},
            ],
        }
    
    @classmethod
    def _get_ki_evaluation_result_schema(cls) -> dict:
        """Get schema definition for KiEvaluationResult."""
        return {
            "class": cls.CLASS_KI_EVALUATION,
            "description": "Aggregated KI evaluation result",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "setup_id", "dataType": ["text"], "description": "Related setup ID"},
                {"name": "llm_result_ids", "dataType": ["text[]"], "description": "Related LLM result IDs"},
                {"name": "final_decision", "dataType": ["text"], "description": "Final decision"},
                {"name": "decision_confidence", "dataType": ["number"], "description": "Decision confidence"},
                {"name": "risk_score", "dataType": ["number"], "description": "Risk score"},
                {"name": "position_size_suggestion", "dataType": ["number"], "description": "Position size"},
                {"name": "entry_price_target", "dataType": ["number"], "description": "Entry price"},
                {"name": "stop_loss_target", "dataType": ["number"], "description": "Stop loss"},
                {"name": "take_profit_target", "dataType": ["number"], "description": "Take profit"},
                {"name": "factors", "dataType": ["object"], "description": "Contributing factors"},
                {"name": "warnings", "dataType": ["text[]"], "description": "Warnings"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
            "references": [
                {"name": "hasSetup", "targetClass": cls.CLASS_SETUP},
                {"name": "hasLLMResults", "targetClass": cls.CLASS_LLM_RESULT},
            ],
        }
    
    @classmethod
    def _get_executed_trade_schema(cls) -> dict:
        """Get schema definition for ExecutedTrade."""
        return {
            "class": cls.CLASS_EXECUTED_TRADE,
            "description": "An actually executed trade",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "setup_id", "dataType": ["text"], "description": "Related setup ID"},
                {"name": "ki_evaluation_id", "dataType": ["text"], "description": "KI evaluation ID"},
                {"name": "broker_deal_id", "dataType": ["text"], "description": "Broker deal ID"},
                {"name": "epic", "dataType": ["text"], "description": "Market identifier"},
                {"name": "direction", "dataType": ["text"], "description": "Trade direction"},
                {"name": "size", "dataType": ["number"], "description": "Position size"},
                {"name": "entry_price", "dataType": ["number"], "description": "Entry price"},
                {"name": "exit_price", "dataType": ["number"], "description": "Exit price"},
                {"name": "stop_loss", "dataType": ["number"], "description": "Stop loss"},
                {"name": "take_profit", "dataType": ["number"], "description": "Take profit"},
                {"name": "status", "dataType": ["text"], "description": "Trade status"},
                {"name": "opened_at", "dataType": ["date"], "description": "Open timestamp"},
                {"name": "closed_at", "dataType": ["date"], "description": "Close timestamp"},
                {"name": "pnl", "dataType": ["number"], "description": "Profit/loss"},
                {"name": "pnl_percent", "dataType": ["number"], "description": "P&L percentage"},
                {"name": "fees", "dataType": ["number"], "description": "Trading fees"},
                {"name": "currency", "dataType": ["text"], "description": "Currency"},
                {"name": "market_snapshot_ids", "dataType": ["text[]"], "description": "Snapshot IDs"},
                {"name": "notes", "dataType": ["text"], "description": "Notes"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
            "references": [
                {"name": "hasSetup", "targetClass": cls.CLASS_SETUP},
                {"name": "hasKiEvaluation", "targetClass": cls.CLASS_KI_EVALUATION},
                {"name": "hasMarketSnapshots", "targetClass": cls.CLASS_MARKET_SNAPSHOT},
            ],
        }
    
    @classmethod
    def _get_shadow_trade_schema(cls) -> dict:
        """Get schema definition for ShadowTrade."""
        return {
            "class": cls.CLASS_SHADOW_TRADE,
            "description": "A simulated/paper trade for strategy validation",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "setup_id", "dataType": ["text"], "description": "Related setup ID"},
                {"name": "ki_evaluation_id", "dataType": ["text"], "description": "KI evaluation ID"},
                {"name": "epic", "dataType": ["text"], "description": "Market identifier"},
                {"name": "direction", "dataType": ["text"], "description": "Trade direction"},
                {"name": "size", "dataType": ["number"], "description": "Position size"},
                {"name": "entry_price", "dataType": ["number"], "description": "Entry price"},
                {"name": "exit_price", "dataType": ["number"], "description": "Exit price"},
                {"name": "stop_loss", "dataType": ["number"], "description": "Stop loss"},
                {"name": "take_profit", "dataType": ["number"], "description": "Take profit"},
                {"name": "status", "dataType": ["text"], "description": "Trade status"},
                {"name": "opened_at", "dataType": ["date"], "description": "Open timestamp"},
                {"name": "closed_at", "dataType": ["date"], "description": "Close timestamp"},
                {"name": "theoretical_pnl", "dataType": ["number"], "description": "Theoretical P&L"},
                {"name": "theoretical_pnl_percent", "dataType": ["number"], "description": "P&L percentage"},
                {"name": "skip_reason", "dataType": ["text"], "description": "Skip reason"},
                {"name": "market_snapshot_ids", "dataType": ["text[]"], "description": "Snapshot IDs"},
                {"name": "notes", "dataType": ["text"], "description": "Notes"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
            "references": [
                {"name": "hasSetup", "targetClass": cls.CLASS_SETUP},
                {"name": "hasKiEvaluation", "targetClass": cls.CLASS_KI_EVALUATION},
                {"name": "hasMarketSnapshots", "targetClass": cls.CLASS_MARKET_SNAPSHOT},
            ],
        }
    
    @classmethod
    def _get_market_snapshot_schema(cls) -> dict:
        """Get schema definition for MarketSnapshot."""
        return {
            "class": cls.CLASS_MARKET_SNAPSHOT,
            "description": "Point-in-time snapshot of market conditions",
            "properties": [
                {"name": "id", "dataType": ["text"], "description": "Unique identifier"},
                {"name": "created_at", "dataType": ["date"], "description": "Creation timestamp"},
                {"name": "epic", "dataType": ["text"], "description": "Market identifier"},
                {"name": "bid", "dataType": ["number"], "description": "Bid price"},
                {"name": "ask", "dataType": ["number"], "description": "Ask price"},
                {"name": "spread", "dataType": ["number"], "description": "Spread"},
                {"name": "mid_price", "dataType": ["number"], "description": "Mid price"},
                {"name": "high", "dataType": ["number"], "description": "Day high"},
                {"name": "low", "dataType": ["number"], "description": "Day low"},
                {"name": "volume", "dataType": ["number"], "description": "Volume"},
                {"name": "atr", "dataType": ["number"], "description": "ATR"},
                {"name": "vwap", "dataType": ["number"], "description": "VWAP"},
                {"name": "trend_direction", "dataType": ["text"], "description": "Trend direction"},
                {"name": "volatility_level", "dataType": ["text"], "description": "Volatility level"},
                {"name": "session_phase", "dataType": ["text"], "description": "Session phase"},
                {"name": "additional_indicators", "dataType": ["object"], "description": "Indicators"},
                {"name": "notes", "dataType": ["text"], "description": "Notes"},
                {"name": "schema_version", "dataType": ["text"], "description": "Schema version"},
            ],
        }
