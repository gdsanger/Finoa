"""
Data models for the Execution Layer.

These models represent execution sessions and configuration,
enabling trade orchestration and lifecycle tracking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Any, TYPE_CHECKING
import yaml

if TYPE_CHECKING:
    from core.services.broker.models import OrderRequest


# Current schema version for all execution models
SCHEMA_VERSION = "1.0"


class ExecutionState(str, Enum):
    """
    State machine for ExecutionSession lifecycle.
    
    Flow:
        NEW_SIGNAL → KI_EVALUATED → RISK_REJECTED/RISK_APPROVED
        RISK_REJECTED → SHADOW_ONLY
        RISK_APPROVED → WAITING_FOR_USER
        WAITING_FOR_USER → USER_ACCEPTED/USER_SHADOW/USER_REJECTED
        USER_ACCEPTED → LIVE_TRADE_OPEN → EXITED
        USER_SHADOW → SHADOW_TRADE_OPEN → EXITED
        USER_REJECTED → DROPPED
    """
    # Initial states
    NEW_SIGNAL = "NEW_SIGNAL"
    KI_EVALUATED = "KI_EVALUATED"
    
    # Risk evaluation outcomes
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    
    # User decision pending
    WAITING_FOR_USER = "WAITING_FOR_USER"
    SHADOW_ONLY = "SHADOW_ONLY"
    
    # User decisions
    USER_ACCEPTED = "USER_ACCEPTED"
    USER_SHADOW = "USER_SHADOW"
    USER_REJECTED = "USER_REJECTED"
    
    # Trade states
    LIVE_TRADE_OPEN = "LIVE_TRADE_OPEN"
    SHADOW_TRADE_OPEN = "SHADOW_TRADE_OPEN"
    
    # Final states
    EXITED = "EXITED"
    DROPPED = "DROPPED"

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (ExecutionState.EXITED, ExecutionState.DROPPED)

    def is_trade_open(self) -> bool:
        """Check if a trade is currently open."""
        return self in (ExecutionState.LIVE_TRADE_OPEN, ExecutionState.SHADOW_TRADE_OPEN)

    def allows_user_action(self) -> bool:
        """Check if user actions are allowed in this state."""
        return self in (ExecutionState.WAITING_FOR_USER, ExecutionState.SHADOW_ONLY)


class ExitReason(str, Enum):
    """Reason for trade exit."""
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"
    MANUAL = "MANUAL"
    TIME_EXIT = "TIME_EXIT"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    MARGIN_CALL = "MARGIN_CALL"


@dataclass
class ExecutionSession:
    """
    Represents an execution session for a trade proposal.
    
    An ExecutionSession is created when signals from Strategy Engine,
    KI Layer, and Risk Engine converge to form a trade opportunity.
    It tracks the state of the trade from proposal to execution/rejection.
    
    Attributes:
        id: Unique identifier for the session.
        setup_id: Reference to the SetupCandidate.
        ki_evaluation_id: Reference to the KiEvaluationResult (if available).
        risk_result_id: Reference to the RiskEvaluationResult (if available).
        state: Current execution state.
        created_at: Timestamp when session was created.
        last_update: Timestamp of last state change.
        proposed_order: Original order from KI + Strategy.
        adjusted_order: Order adjusted by Risk Engine (if any).
        trade_id: Reference to ExecutedTrade or ShadowTrade (once created).
        is_shadow: Whether this is a shadow trade.
        comment: Optional user/system comment.
        meta: Additional metadata.
        schema_version: Schema version for compatibility.
    """
    id: str
    setup_id: str
    state: ExecutionState
    created_at: datetime
    last_update: datetime
    proposed_order: 'OrderRequest'
    
    ki_evaluation_id: Optional[str] = None
    risk_result_id: Optional[str] = None
    adjusted_order: Optional['OrderRequest'] = None
    trade_id: Optional[str] = None
    is_shadow: bool = False
    comment: Optional[str] = None
    meta: Optional[dict[str, Any]] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        """Ensure proper types."""
        if self.meta is None:
            self.meta = {}
        if isinstance(self.state, str):
            self.state = ExecutionState(self.state)

    def get_effective_order(self) -> 'OrderRequest':
        """
        Get the effective order to use for execution.
        
        Returns the adjusted order if available, otherwise the proposed order.
        
        Returns:
            OrderRequest: The order to execute.
        """
        return self.adjusted_order if self.adjusted_order else self.proposed_order

    def transition_to(self, new_state: ExecutionState) -> None:
        """
        Transition to a new state.
        
        Args:
            new_state: The target state.
            
        Raises:
            ValueError: If the transition is invalid.
        """
        # Define valid transitions
        valid_transitions = {
            ExecutionState.NEW_SIGNAL: [ExecutionState.KI_EVALUATED],
            ExecutionState.KI_EVALUATED: [
                ExecutionState.RISK_APPROVED,
                ExecutionState.RISK_REJECTED,
            ],
            ExecutionState.RISK_APPROVED: [ExecutionState.WAITING_FOR_USER],
            ExecutionState.RISK_REJECTED: [ExecutionState.SHADOW_ONLY],
            ExecutionState.WAITING_FOR_USER: [
                ExecutionState.USER_ACCEPTED,
                ExecutionState.USER_SHADOW,
                ExecutionState.USER_REJECTED,
            ],
            ExecutionState.SHADOW_ONLY: [
                ExecutionState.USER_SHADOW,
                ExecutionState.USER_REJECTED,
            ],
            ExecutionState.USER_ACCEPTED: [ExecutionState.LIVE_TRADE_OPEN],
            ExecutionState.USER_SHADOW: [ExecutionState.SHADOW_TRADE_OPEN],
            ExecutionState.USER_REJECTED: [ExecutionState.DROPPED],
            ExecutionState.LIVE_TRADE_OPEN: [ExecutionState.EXITED],
            ExecutionState.SHADOW_TRADE_OPEN: [ExecutionState.EXITED],
        }
        
        allowed = valid_transitions.get(self.state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid state transition: {self.state.value} → {new_state.value}. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )
        
        self.state = new_state
        self.last_update = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Serializable dictionary representation.
        """
        proposed_order_dict = None
        if self.proposed_order is not None:
            proposed_order_dict = self.proposed_order.to_dict()
        
        adjusted_order_dict = None
        if self.adjusted_order is not None:
            adjusted_order_dict = self.adjusted_order.to_dict()
        
        return {
            'id': self.id,
            'setup_id': self.setup_id,
            'ki_evaluation_id': self.ki_evaluation_id,
            'risk_result_id': self.risk_result_id,
            'state': self.state.value if isinstance(self.state, ExecutionState) else self.state,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'proposed_order': proposed_order_dict,
            'adjusted_order': adjusted_order_dict,
            'trade_id': self.trade_id,
            'is_shadow': self.is_shadow,
            'comment': self.comment,
            'meta': self.meta,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionSession':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            ExecutionSession: New instance.
        """
        from core.services.broker.models import OrderRequest, OrderDirection, OrderType

        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)
        
        def parse_order(order_data) -> Optional[OrderRequest]:
            if order_data is None:
                return None
            return OrderRequest(
                epic=order_data['epic'],
                direction=OrderDirection(order_data['direction']),
                size=Decimal(str(order_data['size'])),
                order_type=OrderType(order_data['order_type']),
                limit_price=Decimal(str(order_data['limit_price'])) if order_data.get('limit_price') else None,
                stop_price=Decimal(str(order_data['stop_price'])) if order_data.get('stop_price') else None,
                stop_loss=Decimal(str(order_data['stop_loss'])) if order_data.get('stop_loss') else None,
                take_profit=Decimal(str(order_data['take_profit'])) if order_data.get('take_profit') else None,
                guaranteed_stop=order_data.get('guaranteed_stop', False),
                trailing_stop=order_data.get('trailing_stop', False),
                trailing_stop_distance=Decimal(str(order_data['trailing_stop_distance'])) if order_data.get('trailing_stop_distance') else None,
                currency=order_data.get('currency', 'EUR'),
            )
        
        return cls(
            id=data['id'],
            setup_id=data['setup_id'],
            ki_evaluation_id=data.get('ki_evaluation_id'),
            risk_result_id=data.get('risk_result_id'),
            state=ExecutionState(data['state']),
            created_at=parse_datetime(data['created_at']),
            last_update=parse_datetime(data['last_update']),
            proposed_order=parse_order(data.get('proposed_order')),
            adjusted_order=parse_order(data.get('adjusted_order')),
            trade_id=data.get('trade_id'),
            is_shadow=data.get('is_shadow', False),
            comment=data.get('comment'),
            meta=data.get('meta', {}),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )


@dataclass
class ExecutionConfig:
    """
    Configuration for the Execution Layer.
    
    Defines behavior for execution, shadow trading, and market snapshots.
    Can be loaded from a YAML configuration file.
    
    Attributes:
        allow_shadow_if_risk_denied: Allow shadow trades when risk engine denies.
        track_market_snapshot_minutes_after_exit: Minutes to track market after exit.
        track_snapshot_interval_seconds: Interval between snapshots.
        default_currency: Default currency for trades.
        enable_exit_polling: Whether to poll for exit conditions.
        exit_polling_interval_seconds: How often to check for exits.
    """
    allow_shadow_if_risk_denied: bool = True
    track_market_snapshot_minutes_after_exit: int = 10
    track_snapshot_interval_seconds: int = 60
    default_currency: str = 'EUR'
    enable_exit_polling: bool = True
    exit_polling_interval_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionConfig':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with configuration values.
            
        Returns:
            ExecutionConfig: New instance with values from dictionary.
        """
        return cls(
            allow_shadow_if_risk_denied=data.get('allow_shadow_if_risk_denied', True),
            track_market_snapshot_minutes_after_exit=data.get('track_market_snapshot_minutes_after_exit', 10),
            track_snapshot_interval_seconds=data.get('track_snapshot_interval_seconds', 60),
            default_currency=data.get('default_currency', 'EUR'),
            enable_exit_polling=data.get('enable_exit_polling', True),
            exit_polling_interval_seconds=data.get('exit_polling_interval_seconds', 30),
        )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'ExecutionConfig':
        """
        Load configuration from a YAML file.
        
        Args:
            yaml_path: Path to the YAML configuration file.
            
        Returns:
            ExecutionConfig: New instance with values from YAML file.
        """
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Handle nested 'execution' key if present
        if 'execution' in data:
            data = data['execution']
        
        return cls.from_dict(data)

    @classmethod
    def from_yaml_string(cls, yaml_string: str) -> 'ExecutionConfig':
        """
        Load configuration from a YAML string.
        
        Args:
            yaml_string: YAML configuration as a string.
            
        Returns:
            ExecutionConfig: New instance with values from YAML string.
        """
        data = yaml.safe_load(yaml_string)
        
        # Handle nested 'execution' key if present
        if 'execution' in data:
            data = data['execution']
        
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.
        
        Returns:
            dict: Dictionary representation of the configuration.
        """
        return {
            'allow_shadow_if_risk_denied': self.allow_shadow_if_risk_denied,
            'track_market_snapshot_minutes_after_exit': self.track_market_snapshot_minutes_after_exit,
            'track_snapshot_interval_seconds': self.track_snapshot_interval_seconds,
            'default_currency': self.default_currency,
            'enable_exit_polling': self.enable_exit_polling,
            'exit_polling_interval_seconds': self.exit_polling_interval_seconds,
        }

    def to_yaml(self) -> str:
        """
        Convert to YAML string.
        
        Returns:
            str: YAML representation of the configuration.
        """
        return yaml.dump({'execution': self.to_dict()}, default_flow_style=False)
