# Strategie Engine Dokumentation

## Inhaltsverzeichnis

1. [Überblick](#überblick)
2. [Architektur und Komponenten](#architektur-und-komponenten)
3. [Bedingungen und Validierungen](#bedingungen-und-validierungen)
4. [Prozeduraler Ablauf](#prozeduraler-ablauf)
5. [Trade-Entscheidungsprozess](#trade-entscheidungsprozess)
6. [Candle Lifecycle](#candle-lifecycle)
7. [Breakout-Strategie](#breakout-strategie)
8. [EIA-Strategie](#eia-strategie)
9. [Konfiguration](#konfiguration)
10. [Integration mit Worker](#integration-mit-worker)
11. [Beispiele](#beispiele)

---

## Überblick

### Was macht die Strategie Engine?

Die **Strategie Engine** (`StrategyEngine`) ist das Herzstück des Fiona Trading-Systems. Sie analysiert Marktdaten und identifiziert potenzielle Trading-Setups basierend auf vordefinierten Strategien. 

**Wichtig**: Die Engine trifft KEINE Handelsentscheidungen und platziert KEINE Orders. Sie ist rein analytisch und generiert `SetupCandidate`-Objekte, die von anderen Systemkomponenten (Risk Engine, Execution Service) weiterverarbeitet werden.

### Hauptaufgaben

1. **Marktphasen-Erkennung**: Identifiziert die aktuelle Handelsphase (ASIA_RANGE, LONDON_CORE, PRE_US_RANGE, US_CORE_TRADING, EIA_POST, etc.)
2. **Breakout-Analyse**: Erkennt Ausbrüche aus definierten Preisranges
3. **EIA-Analyse**: Identifiziert Reversion- und Trend-Day-Muster nach EIA-Datenveröffentlichungen
4. **Setup-Generierung**: Erstellt strukturierte Setup-Kandidaten mit allen relevanten Kontextinformationen
5. **Qualitätsprüfung**: Validiert Setups gegen konfigurierbare Qualitätskriterien

### Philosophie: Analyse statt Execution

Die Engine folgt dem **Separation of Concerns**-Prinzip:
- **Strategy Engine**: Identifiziert Marktchancen (Setup-Kandidaten)
- **Risk Engine**: Bewertet Risiken und entscheidet über Trade-Zulässigkeit
- **Execution Service**: Führt genehmigte Trades aus

---

## Architektur und Komponenten

### Hauptklassen

#### 1. StrategyEngine

Die zentrale Klasse, die alle Strategielogik koordiniert.

```python
class StrategyEngine:
    def __init__(
        self,
        market_state: MarketStateProvider,
        config: Optional[StrategyConfig] = None,
        trading_asset=None
    )
```

**Attribute:**
- `market_state`: Provider für Marktdaten (Candles, Ranges, ATR, etc.)
- `config`: Strategie-Konfiguration (Schwellwerte, Timeframes, etc.)
- `trading_asset`: Optional - TradingAsset-Modellinstanz für Breakout-State-Management
- `last_status_message`: Letzte Statusnachricht für externe Verbraucher
- `_status_history`: Historie aller Statusmeldungen während der Evaluation
- `last_discarded_count`: Anzahl verworfener Setups

**Hauptmethoden:**
- `evaluate(epic, ts)`: Hauptevaluierung - gibt Liste von SetupCandidates zurück
- `evaluate_with_diagnostics(epic, ts)`: Erweiterte Evaluierung mit detaillierten Diagnosedaten

#### 2. MarketStateProvider

Interface für Marktdatenzugriff (implementiert z.B. durch `IGMarketStateProvider`).

**Verantwortlichkeiten:**
- Bereitstellung von Candle-Daten
- Verwaltung von Session-Ranges (Asia, London Core, Pre-US)
- Phase-Bestimmung basierend auf Zeitstempel
- ATR-Berechnung

#### 3. Datenmodelle

**SetupCandidate**: Repräsentiert ein identifiziertes Trading-Setup

```python
@dataclass
class SetupCandidate:
    id: str
    created_at: datetime
    epic: str
    setup_kind: SetupKind  # BREAKOUT, EIA_REVERSION, EIA_TRENDDAY
    phase: SessionPhase
    reference_price: float
    direction: Literal["LONG", "SHORT"]
    breakout: Optional[BreakoutContext]
    eia: Optional[EiaContext]
    quality_flags: Optional[dict]
```

**BreakoutContext**: Kontext für Breakout-Setups

```python
@dataclass
class BreakoutContext:
    range_high: float
    range_low: float
    range_height: float
    trigger_price: float
    direction: Literal["LONG", "SHORT"]
    signal_type: Optional[BreakoutSignal]
    atr: Optional[float]
```

**EiaContext**: Kontext für EIA-Setups

```python
@dataclass
class EiaContext:
    eia_timestamp: datetime
    first_impulse_direction: Optional[Literal["LONG", "SHORT"]]
    impulse_range_high: Optional[float]
    impulse_range_low: Optional[float]
    atr: Optional[float]
```

---

## Bedingungen und Validierungen

Die Engine führt mehrere Ebenen von Validierungen durch, bevor ein Setup-Kandidat generiert wird:

### 1. Phase-Validierung

**Prüfung:** Ist die aktuelle Phase handelbar?

**Handelbare Phasen (Standard):**
- `LONDON_CORE`: Handel basierend auf Asia Range
- `US_CORE_TRADING`: Handel basierend auf Pre-US Range
- `US_CORE`: Deprecated, aber noch unterstützt
- `PRE_US_RANGE`: Handel basierend auf London Core Range
- `EIA_POST`: EIA-Strategien

**Methode:** `_is_phase_tradeable(phase)`

```python
tradeable_phases = [
    SessionPhase.LONDON_CORE,
    SessionPhase.US_CORE_TRADING,
    SessionPhase.US_CORE,
    SessionPhase.EIA_POST,
]
```

**Fallback:** Asset-spezifische Tradeability kann über `market_state.is_phase_tradeable()` überschrieben werden.

### 2. Range-Validierung

**Prüfung:** Ist die Referenz-Range verfügbar und gültig?

**Kriterien:**
- Range-Daten müssen vorhanden sein
- Range-Höhe muss innerhalb definierter Tick-Grenzen liegen

```python
def _is_valid_range(range_height, config):
    ticks = range_height / tick_size
    return config.min_range_ticks <= ticks <= config.max_range_ticks
```

**Beispiel (Asia Range):**
- `min_range_ticks`: 10 Ticks
- `max_range_ticks`: 200 Ticks

**Rationale:** Zu kleine Ranges sind Rauschen, zu große Ranges sind nicht handelbar.

### 3. Candle-Verfügbarkeit

**Prüfung:** Sind ausreichend Candle-Daten verfügbar?

**Anforderungen:**
- Mindestens 1 geschlossene Candle für Breakout-Analyse
- 10+ Candles für Kontextanalyse
- Für EIA: `impulse_window_minutes + 5` Candles

### 4. Breakout-Signal-Erkennung

**Prüfung:** Liegt ein gültiger Breakout vor?

**Kriterien:**

1. **Preisposition**: Candle High > Range High (LONG) oder Candle Low < Range Low (SHORT)
2. **Breakout-State**: Asset muss im Zustand `IN_RANGE` sein (keine aktive Breakout-Position)
3. **Tick-Validierung** (wenn TradingAsset gesetzt):
   - **max_pullback_ticks**: Maximale Pullback-Distanz
4. **Candle-Qualität**: Siehe nächster Abschnitt

**Breakout-States:**
- `IN_RANGE`: Preis innerhalb der Range, neue Breakouts erlaubt
- `BROKEN_LONG`: Breakout nach oben erfolgt, keine neuen LONG-Signale
- `BROKEN_SHORT`: Breakout nach unten erfolgt, keine neuen SHORT-Signale

**State-Reset:** Wenn Preis in Range zurückkehrt, wird State auf `IN_RANGE` zurückgesetzt.

### 5. Candle-Qualität

**Prüfung:** Erfüllt die Breakout-Candle Qualitätskriterien?

**Kriterien:**

a) **Richtungsvalidierung**
- LONG-Breakout: Candle muss bullish sein (close > open)
- SHORT-Breakout: Candle muss bearish sein (close < open)

b) **Body-Size**

```python
min_body = range_height * min_breakout_body_fraction
candle.body_size >= min_body
```

- Standard: 50% der Range-Höhe
- Verhindert Doji- und kleine Schein-Ausbrüche

c) **Breakout-Distanz**

```python
min_distance = min_breakout_distance_ticks * tick_size
# Für LONG:
(candle.high - range_high) >= min_distance
# Für SHORT:
(range_low - candle.low) >= min_distance
```

d) **Maximale Candle-Distanz**

```python
max_distance = max_candle_distance_ticks * tick_size
# Für LONG:
(range_high - candle.low) <= max_distance
# Für SHORT:
(candle.high - range_low) <= max_distance
```

**Rationale:** Stellt sicher, dass die Breakout-Candle nicht zu weit von der Range-Boundary entfernt ist.

### 6. EIA-Spezifische Validierungen

**a) Impulse-Analyse:**
- Klare Richtung im Impulse-Fenster (Standard: 3 Minuten)
- Nettobeweg > tick_size

**b) Reversion-Erkennung:**
- Retrace ≥ `reversion_min_retrace_fraction` * impulse_range
- Gegenläufige Candle (bearish nach LONG-Impulse, bullish nach SHORT-Impulse)

**c) Trend-Day-Erkennung:**
- Mindestens `trend_min_follow_candles` Follow-Through-Candles
- LONG: Higher Highs und Higher Lows
- SHORT: Lower Lows und Lower Highs

---

## Prozeduraler Ablauf

### Hauptfluss: evaluate()

```
┌─────────────────────────────────────────┐
│ 1. PHASE DETERMINATION                  │
│    market_state.get_phase(timestamp)    │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 2. PHASE TRADEABILITY CHECK             │
│    _is_phase_tradeable(phase)           │
│    ├─ Not Tradeable → Return []         │
│    └─ Tradeable → Continue              │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 3. STRATEGY SELECTION                   │
│    Based on phase:                      │
│    ├─ LONDON_CORE → Asia Breakout       │
│    ├─ US_CORE_TRADING → US Breakout     │
│    ├─ PRE_US_RANGE → US Breakout        │
│    └─ EIA_POST → EIA Strategies         │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 4. STRATEGY EVALUATION                  │
│    _evaluate_asia_breakout()            │
│    _evaluate_us_breakout()              │
│    _evaluate_eia_setups()               │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 5. CANDIDATE FILTERING                  │
│    _filter_candidates()                 │
│    └─ Remove duplicates                 │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ 6. RETURN SETUP CANDIDATES              │
│    list[SetupCandidate]                 │
└─────────────────────────────────────────┘
```

---

## Trade-Entscheidungsprozess

### Wie kommt die Engine zum Entschluss einen Trade zu erstellen?

Die Engine erstellt **KEINEN Trade**, sondern nur einen **SetupCandidate**. Die eigentliche Trade-Entscheidung erfolgt durch nachgelagerte Komponenten:

```
SetupCandidate (Strategy Engine)
         ↓
Risk Evaluation (Risk Engine)
         ↓
Execution Decision (Execution Service / Worker)
         ↓
Order Placement (Broker Service)
```

**Verantwortlichkeiten:**

1. **Strategy Engine** → Generiert SetupCandidate wenn:
   - Phase ist handelbar
   - Range ist verfügbar und valide
   - Breakout-Signal erkannt
   - Candle-Qualität stimmt
   - Alle Validierungen bestanden

2. **Risk Engine** → Bewertet:
   - Portfolio-Risiko
   - Position-Sizing
   - Exposure-Limits
   - Markt-Volatilität

3. **Execution Service / Worker** → Entscheidet:
   - Auto-Trade aktiviert?
   - Risk-Status erlaubt Trade?
   - Erstellt Signal-Objekt in Datenbank

4. **Broker Service** → Führt aus:
   - Platziert Order beim Broker
   - Managed Order-Lifecycle

### Wie kommt die Engine zum Entschluss KEINEN Trade zu machen?

Die Engine gibt eine **leere Liste** zurück (`[]`) wenn:

1. **Phase nicht handelbar**
2. **Range-Daten fehlen**
3. **Range ungültig**
4. **Keine Candles verfügbar**
5. **Kein Breakout erkannt**
6. **Candle-Qualität unzureichend**
7. **Breakout-State verhindert neue Signale**

**Logging:** Jeder Ablehnungsgrund wird in `last_status_message` und `_status_history` protokolliert.

---

## Candle Lifecycle

### Von der Bewertung bis zur Entscheidung

```
1. MARKET DATA ACQUISITION (Worker)
   ├─ Fiona Worker ruft Broker API auf
   ├─ Neue 1-Minute Candle wird empfangen
   └─ Candle wird in MarketStateProvider gespeichert

2. STRATEGY EVALUATION TRIGGER (Worker)
   ├─ Worker-Cycle startet (z.B. alle 60 Sekunden)
   ├─ Worker ruft strategy_engine.evaluate() auf
   └─ Timestamp: aktuelle UTC-Zeit

3. PHASE DETERMINATION (Strategy Engine)
   ├─ get_phase(timestamp) identifiziert aktuelle Session-Phase
   ├─ Beispiel: 09:30 UTC → LONDON_CORE
   └─ Phase-spezifische Strategie wird ausgewählt

4. RANGE RETRIEVAL (Strategy Engine)
   ├─ Für LONDON_CORE: get_asia_range()
   ├─ Für US_CORE_TRADING: get_pre_us_range()
   └─ Range-Daten (high, low) werden geladen

5. CANDLE FETCHING (Strategy Engine)
   ├─ get_recent_candles(epic, '1m', 10)
   ├─ Holt letzte 10 geschlossene 1-Min-Candles
   └─ Latest candle = candles[-1]

6. BREAKOUT DETECTION (Strategy Engine)
   ├─ _detect_breakout_signal(latest_candle, range_high, range_low)
   ├─ Prüft: candle.high > range_high? (LONG)
   ├─ Prüft: candle.low < range_low? (SHORT)
   └─ Prüft: Breakout-State, Tick-Requirements, Quality

7. SIGNAL CLASSIFICATION (Strategy Engine)
   ├─ LONG_BREAKOUT: High > Range High, Close > Range High
   ├─ SHORT_BREAKOUT: Low < Range Low, Close < Range Low
   ├─ FAILED_LONG_BREAKOUT: High > Range High, Close < Range High
   └─ FAILED_SHORT_BREAKOUT: Low < Range Low, Close > Range Low

8. CANDLE QUALITY VALIDATION (Strategy Engine)
   ├─ Direction: Bullish für LONG, Bearish für SHORT
   ├─ Body Size: >= min_breakout_body_fraction * range_height
   ├─ Breakout Distance: >= min_breakout_distance_ticks
   └─ Max Candle Distance: <= max_candle_distance_ticks

9. SETUP CANDIDATE CREATION (Strategy Engine)
   ├─ _create_breakout_candidate()
   ├─ Erstellt SetupCandidate mit allen Kontextinformationen
   └─ Breakout State Update: IN_RANGE → BROKEN_LONG/SHORT

10. SETUP FILTERING (Strategy Engine)
    ├─ _filter_candidates()
    └─ Returns filtered list

11. RETURN TO WORKER (Strategy Engine)
    └─ Returns: list[SetupCandidate] (0 to N candidates)

12. RISK EVALUATION (Worker → Risk Engine)
13. EXECUTION DECISION (Worker)
14. SIGNAL CREATION (Worker)
15. ORDER PLACEMENT (Execution Service)
16. POST-TRADE MONITORING (Worker)
```

---

## Breakout-Strategie

### Konzept

Die Breakout-Strategie basiert auf dem Prinzip, dass Preise nach einer Konsolidierungsphase (Range) oft in eine klare Richtung ausbrechen und diesen Move fortsetzen.

### Range-Definitionen

#### 1. Asia Range
- **Zeitfenster:** 00:00 - 08:00 UTC (8 Stunden)
- **Zweck:** Identifiziert Konsolidierung während asiatischer Session
- **Trading-Phase:** LONDON_CORE (08:00 - 13:00 UTC)
- **Rationale:** London-Händler reagieren auf Asia-Range-Breakouts

#### 2. London Core Range
- **Zeitfenster:** 08:00 - 13:00 UTC (5 Stunden)
- **Zweck:** Identifiziert Konsolidierung während London-Session
- **Trading-Phase:** PRE_US_RANGE (13:00 - 15:00 UTC)
- **Rationale:** Pre-US-Phase kann London-Range-Breakouts zeigen

#### 3. Pre-US Range
- **Zeitfenster:** 13:00 - 15:00 UTC (2 Stunden)
- **Zweck:** Identifiziert Konsolidierung vor US-Session
- **Trading-Phase:** US_CORE_TRADING (15:00 - 22:00 UTC)
- **Rationale:** US-Händler reagieren auf Pre-US-Range-Breakouts

### Breakout-Signale

#### LONG_BREAKOUT
- **Bedingung:** Candle High > Range High UND Candle Close > Range High
- **Interpretation:** Klarer Ausbruch nach oben mit Bestätigung durch Close
- **Trade-Richtung:** LONG

#### SHORT_BREAKOUT
- **Bedingung:** Candle Low < Range Low UND Candle Close < Range Low
- **Interpretation:** Klarer Ausbruch nach unten mit Bestätigung durch Close
- **Trade-Richtung:** SHORT

#### FAILED_LONG_BREAKOUT
- **Bedingung:** Candle High > Range High ABER Candle Close <= Range High
- **Interpretation:** Scheinausbruch nach oben, Preis kehrt in Range zurück
- **Trade-Richtung:** SHORT (Reversion-Trade)

#### FAILED_SHORT_BREAKOUT
- **Bedingung:** Candle Low < Range Low ABER Candle Close >= Range Low
- **Interpretation:** Scheinausbruch nach unten, Preis kehrt in Range zurück
- **Trade-Richtung:** LONG (Reversion-Trade)

### Breakout-State-Management

Der `breakout_state` im TradingAsset verhindert Multiple-Signaling:

```python
# States
IN_RANGE = 'IN_RANGE'           # Preis in Range, Breakouts erlaubt
BROKEN_LONG = 'BROKEN_LONG'     # LONG Breakout erfolgt, keine neuen LONG-Signale
BROKEN_SHORT = 'BROKEN_SHORT'   # SHORT Breakout erfolgt, keine neuen SHORT-Signale
```

**Wichtig:** Neue Breakout-Signale werden nur im `IN_RANGE`-State generiert!

### Tick-Validierung

#### max_pullback_ticks
- **LONG:** Candle.low darf maximal X Ticks UNTER Range.high liegen
- **SHORT:** Candle.high darf maximal X Ticks ÜBER Range.low liegen
- **Zweck:** Verhindert zu starke Pullbacks innerhalb der Breakout-Candle

---

## EIA-Strategie

### Konzept

Die EIA-Strategie nutzt die Volatilität nach der wöchentlichen Ölinventarveröffentlichung der **Energy Information Administration** (EIA), die jeden Mittwoch um 10:30 AM ET (15:30 UTC) stattfindet.

### Strategietypen

#### 1. EIA Reversion

**Konzept:** Nach einem starken initialen Impulse kehrt der Preis oft teilweise zurück (Mean Reversion).

**Setup-Bedingungen:**
1. Klare Impulse-Richtung in ersten N Minuten nach EIA
2. Retrace ≥ `reversion_min_retrace_fraction` * impulse_range
3. Letzte Candle ist gegenläufig zum Impulse

**Trade-Richtung:** GEGEN den initialen Impulse

#### 2. EIA Trend Day

**Konzept:** Manchmal setzt sich der initiale Impulse fort (Trend Continuation).

**Setup-Bedingungen:**
1. Klare Impulse-Richtung in ersten N Minuten nach EIA
2. Follow-Through: Mindestens M Candles zeigen Trend-Fortsetzung
   - LONG: Higher Highs + Higher Lows
   - SHORT: Lower Lows + Lower Highs

**Trade-Richtung:** MIT dem initialen Impulse

---

## Konfiguration

### StrategyConfig

Die Hauptkonfigurationsklasse für alle Strategien:

```python
@dataclass
class StrategyConfig:
    breakout: BreakoutConfig        # Breakout-Strategien
    eia: EiaConfig                  # EIA-Strategien
    default_epic: str               # Standard-Market-ID
    tick_size: float                # Tick-Größe für Berechnungen
```

### Beispiel-Konfiguration (YAML)

```yaml
tick_size: 0.01
default_epic: "CC.D.CL.UNC.IP"

breakout:
  asia_range:
    min_range_ticks: 10
    max_range_ticks: 200
    min_breakout_body_fraction: 0.5
  
  us_core:
    min_range_ticks: 10
    max_range_ticks: 200
    min_breakout_body_fraction: 0.5

eia:
  impulse_window_minutes: 3
  reversion_min_retrace_fraction: 0.5
  trend_min_follow_candles: 3
```

---

## Integration mit Worker

### Fiona Worker Architektur

Der `run_fiona_worker.py` Command orchestriert den gesamten Trading-Workflow:

```python
# Worker initialisiert Strategy Engine
market_state = IGMarketStateProvider(broker_service, epic, config)
strategy_engine = StrategyEngine(
    market_state=market_state,
    config=strategy_config,
    trading_asset=trading_asset
)

# Worker-Cycle ruft Engine auf
timestamp = datetime.now(timezone.utc)
setup_candidates = strategy_engine.evaluate(epic, timestamp)

# Worker verarbeitet Setups
for setup in setup_candidates:
    risk_result = risk_engine.evaluate(setup, trading_asset)
    
    if trading_asset.auto_trade and risk_result.status in ['GREEN', 'YELLOW']:
        signal = Signal.objects.create(...)
        execution_service.execute(signal)
```

---

## Beispiele

### Beispiel 1: Asia Breakout (LONG)

**Szenario:**
- Phase: LONDON_CORE (09:30 UTC)
- Asia Range: 75.00 - 75.50 (50 Ticks)
- Aktuelle Candle: O:75.45 H:75.65 L:75.43 C:75.60

**Evaluation:**
- Phase Check: LONDON_CORE → Tradeable ✓
- Range Check: 50 Ticks → Valid ✓
- Breakout: High 75.65 > Range High 75.50 ✓
- Close: 75.60 > Range High 75.50 ✓
- Signal: LONG_BREAKOUT ✓
- Direction: Bullish ✓
- Body Size: 0.15 (≥ 0.25 required for 50% of 0.50 range) → Needs bigger body!

**Ergebnis:** Setup generiert wenn Body-Größe ausreichend!

### Beispiel 2: EIA Reversion

**Szenario:**
- EIA Release: 15:30 UTC
- Impulse (15:30-15:33): LONG, 75.00 → 75.50 (Range: 0.50)
- Follow-Up (15:34): C:75.20 (Bearish Candle)

**Evaluation:**
- Impulse: LONG ✓
- Retrace: 75.50 - 75.20 = 0.30 (≥ 0.25 required) ✓
- Last Candle: Bearish ✓

**Ergebnis:** EIA_REVERSION SHORT Setup generiert!

---

## Zusammenfassung

### Kernprinzipien

1. **Separation of Concerns:** Strategy Engine analysiert, trifft aber KEINE Trade-Entscheidungen
2. **State Management:** Breakout-State verhindert Mehrfach-Signaling
3. **Qualitätsfokus:** Multiple Validierungsebenen sichern Setup-Qualität
4. **Konfigurierbar:** Alle Parameter über StrategyConfig anpassbar
5. **Diagnostics:** Detaillierte Logging und Status-Messages für Debugging

### Datenfluss (Vereinfacht)

```
Market Data → Strategy Engine → SetupCandidates → Risk Engine → Execution
```

### Wichtige Klassen

- `StrategyEngine`: Hauptklasse für Strategielogik
- `SetupCandidate`: Output der Engine
- `StrategyConfig`: Konfiguration aller Strategien
- `MarketStateProvider`: Interface für Marktdaten

---

**Version:** 1.0  
**Letzte Aktualisierung:** Dezember 2024  
**Autor:** Fiona Trading System Team
