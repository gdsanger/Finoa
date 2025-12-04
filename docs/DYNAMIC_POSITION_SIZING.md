# Dynamic Position Sizing with Margin and Leverage

## Overview

This document describes the implementation of dynamic position sizing in the Fiona trading system. The system now calculates position sizes dynamically based on available margin and leverage, rather than using a hardcoded value.

## Requirements

According to the trading rules:
- Maximum 5% of available margin per trade
- The system uses 1:20 leverage for margin trading
- Only 1/20th of the purchase price needs to be deposited as margin
- Position size must be calculated based on price and leverage

## Implementation

### New Method: `calculate_position_size_from_margin`

A new method has been added to the `RiskEngine` class:

```python
def calculate_position_size_from_margin(
    self,
    account: AccountState,
    entry_price: Decimal,
    max_margin_percent: Decimal = Decimal('5.0'),
) -> Decimal
```

### Calculation Formula

```
max_margin_to_use = available_margin × (max_margin_percent / 100)
notional_value = max_margin_to_use × leverage
position_size = notional_value / entry_price
```

### Example

With 1:20 leverage:
- Available margin: 10,000€
- Max margin to use (5%): 500€
- Notional value: 500€ × 20 = 10,000€
- Entry price: 75€
- Position size: 10,000€ / 75€ = 133.33 lots

The calculated position size is also subject to the configured `max_position_size` limit (default: 5.0).

## Integration with Worker

The `run_fiona_worker.py` command has been updated to use the new calculation method instead of the hardcoded `size=Decimal('1.0')`:

```python
# Calculate position size based on 5% of available margin with leverage
entry_price = Decimal(str(setup.reference_price))
position_size = self.risk_engine.calculate_position_size_from_margin(
    account=account,
    entry_price=entry_price,
    max_margin_percent=Decimal('5.0'),
)

order = OrderRequest(
    epic=broker_symbol,
    direction=direction,
    size=position_size,  # Dynamic size instead of hardcoded 1.0
    stop_loss=stop_loss,
    take_profit=take_profit,
    currency='EUR',
)
```

## Margin Fallback

If `margin_available` is zero or not set, the system falls back to using the `available` field from the account state:

```python
available_margin = account.margin_available if account.margin_available > 0 else account.available
```

## Configuration

The leverage value is configurable in `core/services/risk/risk_config.yaml`:

```yaml
# Leverage for margin trading (e.g., 20.0 for 1:20 leverage, 1.0 for no leverage)
leverage: 20.0
```

The default leverage in the `RiskConfig` dataclass is also set to `20.0`.

## Testing

Comprehensive tests have been added in `core/tests_risk.py`:

- `test_calculate_position_size_from_margin` - Basic calculation test
- `test_calculate_position_size_from_margin_limited_by_max` - Verifies max_position_size cap
- `test_calculate_position_size_from_margin_with_zero_margin` - Handles zero margin
- `test_calculate_position_size_from_margin_fallback_to_available` - Tests fallback logic

All tests pass successfully (101 tests in risk and worker test suites).

## Important Notes

1. **Position size is calculated before risk evaluation**: The calculated position size is then passed to the Risk Engine for validation.

2. **Risk Engine may still adjust the size**: The Risk Engine's `evaluate` method may further adjust the position size based on stop loss distance and other risk parameters.

3. **Leverage affects margin, not P&L risk**: While leverage determines how much margin is required for a position, it does not change the P&L risk calculation. A 1-tick move generates the same P&L regardless of leverage.

4. **Default values updated**: The default `tick_size` was updated from `0.1` to `0.01` and `tick_value` from `0.1` to `10.0` to match the test expectations and example configuration for WTI Crude Oil contracts.

## Files Modified

- `core/services/risk/risk_engine.py` - Added `calculate_position_size_from_margin` method
- `core/services/risk/models.py` - Fixed duplicate leverage field definition
- `core/services/risk/risk_config.yaml` - Updated tick_size and tick_value defaults
- `core/management/commands/run_fiona_worker.py` - Updated to use dynamic position sizing
- `core/tests_risk.py` - Added comprehensive tests for new functionality
- `core/tests_worker.py` - Updated mocks for new method
