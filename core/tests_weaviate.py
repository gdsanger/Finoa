"""
Tests for Weaviate Core Services.

Tests for:
- Serialize/deserialize all Object-Models
- WeaviateService Mock-Tests
- Query-Tests
- Cross-reference functionality
"""
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from django.test import TestCase

from core.services.strategy.models import (
    SCHEMA_VERSION,
    SetupKind,
    SessionPhase,
    BreakoutContext,
    EiaContext,
    SetupCandidate,
)
from core.services.weaviate.models import (
    LocalLLMResult,
    ReflectionResult,
    KiEvaluationResult,
    ExecutedTrade,
    ShadowTrade,
    MarketSnapshot,
    TradeStatus,
    TradeDirection,
    LLMProvider,
)
from core.services.weaviate.weaviate_service import (
    WeaviateService,
    InMemoryWeaviateClient,
    QueryFilter,
)


class SetupCandidateSerializationTest(TestCase):
    """Tests for SetupCandidate serialization/deserialization."""
    
    def test_setup_candidate_to_dict(self):
        """Test SetupCandidate.to_dict() method."""
        now = datetime.now(timezone.utc)
        setup = SetupCandidate(
            id="setup-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
            quality_flags={"strength": 0.85},
        )
        
        data = setup.to_dict()
        
        self.assertEqual(data['id'], "setup-001")
        self.assertEqual(data['epic'], "CC.D.CL.UNC.IP")
        self.assertEqual(data['setup_kind'], "BREAKOUT")
        self.assertEqual(data['phase'], "LONDON_CORE")
        self.assertEqual(data['reference_price'], 75.50)
        self.assertEqual(data['direction'], "LONG")
        self.assertEqual(data['quality_flags'], {"strength": 0.85})
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_setup_candidate_from_dict(self):
        """Test SetupCandidate.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "setup-002",
            'created_at': now.isoformat(),
            'epic': "CC.D.CL.UNC.IP",
            'setup_kind': "BREAKOUT",
            'phase': "US_CORE",
            'reference_price': 76.25,
            'direction': "SHORT",
            'quality_flags': {"volume_spike": True},
            'schema_version': "1.0",
        }
        
        setup = SetupCandidate.from_dict(data)
        
        self.assertEqual(setup.id, "setup-002")
        self.assertEqual(setup.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(setup.setup_kind, SetupKind.BREAKOUT)
        self.assertEqual(setup.phase, SessionPhase.US_CORE)
        self.assertEqual(setup.reference_price, 76.25)
        self.assertEqual(setup.direction, "SHORT")
        self.assertEqual(setup.schema_version, "1.0")
    
    def test_setup_candidate_with_breakout_context(self):
        """Test SetupCandidate with BreakoutContext serialization."""
        now = datetime.now(timezone.utc)
        breakout = BreakoutContext(
            range_high=77.00,
            range_low=75.00,
            range_height=2.00,
            trigger_price=77.10,
            direction="LONG",
            atr=0.45,
        )
        
        setup = SetupCandidate(
            id="setup-003",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=77.10,
            direction="LONG",
            breakout=breakout,
        )
        
        data = setup.to_dict()
        restored = SetupCandidate.from_dict(data)
        
        self.assertIsNotNone(restored.breakout)
        self.assertEqual(restored.breakout.range_high, 77.00)
        self.assertEqual(restored.breakout.range_low, 75.00)
        self.assertEqual(restored.breakout.direction, "LONG")
    
    def test_setup_candidate_with_eia_context(self):
        """Test SetupCandidate with EiaContext serialization."""
        now = datetime.now(timezone.utc)
        eia = EiaContext(
            eia_timestamp=now,
            first_impulse_direction="LONG",
            impulse_range_high=78.00,
            impulse_range_low=76.00,
            atr=0.50,
        )
        
        setup = SetupCandidate(
            id="setup-004",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=77.50,
            direction="SHORT",
            eia=eia,
        )
        
        data = setup.to_dict()
        restored = SetupCandidate.from_dict(data)
        
        self.assertIsNotNone(restored.eia)
        self.assertEqual(restored.eia.first_impulse_direction, "LONG")
        self.assertEqual(restored.eia.impulse_range_high, 78.00)


class LocalLLMResultSerializationTest(TestCase):
    """Tests for LocalLLMResult serialization/deserialization."""
    
    def test_llm_result_to_dict(self):
        """Test LocalLLMResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = LocalLLMResult(
            id="llm-001",
            created_at=now,
            setup_id="setup-001",
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            prompt="Analyze this setup...",
            response="Based on the analysis...",
            recommendation="BUY",
            confidence=0.85,
            reasoning="Strong breakout pattern",
            tokens_used=150,
            latency_ms=250,
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "llm-001")
        self.assertEqual(data['provider'], "OPENAI")
        self.assertEqual(data['model'], "gpt-4")
        self.assertEqual(data['recommendation'], "BUY")
        self.assertEqual(data['confidence'], 0.85)
        self.assertEqual(data['tokens_used'], 150)
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_llm_result_from_dict(self):
        """Test LocalLLMResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "llm-002",
            'created_at': now.isoformat(),
            'setup_id': "setup-002",
            'provider': "ANTHROPIC",
            'model': "claude-3",
            'prompt': "Evaluate trade...",
            'response': "Analysis complete...",
            'recommendation': "HOLD",
            'confidence': 0.72,
            'reasoning': "Uncertain market conditions",
            'tokens_used': 200,
            'latency_ms': 300,
            'schema_version': "1.0",
        }
        
        result = LocalLLMResult.from_dict(data)
        
        self.assertEqual(result.id, "llm-002")
        self.assertEqual(result.provider, LLMProvider.ANTHROPIC)
        self.assertEqual(result.recommendation, "HOLD")
        self.assertEqual(result.confidence, 0.72)


class ReflectionResultSerializationTest(TestCase):
    """Tests for ReflectionResult serialization/deserialization."""
    
    def test_reflection_result_to_dict(self):
        """Test ReflectionResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = ReflectionResult(
            id="ref-001",
            created_at=now,
            setup_id="setup-001",
            reflection_type="POST_TRADE",
            outcome="POSITIVE",
            trade_id="trade-001",
            lessons_learned=["Entry timing was good", "Should have trailed stop"],
            improvements=["Use tighter stops on breakouts"],
            confidence_adjustment=0.05,
            notes="Solid trade overall",
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "ref-001")
        self.assertEqual(data['reflection_type'], "POST_TRADE")
        self.assertEqual(data['outcome'], "POSITIVE")
        self.assertEqual(len(data['lessons_learned']), 2)
        self.assertEqual(data['confidence_adjustment'], 0.05)
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_reflection_result_from_dict(self):
        """Test ReflectionResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "ref-002",
            'created_at': now.isoformat(),
            'setup_id': "setup-002",
            'reflection_type': "PRE_TRADE",
            'outcome': None,
            'lessons_learned': [],
            'improvements': [],
            'confidence_adjustment': 0.0,
            'notes': "Pre-trade analysis",
            'schema_version': "1.0",
        }
        
        result = ReflectionResult.from_dict(data)
        
        self.assertEqual(result.id, "ref-002")
        self.assertEqual(result.reflection_type, "PRE_TRADE")
        self.assertIsNone(result.outcome)


class KiEvaluationResultSerializationTest(TestCase):
    """Tests for KiEvaluationResult serialization/deserialization."""
    
    def test_ki_evaluation_to_dict(self):
        """Test KiEvaluationResult.to_dict() method."""
        now = datetime.now(timezone.utc)
        result = KiEvaluationResult(
            id="ki-001",
            created_at=now,
            setup_id="setup-001",
            final_decision="EXECUTE",
            decision_confidence=0.88,
            risk_score=0.25,
            llm_result_ids=["llm-001", "llm-002"],
            position_size_suggestion=0.5,
            entry_price_target=75.50,
            stop_loss_target=74.50,
            take_profit_target=77.50,
            factors={"momentum": 0.8, "volume": 0.7},
            warnings=["Low volume environment"],
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['id'], "ki-001")
        self.assertEqual(data['final_decision'], "EXECUTE")
        self.assertEqual(data['decision_confidence'], 0.88)
        self.assertEqual(data['risk_score'], 0.25)
        self.assertEqual(len(data['llm_result_ids']), 2)
        self.assertEqual(data['position_size_suggestion'], 0.5)
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_ki_evaluation_from_dict(self):
        """Test KiEvaluationResult.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "ki-002",
            'created_at': now.isoformat(),
            'setup_id': "setup-002",
            'final_decision': "SKIP",
            'decision_confidence': 0.45,
            'risk_score': 0.65,
            'llm_result_ids': ["llm-003"],
            'warnings': ["High risk score"],
            'schema_version': "1.0",
        }
        
        result = KiEvaluationResult.from_dict(data)
        
        self.assertEqual(result.id, "ki-002")
        self.assertEqual(result.final_decision, "SKIP")
        self.assertEqual(result.decision_confidence, 0.45)
        self.assertEqual(len(result.warnings), 1)


class ExecutedTradeSerializationTest(TestCase):
    """Tests for ExecutedTrade serialization/deserialization."""
    
    def test_executed_trade_to_dict(self):
        """Test ExecutedTrade.to_dict() method."""
        now = datetime.now(timezone.utc)
        trade = ExecutedTrade(
            id="trade-001",
            created_at=now,
            setup_id="setup-001",
            ki_evaluation_id="ki-001",
            broker_deal_id="IG-12345",
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("74.50"),
            take_profit=Decimal("77.50"),
            status=TradeStatus.OPEN,
            opened_at=now,
            fees=Decimal("2.50"),
            currency="USD",
        )
        
        data = trade.to_dict()
        
        self.assertEqual(data['id'], "trade-001")
        self.assertEqual(data['direction'], "LONG")
        self.assertEqual(data['size'], 1.0)
        self.assertEqual(data['entry_price'], 75.50)
        self.assertEqual(data['status'], "OPEN")
        self.assertEqual(data['fees'], 2.50)
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_executed_trade_from_dict(self):
        """Test ExecutedTrade.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "trade-002",
            'created_at': now.isoformat(),
            'setup_id': "setup-002",
            'epic': "CC.D.CL.UNC.IP",
            'direction': "SHORT",
            'size': 2.0,
            'entry_price': 76.00,
            'exit_price': 74.50,
            'stop_loss': 77.00,
            'take_profit': 74.00,
            'status': "CLOSED",
            'opened_at': now.isoformat(),
            'closed_at': now.isoformat(),
            'pnl': 3.00,
            'pnl_percent': 1.5,
            'fees': 5.00,
            'currency': "USD",
            'market_snapshot_ids': ["snap-001"],
            'schema_version': "1.0",
        }
        
        trade = ExecutedTrade.from_dict(data)
        
        self.assertEqual(trade.id, "trade-002")
        self.assertEqual(trade.direction, TradeDirection.SHORT)
        self.assertEqual(trade.size, Decimal("2.0"))
        self.assertEqual(trade.status, TradeStatus.CLOSED)
        self.assertEqual(trade.pnl, Decimal("3.00"))


class ShadowTradeSerializationTest(TestCase):
    """Tests for ShadowTrade serialization/deserialization."""
    
    def test_shadow_trade_to_dict(self):
        """Test ShadowTrade.to_dict() method."""
        now = datetime.now(timezone.utc)
        trade = ShadowTrade(
            id="shadow-001",
            created_at=now,
            setup_id="setup-001",
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("75.50"),
            status=TradeStatus.CLOSED,
            exit_price=Decimal("77.00"),
            theoretical_pnl=Decimal("150.00"),
            theoretical_pnl_percent=1.98,
            skip_reason="Risk too high",
        )
        
        data = trade.to_dict()
        
        self.assertEqual(data['id'], "shadow-001")
        self.assertEqual(data['direction'], "LONG")
        self.assertEqual(data['theoretical_pnl'], 150.00)
        self.assertEqual(data['skip_reason'], "Risk too high")
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_shadow_trade_from_dict(self):
        """Test ShadowTrade.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "shadow-002",
            'created_at': now.isoformat(),
            'setup_id': "setup-002",
            'epic': "CC.D.CL.UNC.IP",
            'direction': "SHORT",
            'size': 0.5,
            'entry_price': 76.00,
            'status': "OPEN",
            'skip_reason': None,
            'market_snapshot_ids': [],
            'schema_version': "1.0",
        }
        
        trade = ShadowTrade.from_dict(data)
        
        self.assertEqual(trade.id, "shadow-002")
        self.assertEqual(trade.direction, TradeDirection.SHORT)
        self.assertEqual(trade.status, TradeStatus.OPEN)


class MarketSnapshotSerializationTest(TestCase):
    """Tests for MarketSnapshot serialization/deserialization."""
    
    def test_market_snapshot_to_dict(self):
        """Test MarketSnapshot.to_dict() method."""
        now = datetime.now(timezone.utc)
        snapshot = MarketSnapshot(
            id="snap-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            bid=Decimal("75.48"),
            ask=Decimal("75.52"),
            spread=Decimal("0.04"),
            high=Decimal("76.50"),
            low=Decimal("74.50"),
            volume=150000.0,
            atr=0.45,
            vwap=75.30,
            trend_direction="UP",
            volatility_level="NORMAL",
            session_phase="US_CORE",
            additional_indicators={"rsi": 62.5},
        )
        
        data = snapshot.to_dict()
        
        self.assertEqual(data['id'], "snap-001")
        self.assertEqual(data['bid'], 75.48)
        self.assertEqual(data['ask'], 75.52)
        self.assertEqual(data['spread'], 0.04)
        self.assertEqual(data['mid_price'], 75.50)
        self.assertEqual(data['trend_direction'], "UP")
        self.assertEqual(data['volatility_level'], "NORMAL")
        self.assertEqual(data['schema_version'], SCHEMA_VERSION)
    
    def test_market_snapshot_from_dict(self):
        """Test MarketSnapshot.from_dict() method."""
        now = datetime.now(timezone.utc)
        data = {
            'id': "snap-002",
            'created_at': now.isoformat(),
            'epic': "CC.D.CL.UNC.IP",
            'bid': 76.00,
            'ask': 76.05,
            'spread': 0.05,
            'high': 77.00,
            'low': 75.00,
            'volume': 200000.0,
            'atr': 0.50,
            'vwap': 76.10,
            'trend_direction': "DOWN",
            'volatility_level': "HIGH",
            'session_phase': "LONDON_CORE",
            'additional_indicators': {"macd": -0.15},
            'schema_version': "1.0",
        }
        
        snapshot = MarketSnapshot.from_dict(data)
        
        self.assertEqual(snapshot.id, "snap-002")
        self.assertEqual(snapshot.bid, Decimal("76.00"))
        self.assertEqual(snapshot.ask, Decimal("76.05"))
        self.assertEqual(snapshot.trend_direction, "DOWN")


class InMemoryWeaviateClientTest(TestCase):
    """Tests for InMemoryWeaviateClient."""
    
    def setUp(self):
        """Set up test client."""
        self.client = InMemoryWeaviateClient()
    
    def test_create_and_get_object(self):
        """Test creating and retrieving an object."""
        obj_id = self.client.create_object(
            "TestClass",
            {"name": "test", "value": 42},
            object_uuid="test-001"
        )
        
        self.assertEqual(obj_id, "test-001")
        
        retrieved = self.client.get_object("TestClass", "test-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['name'], "test")
        self.assertEqual(retrieved['value'], 42)
    
    def test_query_objects_no_filter(self):
        """Test querying objects without filters."""
        self.client.create_object("TestClass", {"name": "a"}, object_uuid="1")
        self.client.create_object("TestClass", {"name": "b"}, object_uuid="2")
        self.client.create_object("TestClass", {"name": "c"}, object_uuid="3")
        
        results = self.client.query_objects("TestClass")
        
        self.assertEqual(len(results), 3)
    
    def test_query_objects_with_filter(self):
        """Test querying objects with filters."""
        self.client.create_object("TestClass", {"name": "a", "type": "x"}, object_uuid="1")
        self.client.create_object("TestClass", {"name": "b", "type": "y"}, object_uuid="2")
        self.client.create_object("TestClass", {"name": "c", "type": "x"}, object_uuid="3")
        
        results = self.client.query_objects("TestClass", filters={"type": "x"})
        
        self.assertEqual(len(results), 2)
    
    def test_query_objects_with_pagination(self):
        """Test querying objects with pagination."""
        for i in range(10):
            self.client.create_object("TestClass", {"idx": i}, object_uuid=str(i))
        
        results = self.client.query_objects("TestClass", limit=3, offset=2)
        
        self.assertEqual(len(results), 3)
    
    def test_delete_object(self):
        """Test deleting an object."""
        self.client.create_object("TestClass", {"name": "test"}, object_uuid="1")
        
        deleted = self.client.delete_object("TestClass", "1")
        
        self.assertTrue(deleted)
        self.assertIsNone(self.client.get_object("TestClass", "1"))
    
    def test_add_reference(self):
        """Test adding cross-references."""
        self.client.create_object("ClassA", {"name": "a"}, object_uuid="a-1")
        self.client.create_object("ClassB", {"name": "b"}, object_uuid="b-1")
        
        success = self.client.add_reference("ClassA", "a-1", "hasB", "b-1")
        
        self.assertTrue(success)
        obj = self.client.get_object("ClassA", "a-1")
        self.assertIn("b-1", obj.get("hasB", []))
    
    def test_clear(self):
        """Test clearing all data."""
        self.client.create_object("TestClass", {"name": "test"}, object_uuid="1")
        
        self.client.clear()
        
        self.assertEqual(self.client.count(), 0)
    
    def test_count(self):
        """Test counting objects."""
        self.client.create_object("ClassA", {"name": "a"}, object_uuid="a-1")
        self.client.create_object("ClassA", {"name": "b"}, object_uuid="a-2")
        self.client.create_object("ClassB", {"name": "c"}, object_uuid="b-1")
        
        self.assertEqual(self.client.count("ClassA"), 2)
        self.assertEqual(self.client.count("ClassB"), 1)
        self.assertEqual(self.client.count(), 3)


class WeaviateServiceTest(TestCase):
    """Tests for WeaviateService."""
    
    def setUp(self):
        """Set up test service."""
        self.service = WeaviateService()
    
    def _create_setup(self, setup_id: str = "setup-001") -> SetupCandidate:
        """Helper to create a SetupCandidate."""
        return SetupCandidate(
            id=setup_id,
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
    
    def _create_llm_result(
        self,
        result_id: str = "llm-001",
        setup_id: str = "setup-001"
    ) -> LocalLLMResult:
        """Helper to create a LocalLLMResult."""
        return LocalLLMResult(
            id=result_id,
            created_at=datetime.now(timezone.utc),
            setup_id=setup_id,
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            prompt="Test prompt",
            response="Test response",
            recommendation="BUY",
            confidence=0.85,
        )
    
    def _create_ki_evaluation(
        self,
        eval_id: str = "ki-001",
        setup_id: str = "setup-001"
    ) -> KiEvaluationResult:
        """Helper to create a KiEvaluationResult."""
        return KiEvaluationResult(
            id=eval_id,
            created_at=datetime.now(timezone.utc),
            setup_id=setup_id,
            final_decision="EXECUTE",
            decision_confidence=0.88,
            risk_score=0.25,
        )
    
    def _create_trade(
        self,
        trade_id: str = "trade-001",
        setup_id: str = "setup-001"
    ) -> ExecutedTrade:
        """Helper to create an ExecutedTrade."""
        return ExecutedTrade(
            id=trade_id,
            created_at=datetime.now(timezone.utc),
            setup_id=setup_id,
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("75.50"),
            status=TradeStatus.OPEN,
        )
    
    def _create_shadow_trade(
        self,
        trade_id: str = "shadow-001",
        setup_id: str = "setup-001"
    ) -> ShadowTrade:
        """Helper to create a ShadowTrade."""
        return ShadowTrade(
            id=trade_id,
            created_at=datetime.now(timezone.utc),
            setup_id=setup_id,
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("75.50"),
            status=TradeStatus.OPEN,
        )
    
    def _create_snapshot(self, snapshot_id: str = "snap-001") -> MarketSnapshot:
        """Helper to create a MarketSnapshot."""
        return MarketSnapshot(
            id=snapshot_id,
            created_at=datetime.now(timezone.utc),
            epic="CC.D.CL.UNC.IP",
            bid=Decimal("75.48"),
            ask=Decimal("75.52"),
            spread=Decimal("0.04"),
        )
    
    def test_store_and_get_setup(self):
        """Test storing and retrieving a SetupCandidate."""
        setup = self._create_setup()
        
        stored_id = self.service.store_setup(setup)
        
        self.assertEqual(stored_id, "setup-001")
        
        retrieved = self.service.get_setup("setup-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, "setup-001")
        self.assertEqual(retrieved.epic, "CC.D.CL.UNC.IP")
        self.assertEqual(retrieved.direction, "LONG")
    
    def test_store_and_get_llm_result(self):
        """Test storing and retrieving a LocalLLMResult."""
        result = self._create_llm_result()
        
        stored_id = self.service.store_llm_result(result)
        
        self.assertEqual(stored_id, "llm-001")
        
        retrieved = self.service.get_llm_result("llm-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.recommendation, "BUY")
    
    def test_store_and_get_reflection(self):
        """Test storing and retrieving a ReflectionResult."""
        result = ReflectionResult(
            id="ref-001",
            created_at=datetime.now(timezone.utc),
            setup_id="setup-001",
            reflection_type="POST_TRADE",
            outcome="POSITIVE",
        )
        
        stored_id = self.service.store_reflection_result(result)
        
        self.assertEqual(stored_id, "ref-001")
        
        retrieved = self.service.get_reflection("ref-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.outcome, "POSITIVE")
    
    def test_store_and_get_ki_evaluation(self):
        """Test storing and retrieving a KiEvaluationResult."""
        result = self._create_ki_evaluation()
        
        stored_id = self.service.store_ki_evaluation(result)
        
        self.assertEqual(stored_id, "ki-001")
        
        retrieved = self.service.get_ki_evaluation("ki-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.final_decision, "EXECUTE")
    
    def test_store_and_get_trade(self):
        """Test storing and retrieving an ExecutedTrade."""
        trade = self._create_trade()
        
        stored_id = self.service.store_trade(trade)
        
        self.assertEqual(stored_id, "trade-001")
        
        retrieved = self.service.get_trade("trade-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.direction, TradeDirection.LONG)
    
    def test_store_and_get_shadow_trade(self):
        """Test storing and retrieving a ShadowTrade."""
        trade = self._create_shadow_trade()
        
        stored_id = self.service.store_shadow_trade(trade)
        
        self.assertEqual(stored_id, "shadow-001")
        
        retrieved = self.service.get_shadow_trade("shadow-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.direction, TradeDirection.LONG)
    
    def test_store_and_get_market_snapshot(self):
        """Test storing and retrieving a MarketSnapshot."""
        snapshot = self._create_snapshot()
        
        stored_id = self.service.store_market_snapshot(snapshot)
        
        self.assertEqual(stored_id, "snap-001")
        
        retrieved = self.service.get_market_snapshot("snap-001")
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.bid, Decimal("75.48"))
    
    def test_query_setups(self):
        """Test querying SetupCandidates."""
        self.service.store_setup(self._create_setup("setup-001"))
        self.service.store_setup(self._create_setup("setup-002"))
        
        results = self.service.query_setups()
        
        self.assertEqual(len(results), 2)
    
    def test_query_setups_with_filter(self):
        """Test querying SetupCandidates with filters."""
        setup1 = self._create_setup("setup-001")
        setup1.epic = "EPIC-A"
        self.service.store_setup(setup1)
        
        setup2 = self._create_setup("setup-002")
        setup2.epic = "EPIC-B"
        self.service.store_setup(setup2)
        
        filters = QueryFilter(epic="EPIC-A")
        results = self.service.query_setups(filters)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].epic, "EPIC-A")
    
    def test_query_trades(self):
        """Test querying ExecutedTrades."""
        self.service.store_trade(self._create_trade("trade-001"))
        self.service.store_trade(self._create_trade("trade-002"))
        
        results = self.service.query_trades()
        
        self.assertEqual(len(results), 2)
    
    def test_query_shadow_trades(self):
        """Test querying ShadowTrades."""
        self.service.store_shadow_trade(self._create_shadow_trade("shadow-001"))
        self.service.store_shadow_trade(self._create_shadow_trade("shadow-002"))
        
        results = self.service.query_shadow_trades()
        
        self.assertEqual(len(results), 2)
    
    def test_query_ki_results(self):
        """Test querying KiEvaluationResults."""
        self.service.store_ki_evaluation(self._create_ki_evaluation("ki-001"))
        self.service.store_ki_evaluation(self._create_ki_evaluation("ki-002"))
        
        results = self.service.query_ki_results()
        
        self.assertEqual(len(results), 2)
    
    def test_query_with_pagination(self):
        """Test querying with pagination."""
        for i in range(5):
            self.service.store_setup(self._create_setup(f"setup-{i:03d}"))
        
        filters = QueryFilter(limit=2, offset=1)
        results = self.service.query_setups(filters)
        
        self.assertEqual(len(results), 2)


class WeaviateServiceIntegrationTest(TestCase):
    """Integration tests for WeaviateService pipeline."""
    
    def setUp(self):
        """Set up test service."""
        self.service = WeaviateService()
    
    def test_full_pipeline_setup_to_trade(self):
        """Test full pipeline: SetupCandidate → KI → Trade → Snapshot."""
        now = datetime.now(timezone.utc)
        
        # 1. Create and store setup
        setup = SetupCandidate(
            id="pipeline-setup-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.BREAKOUT,
            phase=SessionPhase.LONDON_CORE,
            reference_price=75.50,
            direction="LONG",
        )
        setup_id = self.service.store_setup(setup)
        
        # 2. Create and store LLM result
        llm_result = LocalLLMResult(
            id="pipeline-llm-001",
            created_at=now,
            setup_id=setup_id,
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            prompt="Analyze setup",
            response="Bullish setup",
            recommendation="BUY",
            confidence=0.85,
        )
        llm_id = self.service.store_llm_result(llm_result)
        
        # 3. Create and store KI evaluation
        ki_eval = KiEvaluationResult(
            id="pipeline-ki-001",
            created_at=now,
            setup_id=setup_id,
            llm_result_ids=[llm_id],
            final_decision="EXECUTE",
            decision_confidence=0.88,
            risk_score=0.25,
            position_size_suggestion=1.0,
            entry_price_target=75.50,
            stop_loss_target=74.50,
            take_profit_target=77.50,
        )
        ki_id = self.service.store_ki_evaluation(ki_eval)
        
        # 4. Create and store market snapshot
        snapshot = MarketSnapshot(
            id="pipeline-snap-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            bid=Decimal("75.48"),
            ask=Decimal("75.52"),
            spread=Decimal("0.04"),
            trend_direction="UP",
            volatility_level="NORMAL",
        )
        snap_id = self.service.store_market_snapshot(snapshot)
        
        # 5. Create and store executed trade
        trade = ExecutedTrade(
            id="pipeline-trade-001",
            created_at=now,
            setup_id=setup_id,
            ki_evaluation_id=ki_id,
            broker_deal_id="IG-12345",
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.LONG,
            size=Decimal("1.0"),
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("74.50"),
            take_profit=Decimal("77.50"),
            status=TradeStatus.OPEN,
            opened_at=now,
            market_snapshot_ids=[snap_id],
        )
        trade_id = self.service.store_trade(trade)
        
        # Verify all objects are stored and retrievable
        retrieved_setup = self.service.get_setup(setup_id)
        retrieved_llm = self.service.get_llm_result(llm_id)
        retrieved_ki = self.service.get_ki_evaluation(ki_id)
        retrieved_snap = self.service.get_market_snapshot(snap_id)
        retrieved_trade = self.service.get_trade(trade_id)
        
        self.assertIsNotNone(retrieved_setup)
        self.assertIsNotNone(retrieved_llm)
        self.assertIsNotNone(retrieved_ki)
        self.assertIsNotNone(retrieved_snap)
        self.assertIsNotNone(retrieved_trade)
        
        # Verify relationships
        self.assertEqual(retrieved_trade.setup_id, setup_id)
        self.assertEqual(retrieved_trade.ki_evaluation_id, ki_id)
        self.assertIn(snap_id, retrieved_trade.market_snapshot_ids)
        self.assertEqual(retrieved_ki.setup_id, setup_id)
        self.assertIn(llm_id, retrieved_ki.llm_result_ids)
    
    def test_shadow_trade_tracking(self):
        """Test shadow trade creation and tracking."""
        now = datetime.now(timezone.utc)
        
        # Create setup
        setup = SetupCandidate(
            id="shadow-setup-001",
            created_at=now,
            epic="CC.D.CL.UNC.IP",
            setup_kind=SetupKind.EIA_REVERSION,
            phase=SessionPhase.EIA_POST,
            reference_price=76.00,
            direction="SHORT",
        )
        setup_id = self.service.store_setup(setup)
        
        # Create KI evaluation that decides to skip
        ki_eval = KiEvaluationResult(
            id="shadow-ki-001",
            created_at=now,
            setup_id=setup_id,
            final_decision="SKIP",
            decision_confidence=0.55,
            risk_score=0.65,
            warnings=["High risk score", "Low confidence"],
        )
        ki_id = self.service.store_ki_evaluation(ki_eval)
        
        # Create shadow trade to track what would have happened
        shadow = ShadowTrade(
            id="shadow-trade-001",
            created_at=now,
            setup_id=setup_id,
            ki_evaluation_id=ki_id,
            epic="CC.D.CL.UNC.IP",
            direction=TradeDirection.SHORT,
            size=Decimal("1.0"),
            entry_price=Decimal("76.00"),
            status=TradeStatus.OPEN,
            skip_reason="Risk score too high",
        )
        shadow_id = self.service.store_shadow_trade(shadow)
        
        # Verify shadow trade
        retrieved = self.service.get_shadow_trade(shadow_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.skip_reason, "Risk score too high")
        self.assertEqual(retrieved.setup_id, setup_id)
        self.assertEqual(retrieved.ki_evaluation_id, ki_id)


class WeaviateSchemaTest(TestCase):
    """Tests for Weaviate schema definition."""
    
    def test_get_schema_definition(self):
        """Test getting the complete schema definition."""
        schema = WeaviateService.get_schema_definition()
        
        self.assertIn('classes', schema)
        self.assertEqual(len(schema['classes']), 7)
        
        # Check all class names are present
        class_names = [c['class'] for c in schema['classes']]
        expected_classes = [
            'SetupCandidate',
            'LocalLLMResult',
            'ReflectionResult',
            'KiEvaluationResult',
            'ExecutedTrade',
            'ShadowTrade',
            'MarketSnapshot',
        ]
        for name in expected_classes:
            self.assertIn(name, class_names)
    
    def test_schema_has_cross_references(self):
        """Test that schema includes cross-references."""
        schema = WeaviateService.get_schema_definition()
        
        # Find ExecutedTrade class
        trade_class = next(
            c for c in schema['classes'] if c['class'] == 'ExecutedTrade'
        )
        
        self.assertIn('references', trade_class)
        ref_names = [r['name'] for r in trade_class.get('references', [])]
        self.assertIn('hasSetup', ref_names)
        self.assertIn('hasKiEvaluation', ref_names)
        self.assertIn('hasMarketSnapshots', ref_names)
    
    def test_schema_has_version_field(self):
        """Test that all classes have schema_version field."""
        schema = WeaviateService.get_schema_definition()
        
        for cls in schema['classes']:
            prop_names = [p['name'] for p in cls.get('properties', [])]
            self.assertIn(
                'schema_version',
                prop_names,
                f"Class {cls['class']} missing schema_version"
            )
