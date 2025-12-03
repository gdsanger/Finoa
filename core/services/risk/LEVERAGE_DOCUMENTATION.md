# Leverage in the Risk Engine

## Overview

The Risk Engine now supports leverage configuration for margin trading. This document explains how leverage is handled and why the implementation is correct for risk management.

## Configuration

Add the `leverage` parameter to your `risk_config.yaml`:

```yaml
# Leverage for margin trading (e.g., 20.0 for 1:20 leverage, 1.0 for no leverage)
leverage: 20.0
```

- **Default**: 1.0 (no leverage)
- **Example**: 20.0 means 1:20 leverage (you can control $20 with $1 of margin)

## How Leverage Works

### Margin vs. Risk

It's crucial to understand that **leverage affects margin requirements, NOT profit/loss risk**:

1. **Margin Requirement** = Notional Value / Leverage
   - With 1:1 leverage: $10,000 position requires $10,000 margin
   - With 1:20 leverage: $10,000 position requires $500 margin

2. **P&L (Risk)** = Price Movement × Contract Size × Position Size
   - **This is INDEPENDENT of leverage!**
   - If price moves against you by $10, you lose $10 regardless of leverage

### Position Sizing with Leverage

The Risk Engine calculates position size based on **P&L risk**, not margin:

```python
# Example: Trading WTI Crude Oil
equity = $10,000
max_risk = 1% of equity = $100
entry_price = $75.50
stop_loss = $75.40  # 10 ticks away
tick_value = $10 per tick

# Calculate position size
sl_ticks = 10 ticks
risk_per_contract = 10 ticks × $10/tick = $100
max_position_size = $100 / $100 = 1.0 contract

# This is the same for both 1:1 and 1:20 leverage!
# Why? Because the P&L risk is the same.
```

### Leverage with 1:1 (No Leverage)
- Margin required: 1.0 × $75.50 × (contract multiplier) = Full notional value
- Max position from margin: Limited by available capital
- Max position from risk: 1.0 contract (as calculated above)
- **Actual position**: Minimum of the two = depends on capital

### Leverage with 1:20
- Margin required: 1.0 × $75.50 × (contract multiplier) / 20 = 1/20th notional
- Max position from margin: 20x more than without leverage
- Max position from risk: 1.0 contract (SAME as before!)
- **Actual position**: Minimum of the two = 1.0 contract (limited by risk)

## Key Principles

1. **Risk-Based Position Sizing**: The Risk Engine sizes positions to keep potential loss within configured limits (e.g., 1% of equity). This is correct and should NOT be changed.

2. **Leverage Enables Larger Positions**: With high leverage, you CAN trade larger positions with the same capital, but the Risk Engine will still limit you based on P&L risk.

3. **Protection Against Overtrading**: Even with 1:20 leverage, if your risk tolerance is 1% ($100), you won't be allowed to take a position that could lose more than $100 if your stop loss is hit.

4. **Margin is Separate**: The Risk Engine focuses on P&L risk. Brokers will separately check if you have sufficient margin. If you don't have enough margin for the risk-calculated position size, the broker will reject the order.

## Example Scenarios

### Scenario 1: Conservative Trading with Leverage
- Equity: $10,000
- Max risk: 1% = $100
- Leverage: 1:20
- Entry: $75.50, SL: $75.40 (10 ticks)
- **Result**: Position size = 1.0 contract (risk-limited, not margin-limited)
- **Margin used**: ~$378 (plenty of margin available)

### Scenario 2: Aggressive Stop Loss
- Equity: $10,000
- Max risk: 1% = $100  
- Leverage: 1:20
- Entry: $75.50, SL: $74.50 (100 ticks!)
- **Result**: Position size = 0.1 contracts (risk-limited to stay within 1% risk)
- **Margin used**: ~$38 (still protected from large loss)

### Scenario 3: Without Leverage
- Equity: $10,000
- Max risk: 1% = $100
- Leverage: 1:1
- Entry: $75.50, SL: $75.40 (10 ticks)
- **Result**: Position size = 1.0 contract (same as with leverage!)
- **Margin used**: ~$7,550 (might be rejected if insufficient margin)

## Why This Implementation is Correct

The Risk Engine's job is to **protect you from excessive losses**, not to maximize position sizes. By calculating positions based on P&L risk:

1. ✅ You're protected from overleveraging (a common cause of account blowups)
2. ✅ Your risk is consistent and predictable (always ≤ max_risk_per_trade_percent)
3. ✅ The system works correctly for both leveraged and non-leveraged trading
4. ✅ Margin constraints are handled separately by the broker

If you want to trade more aggressively with leverage, increase your `max_risk_per_trade_percent`, but understand this increases your risk of losses.

## Leverage in Risk Metrics

The `leverage` value is now included in risk evaluation metrics for transparency:

```python
result.risk_metrics['leverage']  # e.g., 20.0
```

This helps with:
- Logging and auditing
- Understanding margin usage
- Debugging position sizing issues

## Common Misconceptions

### ❌ Wrong: "With 1:20 leverage, position sizes should be 20x larger"
**Reality**: Position sizes are based on P&L risk, not margin. The risk is the same regardless of leverage.

### ❌ Wrong: "The Risk Engine needs to multiply position size by leverage"  
**Reality**: This would expose you to 20x more risk, which defeats the purpose of risk management.

### ✅ Correct: "Leverage allows me to trade the same position size with less capital"
**Reality**: Yes! This is the benefit of leverage - better capital efficiency, not larger risk exposure.

## Further Reading

- `risk_config.yaml` - Configuration file with leverage setting
- `risk_engine.py` - Implementation of leverage-aware risk calculations
- `tests_risk.py` - Test cases demonstrating leverage behavior
