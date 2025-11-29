# Risk Engine – Dokumentation

## Übersicht

Die **Risk Engine** ist die zentrale Risikomanagement-Komponente im Fiona Trading-System. Sie evaluiert jeden Trade gegen konfigurierbare Risikolimits und entscheidet, ob ein Trade ausgeführt werden darf.

> ⚠️ **Wichtig**: Die Risk Engine ist **deterministisch** – KI darf die Risk-Limits niemals überschreiben. Die Risk Engine hat das letzte Wort über jeden Trade.

---

## Inhaltsverzeichnis

1. [Kernprinzipien](#kernprinzipien)
2. [Architektur](#architektur)
3. [Datenmodelle](#datenmodelle)
4. [YAML-Konfiguration](#yaml-konfiguration)
5. [Risiko-Prüfungen im Detail](#risiko-prüfungen-im-detail)
6. [Positions-Größenberechnung](#positions-größenberechnung)
7. [Integration mit anderen Layern](#integration-mit-anderen-layern)
8. [Diagnostik und Debugging](#diagnostik-und-debugging)
9. [Beispiele](#beispiele)
10. [Fehlerbehebung](#fehlerbehebung)

---

## Kernprinzipien

### Was die Risk Engine macht

- ✅ **Evaluiert** jeden Trade-Vorschlag gegen konfigurierbare Limits
- ✅ **Entscheidet** `allowed = true/false` für jeden Trade
- ✅ **Berechnet** optimale Positionsgrößen basierend auf Risiko
- ✅ **Passt an** – reduziert Positionsgrößen bei Bedarf automatisch
- ✅ **Protokolliert** alle Entscheidungen mit strukturiertem Logging

### Was die Risk Engine NICHT macht

- ❌ **Keine Trading-Signale** – das ist Aufgabe der Strategy Engine
- ❌ **Keine Order-Ausführung** – das übernimmt der Execution Layer
- ❌ **Keine KI-Entscheidungen** – alle Regeln sind deterministisch

### Das 1%-Risiko-Prinzip

Die Risk Engine basiert auf dem bewährten Risikomanagement-Prinzip:

> **Maximal 1% des Kontostands darf pro Trade riskiert werden.**

Beispiel bei 10.000€ Kontostand:
- Maximales Risiko pro Trade: 100€
- Stop-Loss 50 Ticks entfernt, Tick-Wert 10€
- → Potentieller Verlust pro Kontrakt: 500€
- → Maximale Positionsgröße: 100€ / 500€ = **0.2 Kontrakte**

---

## Architektur

### Komponenten der Risk Engine

```
core/services/risk/
├── __init__.py              # Modul-Exporte
├── models.py                # RiskConfig, RiskEvaluationResult
├── risk_engine.py           # Hauptlogik der Risk Engine
├── risk_config.yaml         # Produktiv-Konfiguration
└── risk_config.example.yaml # Beispiel-Konfiguration
```

### Datenfluss

```
┌─────────────────────┐
│  Strategy Engine    │  → SetupCandidate
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Account State     │  → Balance, Equity, Positionen
│   (Broker Service)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    Risk Engine      │  ← Evaluierung gegen alle Limits
│    (RiskConfig)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ RiskEvaluationResult│  → allowed/denied + Begründung
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Execution Layer    │  → Trade ausführen oder ablehnen
└─────────────────────┘
```

### Prüfreihenfolge

Die Risk Engine prüft in folgender Reihenfolge:

1. **Zeitbasierte Einschränkungen** (Wochenende, Freitag-Cutoff, EIA-Fenster)
2. **Verlustlimits** (Tages- und Wochenverlust)
3. **Positionslimits** (maximale offene Positionen)
4. **Trendrichtung** (Countertrend-Regel)
5. **Stop-Loss/Take-Profit-Validierung**
6. **Positionsgröße und Risiko pro Trade**

Bei der ersten Verletzung wird der Trade abgelehnt. Alle Verletzungen werden protokolliert.

---

## Datenmodelle

### RiskConfig

Die Hauptkonfiguration für alle Risikolimits:

```python
from core.services.risk import RiskConfig

# Standard-Konfiguration
config = RiskConfig()

# Aus YAML-Datei laden
config = RiskConfig.from_yaml('core/services/risk/risk_config.yaml')

# Aus Dictionary erstellen
config = RiskConfig.from_dict({
    'max_risk_per_trade_percent': 1.0,
    'max_daily_loss_percent': 3.0,
    'max_open_positions': 1,
})
```

#### Alle Attribute

| Attribut | Typ | Default | Beschreibung |
|----------|-----|---------|--------------|
| `max_risk_per_trade_percent` | Decimal | 1.0 | Max. Risiko pro Trade in % des Equity |
| `max_daily_loss_percent` | Decimal | 3.0 | Max. Tagesverlust in % des Equity |
| `max_weekly_loss_percent` | Decimal | 6.0 | Max. Wochenverlust in % des Equity |
| `max_open_positions` | int | 1 | Max. gleichzeitig offene Positionen |
| `allow_countertrend` | bool | False | Trades gegen den Trend erlauben |
| `max_position_size` | Decimal | 5.0 | Max. Positionsgröße (Kontrakte) |
| `sl_min_ticks` | int | 5 | Min. Stop-Loss-Distanz in Ticks |
| `tp_min_ticks` | int | 5 | Min. Take-Profit-Distanz in Ticks |
| `deny_eia_window_minutes` | int | 5 | Sperrfenster vor/nach EIA (Minuten) |
| `deny_friday_after` | str | "21:00" | Keine neuen Trades nach dieser Zeit am Freitag |
| `deny_overnight` | bool | True | Overnight-Positionen verbieten |
| `tick_size` | Decimal | 0.01 | Tick-Größe des Instruments |
| `tick_value` | Decimal | 10.0 | Wert eines Ticks in Kontowährung |

#### Methoden

```python
# Zu Dictionary konvertieren
data = config.to_dict()

# Zu YAML-String konvertieren
yaml_str = config.to_yaml()

# Freitag-Cutoff-Zeit als time-Objekt
cutoff = config.get_friday_cutoff_time()  # → time(21, 0)
```

### RiskEvaluationResult

Das Ergebnis einer Trade-Evaluierung:

```python
from core.services.risk import RiskEvaluationResult

# Beispiel: Trade erlaubt
result = RiskEvaluationResult(
    allowed=True,
    reason="Trade meets all risk requirements",
)

# Beispiel: Trade abgelehnt
result = RiskEvaluationResult(
    allowed=False,
    reason="Trade denied: Daily loss limit exceeded (3.0%)",
    violations=["Daily loss limit exceeded"],
    risk_metrics={'daily_pnl': -350.0, 'max_daily_loss': 300.0},
)

# Beispiel: Trade mit angepasster Positionsgröße
result = RiskEvaluationResult(
    allowed=True,
    reason="Position size reduced to fit risk limits",
    adjusted_order=adjusted_order_request,
    risk_metrics={'original_size': 2.0, 'adjusted_size': 0.2},
)
```

#### Attribute

| Attribut | Typ | Beschreibung |
|----------|-----|--------------|
| `allowed` | bool | Trade erlaubt (True) oder abgelehnt (False) |
| `reason` | str | Menschenlesbare Begründung |
| `adjusted_order` | Optional[OrderRequest] | Angepasste Order (wenn Größe reduziert) |
| `violations` | list | Liste aller gefundenen Regelverletzungen |
| `risk_metrics` | dict | Berechnete Risiko-Metriken |

#### Methoden

```python
# Zu Dictionary konvertieren
data = result.to_dict()

# Zu JSON konvertieren
json_str = result.to_json()
```

---

## YAML-Konfiguration

Die Risk Engine wird über eine YAML-Datei konfiguriert. Die Datei befindet sich unter:

```
core/services/risk/risk_config.yaml
```

### Vollständige Konfigurationsreferenz

```yaml
# Risk Engine v1.0 Configuration
# ================================

# -----------------------------------------
# Account Risk Limits
# -----------------------------------------

# Maximum risk per trade as percentage of account equity
# Example: 1.0 means max 1% of equity can be risked on a single trade
max_risk_per_trade_percent: 1.0

# Maximum daily loss as percentage of account equity
# When exceeded, all further trades are blocked for the day
max_daily_loss_percent: 3.0

# Maximum weekly loss as percentage of account equity
# When exceeded, all further trades are blocked for the week
max_weekly_loss_percent: 6.0

# -----------------------------------------
# Position Limits
# -----------------------------------------

# Maximum number of concurrent open positions
# Recommended: 1 for v1.0 to prevent overtrading
max_open_positions: 1

# Maximum position size (contracts)
max_position_size: 5.0

# Whether to allow trades against the higher timeframe trend
# When false, breakout trades must align with trend direction
# Note: EIA setups are exempt from this rule
allow_countertrend: false

# -----------------------------------------
# Stop Loss / Take Profit Limits
# -----------------------------------------

# Minimum stop loss distance in ticks
# Prevents overly tight stops that could be triggered by noise
sl_min_ticks: 5

# Minimum take profit distance in ticks
tp_min_ticks: 5

# -----------------------------------------
# Time-Based Restrictions
# -----------------------------------------

# Minutes before and after EIA release when new trades are blocked
# Normal breakout strategies are blocked, but EIA-specific strategies allowed
deny_eia_window_minutes: 5

# Time (CET) after which no new trades on Friday
# Format: "HH:MM"
deny_friday_after: "21:00"

# Whether to deny holding positions overnight
deny_overnight: true

# -----------------------------------------
# Instrument-Specific Settings
# -----------------------------------------

# Tick size for the traded instrument (e.g., 0.01 for WTI Crude Oil)
tick_size: 0.01

# Value of one tick in account currency (e.g., $10 for CL mini contract)
tick_value: 10.0
```

### Parameter im Detail

#### Account Risk Limits

| Parameter | Empfohlener Wert | Beschreibung |
|-----------|------------------|--------------|
| `max_risk_per_trade_percent` | 0.5 – 2.0 | Konservativ: 0.5%, Standard: 1%, Aggressiv: 2% |
| `max_daily_loss_percent` | 2.0 – 5.0 | Typisch: 3× max_risk_per_trade |
| `max_weekly_loss_percent` | 5.0 – 10.0 | Typisch: 2× max_daily_loss |

**Beispiel-Szenarien:**

```yaml
# Konservativ (Anfänger)
max_risk_per_trade_percent: 0.5
max_daily_loss_percent: 2.0
max_weekly_loss_percent: 4.0

# Standard (Fiona Default)
max_risk_per_trade_percent: 1.0
max_daily_loss_percent: 3.0
max_weekly_loss_percent: 6.0

# Aggressiv (erfahrene Trader)
max_risk_per_trade_percent: 2.0
max_daily_loss_percent: 5.0
max_weekly_loss_percent: 10.0
```

#### Position Limits

| Parameter | Beschreibung | Hinweis |
|-----------|--------------|---------|
| `max_open_positions` | Begrenzt gleichzeitige Trades | 1 empfohlen für v1.0 |
| `max_position_size` | Absolute Obergrenze pro Trade | Unabhängig vom Risiko |
| `allow_countertrend` | Trades gegen HTF-Trend | EIA-Setups immer erlaubt |

**Countertrend-Regel:**

Wenn `allow_countertrend: false`:
- LONG-Trade bei SHORT-Trend → **abgelehnt**
- SHORT-Trade bei LONG-Trend → **abgelehnt**
- EIA-Setups (Reversion/Trendday) → **immer erlaubt** (Event-driven)

#### Stop-Loss / Take-Profit

| Parameter | Beschreibung | Warum wichtig |
|-----------|--------------|---------------|
| `sl_min_ticks` | Mindest-SL-Distanz | Verhindert Rausch-Ausstoppen |
| `tp_min_ticks` | Mindest-TP-Distanz | Sichert mindest-R:R |

**Berechnung in Ticks:**

```
SL-Distanz (Ticks) = |Entry-Preis - SL-Preis| / tick_size
```

Beispiel:
- Entry: 75.50
- SL: 75.40
- tick_size: 0.01
- → SL-Distanz: |75.50 - 75.40| / 0.01 = **10 Ticks**

#### Zeit-Einschränkungen

| Parameter | Format | Beschreibung |
|-----------|--------|--------------|
| `deny_eia_window_minutes` | Integer | Sperrfenster ±X Minuten um EIA |
| `deny_friday_after` | "HH:MM" | Cutoff-Zeit am Freitag |
| `deny_overnight` | Boolean | Overnight-Verbot |

**EIA-Fenster:**

```
Bei deny_eia_window_minutes: 5 und EIA um 15:30:

Sperrfenster: 15:25 – 15:35 (±5 Minuten)

→ Normale Breakouts: GESPERRT
→ EIA-Setups (Reversion/Trendday): ERLAUBT
```

**Wochenend-/Freitag-Regeln:**

```
Freitag:
- Vor 21:00: Trading erlaubt
- Ab 21:00: Keine neuen Trades

Samstag/Sonntag:
- Trading komplett gesperrt
```

#### Instrument-Einstellungen

| Parameter | Beschreibung | Beispiele |
|-----------|--------------|-----------|
| `tick_size` | Kleinste Preisänderung | CL: 0.01, ES: 0.25 |
| `tick_value` | Wert in Kontowährung | CL Mini: $10, ES: $12.50 |

**Wichtig:** Diese Werte sind instrumentspezifisch und müssen korrekt konfiguriert werden, da sie direkt die Risikoberechnung beeinflussen.

---

## Risiko-Prüfungen im Detail

### 1. Zeitbasierte Einschränkungen

#### Wochenend-Prüfung
```python
# Samstag (weekday=5) oder Sonntag (weekday=6)
if now.weekday() >= 5:
    return "Trade denied: Weekend trading not allowed"
```

#### Freitag-Cutoff
```python
# Freitag (weekday=4) nach Cutoff-Zeit
if now.weekday() == 4 and now.time() >= cutoff:
    return "Trade denied: Friday after 21:00"
```

#### EIA-Sperrfenster
```python
# Nur für Breakout-Setups, EIA-Setups sind ausgenommen
if setup.setup_kind == SetupKind.BREAKOUT:
    if eia_start <= now <= eia_end:
        return "Trade denied: Within EIA window (5 min before/after)"
```

### 2. Verlustlimits

#### Tagesverlust-Prüfung
```python
max_daily_loss = equity * (max_daily_loss_percent / 100)
if daily_pnl < -max_daily_loss:
    return "Trade denied: Daily loss limit exceeded (3.0%)"
```

#### Wochenverlust-Prüfung
```python
max_weekly_loss = equity * (max_weekly_loss_percent / 100)
if weekly_pnl < -max_weekly_loss:
    return "Trade denied: Weekly loss limit exceeded (6.0%)"
```

### 3. Positionslimit

```python
if len(open_positions) >= max_open_positions:
    return "Trade denied: Max open positions (1) reached"
```

### 4. Countertrend-Regel

```python
# EIA-Setups sind ausgenommen
if setup.setup_kind in (SetupKind.EIA_REVERSION, SetupKind.EIA_TRENDDAY):
    return None  # Erlaubt

if setup.direction != trend_direction:
    return "Trade denied: Countertrend trade (LONG vs SHORT trend)"
```

### 5. Stop-Loss-Validierung

```python
# SL muss gesetzt sein
if order.stop_loss is None:
    return "Trade denied: Stop loss is required"

# SL-Distanz prüfen
sl_ticks = abs(entry - stop_loss) / tick_size
if sl_ticks < sl_min_ticks:
    return "Trade denied: SL distance (3.0 ticks) below minimum (5 ticks)"
```

### 6. Positionsgrößen-Prüfung

```python
# Maximales Risiko berechnen
max_risk_amount = equity * (max_risk_per_trade_percent / 100)

# Potenziellen Verlust berechnen
potential_loss = sl_ticks * tick_value * position_size

if potential_loss > max_risk_amount:
    # Versuche Größe anzupassen
    adjusted_size = max_risk_amount / (sl_ticks * tick_value)
    
    if adjusted_size < 0.1:
        return "Trade denied: SL distance too large → risk > 1% of equity"
    
    # Größe wurde angepasst
    return RiskEvaluationResult(
        allowed=True,
        reason="Position size reduced to fit risk limits",
        adjusted_order=order_with_adjusted_size,
    )
```

---

## Positions-Größenberechnung

Die Risk Engine berechnet die optimale Positionsgröße basierend auf:

1. **Maximales Risiko** = Equity × max_risk_per_trade_percent / 100
2. **Risiko pro Kontrakt** = SL-Distanz (Ticks) × tick_value
3. **Positionsgröße** = Max. Risiko / Risiko pro Kontrakt

### Formel

```
Positionsgröße = (Equity × Risiko%) / (SL-Ticks × Tick-Wert)
```

### Beispielrechnung

```
Gegebene Werte:
- Equity: 10.000€
- max_risk_per_trade_percent: 1.0
- Entry-Preis: 75.50
- Stop-Loss: 75.00
- tick_size: 0.01
- tick_value: 10.00€

Berechnung:
1. Max. Risiko = 10.000€ × 1.0% = 100€
2. SL-Distanz = |75.50 - 75.00| = 0.50
3. SL-Ticks = 0.50 / 0.01 = 50 Ticks
4. Risiko/Kontrakt = 50 × 10€ = 500€
5. Positionsgröße = 100€ / 500€ = 0.2 Kontrakte

Ergebnis: Maximale Positionsgröße = 0.2 Kontrakte
```

### Automatische Anpassung

Die Risk Engine passt die Positionsgröße automatisch an:

```python
# Angefragte Größe: 2.0 Kontrakte
# Berechnete max. Größe: 0.2 Kontrakte
# → Größe wird auf 0.2 reduziert

result = RiskEvaluationResult(
    allowed=True,
    reason="Position size reduced to fit risk limits",
    adjusted_order=OrderRequest(size=0.2, ...),
    risk_metrics={
        'original_size': 2.0,
        'adjusted_size': 0.2,
        'max_risk_amount': 100.0,
    },
)
```

### Minimale Größe

Wenn die berechnete Größe unter 0.1 liegt, wird der Trade abgelehnt:

```python
if adjusted_size < 0.1:
    return RiskEvaluationResult(
        allowed=False,
        reason="Trade denied: SL distance too large → risk > 1% of equity",
    )
```

### Direkte Berechnung

Die Risk Engine bietet auch eine direkte Berechnungsmethode:

```python
from core.services.risk import RiskEngine, RiskConfig

config = RiskConfig()
engine = RiskEngine(config)

size = engine.calculate_position_size(
    account=account_state,
    entry_price=Decimal("75.50"),
    stop_loss_price=Decimal("75.00"),
)
# → Decimal("0.2")
```

---

## Integration mit anderen Layern

### Architektur-Überblick

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Broker Service  │────▶│ Strategy Engine  │────▶│   Risk Engine    │
│  (Marktdaten)    │     │  (Signale)       │     │  (Prüfung)       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                                           │
                                                           ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    Weaviate      │◀────│ Execution Layer  │◀────│   Risk Engine    │
│  (Speicherung)   │     │  (Ausführung)    │     │  (Freigabe)      │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Zusammenspiel der Komponenten

1. **Strategy Engine** → generiert `SetupCandidate` mit Entry/SL/TP
2. **Broker Service** → liefert `AccountState` und offene `Position`s
3. **Risk Engine** → evaluiert und gibt `RiskEvaluationResult` zurück
4. **Execution Layer** → führt Trade aus oder erstellt Shadow-Trade
5. **Weaviate** → speichert `TradeCase` mit vollständigem Kontext

### Konfiguration pro Layer

| Layer | Konfigurationsdatei |
|-------|---------------------|
| Strategy Engine | `strategy_config.yaml` oder Code |
| **Risk Engine** | `core/services/risk/risk_config.yaml` |
| Execution Layer | `core/services/execution/execution_config.yaml` |
| Broker | Django Admin (IG Broker Configuration) |

### Beispiel: Vollständiger Workflow

```python
from datetime import datetime, timezone
from decimal import Decimal

from core.services.broker import create_ig_broker_service
from core.services.broker.models import OrderRequest, OrderDirection, OrderType
from core.services.strategy import StrategyEngine
from core.services.risk import RiskEngine, RiskConfig

# 1. Broker und Strategy Engine initialisieren
broker = create_ig_broker_service()
broker.connect()

# 2. Account und Positionen abrufen
account = broker.get_account_state()
positions = broker.get_open_positions()

# 3. Setup von Strategy Engine erhalten
setup = strategy_candidates[0]  # SetupCandidate

# 4. Order-Request erstellen
order = OrderRequest(
    epic="CC.D.CL.UNC.IP",
    direction=OrderDirection.BUY,
    size=Decimal("1.0"),
    order_type=OrderType.MARKET,
    stop_loss=Decimal("75.00"),
    take_profit=Decimal("76.50"),
)

# 5. Risk Engine evaluieren
config = RiskConfig.from_yaml('core/services/risk/risk_config.yaml')
risk_engine = RiskEngine(config)

result = risk_engine.evaluate(
    account=account,
    positions=positions,
    setup=setup,
    order=order,
    now=datetime.now(timezone.utc),
    daily_pnl=Decimal("-150.00"),  # Heutiger Verlust
    weekly_pnl=Decimal("-400.00"), # Wochenverlust
    trend_direction="LONG",         # HTF-Trend
)

# 6. Ergebnis verarbeiten
if result.allowed:
    if result.adjusted_order:
        print(f"Trade erlaubt mit angepasster Größe: {result.adjusted_order.size}")
        order = result.adjusted_order
    else:
        print(f"Trade erlaubt: {result.reason}")
    
    # → Weiter zum Execution Layer
else:
    print(f"Trade abgelehnt: {result.reason}")
    print(f"Verstöße: {result.violations}")
    
    # → Shadow-Trade oder verwerfen
```

---

## Diagnostik und Debugging

### Debug-Logging aktivieren

```bash
export FIONA_LOG_LEVEL=DEBUG
python manage.py runserver
```

### Log-Ausgaben verstehen

Die Risk Engine loggt strukturierte Debug-Informationen:

```
Risk evaluation started
  - setup_id: setup-123
  - epic: CC.D.CL.UNC.IP
  - direction: BUY
  - size: 1.0
  - stop_loss: 75.4
  - take_profit: 76.5
  - account_equity: 10000.0
  - open_positions: 0
  - daily_pnl: -150.0
  - weekly_pnl: -400.0
  - trend_direction: LONG

Risk check: time restriction passed
Risk check: loss limits passed
Risk check: position limits passed
Risk check: countertrend passed
Risk check: SL/TP valid

Risk evaluation: trade approved
  - size: 1.0
  - max_risk_amount: 100.0
  - potential_loss: 100.0
```

### Typische Log-Meldungen bei Ablehnung

```
Risk check: time restriction violated
  - reason: Trade denied: Friday after 21:00
  - timestamp: 2025-01-17T22:00:00Z

Risk check: loss limit violated
  - reason: Trade denied: Daily loss limit exceeded (3.0%)
  - daily_pnl: -350.0
  - max_daily_loss: 300.0

Risk check: position limit exceeded
  - reason: Trade denied: Max open positions (1) reached
  - current_positions: 1
  - max_positions: 1

Risk check: countertrend trade denied
  - reason: Trade denied: Countertrend trade (LONG vs SHORT trend)
  - trade_direction: LONG
  - trend_direction: SHORT

Risk evaluation: trade denied
  - primary_reason: Trade denied: Daily loss limit exceeded (3.0%)
  - all_violations: [...]
```

### Tests ausführen

```bash
# Alle Risk-Tests
python manage.py test core.tests_risk

# Spezifische Test-Klasse
python manage.py test core.tests_risk.RiskEngineTest

# Mit Verbose-Output
python manage.py test core.tests_risk -v 2
```

---

## Beispiele

### Basis-Verwendung

```python
from datetime import datetime, timezone
from decimal import Decimal
from core.services.risk import RiskEngine, RiskConfig

# Risk Engine initialisieren
config = RiskConfig()
engine = RiskEngine(config)

# Account-State (vom Broker)
from core.services.broker.models import AccountState
account = AccountState(
    account_id="LIVE123",
    account_name="Trading Account",
    balance=Decimal("10000.00"),
    available=Decimal("8000.00"),
    equity=Decimal("10000.00"),
    currency="EUR",
)

# Setup (von Strategy Engine)
from core.services.strategy.models import SetupCandidate, SetupKind, SessionPhase
setup = SetupCandidate(
    id="setup-001",
    created_at=datetime.now(timezone.utc),
    epic="CC.D.CL.UNC.IP",
    setup_kind=SetupKind.BREAKOUT,
    phase=SessionPhase.LONDON_CORE,
    reference_price=75.50,
    direction="LONG",
)

# Order erstellen
from core.services.broker.models import OrderRequest, OrderDirection, OrderType
order = OrderRequest(
    epic="CC.D.CL.UNC.IP",
    direction=OrderDirection.BUY,
    size=Decimal("1.0"),
    order_type=OrderType.MARKET,
    stop_loss=Decimal("75.40"),  # 10 Ticks
    take_profit=Decimal("76.50"),
)

# Evaluieren
result = engine.evaluate(
    account=account,
    positions=[],
    setup=setup,
    order=order,
    now=datetime.now(timezone.utc),
)

print(f"Erlaubt: {result.allowed}")
print(f"Grund: {result.reason}")
```

### Konfiguration aus YAML laden

```python
from core.services.risk import RiskConfig, RiskEngine

# Standard-Konfiguration laden
config = RiskConfig.from_yaml('core/services/risk/risk_config.yaml')

# Engine mit Konfiguration erstellen
engine = RiskEngine(config)

# Konfiguration anzeigen
print(f"Max. Risiko/Trade: {config.max_risk_per_trade_percent}%")
print(f"Max. Tagesverlust: {config.max_daily_loss_percent}%")
print(f"Max. Positionen: {config.max_open_positions}")
```

### Positionsgröße direkt berechnen

```python
from decimal import Decimal
from core.services.risk import RiskEngine, RiskConfig
from core.services.broker.models import AccountState

config = RiskConfig()
engine = RiskEngine(config)

account = AccountState(
    account_id="TEST",
    account_name="Test",
    balance=Decimal("10000"),
    equity=Decimal("10000"),
    currency="EUR",
)

size = engine.calculate_position_size(
    account=account,
    entry_price=Decimal("75.50"),
    stop_loss_price=Decimal("75.00"),
)

print(f"Optimale Positionsgröße: {size} Kontrakte")
# → Optimale Positionsgröße: 0.2 Kontrakte
```

### EIA-Handling

```python
from datetime import datetime, timezone, timedelta

# EIA um 15:30 UTC
eia_time = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
now = datetime(2025, 1, 15, 15, 32, tzinfo=timezone.utc)  # 2 Min nach EIA

# Breakout-Setup wird blockiert
breakout_setup = SetupCandidate(
    setup_kind=SetupKind.BREAKOUT,
    # ...
)

result = engine.evaluate(
    # ...
    setup=breakout_setup,
    now=now,
    eia_timestamp=eia_time,
)
# → result.allowed = False
# → result.reason = "Trade denied: Within EIA window (5 min before/after)"

# EIA-Reversion-Setup ist erlaubt
eia_setup = SetupCandidate(
    setup_kind=SetupKind.EIA_REVERSION,
    # ...
)

result = engine.evaluate(
    # ...
    setup=eia_setup,
    now=now,
    eia_timestamp=eia_time,
)
# → result.allowed = True
```

---

## Fehlerbehebung

### Häufige Probleme

| Problem | Mögliche Ursache | Lösung |
|---------|------------------|--------|
| Trade abgelehnt: Weekend | Aktuelle Zeit ist Sa/So | Warten bis Montag |
| Trade abgelehnt: Friday after | Nach Freitag-Cutoff | `deny_friday_after` anpassen |
| Trade abgelehnt: Daily loss | Tagesverlust überschritten | Warten bis nächster Tag |
| Trade abgelehnt: Weekly loss | Wochenverlust überschritten | Warten bis nächste Woche |
| Trade abgelehnt: Max positions | Position bereits offen | Bestehende Position schließen |
| Trade abgelehnt: Countertrend | LONG vs SHORT trend | `allow_countertrend: true` setzen |
| Trade abgelehnt: SL too close | SL < sl_min_ticks | SL weiter entfernt setzen |
| Trade abgelehnt: SL too large | Positionsgröße zu klein | Größeren Account oder engeren SL |
| Trade abgelehnt: No SL | Stop-Loss nicht gesetzt | Stop-Loss immer setzen |

### Debug-Checkliste

1. ✅ Ist `FIONA_LOG_LEVEL=DEBUG` gesetzt?
2. ✅ Ist die Zeit korrekt? (UTC, kein Wochenende, vor Freitag-Cutoff)
3. ✅ Ist der Tages-/Wochenverlust unter dem Limit?
4. ✅ Sind keine Positionen offen (oder unter max_open_positions)?
5. ✅ Stimmt die Trade-Richtung mit dem Trend überein?
6. ✅ Ist der Stop-Loss gesetzt und weit genug entfernt?
7. ✅ Ist die berechnete Positionsgröße ≥ 0.1?
8. ✅ Sind tick_size und tick_value korrekt konfiguriert?

### Konfiguration validieren

```python
from core.services.risk import RiskConfig

config = RiskConfig.from_yaml('core/services/risk/risk_config.yaml')

# Als Dictionary ausgeben
import pprint
pprint.pprint(config.to_dict())

# Als YAML ausgeben
print(config.to_yaml())
```

### Risk-Metriken analysieren

```python
result = engine.evaluate(...)

if not result.allowed:
    print(f"Hauptgrund: {result.reason}")
    print(f"Alle Verstöße: {result.violations}")

print(f"Risk-Metriken:")
for key, value in result.risk_metrics.items():
    print(f"  {key}: {value}")
```

---

## Weiterführende Dokumentation

- [Fiona Big Picture](fiona-big-picture.md) – Gesamtarchitektur
- [Strategy Engine](STRATEGY_ENGINE.md) – Setup-Erkennung
- [Trading Setup Guide](TRADING_SETUP_GUIDE.md) – Broker & Execution
- [API Documentation](API_Documentation.md) – KIGate Integration

---

*Letzte Aktualisierung: November 2025 | Risk Engine Version: 1.0*
