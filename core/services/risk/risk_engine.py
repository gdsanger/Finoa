"""
Risk Engine implementation for Fiona trading system.

The Risk Engine evaluates trades and determines whether they are
allowed based on configurable risk limits.
"""
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple

from core.services.broker.models import AccountState, Position, OrderRequest, OrderDirection
from core.services.strategy.models import SetupCandidate, SessionPhase, SetupKind
from .models import RiskConfig, RiskEvaluationResult


logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Risk Engine v1.0 for trade evaluation.
    
    The Risk Engine evaluates proposed trades against configurable risk limits
    and determines whether they should be allowed. It can also suggest
    adjustments to make a trade fit within limits.
    
    Example:
        config = RiskConfig.from_yaml('risk_config.yaml')
        engine = RiskEngine(config)
        result = engine.evaluate(
            account=account_state,
            positions=open_positions,
            setup=setup_candidate,
            order=order_request,
            now=datetime.now(timezone.utc),
        )
        if result.allowed:
            # Execute the trade
            pass
        else:
            # Trade denied, log reason
            print(result.reason)
    """

    def __init__(self, config: RiskConfig):
        """
        Initialize the Risk Engine with configuration.
        
        Args:
            config: Risk configuration defining limits and rules.
        """
        self.config = config

    def evaluate(
        self,
        account: AccountState,
        positions: List[Position],
        setup: SetupCandidate,
        order: OrderRequest,
        now: datetime,
        eia_timestamp: Optional[datetime] = None,
        daily_pnl: Decimal = Decimal('0.00'),
        weekly_pnl: Decimal = Decimal('0.00'),
        trend_direction: Optional[str] = None,
    ) -> RiskEvaluationResult:
        """
        Evaluate a proposed trade against risk limits.
        
        Args:
            account: Current account state (balance, equity, margin).
            positions: List of currently open positions.
            setup: The setup candidate that triggered this trade.
            order: The proposed order request.
            now: Current timestamp for time-based rules.
            eia_timestamp: Optional timestamp of next/recent EIA release.
            daily_pnl: Daily profit/loss so far.
            weekly_pnl: Weekly profit/loss so far.
            trend_direction: Higher timeframe trend direction (LONG/SHORT).
            
        Returns:
            RiskEvaluationResult: The evaluation result with allowed flag and reason.
        """
        violations = []
        risk_metrics = {}
        
        logger.debug(
            "Risk evaluation started",
            extra={
                "risk_data": {
                    "setup_id": setup.id,
                    "epic": order.epic,
                    "direction": order.direction.value if hasattr(order.direction, 'value') else str(order.direction),
                    "size": float(order.size),
                    "stop_loss": float(order.stop_loss) if order.stop_loss else None,
                    "take_profit": float(order.take_profit) if order.take_profit else None,
                    "timestamp": now.isoformat(),
                    "account_equity": float(account.equity),
                    "open_positions": len(positions),
                    "daily_pnl": float(daily_pnl),
                    "weekly_pnl": float(weekly_pnl),
                    "trend_direction": trend_direction,
                }
            }
        )
        
        # 1. Check time-based restrictions
        time_result = self._check_time_restrictions(now, eia_timestamp, setup)
        if time_result:
            violations.append(time_result)
            logger.debug(
                "Risk check: time restriction violated",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "check": "time_restrictions",
                        "result": "denied",
                        "reason": time_result,
                        "timestamp": now.isoformat(),
                        "eia_timestamp": eia_timestamp.isoformat() if eia_timestamp else None,
                    }
                }
            )
        
        # 2. Check daily/weekly loss limits
        loss_result = self._check_loss_limits(account, daily_pnl, weekly_pnl)
        if loss_result:
            violations.append(loss_result)
            logger.debug(
                "Risk check: loss limit violated",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "check": "loss_limits",
                        "result": "denied",
                        "reason": loss_result,
                        "daily_pnl": float(daily_pnl),
                        "weekly_pnl": float(weekly_pnl),
                        "max_daily_loss_percent": float(self.config.max_daily_loss_percent),
                        "max_weekly_loss_percent": float(self.config.max_weekly_loss_percent),
                    }
                }
            )
        
        # 3. Check open positions limit
        position_result = self._check_open_positions(positions)
        if position_result:
            violations.append(position_result)
            logger.debug(
                "Risk check: position limit exceeded",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "check": "open_positions",
                        "result": "denied",
                        "reason": position_result,
                        "current_positions": len(positions),
                        "max_positions": self.config.max_open_positions,
                    }
                }
            )
        
        # 4. Check countertrend rule (optional)
        if not self.config.allow_countertrend and trend_direction:
            countertrend_result = self._check_countertrend(setup, trend_direction)
            if countertrend_result:
                violations.append(countertrend_result)
                logger.debug(
                    "Risk check: countertrend trade denied",
                    extra={
                        "risk_data": {
                            "setup_id": setup.id,
                            "check": "countertrend",
                            "result": "denied",
                            "reason": countertrend_result,
                            "trade_direction": setup.direction,
                            "trend_direction": trend_direction,
                        }
                    }
                )
        
        # 5. Check SL/TP validity
        sltp_result = self._check_sltp_validity(order)
        if sltp_result:
            violations.append(sltp_result)
            logger.debug(
                "Risk check: SL/TP invalid",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "check": "sltp_validity",
                        "result": "denied",
                        "reason": sltp_result,
                        "stop_loss": float(order.stop_loss) if order.stop_loss else None,
                        "take_profit": float(order.take_profit) if order.take_profit else None,
                    }
                }
            )
        
        # 6. Check position size and risk per trade
        risk_result, adjusted_order, metrics = self._check_position_risk(
            account, order, setup
        )
        risk_metrics.update(metrics)
        
        if risk_result:
            violations.append(risk_result)
            logger.debug(
                "Risk check: position risk exceeded",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "check": "position_risk",
                        "result": "denied",
                        "reason": risk_result,
                        "risk_metrics": {k: float(v) if isinstance(v, Decimal) else v for k, v in metrics.items()},
                    }
                }
            )
        elif adjusted_order:
            # Order was adjusted to fit risk limits
            # If there are no other violations, return the adjusted order
            if not violations:
                logger.debug(
                    "Risk evaluation: order adjusted to fit limits",
                    extra={
                        "risk_data": {
                            "setup_id": setup.id,
                            "result": "allowed_adjusted",
                            "original_size": float(order.size),
                            "adjusted_size": float(adjusted_order.size),
                            "risk_metrics": {k: float(v) if isinstance(v, Decimal) else v for k, v in metrics.items()},
                        }
                    }
                )
                return RiskEvaluationResult(
                    allowed=True,
                    reason="Position size reduced to fit risk limits",
                    adjusted_order=adjusted_order,
                    violations=[],
                    risk_metrics=risk_metrics,
                )
            # If there are other violations, continue to rejection
        
        # Build final result
        if violations:
            logger.debug(
                "Risk evaluation: trade denied",
                extra={
                    "risk_data": {
                        "setup_id": setup.id,
                        "result": "denied",
                        "primary_reason": violations[0],
                        "all_violations": violations,
                        "risk_metrics": {k: float(v) if isinstance(v, Decimal) else v for k, v in risk_metrics.items()},
                    }
                }
            )
            return RiskEvaluationResult(
                allowed=False,
                reason=violations[0],  # Primary rejection reason
                adjusted_order=None,
                violations=violations,
                risk_metrics=risk_metrics,
            )
        
        logger.debug(
            "Risk evaluation: trade approved",
            extra={
                "risk_data": {
                    "setup_id": setup.id,
                    "result": "allowed",
                    "size": float(order.size),
                    "risk_metrics": {k: float(v) if isinstance(v, Decimal) else v for k, v in risk_metrics.items()},
                }
            }
        )
        return RiskEvaluationResult(
            allowed=True,
            reason="Trade meets all risk requirements",
            adjusted_order=None,
            violations=[],
            risk_metrics=risk_metrics,
        )

    def _check_time_restrictions(
        self,
        now: datetime,
        eia_timestamp: Optional[datetime],
        setup: SetupCandidate,
    ) -> Optional[str]:
        """
        Check time-based trading restrictions.
        
        Args:
            now: Current timestamp.
            eia_timestamp: Optional EIA release timestamp.
            setup: The setup candidate.
            
        Returns:
            str: Violation message if any, None otherwise.
        """
        # Check EIA window restriction
        if eia_timestamp and setup.setup_kind == SetupKind.BREAKOUT:
            window_minutes = self.config.deny_eia_window_minutes
            eia_start = eia_timestamp - timedelta(minutes=window_minutes)
            eia_end = eia_timestamp + timedelta(minutes=window_minutes)
            
            if eia_start <= now <= eia_end:
                return f"Trade denied: Within EIA window ({window_minutes} min before/after)"
        
        # Check Friday evening restriction
        if now.weekday() == 4:  # Friday
            cutoff = self.config.get_friday_cutoff_time()
            current_time = now.time()
            if current_time >= cutoff:
                return f"Trade denied: Friday after {self.config.deny_friday_after}"
        
        # Check weekend restriction
        if now.weekday() >= 5:  # Saturday or Sunday
            return "Trade denied: Weekend trading not allowed"
        
        return None

    def _check_loss_limits(
        self,
        account: AccountState,
        daily_pnl: Decimal,
        weekly_pnl: Decimal,
    ) -> Optional[str]:
        """
        Check daily and weekly loss limits.
        
        Args:
            account: Current account state.
            daily_pnl: Daily profit/loss.
            weekly_pnl: Weekly profit/loss.
            
        Returns:
            str: Violation message if any, None otherwise.
        """
        equity = account.equity
        
        # Check daily loss limit
        max_daily_loss = equity * (self.config.max_daily_loss_percent / Decimal('100'))
        if daily_pnl < -max_daily_loss:
            return f"Trade denied: Daily loss limit exceeded ({self.config.max_daily_loss_percent}%)"
        
        # Check weekly loss limit
        max_weekly_loss = equity * (self.config.max_weekly_loss_percent / Decimal('100'))
        if weekly_pnl < -max_weekly_loss:
            return f"Trade denied: Weekly loss limit exceeded ({self.config.max_weekly_loss_percent}%)"
        
        return None

    def _check_open_positions(
        self,
        positions: List[Position],
    ) -> Optional[str]:
        """
        Check if maximum open positions limit is reached.
        
        Args:
            positions: List of currently open positions.
            
        Returns:
            str: Violation message if any, None otherwise.
        """
        if len(positions) >= self.config.max_open_positions:
            return f"Trade denied: Max open positions ({self.config.max_open_positions}) reached"
        return None

    def _check_countertrend(
        self,
        setup: SetupCandidate,
        trend_direction: str,
    ) -> Optional[str]:
        """
        Check if trade is against the higher timeframe trend.
        
        EIA setups are exempt from this rule as they are event-driven.
        
        Args:
            setup: The setup candidate.
            trend_direction: Higher timeframe trend direction (LONG/SHORT).
            
        Returns:
            str: Violation message if any, None otherwise.
        """
        # EIA setups are exempt from countertrend rule
        if setup.setup_kind in (SetupKind.EIA_REVERSION, SetupKind.EIA_TRENDDAY):
            return None
        
        # Check if trade direction matches trend
        if setup.direction != trend_direction:
            return f"Trade denied: Countertrend trade ({setup.direction} vs {trend_direction} trend)"
        
        return None

    def _check_sltp_validity(
        self,
        order: OrderRequest,
    ) -> Optional[str]:
        """
        Check if stop loss and take profit meet minimum requirements.
        
        Args:
            order: The proposed order request.
            
        Returns:
            str: Violation message if any, None otherwise.
        """
        # Stop loss validation
        if order.stop_loss is None:
            return "Trade denied: Stop loss is required"
        
        # Take profit validation (optional but recommended)
        # If TP is set, check minimum distance
        if order.take_profit is not None:
            # We can't check distance without knowing entry price
            # This would typically be done with market price context
            pass
        
        return None

    def _check_position_risk(
        self,
        account: AccountState,
        order: OrderRequest,
        setup: SetupCandidate,
    ) -> Tuple[Optional[str], Optional[OrderRequest], dict]:
        """
        Check position size and risk per trade limits.
        
        Args:
            account: Current account state.
            order: The proposed order request.
            setup: The setup candidate.
            
        Returns:
            tuple: (violation_message, adjusted_order, risk_metrics)
        """
        risk_metrics = {}
        adjusted_order = None
        working_size = order.size
        
        # Calculate maximum allowed risk amount
        max_risk_amount = account.equity * (self.config.max_risk_per_trade_percent / Decimal('100'))
        risk_metrics['max_risk_amount'] = float(max_risk_amount)
        risk_metrics['equity'] = float(account.equity)
        
        # Check position size limit and cap if needed
        if working_size > self.config.max_position_size:
            working_size = self.config.max_position_size
            risk_metrics['size_capped_to_max'] = True
        
        # Calculate potential loss if stop loss is hit
        if order.stop_loss is not None:
            entry_price = Decimal(str(setup.reference_price))
            sl_price = order.stop_loss
            
            # Calculate SL distance in ticks
            sl_distance = abs(entry_price - sl_price)
            sl_ticks = sl_distance / self.config.tick_size
            risk_metrics['sl_distance'] = float(sl_distance)
            risk_metrics['sl_ticks'] = float(sl_ticks)
            
            # Check minimum SL distance
            if sl_ticks < self.config.sl_min_ticks:
                return (
                    f"Trade denied: SL distance ({sl_ticks:.1f} ticks) below minimum ({self.config.sl_min_ticks} ticks)",
                    None,
                    risk_metrics,
                )
            
            # Calculate potential loss with working size
            potential_loss = sl_ticks * self.config.tick_value * working_size
            risk_metrics['potential_loss'] = float(potential_loss)
            
            # Check if loss exceeds maximum risk
            if potential_loss > max_risk_amount:
                # Try to adjust position size
                max_size = max_risk_amount / (sl_ticks * self.config.tick_value)
                
                if max_size < Decimal('0.1'):  # Too small to trade
                    return (
                        f"Trade denied: SL distance too large → risk > {self.config.max_risk_per_trade_percent}% of equity",
                        None,
                        risk_metrics,
                    )
                
                # Round down to reasonable precision
                working_size = Decimal(str(round(float(max_size), 1)))
                # Cap at max position size
                working_size = min(working_size, self.config.max_position_size)
                risk_metrics['adjusted_size'] = float(working_size)
        
        # If size was adjusted from original, create adjusted order
        if working_size != order.size:
            adjusted_order = self._create_adjusted_order(order, working_size)
        
        risk_metrics['final_size'] = float(working_size)
        return (None, adjusted_order, risk_metrics)

    def _create_adjusted_order(
        self,
        original: OrderRequest,
        new_size: Decimal,
    ) -> OrderRequest:
        """
        Create a copy of the order with adjusted size.
        
        Args:
            original: The original order request.
            new_size: The new position size.
            
        Returns:
            OrderRequest: A new order request with adjusted size.
        """
        return OrderRequest(
            epic=original.epic,
            direction=original.direction,
            size=new_size,
            order_type=original.order_type,
            limit_price=original.limit_price,
            stop_price=original.stop_price,
            stop_loss=original.stop_loss,
            take_profit=original.take_profit,
            guaranteed_stop=original.guaranteed_stop,
            trailing_stop=original.trailing_stop,
            trailing_stop_distance=original.trailing_stop_distance,
            currency=original.currency,
        )

    def calculate_position_size(
        self,
        account: AccountState,
        entry_price: Decimal,
        stop_loss_price: Decimal,
    ) -> Decimal:
        """
        Calculate optimal position size based on risk parameters.
        
        Args:
            account: Current account state.
            entry_price: Planned entry price.
            stop_loss_price: Planned stop loss price.
            
        Returns:
            Decimal: Recommended position size.
        """
        # Calculate maximum risk amount
        max_risk = account.equity * (self.config.max_risk_per_trade_percent / Decimal('100'))
        
        # Calculate SL distance in ticks
        sl_distance = abs(entry_price - stop_loss_price)
        sl_ticks = sl_distance / self.config.tick_size
        
        # Calculate position size
        if sl_ticks <= 0:
            return Decimal('0')
        
        position_size = max_risk / (sl_ticks * self.config.tick_value)
        
        # Apply maximum position size limit
        position_size = min(position_size, self.config.max_position_size)
        
        # Round to one decimal place
        return Decimal(str(round(float(position_size), 1)))
