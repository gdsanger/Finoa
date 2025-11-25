"""
Strategy Engine for Fiona.

Analyzes market data and generates SetupCandidate objects for potential trades.
Does NOT make trading decisions or place orders.
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from .config import StrategyConfig
from .models import (
    BreakoutContext,
    Candle,
    EiaContext,
    SessionPhase,
    SetupCandidate,
    SetupKind,
)
from .providers import MarketStateProvider


class StrategyEngine:
    """
    Strategy Engine that analyzes market state and generates setup candidates.
    
    The engine evaluates market conditions and identifies potential trading
    setups based on breakout and EIA strategies. It does NOT make decisions
    about whether to trade or place orders.
    
    Attributes:
        market_state: Provider for market data and state.
        config: Strategy configuration parameters.
    """

    def __init__(
        self,
        market_state: MarketStateProvider,
        config: Optional[StrategyConfig] = None
    ) -> None:
        """
        Initialize the Strategy Engine.
        
        Args:
            market_state: Market state provider for data access.
            config: Strategy configuration (uses defaults if not provided).
        """
        self.market_state = market_state
        self.config = config or StrategyConfig()

    def evaluate(self, epic: str, ts: datetime) -> list[SetupCandidate]:
        """
        Analyze the current market state and generate setup candidates.
        
        Args:
            epic: Market identifier to analyze.
            ts: Timestamp for evaluation.
            
        Returns:
            List of SetupCandidate objects (0 to N candidates).
        """
        candidates: list[SetupCandidate] = []
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        
        # Evaluate breakout strategies based on phase
        if phase == SessionPhase.LONDON_CORE:
            breakout_candidates = self._evaluate_asia_breakout(epic, ts, phase)
            candidates.extend(breakout_candidates)
        
        if phase == SessionPhase.US_CORE:
            breakout_candidates = self._evaluate_us_breakout(epic, ts, phase)
            candidates.extend(breakout_candidates)
        
        # Evaluate EIA strategies
        if phase == SessionPhase.EIA_POST:
            eia_candidates = self._evaluate_eia_setups(epic, ts, phase)
            candidates.extend(eia_candidates)
        
        # Filter duplicates and invalid setups
        candidates = self._filter_candidates(candidates)
        
        return candidates

    def _evaluate_asia_breakout(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase
    ) -> list[SetupCandidate]:
        """
        Evaluate Asia Range breakout during London session.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.
            
        Returns:
            List of breakout SetupCandidate objects.
        """
        candidates: list[SetupCandidate] = []
        
        # Get Asia range
        asia_range = self.market_state.get_asia_range(epic)
        if not asia_range:
            return candidates
        
        range_high, range_low = asia_range
        range_height = range_high - range_low
        
        # Check range size constraints
        if not self._is_valid_range(range_height, self.config.breakout.asia_range):
            return candidates
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        if not candles:
            return candidates
        
        # Check for breakout
        latest_candle = candles[-1]
        
        # Long breakout: close above Asia high
        if latest_candle.close > range_high:
            if self._is_valid_breakout_candle(latest_candle, range_height, 'LONG', self.config.breakout.asia_range.min_breakout_body_fraction):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction='LONG',
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                )
                candidates.append(candidate)
        
        # Short breakout: close below Asia low
        if latest_candle.close < range_low:
            if self._is_valid_breakout_candle(latest_candle, range_height, 'SHORT', self.config.breakout.asia_range.min_breakout_body_fraction):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction='SHORT',
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                )
                candidates.append(candidate)
        
        return candidates

    def _evaluate_us_breakout(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase
    ) -> list[SetupCandidate]:
        """
        Evaluate Pre-US Range breakout during US Core session.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.
            
        Returns:
            List of breakout SetupCandidate objects.
        """
        candidates: list[SetupCandidate] = []
        
        # Get pre-US range
        pre_us_range = self.market_state.get_pre_us_range(epic)
        if not pre_us_range:
            return candidates
        
        range_high, range_low = pre_us_range
        range_height = range_high - range_low
        
        # Check range size constraints
        if not self._is_valid_range(range_height, self.config.breakout.us_core):
            return candidates
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        if not candles:
            return candidates
        
        # Check for breakout
        latest_candle = candles[-1]
        
        # Long breakout: close above range high
        if latest_candle.close > range_high:
            if self._is_valid_breakout_candle(latest_candle, range_height, 'LONG', self.config.breakout.us_core.min_breakout_body_fraction):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction='LONG',
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                )
                candidates.append(candidate)
        
        # Short breakout: close below range low
        if latest_candle.close < range_low:
            if self._is_valid_breakout_candle(latest_candle, range_height, 'SHORT', self.config.breakout.us_core.min_breakout_body_fraction):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction='SHORT',
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                )
                candidates.append(candidate)
        
        return candidates

    def _evaluate_eia_setups(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase
    ) -> list[SetupCandidate]:
        """
        Evaluate EIA setups (reversion and trend day).
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.
            
        Returns:
            List of EIA SetupCandidate objects.
        """
        candidates: list[SetupCandidate] = []
        
        # Get EIA timestamp
        eia_timestamp = self.market_state.get_eia_timestamp()
        if not eia_timestamp:
            return candidates
        
        # Get candles since EIA release
        # We fetch impulse_window + 5 extra candles to analyze follow-through
        # after the initial impulse period
        candles = self.market_state.get_recent_candles(
            epic,
            '1m',
            self.config.eia.impulse_window_minutes + 5
        )
        if not candles or len(candles) < self.config.eia.impulse_window_minutes:
            return candidates
        
        # Analyze impulse from the candles
        impulse_candles = candles[:self.config.eia.impulse_window_minutes]
        impulse_direction, impulse_high, impulse_low = self._analyze_impulse(impulse_candles)
        
        if not impulse_direction:
            return candidates
        
        impulse_range = impulse_high - impulse_low
        
        # Check for EIA Reversion
        reversion_candidate = self._check_eia_reversion(
            epic=epic,
            ts=ts,
            phase=phase,
            eia_timestamp=eia_timestamp,
            impulse_direction=impulse_direction,
            impulse_high=impulse_high,
            impulse_low=impulse_low,
            impulse_range=impulse_range,
            recent_candles=candles[self.config.eia.impulse_window_minutes:],
        )
        if reversion_candidate:
            candidates.append(reversion_candidate)
        
        # Check for EIA Trend Day
        trendday_candidate = self._check_eia_trendday(
            epic=epic,
            ts=ts,
            phase=phase,
            eia_timestamp=eia_timestamp,
            impulse_direction=impulse_direction,
            impulse_high=impulse_high,
            impulse_low=impulse_low,
            recent_candles=candles[self.config.eia.impulse_window_minutes:],
        )
        if trendday_candidate:
            candidates.append(trendday_candidate)
        
        return candidates

    def _analyze_impulse(
        self,
        candles: list[Candle]
    ) -> tuple[Optional[Literal["LONG", "SHORT"]], float, float]:
        """
        Analyze the initial impulse direction and range.
        
        Args:
            candles: Candles to analyze.
            
        Returns:
            Tuple of (direction, high, low) or (None, 0, 0) if no clear impulse.
        """
        if not candles:
            return None, 0.0, 0.0
        
        first_open = candles[0].open
        last_close = candles[-1].close
        
        high = max(c.high for c in candles)
        low = min(c.low for c in candles)
        
        # Determine direction based on net movement
        # Use tick_size as minimum threshold for significant movement
        net_move = last_close - first_open
        min_movement = self.config.tick_size if hasattr(self, 'config') else 0.001
        
        if abs(net_move) < min_movement:
            return None, high, low
        
        direction: Literal["LONG", "SHORT"] = "LONG" if net_move > 0 else "SHORT"
        
        return direction, high, low

    def _check_eia_reversion(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        eia_timestamp: datetime,
        impulse_direction: Literal["LONG", "SHORT"],
        impulse_high: float,
        impulse_low: float,
        impulse_range: float,
        recent_candles: list[Candle],
    ) -> Optional[SetupCandidate]:
        """
        Check for EIA reversion setup.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.
            eia_timestamp: EIA release timestamp.
            impulse_direction: Direction of initial impulse.
            impulse_high: High of impulse range.
            impulse_low: Low of impulse range.
            impulse_range: Size of impulse range.
            recent_candles: Candles after impulse window.
            
        Returns:
            SetupCandidate if reversion detected, None otherwise.
        """
        if not recent_candles or impulse_range < 0.001:
            return None
        
        min_retrace = self.config.eia.reversion_min_retrace_fraction * impulse_range
        
        # Check if price has retraced significantly
        latest_candle = recent_candles[-1]
        
        if impulse_direction == "LONG":
            # For long impulse, reversion means price comes back down
            retrace = impulse_high - latest_candle.close
            if retrace >= min_retrace and latest_candle.is_bearish:
                # Reversion detected - SHORT setup
                return self._create_eia_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    setup_kind=SetupKind.EIA_REVERSION,
                    direction="SHORT",
                    eia_timestamp=eia_timestamp,
                    impulse_direction=impulse_direction,
                    impulse_high=impulse_high,
                    impulse_low=impulse_low,
                    reference_price=latest_candle.close,
                )
        else:  # SHORT impulse
            # For short impulse, reversion means price comes back up
            retrace = latest_candle.close - impulse_low
            if retrace >= min_retrace and latest_candle.is_bullish:
                # Reversion detected - LONG setup
                return self._create_eia_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    setup_kind=SetupKind.EIA_REVERSION,
                    direction="LONG",
                    eia_timestamp=eia_timestamp,
                    impulse_direction=impulse_direction,
                    impulse_high=impulse_high,
                    impulse_low=impulse_low,
                    reference_price=latest_candle.close,
                )
        
        return None

    def _check_eia_trendday(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        eia_timestamp: datetime,
        impulse_direction: Literal["LONG", "SHORT"],
        impulse_high: float,
        impulse_low: float,
        recent_candles: list[Candle],
    ) -> Optional[SetupCandidate]:
        """
        Check for EIA trend day setup.
        
        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.
            eia_timestamp: EIA release timestamp.
            impulse_direction: Direction of initial impulse.
            impulse_high: High of impulse range.
            impulse_low: Low of impulse range.
            recent_candles: Candles after impulse window.
            
        Returns:
            SetupCandidate if trend day pattern detected, None otherwise.
        """
        min_follow_candles = self.config.eia.trend_min_follow_candles
        
        if len(recent_candles) < min_follow_candles:
            return None
        
        # Check for continuation pattern
        follow_candles = recent_candles[:min_follow_candles]
        
        if impulse_direction == "LONG":
            # Check for higher highs and higher lows
            if self._is_higher_highs_lows(follow_candles):
                return self._create_eia_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    setup_kind=SetupKind.EIA_TRENDDAY,
                    direction="LONG",
                    eia_timestamp=eia_timestamp,
                    impulse_direction=impulse_direction,
                    impulse_high=impulse_high,
                    impulse_low=impulse_low,
                    reference_price=recent_candles[-1].close,
                )
        else:  # SHORT impulse
            # Check for lower lows and lower highs
            if self._is_lower_lows_highs(follow_candles):
                return self._create_eia_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    setup_kind=SetupKind.EIA_TRENDDAY,
                    direction="SHORT",
                    eia_timestamp=eia_timestamp,
                    impulse_direction=impulse_direction,
                    impulse_high=impulse_high,
                    impulse_low=impulse_low,
                    reference_price=recent_candles[-1].close,
                )
        
        return None

    def _is_higher_highs_lows(self, candles: list[Candle]) -> bool:
        """Check if candles form higher highs and higher lows pattern."""
        if len(candles) < 2:
            return False
        
        for i in range(1, len(candles)):
            if candles[i].high <= candles[i-1].high:
                return False
            if candles[i].low <= candles[i-1].low:
                return False
        
        return True

    def _is_lower_lows_highs(self, candles: list[Candle]) -> bool:
        """Check if candles form lower lows and lower highs pattern."""
        if len(candles) < 2:
            return False
        
        for i in range(1, len(candles)):
            if candles[i].high >= candles[i-1].high:
                return False
            if candles[i].low >= candles[i-1].low:
                return False
        
        return True

    def _is_valid_range(self, range_height: float, config) -> bool:
        """Check if range height is within valid bounds."""
        ticks = range_height / self.config.tick_size
        return config.min_range_ticks <= ticks <= config.max_range_ticks

    def _is_valid_breakout_candle(
        self,
        candle: Candle,
        range_height: float,
        direction: Literal["LONG", "SHORT"],
        min_body_fraction: float
    ) -> bool:
        """
        Check if candle is a valid breakout candle.
        
        Args:
            candle: The candle to check.
            range_height: Height of the range being broken.
            direction: Expected breakout direction.
            min_body_fraction: Minimum body size as fraction of range.
            
        Returns:
            True if valid breakout candle, False otherwise.
        """
        # Check direction matches candle
        if direction == "LONG" and candle.is_bearish:
            return False
        if direction == "SHORT" and candle.is_bullish:
            return False
        
        # Check body size
        min_body = range_height * min_body_fraction
        return candle.body_size >= min_body

    def _create_breakout_candidate(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        direction: Literal["LONG", "SHORT"],
        range_high: float,
        range_low: float,
        trigger_price: float,
    ) -> SetupCandidate:
        """Create a breakout SetupCandidate."""
        atr = self.market_state.get_atr(epic, '1h', 14)
        
        breakout_context = BreakoutContext(
            range_high=range_high,
            range_low=range_low,
            range_height=range_high - range_low,
            trigger_price=trigger_price,
            direction=direction,
            atr=atr,
        )
        
        return SetupCandidate(
            id=str(uuid.uuid4()),
            created_at=ts,
            epic=epic,
            setup_kind=SetupKind.BREAKOUT,
            phase=phase,
            reference_price=trigger_price,
            direction=direction,
            breakout=breakout_context,
            eia=None,
            quality_flags={
                'clean_range': True,
                'strong_close': True,
            },
        )

    def _create_eia_candidate(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        setup_kind: SetupKind,
        direction: Literal["LONG", "SHORT"],
        eia_timestamp: datetime,
        impulse_direction: Literal["LONG", "SHORT"],
        impulse_high: float,
        impulse_low: float,
        reference_price: float,
    ) -> SetupCandidate:
        """Create an EIA SetupCandidate."""
        atr = self.market_state.get_atr(epic, '1h', 14)
        
        eia_context = EiaContext(
            eia_timestamp=eia_timestamp,
            first_impulse_direction=impulse_direction,
            impulse_range_high=impulse_high,
            impulse_range_low=impulse_low,
            atr=atr,
        )
        
        return SetupCandidate(
            id=str(uuid.uuid4()),
            created_at=ts,
            epic=epic,
            setup_kind=setup_kind,
            phase=phase,
            reference_price=reference_price,
            direction=direction,
            breakout=None,
            eia=eia_context,
            quality_flags={
                'impulse_clear': True,
            },
        )

    def _filter_candidates(
        self,
        candidates: list[SetupCandidate]
    ) -> list[SetupCandidate]:
        """
        Filter and deduplicate setup candidates.
        
        Args:
            candidates: List of candidates to filter.
            
        Returns:
            Filtered list of valid candidates.
        """
        # Remove duplicates based on setup_kind and direction
        seen = set()
        filtered = []
        
        for candidate in candidates:
            key = (candidate.setup_kind, candidate.direction)
            if key not in seen:
                seen.add(key)
                filtered.append(candidate)
        
        return filtered
