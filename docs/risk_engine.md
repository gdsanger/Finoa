# Risk Engine Dokumentation

## Inhaltsverzeichnis

1. [Überblick](#überblick)
2. [Architektur und Komponenten](#architektur-und-komponenten)
3. [Risk Evaluation Prozess](#risk-evaluation-prozess)
4. [Validierungen und Prüfungen](#validierungen-und-prüfungen)
5. [Position Sizing](#position-sizing)
6. [Konfiguration](#konfiguration)
7. [Integration mit Strategy Engine](#integration-mit-strategy-engine)
8. [Logging und Diagnostics](#logging-und-diagnostics)
9. [Beispiele](#beispiele)
10. [Best Practices](#best-practices)

---

## Überblick

### Was macht die Risk Engine?

Die **Risk Engine** (`RiskEngine`) ist die zentrale Risikomanagement-Komponente des Fiona Trading-Systems. Sie bewertet vorgeschlagene Trades gegen konfigurierbare Risikolimits und entscheidet, ob ein Trade ausgeführt werden darf.

**Wichtig**: Die Risk Engine trifft KEINE Trading-Entscheidungen darüber, WELCHE Trades eingegangen werden sollen. Sie prüft nur, ob ein vorgeschlagener Trade die definierten Risikoparameter einhält.

### Hauptaufgaben

1. **Risikobewertung**: Prüft jeden vorgeschlagenen Trade gegen Risikolimits
2. **Position Sizing**: Berechnet optimale Positionsgrößen basierend auf Risiko
3. **Loss Protection**: Überwacht tägliche und wöchentliche Verlustlimits
4. **Time-Based Restrictions**: Verhindert Trades zu bestimmten Zeiten (EIA, Wochenende, Freitag abend)
5. **Leverage Management**: Berücksichtigt Hebel bei Margin-Berechnungen
6. **Order Adjustment**: Passt Ordergrößen an, um innerhalb der Limits zu bleiben

### Philosophie: Schutz vor Überrisiko

Die Engine folgt dem Prinzip **"Safety First"**:
- **Strategy Engine**: Identifiziert Trading-Chancen (Setup-Kandidaten)
- **Risk Engine**: Bewertet Risiken und schützt vor Überexposure
- **Execution Service**: Führt genehmigte Trades aus

Die Risk Engine fungiert als **Gatekeeper** zwischen Setup-Erkennung und Trade-Execution.

---

## Architektur und Komponenten

### Hauptklassen

#### 1. RiskEngine

Die zentrale Klasse für alle Risikobewertungen.

```python
class RiskEngine:
    def __init__(self, config: RiskConfig):
        """
        Initialize Risk Engine with configuration.
        
        Args:
            config: Risk configuration defining all limits and rules
        """
```

**Attribute:**
- `config`: RiskConfig-Instanz mit allen Limits und Regeln

**Hauptmethoden:**
- `evaluate()`: Hauptmethode - bewertet einen vorgeschlagenen Trade
- `calculate_position_size()`: Berechnet Positionsgröße basierend auf Risiko
- `calculate_position_size_from_margin()`: Berechnet Positionsgröße basierend auf Margin

#### 2. RiskConfig

Konfigurationsdatenmodell für alle Risikogrenzen.

```python
@dataclass
class RiskConfig:
    # Risk Limits
    max_risk_per_trade_percent: Decimal = Decimal('1.0')
    max_daily_loss_percent: Decimal = Decimal('3.0')
    max_weekly_loss_percent: Decimal = Decimal('6.0')
    
    # Position Limits
    max_open_positions: int = 1
    max_position_size: Decimal = Decimal('5.0')
    
    # Stop Loss/Take Profit
    sl_min_ticks: int = 5
    tp_min_ticks: int = 5
    
    # Time-Based Rules
    deny_eia_window_minutes: int = 5
    deny_friday_after: str = '21:00'
    deny_overnight: bool = True
    
    # Trading Rules
    allow_countertrend: bool = False
    
    # Instrument Settings
    tick_size: Decimal = Decimal('0.1')
    tick_value: Decimal = Decimal('0.1')
    leverage: Decimal = Decimal('20.0')
```

**Factory Methods:**
- `from_dict(data)`: Erstellt Config aus Dictionary
- `from_yaml(path)`: Lädt Config aus YAML-Datei
- `from_yaml_string(yaml_str)`: Lädt Config aus YAML-String

**Utility Methods:**
- `to_dict()`: Serialisiert zu Dictionary
- `to_yaml()`: Serialisiert zu YAML-String
- `get_friday_cutoff_time()`: Gibt Freitag-Cutoff als time-Objekt zurück

#### 3. RiskEvaluationResult

Ergebnis einer Risikobewertung.

```python
@dataclass
class RiskEvaluationResult:
    allowed: bool                           # Ist der Trade erlaubt?
    reason: str                             # Begründung der Entscheidung
    adjusted_order: Optional[OrderRequest]  # Optional angepasste Order
    violations: list                        # Liste aller Regelverstöße
    risk_metrics: dict                      # Berechnete Risikometriken
```

**Wichtig**: Auch wenn `allowed=True`, kann `adjusted_order` gesetzt sein, falls die Positionsgröße reduziert werden musste.

---

## Risk Evaluation Prozess

### Hauptfluss: evaluate()

```
┌─────────────────────────────────────────┐
│ INPUT                                   │
│ - AccountState (Balance, Equity, etc.)  │
│ - Open Positions                        │
│ - SetupCandidate (from Strategy Engine) │
│ - OrderRequest (proposed trade)         │
│ - Context (timestamp, PnL, trend)       │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 1. TIME RESTRICTIONS CHECK              │
│    _check_time_restrictions()           │
│    ├─ EIA Window?                       │
│    ├─ Friday Evening?                   │
│    └─ Weekend?                          │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 2. LOSS LIMITS CHECK                    │
│    _check_loss_limits()                 │
│    ├─ Daily Loss Limit                  │
│    └─ Weekly Loss Limit                 │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 3. OPEN POSITIONS CHECK                 │
│    _check_open_positions()              │
│    └─ Max Open Positions Reached?       │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 4. COUNTERTREND CHECK (optional)        │
│    _check_countertrend()                │
│    └─ Trade against Trend?              │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 5. SL/TP VALIDITY CHECK                 │
│    _check_sltp_validity()               │
│    ├─ Stop Loss set?                    │
│    └─ Minimum distances met?            │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 6. POSITION RISK CHECK                  │
│    _check_position_risk()               │
│    ├─ Calculate potential loss          │
│    ├─ Check vs max risk per trade       │
│    ├─ Adjust position size if needed    │
│    └─ Apply max position size cap       │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 7. BUILD RESULT                         │
│    - If violations: DENIED              │
│    - If adjusted: ALLOWED with new size │
│    - Otherwise: ALLOWED as requested    │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ OUTPUT: RiskEvaluationResult            │
│ - allowed: bool                         │
│ - reason: str                           │
│ - adjusted_order: Optional              │
│ - violations: list                      │
│ - risk_metrics: dict                    │
└─────────────────────────────────────────┘
```

### Wichtige Eigenschaften

1. **Sequentielle Prüfung**: Checks werden in definierter Reihenfolge durchgeführt
2. **Fail-Fast**: Erste Verletzung führt zu Ablehnung
3. **Auto-Adjustment**: Position Size kann automatisch reduziert werden
4. **Comprehensive Logging**: Jede Prüfung wird detailliert geloggt
5. **Metrics Collection**: Alle berechneten Werte werden in `risk_metrics` gesammelt

---

## Validierungen und Prüfungen

### 1. Time-Based Restrictions

**Methode:** `_check_time_restrictions(now, eia_timestamp, setup)`

#### a) EIA Window Protection

**Zweck**: Verhindert Trades kurz vor/nach EIA-Datenveröffentlichung (hohe Volatilität)

**Regel:**
```python
if setup.setup_kind == SetupKind.BREAKOUT:
    window = config.deny_eia_window_minutes
    if eia_time - window <= now <= eia_time + window:
        DENY
```

**Standard**: 5 Minuten vor und nach EIA

**Ausnahme**: EIA-spezifische Setups (EIA_REVERSION, EIA_TRENDDAY) sind NICHT betroffen

#### b) Friday Evening Cutoff

**Zweck**: Verhindert neue Positionen kurz vor Wochenende

**Regel:**
```python
if now.weekday() == 4:  # Friday
    if now.time() >= config.get_friday_cutoff_time():
        DENY
```

**Standard**: 21:00 Uhr CET

**Rationale**: Overnight-Risiko und reduzierte Liquidität

#### c) Weekend Trading Block

**Zweck**: Keine Trades während Marktstillstand

**Regel:**
```python
if now.weekday() >= 5:  # Saturday or Sunday
    DENY
```

---

### 2. Loss Limits

**Methode:** `_check_loss_limits(account, daily_pnl, weekly_pnl)`

#### a) Daily Loss Limit

**Berechnung:**
```python
max_daily_loss = account.equity * (max_daily_loss_percent / 100)
if daily_pnl < -max_daily_loss:
    DENY
```

**Standard**: 3% des Eigenkapitals

**Beispiel**: Bei 10.000€ Equity → Max. -300€ pro Tag

#### b) Weekly Loss Limit

**Berechnung:**
```python
max_weekly_loss = account.equity * (max_weekly_loss_percent / 100)
if weekly_pnl < -max_weekly_loss:
    DENY
```

**Standard**: 6% des Eigenkapitals

**Beispiel**: Bei 10.000€ Equity → Max. -600€ pro Woche

**Wichtig**: Diese Limits schützen vor emotionalem Übertrading nach Verlusten

---

### 3. Position Limits

**Methode:** `_check_open_positions(positions)`

**Regel:**
```python
if len(positions) >= config.max_open_positions:
    DENY
```

**Standard**: 1 Position

**Rationale**: Fokussierung und Risikokontrolle für systematisches Trading

---

### 4. Countertrend Protection

**Methode:** `_check_countertrend(setup, trend_direction)`

**Regel:**
```python
if not config.allow_countertrend:
    if setup.direction != trend_direction:
        DENY
```

**Standard**: `allow_countertrend = False`

**Ausnahme**: EIA-Setups (event-driven, daher exempt)

**Beispiel:**
- Trend: LONG
- Setup: SHORT Breakout
- Ergebnis: DENY (wenn allow_countertrend = False)

---

### 5. Stop Loss / Take Profit Validity

**Methode:** `_check_sltp_validity(order)`

#### a) Stop Loss Requirement

**Regel:**
```python
if order.stop_loss is None:
    DENY "Stop loss is required"
```

**Rationale**: JEDER Trade braucht einen Stop Loss für Risikomanagement

#### b) Minimum SL Distance

**Prüfung:**
```python
sl_distance = abs(entry_price - sl_price)
sl_ticks = sl_distance / tick_size

if sl_ticks < config.sl_min_ticks:
    DENY
```

**Standard**: 5 Ticks

**Rationale**: Zu enge Stops führen zu häufigen Fehlauslösungen

---

### 6. Position Risk Calculation

**Methode:** `_check_position_risk(account, order, setup)`

Dies ist die **wichtigste und komplexeste** Prüfung.

#### Schritt 1: Max Risk Amount

```python
max_risk_amount = account.equity * (max_risk_per_trade_percent / 100)
```

**Standard**: 1% des Eigenkapitals

**Beispiel**: 10.000€ Equity → Max. 100€ Risiko pro Trade

#### Schritt 2: Position Size Cap

```python
working_size = min(order.size, config.max_position_size)
```

**Standard**: 5.0 Lots

#### Schritt 3: SL Distance Calculation

```python
entry_price = setup.reference_price
sl_price = order.stop_loss
sl_distance = abs(entry_price - sl_price)
sl_ticks = sl_distance / config.tick_size
```

#### Schritt 4: Potential Loss

```python
potential_loss = sl_ticks * config.tick_value * working_size
```

**Wichtig**: Diese Berechnung ist **unabhängig von Leverage**!
- Leverage beeinflusst Margin-Anforderungen
- P&L hängt NUR von Preisbewegung, Tick Value und Position Size ab

#### Schritt 5: Risk Check & Adjustment

```python
if potential_loss > max_risk_amount:
    # Calculate max allowed size
    max_size = max_risk_amount / (sl_ticks * tick_value)
    
    if max_size < 0.1:
        DENY "SL distance too large → risk exceeds limit"
    
    # Adjust position size
    working_size = min(max_size, max_position_size)
    adjusted_order = create_adjusted_order(working_size)
```

#### Risk Metrics Collected

```python
risk_metrics = {
    'max_risk_amount': float,        # Max erlaubtes Risiko in €
    'equity': float,                 # Account Equity
    'leverage': float,               # Configured Leverage
    'sl_distance': float,            # SL Distanz in Preis
    'sl_ticks': float,               # SL Distanz in Ticks
    'potential_loss': float,         # Berechneter Verlust bei SL
    'final_size': float,             # Finale Positionsgröße
    'adjusted_size': float,          # Falls angepasst
    'size_capped_to_max': bool,     # Falls auf Max gekappt
}
```

---

## Position Sizing

Die Risk Engine bietet zwei Methoden zur Position Size Calculation:

### 1. Risk-Based Position Sizing (Primary)

**Methode:** `calculate_position_size(account, entry_price, stop_loss_price)`

**Konzept**: Berechnet Position Size basierend auf maximalem Risiko pro Trade

**Formel:**
```python
max_risk = account.equity * (max_risk_per_trade_percent / 100)
sl_distance = abs(entry_price - stop_loss_price)
sl_ticks = sl_distance / tick_size
position_size = max_risk / (sl_ticks * tick_value)
position_size = min(position_size, max_position_size)
```

**Beispiel:**
```
Equity: 10,000€
Max Risk: 1% = 100€
Entry: 75.00
Stop Loss: 74.50
SL Distance: 0.50 = 50 Ticks
Tick Value: 0.1€

Position Size = 100€ / (50 * 0.1€) = 100€ / 5€ = 20 Lots
```

**Wichtig**: Diese Methode ist **leverage-unabhängig** für P&L-Berechnungen!

### 2. Margin-Based Position Sizing (Alternative)

**Methode:** `calculate_position_size_from_margin(account, entry_price, max_margin_percent=5.0)`

**Konzept**: Berechnet Position Size basierend auf verfügbarer Margin und Leverage

**Formel:**
```python
max_margin_to_use = margin_available * (max_margin_percent / 100)
notional_value = max_margin_to_use * leverage
position_size = notional_value / entry_price
position_size = min(position_size, max_position_size)
```

**Beispiel mit 1:20 Leverage:**
```
Margin Available: 10,000€
Max Margin to Use (5%): 500€
Leverage: 20
Notional Value: 500€ * 20 = 10,000€
Entry Price: 75€
Position Size: 10,000€ / 75€ = 133.33 Lots
```

**Verwendung**: Diese Methode ist nützlich für:
- Margin-basierte Trading-Strategien
- Maximierung der Kapitaleffizienz
- Situations wo Risk-Based Sizing zu konservativ ist

**Warnung**: Kann zu höherem Risiko führen wenn SL weit ist!

### Leverage Verständnis

**Wichtig**: Leverage beeinflusst NUR die Margin-Anforderungen, NICHT das P&L-Risiko!

**Mit 1:1 Leverage (kein Hebel):**
- 1 Lot bei 75€ → 75€ Margin benötigt
- Preisbewegung 1€ → P&L = 1€ * tick_value * 1 Lot

**Mit 1:20 Leverage:**
- 1 Lot bei 75€ → 75€ / 20 = 3.75€ Margin benötigt
- Preisbewegung 1€ → P&L = 1€ * tick_value * 1 Lot (gleich!)

**Leverage-Effekte:**
- ✓ Reduziert Margin-Anforderungen
- ✓ Ermöglicht größere Positionen mit gleichem Kapital
- ✗ ERHÖHT RISIKO wenn nicht korrekt managed
- ✗ Vergrößert sowohl Gewinne als auch Verluste

---

## Konfiguration

### RiskConfig Struktur

```yaml
# Risk Limits
max_risk_per_trade_percent: 1.0    # Max 1% risk per trade
max_daily_loss_percent: 3.0        # Max 3% daily loss
max_weekly_loss_percent: 6.0       # Max 6% weekly loss

# Position Limits
max_open_positions: 1              # Max 1 concurrent position
max_position_size: 5.0             # Max 5 lots per position

# Stop Loss / Take Profit
sl_min_ticks: 5                    # Min 5 ticks SL distance
tp_min_ticks: 5                    # Min 5 ticks TP distance

# Time-Based Rules
deny_eia_window_minutes: 5         # No trades 5 min before/after EIA
deny_friday_after: "21:00"         # No new trades Friday after 21:00
deny_overnight: true               # Close positions before EOD

# Trading Rules
allow_countertrend: false          # Deny countertrend trades

# Instrument Settings (WTI Crude Oil Example)
tick_size: 0.1                     # 0.1 per tick
tick_value: 0.1                    # 0.1€ per tick (mini contract)
leverage: 20.0                     # 1:20 leverage
```

### Config Loading

#### Aus YAML-Datei:
```python
config = RiskConfig.from_yaml('risk_config.yaml')
```

#### Aus Dictionary:
```python
data = {
    'max_risk_per_trade_percent': 1.5,
    'max_daily_loss_percent': 4.0,
    # ...
}
config = RiskConfig.from_dict(data)
```

#### Aus YAML-String:
```python
yaml_str = """
max_risk_per_trade_percent: 1.0
max_open_positions: 1
"""
config = RiskConfig.from_yaml_string(yaml_str)
```

### Config Anpassungen

#### Konservatives Profil (Anfänger)
```yaml
max_risk_per_trade_percent: 0.5    # Sehr geringes Risiko
max_daily_loss_percent: 1.5
max_weekly_loss_percent: 3.0
max_open_positions: 1
allow_countertrend: false
deny_overnight: true
```

#### Aggressives Profil (Erfahren)
```yaml
max_risk_per_trade_percent: 2.0    # Höheres Risiko
max_daily_loss_percent: 5.0
max_weekly_loss_percent: 10.0
max_open_positions: 3
allow_countertrend: true           # Erlaubt Countertrend
deny_overnight: false              # Erlaubt Overnight
```

---

## Integration mit Strategy Engine

### Workflow Integration

```python
# 1. Strategy Engine identifiziert Setup
setup_candidates = strategy_engine.evaluate(epic, timestamp)

for setup in setup_candidates:
    # 2. Create Order Request basierend auf Setup
    order = OrderRequest(
        epic=setup.epic,
        direction=OrderDirection.BUY if setup.direction == "LONG" else OrderDirection.SELL,
        size=Decimal('1.0'),  # Initial size
        order_type=OrderType.MARKET,
        stop_loss=calculate_stop_loss(setup),
        take_profit=calculate_take_profit(setup),
    )
    
    # 3. Risk Engine bewertet Trade
    risk_result = risk_engine.evaluate(
        account=get_account_state(),
        positions=get_open_positions(),
        setup=setup,
        order=order,
        now=datetime.now(timezone.utc),
        eia_timestamp=get_next_eia_time(),
        daily_pnl=calculate_daily_pnl(),
        weekly_pnl=calculate_weekly_pnl(),
        trend_direction=get_trend_direction(),
    )
    
    # 4. Handle Result
    if risk_result.allowed:
        if risk_result.adjusted_order:
            # Position size was reduced
            order = risk_result.adjusted_order
            logger.info(f"Order adjusted: size reduced to {order.size}")
        
        # Execute trade
        execution_service.execute(order)
    else:
        # Trade denied
        logger.warning(f"Trade denied: {risk_result.reason}")
        logger.debug(f"Violations: {risk_result.violations}")
```

### Datenfluss

```
┌──────────────────┐
│ Market Data      │
└────────┬─────────┘
         │
         v
┌──────────────────┐
│ Strategy Engine  │  → SetupCandidate
└────────┬─────────┘
         │
         v
┌──────────────────┐
│ Order Creation   │  → OrderRequest
└────────┬─────────┘
         │
         v
┌──────────────────┐
│   Risk Engine    │  → RiskEvaluationResult
│   ┌──────────┐   │     ├─ allowed: bool
│   │ evaluate │   │     ├─ reason: str
│   └──────────┘   │     ├─ adjusted_order
│                  │     ├─ violations
└────────┬─────────┘     └─ risk_metrics
         │
         v
    ┌────────┐
    │allowed?│
    └───┬────┘
        │
    ┌───┴────┐
    │        │
   YES       NO
    │        │
    v        v
┌────────┐ ┌──────────┐
│Execute │ │  Reject  │
└────────┘ └──────────┘
```

---

## Logging und Diagnostics

### Logging Levels

Die Risk Engine verwendet strukturiertes Logging mit verschiedenen Levels:

#### DEBUG Level
- Account State Details
- Risk Metrics Calculations
- Position Size Adjustments

```python
logger.debug(
    "Risk evaluation: account state",
    extra={
        "risk_data": {
            "equity": float(account.equity),
            "max_risk_amount": float(max_risk_amount),
            # ...
        }
    }
)
```

#### INFO Level
- Individual Check Violations
- Rule Enforcement Actions

```python
logger.info(
    f"Risk check: time restriction violated - {reason}",
    extra={
        "risk_data": {
            "check": "time_restrictions",
            "result": "denied",
            "reason": time_result,
            # ...
        }
    }
)
```

#### WARNING Level
- Trade Denials
- Account Issues (zero equity)

```python
logger.warning(
    f"Risk evaluation: trade DENIED - {violations[0]}",
    extra={
        "risk_data": {
            "result": "denied",
            "primary_reason": violations[0],
            "all_violations": violations,
            # ...
        }
    }
)
```

### Structured Logging

Alle Logs enthalten strukturierte `risk_data`:

```python
{
    "risk_data": {
        "setup_id": str,              # Setup Candidate ID
        "epic": str,                  # Trading Instrument
        "direction": str,             # LONG/SHORT
        "size": float,                # Position Size
        "timestamp": str,             # ISO timestamp
        "account_equity": float,      # Current Equity
        "open_positions": int,        # Number of open positions
        "check": str,                 # Which check
        "result": str,                # allowed/denied
        "reason": str,                # Detailed reason
        "risk_metrics": dict,         # Calculated metrics
    }
}
```

### Risk Metrics Output

```python
risk_metrics = {
    'max_risk_amount': 100.0,          # €
    'equity': 10000.0,                 # €
    'leverage': 20.0,                  # 1:20
    'sl_distance': 0.5,                # Price units
    'sl_ticks': 50.0,                  # Ticks
    'potential_loss': 50.0,            # €
    'final_size': 2.0,                 # Lots
    'adjusted_size': 2.0,              # If adjusted
    'size_capped_to_max': False,      # Bool
}
```

---

## Beispiele

### Beispiel 1: Trade Approved (Keine Anpassung)

**Szenario:**
```python
account = AccountState(
    equity=Decimal('10000.00'),
    available=Decimal('9500.00'),
)
setup = SetupCandidate(
    direction='LONG',
    reference_price=75.00,
    # ...
)
order = OrderRequest(
    size=Decimal('1.0'),
    stop_loss=Decimal('74.50'),
    # ...
)
```

**Risk Evaluation:**
```
Max Risk: 10,000€ * 1% = 100€
SL Distance: 75.00 - 74.50 = 0.50 = 50 Ticks
Potential Loss: 50 * 0.1€ * 1.0 = 5€
Check: 5€ < 100€ ✓

Time Check: OK ✓
Loss Limits: OK ✓
Position Limit: OK ✓
```

**Result:**
```python
RiskEvaluationResult(
    allowed=True,
    reason="Trade meets all risk requirements",
    adjusted_order=None,
    violations=[],
    risk_metrics={...}
)
```

---

### Beispiel 2: Trade Adjusted (Size Reduced)

**Szenario:**
```python
account = AccountState(equity=Decimal('10000.00'))
order = OrderRequest(
    size=Decimal('5.0'),        # Initial: 5 Lots
    stop_loss=Decimal('74.00'),  # Wide SL!
)
setup.reference_price = 75.00
```

**Risk Evaluation:**
```
Max Risk: 10,000€ * 1% = 100€
SL Distance: 75.00 - 74.00 = 1.00 = 100 Ticks
Potential Loss: 100 * 0.1€ * 5.0 = 50€
Check: 50€ < 100€ ✓

BUT: Let's say original was larger...
Original Size: 5.0 Lots
Potential Loss: 100 * 0.1€ * 5.0 = 50€ ... OK

Actually, if size was 3.0:
Potential Loss: 100 * 0.1€ * 3.0 = 30€ ... OK

Let's use realistic numbers:
Size: 5.0, SL: 74.00
Potential Loss: 100 * 0.1 * 5.0 = 50€ < 100€ ✓
```

**Better Example for Adjustment:**
```
Initial Size: 10.0 Lots
SL Distance: 100 Ticks
Potential Loss: 100 * 0.1€ * 10.0 = 100€
Check: 100€ = 100€ (borderline)

If size was 15.0:
Potential Loss: 100 * 0.1€ * 15.0 = 150€
Check: 150€ > 100€ ✗

Max Allowed Size: 100€ / (100 * 0.1€) = 10.0 Lots
Adjusted: 15.0 → 10.0 Lots
```

**Result:**
```python
RiskEvaluationResult(
    allowed=True,
    reason="Position size reduced to fit risk limits",
    adjusted_order=OrderRequest(size=Decimal('10.0')),
    violations=[],
    risk_metrics={'adjusted_size': 10.0, ...}
)
```

---

### Beispiel 3: Trade Denied (Daily Loss Limit)

**Szenario:**
```python
account = AccountState(equity=Decimal('10000.00'))
daily_pnl = Decimal('-350.00')  # Already lost 350€ today!
```

**Risk Evaluation:**
```
Max Daily Loss: 10,000€ * 3% = 300€
Current Daily PnL: -350€
Check: -350€ < -300€ ✗

DENIED!
```

**Result:**
```python
RiskEvaluationResult(
    allowed=False,
    reason="Trade denied: Daily loss limit exceeded (3%)",
    adjusted_order=None,
    violations=["Daily loss limit exceeded (3%)"],
    risk_metrics={...}
)
```

---

### Beispiel 4: Trade Denied (EIA Window)

**Szenario:**
```python
now = datetime(2024, 12, 9, 15, 28, 0, tzinfo=timezone.utc)
eia_timestamp = datetime(2024, 12, 9, 15, 30, 0, tzinfo=timezone.utc)
setup.setup_kind = SetupKind.BREAKOUT
config.deny_eia_window_minutes = 5
```

**Risk Evaluation:**
```
EIA Time: 15:30
Window: ±5 minutes = 15:25 to 15:35
Current Time: 15:28
Check: 15:28 in [15:25, 15:35] ✗

DENIED!
```

**Result:**
```python
RiskEvaluationResult(
    allowed=False,
    reason="Trade denied: Within EIA window (5 min before/after)",
    adjusted_order=None,
    violations=["Within EIA window (5 min before/after)"],
    risk_metrics={...}
)
```

---

### Beispiel 5: Trade Denied (Stop Loss Too Tight)

**Szenario:**
```python
order = OrderRequest(
    stop_loss=Decimal('74.96'),  # Too tight!
)
setup.reference_price = 75.00
config.sl_min_ticks = 5
config.tick_size = Decimal('0.1')
```

**Risk Evaluation:**
```
Entry: 75.00
SL: 74.96
Distance: 0.04 = 4 Ticks
Min Required: 5 Ticks
Check: 4 < 5 ✗

DENIED!
```

**Result:**
```python
RiskEvaluationResult(
    allowed=False,
    reason="Trade denied: SL distance (4.0 ticks) below minimum (5 ticks)",
    adjusted_order=None,
    violations=["SL distance below minimum"],
    risk_metrics={'sl_ticks': 4.0, ...}
)
```

---

### Beispiel 6: Position Sizing Calculation

**Scenario A: Risk-Based Sizing**
```python
account = AccountState(equity=Decimal('10000.00'))
entry_price = Decimal('75.00')
stop_loss = Decimal('74.50')

size = risk_engine.calculate_position_size(
    account, entry_price, stop_loss
)

# Calculation:
# Max Risk: 10,000€ * 1% = 100€
# SL Distance: 0.50 = 50 Ticks
# Size: 100€ / (50 * 0.1€) = 20.0 Lots
```

**Result:** `size = 20.0 Lots`

**Scenario B: Margin-Based Sizing (1:20 Leverage)**
```python
account = AccountState(
    equity=Decimal('10000.00'),
    available=Decimal('9500.00'),
)
entry_price = Decimal('75.00')

size = risk_engine.calculate_position_size_from_margin(
    account, entry_price, max_margin_percent=Decimal('5.0')
)

# Calculation:
# Available: 9,500€
# Max Margin: 9,500€ * 5% = 475€
# Notional: 475€ * 20 = 9,500€
# Size: 9,500€ / 75€ = 126.67 Lots
# Capped at max_position_size (5.0): 5.0 Lots
```

**Result:** `size = 5.0 Lots` (capped)

---

## Best Practices

### 1. Configuration Management

**DO:**
- ✓ Store configs in version control (YAML files)
- ✓ Use different configs for paper trading vs live
- ✓ Document why each parameter is set to its value
- ✓ Start conservative and adjust based on data

**DON'T:**
- ✗ Hardcode risk parameters in code
- ✗ Use same config for all instruments
- ✗ Change limits emotionally after losses
- ✗ Disable safety checks "temporarily"

### 2. Risk Parameter Selection

**Max Risk Per Trade:**
- Beginners: 0.5% - 1.0%
- Intermediate: 1.0% - 1.5%
- Advanced: 1.5% - 2.0%
- Never: > 3.0%

**Max Daily Loss:**
- Should be 2-3x max risk per trade
- Prevents revenge trading
- Typical: 2% - 5%

**Max Weekly Loss:**
- Should be 2x daily loss limit
- Prevents strategy deterioration
- Typical: 4% - 10%

### 3. Leverage Usage

**Guidelines:**
- Understand that leverage multiplies both gains AND losses
- Higher leverage = lower margin, but same P&L per move
- Use risk-based position sizing, not margin-based
- Margin-based sizing only for specific strategies
- Never use max leverage available

**Example Comparison:**
```
Scenario: 10,000€ capital, 75€ entry

1:1 Leverage (No Leverage):
- Can buy: 10,000€ / 75€ = 133 Lots
- Margin per Lot: 75€

1:20 Leverage:
- Can buy: 10,000€ * 20 / 75€ = 2,666 Lots (!!!)
- Margin per Lot: 3.75€
- Risk: EXTREMELY HIGH if not properly sized!

Proper Approach with Risk-Based Sizing:
- Max Risk: 1% = 100€
- SL: 50 Ticks
- Max Size: 100€ / (50 * 0.1€) = 20 Lots
- Margin Needed (1:20): 20 * 3.75€ = 75€
- Safe and controlled!
```

### 4. Stop Loss Management

**Best Practices:**
- Always use a stop loss
- Place based on technical levels, not arbitrary distances
- Respect minimum SL distance (prevent noise)
- Don't move SL against your position
- Consider volatility (ATR-based stops)

### 5. Monitoring and Alerts

**Setup Alerts For:**
- Daily loss limit approaching (e.g., 80%)
- Weekly loss limit approaching
- Multiple trade denials (config issue?)
- Zero equity warnings
- Unusual risk metrics

### 6. Testing

**Before Going Live:**
- Test with historical data
- Run paper trading for 2+ weeks
- Verify all deny scenarios work
- Check position sizing calculations
- Test edge cases (zero equity, weekend, etc.)

### 7. Logging Analysis

**Regular Review:**
- Check denied trades and reasons
- Analyze risk metrics distributions
- Monitor position size adjustments
- Review loss limit hits
- Track time-based denials

### 8. Integration Points

**Critical Checks:**
- Verify account state updates correctly
- Ensure PnL calculations are accurate
- Confirm EIA timestamp is current
- Validate trend direction updates
- Test setup candidate quality

---

## Zusammenfassung

### Kernprinzipien

1. **Safety First**: Risk Engine ist der Gatekeeper für alle Trades
2. **Risk-Based Sizing**: Position Size basiert auf Risiko, nicht auf Kapital
3. **Multi-Layer Protection**: Mehrere unabhängige Checks
4. **Automated Adjustment**: Engine passt Orders automatisch an wenn möglich
5. **Comprehensive Logging**: Volle Transparenz über alle Entscheidungen
6. **Configuration-Driven**: Alle Parameter zentral konfigurierbar

### Datenfluss (Zusammenfassung)

```
Market Data → Strategy Engine → SetupCandidate
                                      ↓
                                 OrderRequest
                                      ↓
                               Risk Engine
                                      ↓
                           RiskEvaluationResult
                                      ↓
                          Execution Service (if allowed)
```

### Entscheidungslogik

```
ALL checks must pass:
  ✓ Time restrictions
  ✓ Loss limits
  ✓ Position limits
  ✓ Countertrend rules
  ✓ SL/TP validity
  ✓ Position risk

IF any fails → DENY
IF position too large → ADJUST (if possible)
IF all pass → ALLOW
```

### Wichtigste Funktionen

- `RiskEngine.evaluate()`: Hauptbewertungsmethode
- `RiskEngine.calculate_position_size()`: Risk-based sizing
- `RiskEngine.calculate_position_size_from_margin()`: Margin-based sizing
- `RiskConfig.from_yaml()`: Config loading
- `RiskEvaluationResult.to_dict()`: Result serialization

### Key Takeaways

1. Risk Engine schützt vor Überrisiko, trifft aber KEINE Trading-Entscheidungen
2. Leverage beeinflusst Margin, NICHT P&L-Risiko
3. Risk-based position sizing ist der Standard-Ansatz
4. Multi-layer checks bieten comprehensive protection
5. Automated adjustment reduziert Trade-Denials
6. Comprehensive logging ermöglicht volle Nachvollziehbarkeit

---

**Version:** 1.0  
**Letzte Aktualisierung:** Dezember 2024  
**Autor:** Fiona Trading System Team
