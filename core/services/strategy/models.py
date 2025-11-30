"""
Data models for the Strategy Engine.

These models represent trading setup candidates and related context,
independent of execution or risk management decisions.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

# Current schema version for all models
SCHEMA_VERSION = "1.0"


class SetupKind(str, Enum):
    """Type of trading setup identified by the Strategy Engine."""
    BREAKOUT = "BREAKOUT"
    EIA_REVERSION = "EIA_REVERSION"
    EIA_TRENDDAY = "EIA_TRENDDAY"


class SessionPhase(str, Enum):
    """Current market session phase for strategy evaluation."""
    ASIA_RANGE = "ASIA_RANGE"
    LONDON_CORE = "LONDON_CORE"
    PRE_US_RANGE = "PRE_US_RANGE"
    US_CORE_TRADING = "US_CORE_TRADING"
    US_CORE = "US_CORE"  # Deprecated: kept for backwards compatibility
    EIA_PRE = "EIA_PRE"
    EIA_POST = "EIA_POST"
    FRIDAY_LATE = "FRIDAY_LATE"
    OTHER = "OTHER"


class BreakoutSignal(str, Enum):
    """Breakout signal classification including fakeouts."""

    LONG_BREAKOUT = "LONG_BREAKOUT"
    SHORT_BREAKOUT = "SHORT_BREAKOUT"
    FAILED_LONG_BREAKOUT = "FAILED_LONG_BREAKOUT"
    FAILED_SHORT_BREAKOUT = "FAILED_SHORT_BREAKOUT"


@dataclass
class BreakoutContext:
    """
    Context information for a breakout setup.
    
    Attributes:
        range_high: Upper boundary of the range.
        range_low: Lower boundary of the range.
        range_height: Height of the range (high - low).
        trigger_price: Price that triggered the breakout.
        direction: Direction of the breakout (LONG or SHORT).
        signal_type: Breakout signal classification (including fakeouts).
        atr: Average True Range (optional volatility measure).
        vwap: Volume Weighted Average Price (optional).
        volume_spike: Whether a volume spike was detected (optional).
    """
    range_high: float
    range_low: float
    range_height: float
    trigger_price: float
    direction: Literal["LONG", "SHORT"]
    signal_type: Optional['BreakoutSignal'] = None
    atr: Optional[float] = None
    vwap: Optional[float] = None
    volume_spike: Optional[bool] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'range_high': self.range_high,
            'range_low': self.range_low,
            'range_height': self.range_height,
            'trigger_price': self.trigger_price,
            'direction': self.direction,
            'signal_type': self.signal_type.value if self.signal_type else None,
            'atr': self.atr,
            'vwap': self.vwap,
            'volume_spike': self.volume_spike,
        }


@dataclass
class EiaContext:
    """
    Context information for an EIA (Energy Information Administration) setup.
    
    Attributes:
        eia_timestamp: Timestamp of the EIA release.
        first_impulse_direction: Direction of the initial price impulse.
        impulse_range_high: High of the impulse range.
        impulse_range_low: Low of the impulse range.
        atr: Average True Range (optional volatility measure).
    """
    eia_timestamp: datetime
    first_impulse_direction: Optional[Literal["LONG", "SHORT"]] = None
    impulse_range_high: Optional[float] = None
    impulse_range_low: Optional[float] = None
    atr: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'eia_timestamp': self.eia_timestamp.isoformat() if self.eia_timestamp else None,
            'first_impulse_direction': self.first_impulse_direction,
            'impulse_range_high': self.impulse_range_high,
            'impulse_range_low': self.impulse_range_low,
            'atr': self.atr,
        }


@dataclass
class Candle:
    """
    Represents a price candle (OHLCV data).
    
    Attributes:
        timestamp: Candle timestamp.
        open: Opening price.
        high: High price.
        low: Low price.
        close: Closing price.
        volume: Trading volume (optional).
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

    @property
    def body_high(self) -> float:
        """Get the higher of open and close."""
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        """Get the lower of open and close."""
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        """Get the absolute body size."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish (close > open)."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Check if candle is bearish (close < open)."""
        return self.close < self.open

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }


@dataclass
class SetupCandidate:
    """
    Represents a potential trading setup identified by the Strategy Engine.
    
    This is an output object that describes a trade opportunity without
    making any decisions about whether to trade or placing orders.
    
    Attributes:
        id: Unique identifier for the setup.
        created_at: Timestamp when the setup was identified.
        epic: Market identifier (e.g., 'CC.D.CL.UNC.IP').
        setup_kind: Type of setup (BREAKOUT, EIA_REVERSION, EIA_TRENDDAY).
        phase: Current session phase when setup was identified.
        reference_price: Reference price at the time of setup.
        direction: Suggested trade direction (LONG or SHORT).
        breakout: Breakout context (if setup_kind is BREAKOUT).
        eia: EIA context (if setup_kind is EIA_*).
        quality_flags: Additional quality indicators.
        schema_version: Schema version for compatibility.
    """
    id: str
    created_at: datetime
    epic: str
    setup_kind: SetupKind
    phase: SessionPhase
    reference_price: float
    direction: Literal["LONG", "SHORT"]
    breakout: Optional[BreakoutContext] = None
    eia: Optional[EiaContext] = None
    quality_flags: Optional[dict] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'epic': self.epic,
            'setup_kind': self.setup_kind.value if isinstance(self.setup_kind, SetupKind) else self.setup_kind,
            'phase': self.phase.value if isinstance(self.phase, SessionPhase) else self.phase,
            'reference_price': self.reference_price,
            'direction': self.direction,
            'breakout': self.breakout.to_dict() if self.breakout else None,
            'eia': self.eia.to_dict() if self.eia else None,
            'quality_flags': self.quality_flags,
            'schema_version': self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SetupCandidate':
        """
        Create instance from dictionary.
        
        Args:
            data: Dictionary with field values.
            
        Returns:
            SetupCandidate: New instance.
        """
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        setup_kind = data.get('setup_kind')
        if isinstance(setup_kind, str):
            setup_kind = SetupKind(setup_kind)
        
        phase = data.get('phase')
        if isinstance(phase, str):
            phase = SessionPhase(phase)
        
        breakout = None
        if data.get('breakout'):
            breakout_data = data['breakout']
            signal_type = breakout_data.get('signal_type')
            if isinstance(signal_type, str):
                signal_type = BreakoutSignal(signal_type)

            breakout = BreakoutContext(
                range_high=breakout_data['range_high'],
                range_low=breakout_data['range_low'],
                range_height=breakout_data['range_height'],
                trigger_price=breakout_data['trigger_price'],
                direction=breakout_data['direction'],
                signal_type=signal_type,
                atr=breakout_data.get('atr'),
                vwap=breakout_data.get('vwap'),
                volume_spike=breakout_data.get('volume_spike'),
            )
        
        eia = None
        if data.get('eia'):
            eia_data = data['eia']
            eia_timestamp = eia_data.get('eia_timestamp')
            if isinstance(eia_timestamp, str):
                eia_timestamp = datetime.fromisoformat(eia_timestamp)
            eia = EiaContext(
                eia_timestamp=eia_timestamp,
                first_impulse_direction=eia_data.get('first_impulse_direction'),
                impulse_range_high=eia_data.get('impulse_range_high'),
                impulse_range_low=eia_data.get('impulse_range_low'),
                atr=eia_data.get('atr'),
            )
        
        return cls(
            id=data['id'],
            created_at=created_at,
            epic=data['epic'],
            setup_kind=setup_kind,
            phase=phase,
            reference_price=data['reference_price'],
            direction=data['direction'],
            breakout=breakout,
            eia=eia,
            quality_flags=data.get('quality_flags', {}),
            schema_version=data.get('schema_version', SCHEMA_VERSION),
        )
