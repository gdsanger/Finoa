"""
Breakout Range Diagnostics for the Strategy Engine.

Provides detailed diagnostic information about breakout ranges,
useful for debugging and validating the Strategy Engine's decisions.

Supports all four phases:
- Asia Range (00:00-08:00 UTC)
- London Core (08:00-12:00 UTC)
- Pre-US Range (13:00-15:00 UTC)
- US Core Trading (15:00-22:00 UTC)
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from .config import AsiaRangeConfig, LondonCoreConfig, StrategyConfig, UsCoreConfig
from .models import Candle, SessionPhase
from .providers import MarketStateProvider


class PricePosition(str, Enum):
    """Position of price relative to range."""
    BELOW = "BELOW"
    INSIDE = "INSIDE"
    ABOVE = "ABOVE"


class BreakoutStatus(str, Enum):
    """Current breakout status."""
    NO_BREAKOUT = "NO_BREAKOUT"
    POTENTIAL_BREAKOUT = "POTENTIAL_BREAKOUT"
    VALID_BREAKOUT = "VALID_BREAKOUT"


class RangeValidation(str, Enum):
    """Range validation result."""
    VALID = "VALID"
    TOO_SMALL = "TOO_SMALL"
    TOO_LARGE = "TOO_LARGE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    INCOMPLETE = "INCOMPLETE"


class BreakoutEligibility(str, Enum):
    """Breakout eligibility status."""
    ELIGIBLE_LONG = "ELIGIBLE_LONG"
    ELIGIBLE_SHORT = "ELIGIBLE_SHORT"
    ELIGIBLE_BOTH = "ELIGIBLE_BOTH"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


@dataclass
class BreakoutRangeDiagnostics:
    """
    Diagnostic information about a breakout range.
    
    Provides detailed insights into range data, current price position,
    and why a breakout setup may or may not be active.
    """
    # Range identification
    range_type: str  # "Asia Range", "London Core", "Pre-US Range", or "US Core Trading"
    range_period_start: str  # e.g., "00:00"
    range_period_end: str  # e.g., "08:00"
    
    # Range data (None if not available)
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    range_height: Optional[float] = None
    range_height_ticks: Optional[int] = None
    
    # Candle information
    candle_count: int = 0
    timeframe: str = "1m"
    
    # Current market state
    current_price: Optional[float] = None
    price_position: Optional[PricePosition] = None
    distance_to_high: Optional[float] = None
    distance_to_low: Optional[float] = None
    
    # Breakout status
    breakout_status: BreakoutStatus = BreakoutStatus.NO_BREAKOUT
    potential_direction: Optional[Literal["LONG", "SHORT"]] = None
    
    # Configuration values
    min_range_ticks: int = 10
    max_range_ticks: int = 200
    min_breakout_body_fraction: float = 0.5
    require_volume_spike: bool = False
    require_clean_range: bool = False
    tick_size: float = 0.01
    
    # Validation
    range_validation: RangeValidation = RangeValidation.NOT_AVAILABLE
    
    # Current phase
    current_phase: Optional[SessionPhase] = None
    
    # Diagnostic messages
    diagnostic_message: str = ""
    detailed_explanation: str = ""
    
    # ATR value if available
    atr: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'range_type': self.range_type,
            'range_period': {
                'start': self.range_period_start,
                'end': self.range_period_end,
            },
            'range_data': {
                'high': self.range_high,
                'low': self.range_low,
                'height': self.range_height,
                'height_ticks': self.range_height_ticks,
                'candle_count': self.candle_count,
                'timeframe': self.timeframe,
            },
            'current_market': {
                'price': self.current_price,
                'position': self.price_position.value if self.price_position else None,
                'distance_to_high': self.distance_to_high,
                'distance_to_low': self.distance_to_low,
            },
            'breakout_status': {
                'status': self.breakout_status.value,
                'potential_direction': self.potential_direction,
            },
            'config': {
                'min_range_ticks': self.min_range_ticks,
                'max_range_ticks': self.max_range_ticks,
                'min_breakout_body_fraction': self.min_breakout_body_fraction,
                'require_volume_spike': self.require_volume_spike,
                'require_clean_range': self.require_clean_range,
                'tick_size': self.tick_size,
            },
            'validation': {
                'range_validation': self.range_validation.value,
            },
            'current_phase': self.current_phase.value if self.current_phase else None,
            'diagnostics': {
                'message': self.diagnostic_message,
                'detailed_explanation': self.detailed_explanation,
            },
            'atr': self.atr,
        }


class BreakoutRangeDiagnosticService:
    """
    Service for generating breakout range diagnostics.
    
    Provides detailed analysis of breakout ranges for debugging
    and understanding Strategy Engine decisions.
    """

    def __init__(
        self,
        market_state: MarketStateProvider,
        config: Optional[StrategyConfig] = None
    ) -> None:
        """
        Initialize the diagnostic service.
        
        Args:
            market_state: Market state provider for data access.
            config: Strategy configuration (uses defaults if not provided).
        """
        self.market_state = market_state
        self.config = config or StrategyConfig()

    def get_asia_range_diagnostics(
        self,
        epic: str,
        ts: datetime,
        current_price: Optional[float] = None
    ) -> BreakoutRangeDiagnostics:
        """
        Get diagnostic information for Asia Range.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            current_price: Current market price (if available).
            
        Returns:
            BreakoutRangeDiagnostics with Asia Range analysis.
        """
        asia_config = self.config.breakout.asia_range
        
        # Create base diagnostics
        diagnostics = BreakoutRangeDiagnostics(
            range_type="Asia Range",
            range_period_start=asia_config.start,
            range_period_end=asia_config.end,
            min_range_ticks=asia_config.min_range_ticks,
            max_range_ticks=asia_config.max_range_ticks,
            min_breakout_body_fraction=asia_config.min_breakout_body_fraction,
            require_volume_spike=asia_config.require_volume_spike,
            require_clean_range=asia_config.require_clean_range,
            tick_size=self.config.tick_size,
        )
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        diagnostics.current_phase = phase
        
        # Get Asia range data
        asia_range = self.market_state.get_asia_range(epic)
        if asia_range is None:
            diagnostics.range_validation = RangeValidation.NOT_AVAILABLE
            diagnostics.diagnostic_message = "No Asia Range data available"
            diagnostics.detailed_explanation = (
                "The Asia Range data is not available. This could be because:\n"
                "- The worker has not been running long enough to capture the range\n"
                "- No market data was available during the Asia session (00:00-08:00 UTC)\n"
                "- The market was closed during the Asia session"
            )
            return diagnostics
        
        range_high, range_low = asia_range
        range_height = range_high - range_low
        
        # Calculate ticks, ensuring tick_size is valid to avoid division by zero
        tick_size = self.config.tick_size if self.config.tick_size > 0 else 0.01
        range_height_ticks = int(range_height / tick_size)
        
        diagnostics.range_high = range_high
        diagnostics.range_low = range_low
        diagnostics.range_height = range_height
        diagnostics.range_height_ticks = range_height_ticks
        
        # Get candles for count
        candles = self.market_state.get_recent_candles(epic, '1m', 500)
        diagnostics.candle_count = len(candles) if candles else 0
        
        # Get ATR
        atr = self.market_state.get_atr(epic, '1h', 14)
        diagnostics.atr = atr
        
        # Validate range size
        diagnostics = self._validate_range(diagnostics, range_height_ticks, asia_config)
        
        # Analyze current price position
        if current_price is not None:
            diagnostics = self._analyze_price_position(
                diagnostics, current_price, range_high, range_low
            )
            
            # Analyze breakout status based on latest candle
            if candles:
                diagnostics = self._analyze_breakout_status(
                    diagnostics, candles[-1], range_high, range_low, range_height, asia_config
                )
        
        # Generate diagnostic message
        diagnostics = self._generate_diagnostic_message(diagnostics, phase)
        
        return diagnostics

    def get_pre_us_range_diagnostics(
        self,
        epic: str,
        ts: datetime,
        current_price: Optional[float] = None
    ) -> BreakoutRangeDiagnostics:
        """
        Get diagnostic information for Pre-US Range.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            current_price: Current market price (if available).
            
        Returns:
            BreakoutRangeDiagnostics with Pre-US Range analysis.
        """
        us_config = self.config.breakout.us_core
        
        # Create base diagnostics
        diagnostics = BreakoutRangeDiagnostics(
            range_type="Pre-US Range",
            range_period_start=us_config.pre_us_start,
            range_period_end=us_config.pre_us_end,
            min_range_ticks=us_config.min_range_ticks,
            max_range_ticks=us_config.max_range_ticks,
            min_breakout_body_fraction=us_config.min_breakout_body_fraction,
            require_volume_spike=us_config.require_volume_spike,
            require_clean_range=us_config.require_clean_range,
            tick_size=self.config.tick_size,
        )
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        diagnostics.current_phase = phase
        
        # Get Pre-US range data
        pre_us_range = self.market_state.get_pre_us_range(epic)
        if pre_us_range is None:
            diagnostics.range_validation = RangeValidation.NOT_AVAILABLE
            diagnostics.diagnostic_message = "No Pre-US Range data available"
            diagnostics.detailed_explanation = (
                "The Pre-US Range data is not available. This could be because:\n"
                "- The worker has not been running long enough to capture the range\n"
                "- No market data was available during the Pre-US session\n"
                "- The market was closed during the Pre-US session"
            )
            return diagnostics
        
        range_high, range_low = pre_us_range
        range_height = range_high - range_low
        
        # Calculate ticks, ensuring tick_size is valid to avoid division by zero
        tick_size = self.config.tick_size if self.config.tick_size > 0 else 0.01
        range_height_ticks = int(range_height / tick_size)
        
        diagnostics.range_high = range_high
        diagnostics.range_low = range_low
        diagnostics.range_height = range_height
        diagnostics.range_height_ticks = range_height_ticks
        
        # Get candles for count
        candles = self.market_state.get_recent_candles(epic, '1m', 500)
        diagnostics.candle_count = len(candles) if candles else 0
        
        # Get ATR
        atr = self.market_state.get_atr(epic, '1h', 14)
        diagnostics.atr = atr
        
        # Validate range size
        diagnostics = self._validate_range(diagnostics, range_height_ticks, us_config)
        
        # Analyze current price position
        if current_price is not None:
            diagnostics = self._analyze_price_position(
                diagnostics, current_price, range_high, range_low
            )
            
            # Analyze breakout status based on latest candle
            if candles:
                diagnostics = self._analyze_breakout_status(
                    diagnostics, candles[-1], range_high, range_low, range_height, us_config
                )
        
        # Generate diagnostic message
        diagnostics = self._generate_diagnostic_message(diagnostics, phase)
        
        return diagnostics

    def get_london_core_range_diagnostics(
        self,
        epic: str,
        ts: datetime,
        current_price: Optional[float] = None
    ) -> BreakoutRangeDiagnostics:
        """
        Get diagnostic information for London Core Range.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            current_price: Current market price (if available).
            
        Returns:
            BreakoutRangeDiagnostics with London Core Range analysis.
        """
        london_config = self.config.breakout.london_core
        
        # Create base diagnostics
        diagnostics = BreakoutRangeDiagnostics(
            range_type="London Core",
            range_period_start=london_config.start,
            range_period_end=london_config.end,
            min_range_ticks=london_config.min_range_ticks,
            max_range_ticks=london_config.max_range_ticks,
            min_breakout_body_fraction=london_config.min_breakout_body_fraction,
            require_volume_spike=london_config.require_volume_spike,
            require_clean_range=london_config.require_clean_range,
            tick_size=self.config.tick_size,
        )
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        diagnostics.current_phase = phase
        
        # Get London Core range data
        london_range = self.market_state.get_london_core_range(epic)
        if london_range is None:
            diagnostics.range_validation = RangeValidation.NOT_AVAILABLE
            diagnostics.diagnostic_message = "No London Core Range data available"
            diagnostics.detailed_explanation = (
                "The London Core Range data is not available. This could be because:\n"
                "- The worker has not been running long enough to capture the range\n"
                "- No market data was available during the London Core session (08:00-12:00 UTC)\n"
                "- The market was closed during the London Core session"
            )
            return diagnostics
        
        range_high, range_low = london_range
        range_height = range_high - range_low
        
        # Calculate ticks, ensuring tick_size is valid to avoid division by zero
        tick_size = self.config.tick_size if self.config.tick_size > 0 else 0.01
        range_height_ticks = int(range_height / tick_size)
        
        diagnostics.range_high = range_high
        diagnostics.range_low = range_low
        diagnostics.range_height = range_height
        diagnostics.range_height_ticks = range_height_ticks
        
        # Get candles for count
        candles = self.market_state.get_recent_candles(epic, '1m', 500)
        diagnostics.candle_count = len(candles) if candles else 0
        
        # Get ATR
        atr = self.market_state.get_atr(epic, '1h', 14)
        diagnostics.atr = atr
        
        # Validate range size
        diagnostics = self._validate_range(diagnostics, range_height_ticks, london_config)
        
        # Analyze current price position
        if current_price is not None:
            diagnostics = self._analyze_price_position(
                diagnostics, current_price, range_high, range_low
            )
            
            # Analyze breakout status based on latest candle
            if candles:
                diagnostics = self._analyze_breakout_status(
                    diagnostics, candles[-1], range_high, range_low, range_height, london_config
                )
        
        # Generate diagnostic message
        diagnostics = self._generate_diagnostic_message(diagnostics, phase)
        
        return diagnostics

    def get_us_core_trading_diagnostics(
        self,
        epic: str,
        ts: datetime,
        current_price: Optional[float] = None
    ) -> BreakoutRangeDiagnostics:
        """
        Get diagnostic information for US Core Trading session.
        
        US Core Trading uses the Pre-US Range for breakouts, so this method
        returns diagnostics based on the Pre-US Range with additional context
        about the trading session.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            current_price: Current market price (if available).
            
        Returns:
            BreakoutRangeDiagnostics with US Core Trading session analysis.
        """
        us_config = self.config.breakout.us_core
        
        # Create base diagnostics
        diagnostics = BreakoutRangeDiagnostics(
            range_type="US Core Trading",
            range_period_start=us_config.us_core_trading_start,
            range_period_end=us_config.us_core_trading_end,
            min_range_ticks=us_config.min_range_ticks,
            max_range_ticks=us_config.max_range_ticks,
            min_breakout_body_fraction=us_config.min_breakout_body_fraction,
            require_volume_spike=us_config.require_volume_spike,
            require_clean_range=us_config.require_clean_range,
            tick_size=self.config.tick_size,
        )
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        diagnostics.current_phase = phase
        
        # US Core Trading uses Pre-US Range for breakouts
        pre_us_range = self.market_state.get_pre_us_range(epic)
        if pre_us_range is None:
            diagnostics.range_validation = RangeValidation.NOT_AVAILABLE
            diagnostics.diagnostic_message = "No Pre-US Range data available for US Core Trading"
            diagnostics.detailed_explanation = (
                "The US Core Trading session uses the Pre-US Range (13:00-15:00 UTC) for breakouts.\n"
                "The Pre-US Range data is not available. This could be because:\n"
                "- The worker has not been running long enough to capture the Pre-US Range\n"
                "- No market data was available during the Pre-US session\n"
                "- The market was closed during the Pre-US session"
            )
            return diagnostics
        
        range_high, range_low = pre_us_range
        range_height = range_high - range_low
        
        # Calculate ticks, ensuring tick_size is valid to avoid division by zero
        tick_size = self.config.tick_size if self.config.tick_size > 0 else 0.01
        range_height_ticks = int(range_height / tick_size)
        
        diagnostics.range_high = range_high
        diagnostics.range_low = range_low
        diagnostics.range_height = range_height
        diagnostics.range_height_ticks = range_height_ticks
        
        # Get candles for count
        candles = self.market_state.get_recent_candles(epic, '1m', 500)
        diagnostics.candle_count = len(candles) if candles else 0
        
        # Get ATR
        atr = self.market_state.get_atr(epic, '1h', 14)
        diagnostics.atr = atr
        
        # Validate range size
        diagnostics = self._validate_range(diagnostics, range_height_ticks, us_config)
        
        # Analyze current price position
        if current_price is not None:
            diagnostics = self._analyze_price_position(
                diagnostics, current_price, range_high, range_low
            )
            
            # Analyze breakout status based on latest candle
            if candles:
                diagnostics = self._analyze_breakout_status(
                    diagnostics, candles[-1], range_high, range_low, range_height, us_config
                )
        
        # Generate diagnostic message with US Core Trading context
        diagnostics = self._generate_diagnostic_message(diagnostics, phase)
        
        return diagnostics

    def get_all_phase_diagnostics(
        self,
        epic: str,
        ts: datetime,
        current_price: Optional[float] = None
    ) -> dict[str, BreakoutRangeDiagnostics]:
        """
        Get diagnostic information for all phases.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            current_price: Current market price (if available).
            
        Returns:
            Dictionary mapping phase names to BreakoutRangeDiagnostics.
        """
        return {
            'ASIA_RANGE': self.get_asia_range_diagnostics(epic, ts, current_price),
            'LONDON_CORE': self.get_london_core_range_diagnostics(epic, ts, current_price),
            'PRE_US_RANGE': self.get_pre_us_range_diagnostics(epic, ts, current_price),
            'US_CORE_TRADING': self.get_us_core_trading_diagnostics(epic, ts, current_price),
        }

    def _validate_range(
        self,
        diagnostics: BreakoutRangeDiagnostics,
        range_height_ticks: int,
        config
    ) -> BreakoutRangeDiagnostics:
        """Validate range size against configuration."""
        if range_height_ticks < config.min_range_ticks:
            diagnostics.range_validation = RangeValidation.TOO_SMALL
        elif range_height_ticks > config.max_range_ticks:
            diagnostics.range_validation = RangeValidation.TOO_LARGE
        else:
            diagnostics.range_validation = RangeValidation.VALID
        return diagnostics

    def _analyze_price_position(
        self,
        diagnostics: BreakoutRangeDiagnostics,
        current_price: float,
        range_high: float,
        range_low: float
    ) -> BreakoutRangeDiagnostics:
        """Analyze current price position relative to range."""
        diagnostics.current_price = current_price
        diagnostics.distance_to_high = range_high - current_price
        diagnostics.distance_to_low = current_price - range_low
        
        if current_price > range_high:
            diagnostics.price_position = PricePosition.ABOVE
        elif current_price < range_low:
            diagnostics.price_position = PricePosition.BELOW
        else:
            diagnostics.price_position = PricePosition.INSIDE
        
        return diagnostics

    def _analyze_breakout_status(
        self,
        diagnostics: BreakoutRangeDiagnostics,
        latest_candle: Candle,
        range_high: float,
        range_low: float,
        range_height: float,
        config
    ) -> BreakoutRangeDiagnostics:
        """Analyze breakout status based on latest candle."""
        if diagnostics.range_validation != RangeValidation.VALID:
            diagnostics.breakout_status = BreakoutStatus.NO_BREAKOUT
            return diagnostics
        
        # Check for potential or valid breakout
        min_body = range_height * config.min_breakout_body_fraction
        
        if latest_candle.close > range_high:
            diagnostics.potential_direction = "LONG"
            if latest_candle.is_bullish and latest_candle.body_size >= min_body:
                diagnostics.breakout_status = BreakoutStatus.VALID_BREAKOUT
            else:
                diagnostics.breakout_status = BreakoutStatus.POTENTIAL_BREAKOUT
        elif latest_candle.close < range_low:
            diagnostics.potential_direction = "SHORT"
            if latest_candle.is_bearish and latest_candle.body_size >= min_body:
                diagnostics.breakout_status = BreakoutStatus.VALID_BREAKOUT
            else:
                diagnostics.breakout_status = BreakoutStatus.POTENTIAL_BREAKOUT
        else:
            diagnostics.breakout_status = BreakoutStatus.NO_BREAKOUT
        
        return diagnostics

    def _generate_diagnostic_message(
        self,
        diagnostics: BreakoutRangeDiagnostics,
        phase: SessionPhase
    ) -> BreakoutRangeDiagnostics:
        """Generate human-readable diagnostic messages."""
        messages = []
        explanations = []
        
        # Check range availability
        if diagnostics.range_validation == RangeValidation.NOT_AVAILABLE:
            return diagnostics  # Already has message set
        
        # Check range size
        if diagnostics.range_validation == RangeValidation.TOO_SMALL:
            messages.append(
                f"Range height ({diagnostics.range_height_ticks} ticks) "
                f"below min_range_ticks ({diagnostics.min_range_ticks})"
            )
            explanations.append(
                f"The {diagnostics.range_type} is too narrow. "
                f"Current range: {diagnostics.range_height_ticks} ticks, "
                f"minimum required: {diagnostics.min_range_ticks} ticks."
            )
        elif diagnostics.range_validation == RangeValidation.TOO_LARGE:
            messages.append(
                f"Range height ({diagnostics.range_height_ticks} ticks) "
                f"exceeds max_range_ticks ({diagnostics.max_range_ticks})"
            )
            explanations.append(
                f"The {diagnostics.range_type} is too wide. "
                f"Current range: {diagnostics.range_height_ticks} ticks, "
                f"maximum allowed: {diagnostics.max_range_ticks} ticks."
            )
        else:
            messages.append("Range valid")
            explanations.append(
                f"{diagnostics.range_type} is valid with {diagnostics.range_height_ticks} ticks "
                f"(min: {diagnostics.min_range_ticks}, max: {diagnostics.max_range_ticks})."
            )
        
        # Check price position
        if diagnostics.current_price is not None:
            if diagnostics.price_position == PricePosition.INSIDE:
                messages.append(
                    f"Current price ({diagnostics.current_price:.2f}) inside range "
                    f"({diagnostics.range_low:.2f}–{diagnostics.range_high:.2f})"
                )
                explanations.append(
                    f"Price is still within the range. "
                    f"Distance to high: {diagnostics.distance_to_high:.2f}, "
                    f"distance to low: {diagnostics.distance_to_low:.2f}."
                )
            elif diagnostics.price_position == PricePosition.ABOVE:
                messages.append(
                    f"Current price ({diagnostics.current_price:.2f}) above range high "
                    f"({diagnostics.range_high:.2f})"
                )
                explanations.append(
                    f"Price has broken above the range high. "
                    f"Potential LONG breakout."
                )
            else:
                messages.append(
                    f"Current price ({diagnostics.current_price:.2f}) below range low "
                    f"({diagnostics.range_low:.2f})"
                )
                explanations.append(
                    f"Price has broken below the range low. "
                    f"Potential SHORT breakout."
                )
        
        # Check breakout status
        if diagnostics.breakout_status == BreakoutStatus.NO_BREAKOUT:
            if diagnostics.range_validation == RangeValidation.VALID:
                messages.append("No breakout detected")
                explanations.append(
                    "No valid breakout candle detected. "
                    "Waiting for price to break out of the range with a strong candle."
                )
        elif diagnostics.breakout_status == BreakoutStatus.POTENTIAL_BREAKOUT:
            messages.append(
                f"Potential {diagnostics.potential_direction} breakout, "
                "but candle body too small"
            )
            explanations.append(
                f"Price has crossed the range boundary, but the breakout candle's body "
                f"is smaller than the required {diagnostics.min_breakout_body_fraction * 100:.0f}% "
                f"of the range height."
            )
        elif diagnostics.breakout_status == BreakoutStatus.VALID_BREAKOUT:
            messages.append(f"Valid {diagnostics.potential_direction} breakout!")
            explanations.append(
                f"A valid {diagnostics.potential_direction} breakout has been detected. "
                f"The breakout candle has sufficient body size."
            )
        
        # Check phase suitability
        if diagnostics.range_type == "Asia Range" and phase != SessionPhase.LONDON_CORE:
            messages.append(f"Current phase ({phase.value}) not suitable for Asia breakout")
            explanations.append(
                f"Asia Range breakouts are evaluated during LONDON_CORE phase, "
                f"but current phase is {phase.value}."
            )
        elif diagnostics.range_type == "London Core" and phase != SessionPhase.PRE_US_RANGE:
            # London Core range is used for reference but typically not for direct breakouts
            messages.append(f"Current phase: {phase.value}")
            explanations.append(
                f"London Core Range data is available for reference. "
                f"Current phase is {phase.value}."
            )
        elif diagnostics.range_type == "Pre-US Range" and phase not in (SessionPhase.US_CORE_TRADING, SessionPhase.US_CORE):
            messages.append(f"Current phase ({phase.value}) not suitable for Pre-US breakout")
            explanations.append(
                f"Pre-US Range breakouts are evaluated during US_CORE_TRADING phase, "
                f"but current phase is {phase.value}."
            )
        elif diagnostics.range_type == "US Core Trading" and phase != SessionPhase.US_CORE_TRADING:
            messages.append(f"Current phase ({phase.value}) not suitable for US Core Trading")
            explanations.append(
                f"US Core Trading uses Pre-US Range for breakouts. "
                f"This is evaluated during US_CORE_TRADING phase (15:00-22:00 UTC), "
                f"but current phase is {phase.value}."
            )
        
        diagnostics.diagnostic_message = "; ".join(messages)
        diagnostics.detailed_explanation = "\n".join(explanations)
        
        return diagnostics
