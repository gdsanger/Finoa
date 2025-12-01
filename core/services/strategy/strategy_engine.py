"""
Strategy Engine for Fiona.

Analyzes market data and generates SetupCandidate objects for potential trades.
Does NOT make trading decisions or place orders.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from .config import StrategyConfig
from .models import (
    BreakoutContext,
    BreakoutSignal,
    Candle,
    EiaContext,
    SessionPhase,
    SetupCandidate,
    SetupKind,
)
from .providers import MarketStateProvider


logger = logging.getLogger(__name__)


@dataclass
class DiagnosticCriterion:
    """A single diagnostic criterion with pass/fail status."""
    name: str
    passed: bool
    detail: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class EvaluationResult:
    """Result of strategy evaluation including diagnostics."""
    setups: list[SetupCandidate] = field(default_factory=list)
    criteria: list[DiagnosticCriterion] = field(default_factory=list)
    summary: str = ""
    
    def to_criteria_list(self) -> list[dict]:
        """Convert criteria to list of dicts for JSON serialization."""
        return [c.to_dict() for c in self.criteria]


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
        self.last_status_message: Optional[str] = None
        # Collects all status messages for the current evaluation run.
        self._status_history: list[str] = []

    def _set_status(self, message: str) -> None:
        """Record the latest status message for external consumers."""
        self.last_status_message = message
        self._status_history.append(message)

    def _is_phase_tradeable(self, phase: SessionPhase) -> tuple[bool, list[str]]:
        """Determine if the given phase is tradeable for the current asset."""
        tradeable_phases = [
            SessionPhase.LONDON_CORE,
            SessionPhase.US_CORE_TRADING,
            SessionPhase.US_CORE,
            SessionPhase.EIA_POST,
        ]

        phase_tradeable = phase in tradeable_phases
        try:
            if hasattr(self.market_state, "is_phase_tradeable"):
                phase_tradeable = bool(self.market_state.is_phase_tradeable(phase))
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug(
                "Failed to read asset-specific phase tradeability; using defaults", 
                extra={"strategy_data": {"phase": phase.value, "error": str(exc)}}
            )

        return phase_tradeable, tradeable_phases

    def evaluate(self, epic: str, ts: datetime) -> list[SetupCandidate]:
        """
        Analyze the current market state and generate setup candidates.
        
        Args:
            epic: Market identifier to analyze.
            ts: Timestamp for evaluation.
            
        Returns:
            List of SetupCandidate objects (0 to N candidates).
        """
        self.last_status_message = None
        self._status_history = []
        candidates: list[SetupCandidate] = []
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        
        # Get current price data for comprehensive logging
        candles = self.market_state.get_recent_candles(epic, '1m', 1, closed_only=True)
        current_price = candles[-1].close if candles else None
        
        # Get range data only for the relevant phase to avoid misleading log messages
        # According to the phase -> reference range mapping:
        # - LONDON_CORE uses ASIA_RANGE
        # - PRE_US_RANGE uses LONDON_CORE range
        # - US_CORE_TRADING / US_CORE uses PRE_US_RANGE
        # - Other phases don't need range data
        asia_range = None
        london_core_range = None
        pre_us_range = None
        
        if phase == SessionPhase.LONDON_CORE:
            # London Core trades based on Asia Range breakouts
            asia_range = self.market_state.get_asia_range(epic)
        elif phase == SessionPhase.PRE_US_RANGE:
            # Pre-US Range phase uses London Core range for reference
            london_core_range = self.market_state.get_london_core_range(epic)
        elif phase in (SessionPhase.US_CORE_TRADING, SessionPhase.US_CORE):
            # US Core Trading trades based on Pre-US Range breakouts
            pre_us_range = self.market_state.get_pre_us_range(epic)
        elif phase in (SessionPhase.EIA_PRE, SessionPhase.EIA_POST):
            # EIA phases may need both ranges for analysis
            asia_range = self.market_state.get_asia_range(epic)
            pre_us_range = self.market_state.get_pre_us_range(epic)
        
        logger.debug(
            "Strategy evaluation started",
            extra={
                "strategy_data": {
                    "epic": epic,
                    "timestamp": ts.isoformat(),
                    "phase": phase.value,
                    "current_price": current_price,
                    "asia_range_high": asia_range[0] if asia_range else None,
                    "asia_range_low": asia_range[1] if asia_range else None,
                    "london_core_range_high": london_core_range[0] if london_core_range else None,
                    "london_core_range_low": london_core_range[1] if london_core_range else None,
                    "pre_us_range_high": pre_us_range[0] if pre_us_range else None,
                    "pre_us_range_low": pre_us_range[1] if pre_us_range else None,
                }
            }
        )
        
        # Define tradeable phases for logging
        is_tradeable_phase, default_tradeable_phases = self._is_phase_tradeable(phase)
        
        # Log if phase is not tradeable with detailed market data
        if not is_tradeable_phase:
            self._set_status(f"Phase {phase.value} not tradeable - no breakout evaluation")
            # Still log the price position relative to ranges for analysis
            price_analysis = self._analyze_price_position(
                current_price, asia_range, pre_us_range, london_core_range
            )
            logger.debug(
                "Phase is not tradeable - no breakout evaluation performed",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "is_tradeable_phase": False,
                        "tradeable_phases": [p.value for p in default_tradeable_phases],
                        "current_price": current_price,
                        "asia_range_high": asia_range[0] if asia_range else None,
                        "asia_range_low": asia_range[1] if asia_range else None,
                        "london_core_range_high": london_core_range[0] if london_core_range else None,
                        "london_core_range_low": london_core_range[1] if london_core_range else None,
                        "pre_us_range_high": pre_us_range[0] if pre_us_range else None,
                        "pre_us_range_low": pre_us_range[1] if pre_us_range else None,
                        "price_analysis": price_analysis,
                        "reason": f"Phase {phase.value} is not in tradeable phases. "
                                  f"No breakout evaluation performed.",
                    }
                }
            )
            return candidates
        
        # Evaluate breakout strategies based on phase
        if phase == SessionPhase.LONDON_CORE:
            breakout_candidates = self._evaluate_asia_breakout(epic, ts, phase)
            candidates.extend(breakout_candidates)
        
        # US Core Trading - allows breakouts based on Pre-US Range
        if phase in (SessionPhase.US_CORE_TRADING, SessionPhase.PRE_US_RANGE):
            breakout_candidates = self._evaluate_us_breakout(epic, ts, phase)
            candidates.extend(breakout_candidates)
        
        # Deprecated US_CORE - kept for backwards compatibility
        if phase == SessionPhase.US_CORE:
            breakout_candidates = self._evaluate_us_breakout(epic, ts, phase)
            candidates.extend(breakout_candidates)
        
        # Evaluate EIA strategies
        if phase == SessionPhase.EIA_POST:
            eia_candidates = self._evaluate_eia_setups(epic, ts, phase)
            candidates.extend(eia_candidates)
        
        # Filter duplicates and invalid setups
        candidates = self._filter_candidates(candidates)
        
        # Log evaluation result
        if candidates:
            for candidate in candidates:
                logger.debug(
                    "Setup candidate generated",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "timestamp": ts.isoformat(),
                            "phase": phase.value,
                            "setup_kind": candidate.setup_kind.value,
                            "direction": candidate.direction,
                            "reference_price": candidate.reference_price,
                            "setup_id": candidate.id,
                        }
                    }
                )
        else:
            # Provide detailed reason for no setups
            if is_tradeable_phase:
                reason = f"Phase {phase.value} is tradeable but no valid setups found"
            else:
                reason = f"Phase {phase.value} is not a tradeable phase"

            price_analysis = self._analyze_price_position(
                current_price, asia_range, pre_us_range, london_core_range
            )

            status_trace = list(dict.fromkeys(self._status_history))
            # Append the phase-level summary to the trace for maximum clarity
            status_trace.append(reason)
            detailed_reason = "; ".join(status_trace)

            self._set_status(detailed_reason)
            logger.debug(
                "No setup candidates generated",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "is_tradeable_phase": is_tradeable_phase,
                        "current_price": current_price,
                        "asia_range_high": asia_range[0] if asia_range else None,
                        "asia_range_low": asia_range[1] if asia_range else None,
                        "london_core_range_high": london_core_range[0] if london_core_range else None,
                        "london_core_range_low": london_core_range[1] if london_core_range else None,
                        "pre_us_range_high": pre_us_range[0] if pre_us_range else None,
                        "pre_us_range_low": pre_us_range[1] if pre_us_range else None,
                        "price_analysis": price_analysis,
                        "reason": detailed_reason,
                        "status_trace": status_trace,
                    }
                }
            )
        
        return candidates
    
    def _analyze_price_position(
        self,
        current_price: Optional[float],
        asia_range: Optional[tuple[float, float]],
        pre_us_range: Optional[tuple[float, float]],
        london_core_range: Optional[tuple[float, float]] = None,
    ) -> dict:
        """
        Analyze current price position relative to ranges.
        
        Returns a dictionary with analysis of where price is relative to ranges,
        useful for debugging why setups may not be generated.
        """
        analysis = {
            "has_price": current_price is not None,
            "has_asia_range": asia_range is not None,
            "has_london_core_range": london_core_range is not None,
            "has_pre_us_range": pre_us_range is not None,
        }
        
        if current_price is not None and asia_range is not None:
            asia_high, asia_low = asia_range
            if current_price > asia_high:
                analysis["asia_position"] = "above_high"
                analysis["asia_breakout_potential"] = "LONG"
            elif current_price < asia_low:
                analysis["asia_position"] = "below_low"
                analysis["asia_breakout_potential"] = "SHORT"
            else:
                analysis["asia_position"] = "within_range"
                analysis["asia_breakout_potential"] = None
        
        if current_price is not None and london_core_range is not None:
            london_high, london_low = london_core_range
            if current_price > london_high:
                analysis["london_core_position"] = "above_high"
                analysis["london_core_breakout_potential"] = "LONG"
            elif current_price < london_low:
                analysis["london_core_position"] = "below_low"
                analysis["london_core_breakout_potential"] = "SHORT"
            else:
                analysis["london_core_position"] = "within_range"
                analysis["london_core_breakout_potential"] = None
        
        if current_price is not None and pre_us_range is not None:
            pre_us_high, pre_us_low = pre_us_range
            if current_price > pre_us_high:
                analysis["pre_us_position"] = "above_high"
                analysis["pre_us_breakout_potential"] = "LONG"
            elif current_price < pre_us_low:
                analysis["pre_us_position"] = "below_low"
                analysis["pre_us_breakout_potential"] = "SHORT"
            else:
                analysis["pre_us_position"] = "within_range"
                analysis["pre_us_breakout_potential"] = None
        
        return analysis

    def evaluate_with_diagnostics(self, epic: str, ts: datetime) -> EvaluationResult:
        """
        Analyze the current market state with detailed diagnostics.
        
        Returns both setup candidates and a list of criteria with pass/fail status,
        useful for UI display showing why setups were or were not found.
        
        Args:
            epic: Market identifier to analyze.
            ts: Timestamp for evaluation.
            
        Returns:
            EvaluationResult with setups and diagnostic criteria.
        """
        self.last_status_message = None
        self._status_history = []
        result = EvaluationResult()
        
        # Get current phase
        phase = self.market_state.get_phase(ts)
        result.criteria.append(DiagnosticCriterion(
            name="Session Phase",
            passed=True,  # Always passes, informational
            detail=f"Current phase: {phase.value}",
        ))
        
        # Check if phase is tradeable using provider (falls back to defaults)
        phase_tradeable, default_tradeable_phases = self._is_phase_tradeable(phase)

        result.criteria.append(DiagnosticCriterion(
            name="Phase is tradeable",
            passed=phase_tradeable,
            detail=(
                f"{phase.value} {'is' if phase_tradeable else 'is not'} a tradeable phase"
                if phase_tradeable or default_tradeable_phases else
                f"{phase.value} tradeability unknown"
            ),
        ))

        if not phase_tradeable:
            result.summary = f"Phase {phase.value} is not tradeable"
            self._set_status(result.summary)
            return result
        
        # Evaluate based on phase
        if phase == SessionPhase.LONDON_CORE:
            self._evaluate_asia_breakout_with_diagnostics(epic, ts, phase, result)
        elif phase in (SessionPhase.US_CORE_TRADING, SessionPhase.US_CORE, SessionPhase.PRE_US_RANGE):
            self._evaluate_us_breakout_with_diagnostics(epic, ts, phase, result)
        elif phase == SessionPhase.EIA_POST:
            self._evaluate_eia_with_diagnostics(epic, ts, phase, result)
        
        # Filter duplicates
        result.setups = self._filter_candidates(result.setups)
        
        # Set summary
        if result.setups:
            result.summary = f"Found {len(result.setups)} setup(s)"
            self._set_status(result.summary)
        else:
            # Find first failed criterion for summary
            failed = [c for c in result.criteria if not c.passed]
            if failed:
                result.summary = f"No setups: {failed[-1].name}"
            else:
                result.summary = "No setups found"
            self._set_status(result.summary)

        return result

    def _evaluate_asia_breakout_with_diagnostics(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        result: EvaluationResult,
    ) -> None:
        """Evaluate Asia Range breakout with diagnostic criteria."""
        # Get Asia range
        asia_range = self.market_state.get_asia_range(epic)
        has_range = asia_range is not None
        
        if not has_range:
            result.criteria.append(DiagnosticCriterion(
                name="Asia Range available",
                passed=False,
                detail="No Asia Range data available",
            ))
            return
        
        range_high, range_low = asia_range
        range_height = range_high - range_low
        
        result.criteria.append(DiagnosticCriterion(
            name="Asia Range available",
            passed=True,
            detail=f"Range: {range_low:.4f} - {range_high:.4f}",
        ))
        
        # Check range size constraints
        range_valid = self._is_valid_range(range_height, self.config.breakout.asia_range)
        min_ticks = self.config.breakout.asia_range.min_range_ticks
        max_ticks = self.config.breakout.asia_range.max_range_ticks
        # Prevent division by zero
        actual_ticks = range_height / self.config.tick_size if self.config.tick_size > 0 else 0
        
        result.criteria.append(DiagnosticCriterion(
            name="Range size valid",
            passed=range_valid,
            detail=f"Range: {actual_ticks:.1f} ticks (valid: {min_ticks}-{max_ticks})",
        ))
        
        if not range_valid:
            return
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        has_candles = candles is not None and len(candles) > 0
        
        result.criteria.append(DiagnosticCriterion(
            name="Price data available",
            passed=has_candles,
            detail=f"{len(candles) if candles else 0} candles" if has_candles else "No candle data",
        ))
        
        if not has_candles:
            return
        
        latest_candle = candles[-1]
        current_price = latest_candle.close
        
        breakout_signal = self._detect_breakout_signal(
            latest_candle,
            range_high,
            range_low,
            range_height,
            self.config.breakout.asia_range.min_breakout_body_fraction,
            context="Asia breakout evaluation",
        )

        if breakout_signal:
            validation_direction, trade_direction = self._map_breakout_signal_directions(breakout_signal)
            result.criteria.append(DiagnosticCriterion(
                name="Price broke Asia High" if validation_direction == 'LONG' else "Price broke Asia Low",
                passed=True,
                detail=(
                    f"High {latest_candle.high:.4f} > Range High {range_high:.4f}"
                    if validation_direction == 'LONG'
                    else f"Low {latest_candle.low:.4f} < Range Low {range_low:.4f}"
                ) + f" ({breakout_signal.value})",
            ))

            candle_valid = self._is_valid_breakout_candle(
                latest_candle,
                range_height,
                validation_direction,
                self.config.breakout.asia_range.min_breakout_body_fraction
            )
            min_body = self.config.breakout.asia_range.min_breakout_body_fraction * 100
            result.criteria.append(DiagnosticCriterion(
                name="Breakout candle quality (LONG)" if validation_direction == 'LONG' else "Breakout candle quality (SHORT)",
                passed=candle_valid,
                detail=f"Body size: {latest_candle.body_size:.4f}, min fraction: {min_body:.0f}%",
            ))
            if candle_valid:
                candidate = self._create_breakout_candidate(
                    epic=epic, ts=ts, phase=phase, direction=trade_direction,
                    range_high=range_high, range_low=range_low,
                    trigger_price=current_price,
                    signal_type=breakout_signal,
                )
                result.setups.append(candidate)
        else:
            price_position = "within range"
            if current_price > range_high:
                price_position = "above range"
            elif current_price < range_low:
                price_position = "below range"

            result.criteria.append(DiagnosticCriterion(
                name="Price breakout",
                passed=False,
                detail=(
                    f"Price {current_price:.4f} {price_position} "
                    f"({range_low:.4f} - {range_high:.4f})"
                ),
            ))

    def _evaluate_us_breakout_with_diagnostics(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        result: EvaluationResult,
    ) -> None:
        """Evaluate Pre-US Range breakout with diagnostic criteria."""
        # Get pre-US range
        pre_us_range = self.market_state.get_pre_us_range(epic)
        has_range = pre_us_range is not None
        
        if not has_range:
            result.criteria.append(DiagnosticCriterion(
                name="Pre-US Range available",
                passed=False,
                detail="No Pre-US Range data available",
            ))
            return
        
        range_high, range_low = pre_us_range
        range_height = range_high - range_low
        
        result.criteria.append(DiagnosticCriterion(
            name="Pre-US Range available",
            passed=True,
            detail=f"Range: {range_low:.4f} - {range_high:.4f}",
        ))
        
        # Check range size constraints
        range_valid = self._is_valid_range(range_height, self.config.breakout.us_core)
        min_ticks = self.config.breakout.us_core.min_range_ticks
        max_ticks = self.config.breakout.us_core.max_range_ticks
        # Prevent division by zero
        actual_ticks = range_height / self.config.tick_size if self.config.tick_size > 0 else 0
        
        result.criteria.append(DiagnosticCriterion(
            name="Range size valid",
            passed=range_valid,
            detail=f"Range: {actual_ticks:.1f} ticks (valid: {min_ticks}-{max_ticks})",
        ))
        
        if not range_valid:
            return
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        has_candles = candles is not None and len(candles) > 0
        
        result.criteria.append(DiagnosticCriterion(
            name="Price data available",
            passed=has_candles,
            detail=f"{len(candles) if candles else 0} candles" if has_candles else "No candle data",
        ))
        
        if not has_candles:
            return
        
        latest_candle = candles[-1]
        current_price = latest_candle.close
        
        breakout_signal = self._detect_breakout_signal(
            latest_candle,
            range_high,
            range_low,
            range_height,
            self.config.breakout.us_core.min_breakout_body_fraction,
            context="US breakout evaluation",
        )

        if breakout_signal:
            validation_direction, trade_direction = self._map_breakout_signal_directions(breakout_signal)
            result.criteria.append(DiagnosticCriterion(
                name="Price broke Pre-US High" if validation_direction == 'LONG' else "Price broke Pre-US Low",
                passed=True,
                detail=(
                    f"High {latest_candle.high:.4f} > Range High {range_high:.4f}"
                    if validation_direction == 'LONG'
                    else f"Low {latest_candle.low:.4f} < Range Low {range_low:.4f}"
                ) + f" ({breakout_signal.value})",
            ))

            candle_valid = self._is_valid_breakout_candle(
                latest_candle, range_height, validation_direction,
                self.config.breakout.us_core.min_breakout_body_fraction
            )
            min_body = self.config.breakout.us_core.min_breakout_body_fraction * 100
            result.criteria.append(DiagnosticCriterion(
                name="Breakout candle quality (LONG)" if validation_direction == 'LONG' else "Breakout candle quality (SHORT)",
                passed=candle_valid,
                detail=f"Body size: {latest_candle.body_size:.4f}, min fraction: {min_body:.0f}%",
            ))
            if candle_valid:
                candidate = self._create_breakout_candidate(
                    epic=epic, ts=ts, phase=phase, direction=trade_direction,
                    range_high=range_high, range_low=range_low,
                    trigger_price=current_price,
                    signal_type=breakout_signal,
                )
                result.setups.append(candidate)
        else:
            result.criteria.append(DiagnosticCriterion(
                name="Price breakout",
                passed=False,
                detail=f"Price {current_price:.4f} within range ({range_low:.4f} - {range_high:.4f})",
            ))

    def _evaluate_eia_with_diagnostics(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase,
        result: EvaluationResult,
    ) -> None:
        """Evaluate EIA setups with diagnostic criteria."""
        # Get EIA timestamp
        eia_timestamp = self.market_state.get_eia_timestamp()
        has_eia = eia_timestamp is not None
        
        result.criteria.append(DiagnosticCriterion(
            name="EIA timestamp set",
            passed=has_eia,
            detail=f"EIA at {eia_timestamp}" if has_eia else "No EIA timestamp configured",
        ))
        
        if not has_eia:
            return
        
        # Get candles since EIA release
        required_candles = self.config.eia.impulse_window_minutes + 5
        candles = self.market_state.get_recent_candles(epic, '1m', required_candles)
        has_enough_candles = candles and len(candles) >= self.config.eia.impulse_window_minutes
        
        result.criteria.append(DiagnosticCriterion(
            name="Sufficient post-EIA data",
            passed=has_enough_candles,
            detail=f"{len(candles) if candles else 0} candles (need {self.config.eia.impulse_window_minutes})",
        ))
        
        if not has_enough_candles:
            return
        
        # Analyze impulse
        impulse_candles = candles[:self.config.eia.impulse_window_minutes]
        impulse_direction, impulse_high, impulse_low = self._analyze_impulse(impulse_candles)
        has_impulse = impulse_direction is not None
        
        result.criteria.append(DiagnosticCriterion(
            name="Clear impulse detected",
            passed=has_impulse,
            detail=f"Impulse: {impulse_direction or 'None'} ({impulse_low:.4f} - {impulse_high:.4f})" if has_impulse else "No clear impulse movement",
        ))
        
        if not has_impulse:
            return
        
        impulse_range = impulse_high - impulse_low
        
        # Check for EIA Reversion and Trend Day patterns
        recent_candles = candles[self.config.eia.impulse_window_minutes:]
        
        reversion_candidate = self._check_eia_reversion(
            epic=epic, ts=ts, phase=phase,
            eia_timestamp=eia_timestamp,
            impulse_direction=impulse_direction,
            impulse_high=impulse_high,
            impulse_low=impulse_low,
            impulse_range=impulse_range,
            recent_candles=recent_candles,
        )
        
        if reversion_candidate:
            result.criteria.append(DiagnosticCriterion(
                name="EIA Reversion pattern",
                passed=True,
                detail=f"Reversion {reversion_candidate.direction} detected",
            ))
            result.setups.append(reversion_candidate)
        else:
            result.criteria.append(DiagnosticCriterion(
                name="EIA Reversion pattern",
                passed=False,
                detail="No significant reversion detected",
            ))
        
        trendday_candidate = self._check_eia_trendday(
            epic=epic, ts=ts, phase=phase,
            eia_timestamp=eia_timestamp,
            impulse_direction=impulse_direction,
            impulse_high=impulse_high,
            impulse_low=impulse_low,
            recent_candles=recent_candles,
        )
        
        if trendday_candidate:
            result.criteria.append(DiagnosticCriterion(
                name="EIA Trend Day pattern",
                passed=True,
                detail=f"Trend Day {trendday_candidate.direction} detected",
            ))
            result.setups.append(trendday_candidate)
        else:
            result.criteria.append(DiagnosticCriterion(
                name="EIA Trend Day pattern",
                passed=False,
                detail="No trend continuation pattern detected",
            ))

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
            self._set_status("Asia breakout evaluation: no range data")
            logger.debug(
                "Asia breakout evaluation: no range data",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "asia_breakout",
                        "result": "no_setup",
                        "reason": "Asia range data not available",
                    }
                }
            )
            return candidates
        
        range_high, range_low = asia_range
        range_height = range_high - range_low
        
        # Check range size constraints
        if not self._is_valid_range(range_height, self.config.breakout.asia_range):
            ticks = range_height / self.config.tick_size if self.config.tick_size > 0 else 0
            self._set_status("Asia breakout evaluation: invalid range size")
            logger.debug(
                "Asia breakout evaluation: invalid range size",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "asia_breakout",
                        "result": "no_setup",
                        "reason": "Range size out of valid bounds",
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_height": range_height,
                        "range_ticks": ticks,
                        "min_ticks": self.config.breakout.asia_range.min_range_ticks,
                        "max_ticks": self.config.breakout.asia_range.max_range_ticks,
                    }
                }
            )
            return candidates
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        if not candles:
            self._set_status("Asia breakout evaluation: no candle data")
            logger.debug(
                "Asia breakout evaluation: no candle data",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "asia_breakout",
                        "result": "no_setup",
                        "reason": "No candle data available",
                    }
                }
            )
            return candidates
        
        # Check for breakout
        latest_candle = candles[-1]
        current_price = latest_candle.close

        breakout_signal = self._detect_breakout_signal(
            latest_candle,
            range_high,
            range_low,
            range_height,
            self.config.breakout.asia_range.min_breakout_body_fraction,
            context="Asia diagnostics breakout evaluation",
        )

        if breakout_signal:
            validation_direction, trade_direction = self._map_breakout_signal_directions(breakout_signal)
            min_body_fraction = self.config.breakout.asia_range.min_breakout_body_fraction
            if self._is_valid_breakout_candle(
                latest_candle, range_height, validation_direction, min_body_fraction
            ):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction=trade_direction,
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                    signal_type=breakout_signal,
                )
                candidates.append(candidate)

                logger.info(
                    "[STRATEGY] BREAKOUT detected",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "phase": phase.value,
                            "breakout_type": breakout_signal.value,
                            "direction": trade_direction,
                        }
                    },
                )

                if breakout_signal in (
                    BreakoutSignal.FAILED_LONG_BREAKOUT,
                    BreakoutSignal.FAILED_SHORT_BREAKOUT,
                ):
                    self._set_status(
                        "BREAKOUT FAILED: candle returned into range "
                        f"({trade_direction} signal)"
                    )
                else:
                    self._set_status(
                        f"Asia breakout evaluation: {trade_direction} setup detected"
                    )

                logger.debug(
                    "Asia breakout evaluation: breakout signal detected",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "timestamp": ts.isoformat(),
                            "phase": phase.value,
                            "evaluation_type": "asia_breakout",
                            "result": "setup_found",
                            "direction": trade_direction,
                            "signal_type": breakout_signal.value,
                            "current_price": current_price,
                            "range_high": range_high,
                            "range_low": range_low,
                            "candle_body_size": latest_candle.body_size,
                        }
                    }
                )
            else:
                self._set_status(
                    "Asia breakout evaluation: breakout detected but candle invalid"
                )
                logger.debug(
                    "Asia breakout evaluation: breakout detected but candle invalid",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "timestamp": ts.isoformat(),
                            "phase": phase.value,
                            "evaluation_type": "asia_breakout",
                            "result": "no_setup",
                            "reason": "Breakout candle body too small or wrong direction",
                            "direction": validation_direction,
                            "signal_type": breakout_signal.value,
                            "current_price": current_price,
                            "range_high": range_high,
                            "range_low": range_low,
                            "candle_body_size": latest_candle.body_size,
                            "min_body_fraction": min_body_fraction,
                        }
                    }
                )
        else:
            # Price within range
            self._set_status("Asia breakout evaluation: price within range")
            logger.debug(
                "Asia breakout evaluation: price within range",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "asia_breakout",
                        "result": "no_setup",
                        "reason": "Price within range bounds",
                        "current_price": current_price,
                        "range_high": range_high,
                        "range_low": range_low,
                    }
                }
            )
        
        return candidates

    def _evaluate_us_breakout(
        self,
        epic: str,
        ts: datetime,
        phase: SessionPhase
    ) -> list[SetupCandidate]:
        """
        Evaluate US-related breakout using the prior phase's reference range.

        Args:
            epic: Market identifier.
            ts: Current timestamp.
            phase: Current session phase.

        Returns:
            List of breakout SetupCandidate objects.
        """
        candidates: list[SetupCandidate] = []

        # Select the correct reference range based on the phase mapping:
        # - PRE_US_RANGE evaluates breakouts against the London Core range
        # - US_CORE_TRADING / US_CORE evaluate breakouts against the Pre-US range
        range_source = "Pre-US"
        reference_range = self.market_state.get_pre_us_range(epic)
        if phase == SessionPhase.PRE_US_RANGE:
            range_source = "London Core"
            reference_range = self.market_state.get_london_core_range(epic)

        if not reference_range:
            self._set_status(f"US breakout evaluation: no {range_source} range data")
            logger.debug(
                "US breakout evaluation: no range data",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "no_setup",
                        "reason": f"{range_source} range data not available",
                        "range_source": range_source,
                    }
                }
            )
            return candidates

        range_high, range_low = reference_range
        range_height = range_high - range_low
        
        # Check range size constraints
        if not self._is_valid_range(range_height, self.config.breakout.us_core):
            ticks = range_height / self.config.tick_size if self.config.tick_size > 0 else 0
            self._set_status("US breakout evaluation: invalid range size")
            logger.debug(
                "US breakout evaluation: invalid range size",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "no_setup",
                        "reason": "Range size out of valid bounds",
                        "range_source": range_source,
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_height": range_height,
                        "range_ticks": ticks,
                        "min_ticks": self.config.breakout.us_core.min_range_ticks,
                        "max_ticks": self.config.breakout.us_core.max_range_ticks,
                    }
                }
            )
            return candidates
        
        # Get recent candles
        candles = self.market_state.get_recent_candles(epic, '1m', 10)
        if not candles:
            self._set_status("US breakout evaluation: no candle data")
            logger.debug(
                "US breakout evaluation: no candle data",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "no_setup",
                        "reason": "No candle data available",
                        "range_source": range_source,
                    }
                }
            )
            return candidates
        
        # Check for breakout
        latest_candle = candles[-1]
        current_price = latest_candle.close

        breakout_signal = self._detect_breakout_signal(
            latest_candle,
            range_high,
            range_low,
            range_height,
            self.config.breakout.us_core.min_breakout_body_fraction,
            context="US diagnostics breakout evaluation",
        )

        if breakout_signal:
            validation_direction, trade_direction = self._map_breakout_signal_directions(breakout_signal)
            min_body_fraction = self.config.breakout.us_core.min_breakout_body_fraction
            if self._is_valid_breakout_candle(
                latest_candle, range_height, validation_direction, min_body_fraction
            ):
                candidate = self._create_breakout_candidate(
                    epic=epic,
                    ts=ts,
                    phase=phase,
                    direction=trade_direction,
                    range_high=range_high,
                    range_low=range_low,
                    trigger_price=latest_candle.close,
                    signal_type=breakout_signal,
                )
                candidates.append(candidate)

                logger.info(
                    "[STRATEGY] BREAKOUT detected",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "phase": phase.value,
                            "breakout_type": breakout_signal.value,
                            "direction": trade_direction,
                        }
                    },
                )

                if breakout_signal in (
                    BreakoutSignal.FAILED_LONG_BREAKOUT,
                    BreakoutSignal.FAILED_SHORT_BREAKOUT,
                ):
                    self._set_status(
                        "BREAKOUT FAILED: candle returned into range "
                        f"({trade_direction} signal)"
                    )
                else:
                    self._set_status(
                        f"US breakout evaluation: {trade_direction} setup detected"
                    )

                logger.debug(
                    "US breakout evaluation: breakout signal detected",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "timestamp": ts.isoformat(),
                            "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "setup_found",
                        "direction": trade_direction,
                        "signal_type": breakout_signal.value,
                        "current_price": current_price,
                        "range_source": range_source,
                        "range_high": range_high,
                        "range_low": range_low,
                        "candle_body_size": latest_candle.body_size,
                    }
                }
                )
            else:
                self._set_status(
                    "US breakout evaluation: breakout detected but candle invalid"
                )
                logger.debug(
                    "US breakout evaluation: breakout detected but candle invalid",
                    extra={
                        "strategy_data": {
                            "epic": epic,
                            "timestamp": ts.isoformat(),
                            "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "no_setup",
                        "reason": "Breakout candle body too small or wrong direction",
                        "direction": validation_direction,
                        "signal_type": breakout_signal.value,
                        "current_price": current_price,
                        "range_source": range_source,
                        "range_high": range_high,
                        "range_low": range_low,
                        "candle_body_size": latest_candle.body_size,
                        "min_body_fraction": min_body_fraction,
                    }
                    }
                )
        else:
            # No valid breakout signal detected; report actual price position
            price_position = "within range"
            reason = "Price within range bounds"
            if current_price is not None:
                if current_price > range_high:
                    price_position = "above range"
                    reason = "Price above range high without valid breakout"
                elif current_price < range_low:
                    price_position = "below range"
                    reason = "Price below range low without valid breakout"

            self._set_status(f"US breakout evaluation: price {price_position}")
            logger.debug(
                f"US breakout evaluation: no breakout signal {current_price} ({range_high} - {range_low})", 
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "us_breakout",
                        "result": "no_setup",
                        "reason": reason,
                        "price_position": price_position,
                        "current_price": current_price,
                        "range_source": range_source,
                        "range_high": range_high,
                        "range_low": range_low,
                    }
                }
            )
        
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
            logger.debug(
                "EIA evaluation: no EIA timestamp",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia",
                        "result": "no_setup",
                        "reason": "EIA timestamp not configured",
                    }
                }
            )
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
            logger.debug(
                "EIA evaluation: insufficient candle data",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia",
                        "result": "no_setup",
                        "reason": "Insufficient candle data for EIA analysis",
                        "candles_available": len(candles) if candles else 0,
                        "candles_required": self.config.eia.impulse_window_minutes,
                    }
                }
            )
            return candidates
        
        # Analyze impulse from the candles
        impulse_candles = candles[:self.config.eia.impulse_window_minutes]
        impulse_direction, impulse_high, impulse_low = self._analyze_impulse(impulse_candles)
        
        if not impulse_direction:
            logger.debug(
                "EIA evaluation: no clear impulse detected",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia",
                        "result": "no_setup",
                        "reason": "No clear impulse movement detected after EIA",
                        "eia_timestamp": eia_timestamp.isoformat(),
                        "impulse_high": impulse_high,
                        "impulse_low": impulse_low,
                    }
                }
            )
            return candidates
        
        impulse_range = impulse_high - impulse_low
        
        logger.debug(
            "EIA evaluation: impulse analyzed",
            extra={
                "strategy_data": {
                    "epic": epic,
                    "timestamp": ts.isoformat(),
                    "phase": phase.value,
                    "evaluation_type": "eia",
                    "eia_timestamp": eia_timestamp.isoformat(),
                    "impulse_direction": impulse_direction,
                    "impulse_high": impulse_high,
                    "impulse_low": impulse_low,
                    "impulse_range": impulse_range,
                }
            }
        )
        
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
            logger.debug(
                "EIA evaluation: reversion setup detected",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia_reversion",
                        "result": "setup_found",
                        "direction": reversion_candidate.direction,
                        "impulse_direction": impulse_direction,
                    }
                }
            )
        else:
            logger.debug(
                "EIA evaluation: no reversion pattern",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia_reversion",
                        "result": "no_setup",
                        "reason": "No significant reversion detected",
                        "impulse_direction": impulse_direction,
                    }
                }
            )
        
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
            logger.debug(
                "EIA evaluation: trend day setup detected",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia_trendday",
                        "result": "setup_found",
                        "direction": trendday_candidate.direction,
                        "impulse_direction": impulse_direction,
                    }
                }
            )
        else:
            logger.debug(
                "EIA evaluation: no trend day pattern",
                extra={
                    "strategy_data": {
                        "epic": epic,
                        "timestamp": ts.isoformat(),
                        "phase": phase.value,
                        "evaluation_type": "eia_trendday",
                        "result": "no_setup",
                        "reason": "No trend continuation pattern detected",
                        "impulse_direction": impulse_direction,
                    }
                }
            )
        
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

    def _detect_breakout_signal(
        self,
        candle: Candle,
        range_high: float,
        range_low: float,
        range_height: float,
        min_body_fraction: float,
        context: Optional[str] = None,
    ) -> Optional[BreakoutSignal]:
        """Detect breakout or fakeout signal for a candle relative to a range."""

        context_suffix = f" [{context}]" if context else ""

        if candle.high > range_high:
            passed, reason = self._passes_breakout_filters(
                candle,
                range_height,
                "LONG",
                range_high,
                range_low,
                min_body_fraction,
            )
            if not passed:
                rejection_reason = (
                    f"Breakout rejected: LONG validation failed - {reason}{context_suffix}"
                )
                self._set_status(rejection_reason)
                logger.debug(
                    "Breakout signal rejected%s: %s",
                    context_suffix,
                    reason,
                    extra={
                        "strategy_data": {
                            "candle_high": candle.high,
                            "candle_low": candle.low,
                            "candle_close": candle.close,
                            "range_high": range_high,
                            "range_low": range_low,
                            "range_height": range_height,
                            "direction": "LONG",
                        }
                    },
                )
                return None
            if candle.close > range_high:
                return BreakoutSignal.LONG_BREAKOUT
            return BreakoutSignal.FAILED_LONG_BREAKOUT

        if candle.low < range_low:
            passed, reason = self._passes_breakout_filters(
                candle,
                range_height,
                "SHORT",
                range_high,
                range_low,
                min_body_fraction,
            )
            if not passed:
                rejection_reason = (
                    f"Breakout rejected: SHORT validation failed - {reason}{context_suffix}"
                )
                self._set_status(rejection_reason)
                logger.debug(
                    "Breakout signal rejected%s: %s",
                    context_suffix,
                    reason,
                    extra={
                        "strategy_data": {
                            "candle_high": candle.high,
                            "candle_low": candle.low,
                            "candle_close": candle.close,
                            "range_high": range_high,
                            "range_low": range_low,
                            "range_height": range_height,
                            "direction": "SHORT",
                        }
                    },
                )
                return None
            if candle.close < range_low:
                return BreakoutSignal.SHORT_BREAKOUT
            return BreakoutSignal.FAILED_SHORT_BREAKOUT

        logger.debug(
            "Breakout signal not generated%s: candle remained inside range",
            context_suffix,
            extra={
                "strategy_data": {
                    "candle_high": candle.high,
                    "candle_low": candle.low,
                    "candle_close": candle.close,
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_height": range_height,
                }
            },
        )
        return None

    def _passes_breakout_filters(
        self,
        candle: Candle,
        range_height: float,
        validation_direction: Literal["LONG", "SHORT"],
        range_high: float,
        range_low: float,
        min_body_fraction: float,
    ) -> tuple[bool, str]:
        """Apply existing breakout quality filters before classifying signals."""
        # Direction check with explicit detail
        if validation_direction == "LONG" and candle.is_bearish:
            return False, (
                "Bullish breakout required but candle closed lower than it opened "
                f"(open {candle.open:.4f} > close {candle.close:.4f})"
            )

        if validation_direction == "SHORT" and candle.is_bullish:
            return False, (
                "Bearish breakout required but candle closed higher than it opened "
                f"(open {candle.open:.4f} < close {candle.close:.4f})"
            )

        # Body-size check with numeric context
        min_body = range_height * min_body_fraction
        if candle.body_size < min_body:
            return False, (
                f"Candle body {candle.body_size:.4f} below minimum {min_body:.4f} "
                f"({min_body_fraction * 100:.0f}% of range)"
            )

        # Enforce minimum breakout distance using configured ticks.
        min_ticks = self.config.breakout.min_breakout_distance_ticks
        if min_ticks and self.config.tick_size > 0:
            tick_distance = (
                candle.high - range_high
                if validation_direction == "LONG"
                else range_low - candle.low
            )
            if tick_distance / self.config.tick_size < min_ticks:
                return False, (
                    f"Breakout distance {tick_distance:.4f} below minimum of {min_ticks} ticks"
                )

        return True, ""

    def _map_breakout_signal_directions(
        self, signal: BreakoutSignal
    ) -> tuple[Literal["LONG", "SHORT"], Literal["LONG", "SHORT"]]:
        """Map breakout signal to validation and trade directions."""

        if signal == BreakoutSignal.LONG_BREAKOUT:
            return "LONG", "LONG"
        if signal == BreakoutSignal.SHORT_BREAKOUT:
            return "SHORT", "SHORT"
        if signal == BreakoutSignal.FAILED_LONG_BREAKOUT:
            return "LONG", "SHORT"
        return "SHORT", "LONG"

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
        signal_type: Optional[BreakoutSignal] = None,
    ) -> SetupCandidate:
        """Create a breakout SetupCandidate."""
        atr = self.market_state.get_atr(epic, '1h', 14)

        breakout_context = BreakoutContext(
            range_high=range_high,
            range_low=range_low,
            range_height=range_high - range_low,
            trigger_price=trigger_price,
            direction=direction,
            signal_type=signal_type,
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
