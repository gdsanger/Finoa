# Strategy Engine – Dokumentation

## Übersicht

Die **Strategy Engine** ist das Herzstück der Signalgenerierung im Fiona Trading-System. Sie analysiert Marktdaten und identifiziert potenzielle Trading-Setups basierend auf regelbasierten Strategien für **Breakouts** und **EIA-Events**.

> ⚠️ **Wichtig**: Die Strategy Engine **trifft keine Trading-Entscheidungen** und platziert keine Orders. Sie liefert lediglich `SetupCandidate`-Objekte, die dann von der Risk Engine geprüft und vom Execution Layer ausgeführt werden.

---

## Inhaltsverzeichnis

1. [Architektur](#architektur)
2. [Session-Phasen](#session-phasen)
3. [Breakout-Strategien](#breakout-strategien)
4. [EIA-Strategien](#eia-strategien)
5. [Konfiguration](#konfiguration)
6. [Datenmodelle](#datenmodelle)
7. [MarketStateProvider](#marketstateprovider)
8. [Diagnostik und Debugging](#diagnostik-und-debugging)
9. [Integration mit anderen Layern](#integration-mit-anderen-layern)
10. [Beispiele](#beispiele)

---

## Architektur

### Komponenten der Strategy Engine

```
core/services/strategy/
├── __init__.py          # Modul-Exporte
├── models.py            # Datenmodelle (SetupCandidate, Candle, etc.)
├── config.py            # Konfigurationsklassen
├── providers.py         # MarketStateProvider Interface
├── strategy_engine.py   # Hauptlogik der Strategy Engine
└── diagnostics.py       # Diagnose-Service für Range-Analyse
```

### Datenfluss

```
┌─────────────────────┐
│ MarketStateProvider │  ← Marktdaten (Candles, Ranges, ATR)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Strategy Engine   │  ← Analyse & Setup-Erkennung
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  SetupCandidate[]   │  → Weiter zur Risk Engine
└─────────────────────┘
```

---

## Session-Phasen

Die Strategy Engine arbeitet phasenbasiert. Jede Phase hat spezifische Regeln für Setup-Erkennung.

### Übersicht aller Phasen

| Phase | Zeitraum (UTC) | Beschreibung | Tradeable |
|-------|----------------|--------------|-----------|
| `ASIA_RANGE` | 00:00 – 08:00 | Range-Bildung der Asia-Session | ❌ |
| `LONDON_CORE` | 08:00 – 12:00 | Haupthandelszeit London, Asia-Breakouts | ✅ |
| `PRE_US_RANGE` | 13:00 – 15:00 | Range-Bildung vor US-Session | ❌ |
| `US_CORE_TRADING` | 15:00 – 22:00 | Haupthandelszeit US, Pre-US-Breakouts | ✅ |
| `US_CORE` | (deprecated) | Alte Phase, für Kompatibilität | ✅ |
| `EIA_PRE` | Vor EIA-Release | EIA-Sperrfenster | ❌ |
| `EIA_POST` | Nach EIA-Release | EIA-Setups möglich | ✅ |
| `FRIDAY_LATE` | Freitag Abend | Keine neuen Trades | ❌ |
| `OTHER` | Sonstige Zeiten | Nicht handelbar | ❌ |

### Wichtige Regeln

1. **Range-Phasen** (`ASIA_RANGE`, `PRE_US_RANGE`) sind **nicht tradeable** – hier wird nur die Range gesammelt
2. **Breakout-Phasen** (`LONDON_CORE`, `US_CORE_TRADING`) erlauben Breakout-Trades
3. **EIA_POST** ist für EIA-spezifische Setups reserviert
4. Nur in **tradeable Phasen** werden SetupCandidates generiert

---

## Breakout-Strategien

### Wie Breakouts funktionieren

Ein Breakout-Setup wird erkannt, wenn:

1. Eine **gültige Range** existiert (min/max Tick-Grenzen)
2. Der **Preis die Range verlässt** (über High oder unter Low)
3. Die **Breakout-Candle qualitativ gut** ist (Mindest-Body-Größe)

### Asia Range Breakout

**Wann**: Während `LONDON_CORE` Phase (08:00–12:00 UTC)

**Range-Definition**: High/Low der Asia-Session (00:00–08:00 UTC)

**Logik**:
- Preis schließt **über Asia High** → **LONG** Setup
- Preis schließt **unter Asia Low** → **SHORT** Setup

**Validierung**:
- Range-Höhe muss zwischen `min_range_ticks` und `max_range_ticks` liegen
- Breakout-Candle Body muss >= `min_breakout_body_fraction` × Range-Höhe sein
- Candle-Richtung muss zur Breakout-Richtung passen (bullish für LONG, bearish für SHORT)

```python
# Beispiel: Asia Breakout LONG
# Asia Range: High=75.20, Low=75.00 (20 Ticks)
# Aktuelle Candle: Open=75.15, Close=75.28, Body=0.13
# → Preis > Asia High (75.20)
# → Candle ist bullish
# → Body (0.13) >= 50% × Range (0.20) = 0.10 ✓
# → LONG Setup wird generiert
```

### Pre-US Range Breakout

**Wann**: Während `US_CORE_TRADING` Phase (15:00–22:00 UTC)

**Range-Definition**: High/Low der Pre-US-Session (13:00–15:00 UTC)

**Logik**: Identisch zu Asia Breakout, aber mit Pre-US Range

### London Core Range

**Hinweis**: Die London Core Range (08:00–12:00 UTC) wird erfasst und kann für Diagnose/Analyse verwendet werden, wird aber derzeit nicht für direkte Breakouts genutzt.

---

## EIA-Strategien

Die EIA (Energy Information Administration) veröffentlicht wöchentlich Öl-Bestandsdaten. Diese lösen oft starke Kursbewegungen aus.

### EIA Reversion

**Wann**: Während `EIA_POST` Phase (nach EIA-Release)

**Logik**:
1. Erste Impulsbewegung nach EIA analysieren (`impulse_window_minutes`)
2. Wenn Impuls **LONG** war und Preis signifikant zurückkommt → **SHORT** Reversion
3. Wenn Impuls **SHORT** war und Preis signifikant zurückkommt → **LONG** Reversion

**Validierung**:
- Reversion muss >= `reversion_min_retrace_fraction` × Impuls-Range zurücklegen
- Reversion-Candle muss in Reversion-Richtung sein (bearish für SHORT, bullish für LONG)

```python
# Beispiel: EIA Reversion SHORT
# Impuls: 3 Candles LONG von 74.00 auf 75.50 (Range = 1.50)
# Min. Retrace: 50% × 1.50 = 0.75
# Aktuelle Candle: Close=74.60 (Retrace = 0.90)
# → Retrace (0.90) >= Min (0.75) ✓
# → Candle ist bearish ✓
# → SHORT Reversion Setup wird generiert
```

### EIA Trend Day

**Wann**: Während `EIA_POST` Phase (nach EIA-Release)

**Logik**:
1. Erste Impulsbewegung analysieren
2. Prüfen ob nachfolgende Candles den Trend fortsetzen:
   - **LONG**: Higher Highs und Higher Lows
   - **SHORT**: Lower Lows und Lower Highs

**Validierung**:
- Mindestens `trend_min_follow_candles` konsekutive Trend-Candles erforderlich

---

## Konfiguration

### StrategyConfig Struktur

```python
from core.services.strategy import StrategyConfig

config = StrategyConfig(
    breakout=BreakoutConfig(
        asia_range=AsiaRangeConfig(...),
        london_core=LondonCoreConfig(...),
        us_core=UsCoreConfig(...),
        candle_quality=CandleQualityConfig(...),
        advanced_filter=AdvancedFilterConfig(...),
        atr=AtrConfig(...),
    ),
    eia=EiaConfig(...),
    default_epic="CC.D.CL.UNC.IP",
    tick_size=0.01,
)
```

### Asia Range Konfiguration

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `start` | str | "00:00" | Beginn der Asia-Range (UTC) |
| `end` | str | "08:00" | Ende der Asia-Range (UTC) |
| `min_range_ticks` | int | 10 | Minimum Range-Höhe in Ticks |
| `max_range_ticks` | int | 200 | Maximum Range-Höhe in Ticks |
| `min_breakout_body_fraction` | float | 0.5 | Min. Body als Anteil der Range |
| `require_volume_spike` | bool | False | Volume-Spike erforderlich |
| `require_clean_range` | bool | False | Saubere Range erforderlich |

### US Core Konfiguration

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `pre_us_start` | str | "13:00" | Beginn Pre-US Range (UTC) |
| `pre_us_end` | str | "15:00" | Ende Pre-US Range (UTC) |
| `us_core_trading_start` | str | "15:00" | Beginn US Trading (UTC) |
| `us_core_trading_end` | str | "22:00" | Ende US Trading (UTC) |
| `us_core_trading_enabled` | bool | True | US Trading aktiviert |
| `min_range_ticks` | int | 10 | Minimum Range-Höhe |
| `max_range_ticks` | int | 200 | Maximum Range-Höhe |
| `min_breakout_body_fraction` | float | 0.5 | Min. Body-Anteil |

### EIA Konfiguration

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `impulse_window_minutes` | int | 3 | Fenster für Impuls-Analyse |
| `reversion_min_retrace_fraction` | float | 0.5 | Min. Retrace für Reversion |
| `trend_min_follow_candles` | int | 3 | Min. Follow-Candles für Trend Day |
| `min_body_fraction` | float | 0.6 | Min. Body-Anteil |
| `reversion_window_min_sec` | int | 30 | Min. Zeit für Reversion |
| `reversion_window_max_sec` | int | 300 | Max. Zeit für Reversion |
| `max_impulse_duration_min` | int | 5 | Max. Impuls-Dauer |

### Erweiterte Filter

#### Candle Quality Config

| Parameter | Beschreibung |
|-----------|--------------|
| `min_wick_ratio` | Minimales Docht-Verhältnis |
| `max_wick_ratio` | Maximales Docht-Verhältnis |
| `min_candle_body_absolute` | Absolute Min.-Body-Größe |
| `max_spread_ticks` | Max. Spread in Ticks |
| `filter_doji_breakouts` | Doji-Breakouts filtern |

#### Advanced Filter Config

| Parameter | Beschreibung |
|-----------|--------------|
| `consecutive_candle_filter` | Anzahl konsekutiver Candles |
| `momentum_threshold` | Momentum-Schwellenwert |
| `volatility_throttle_min_atr` | Min. ATR für Volatilitäts-Filter |
| `session_volatility_cap` | Max. Session-Volatilität |

#### ATR Config

| Parameter | Beschreibung |
|-----------|--------------|
| `require_atr_minimum` | ATR-Minimum erforderlich |
| `min_atr_value` | Minimaler ATR-Wert |
| `max_atr_value` | Maximaler ATR-Wert |

### Konfiguration aus YAML laden

```python
import yaml
from core.services.strategy import StrategyConfig

with open('strategy_config.yaml', 'r') as f:
    data = yaml.safe_load(f)

config = StrategyConfig.from_dict(data)
```

**Beispiel YAML**:

```yaml
breakout:
  asia_range:
    start: "00:00"
    end: "08:00"
    min_range_ticks: 15
    max_range_ticks: 150
    min_breakout_body_fraction: 0.5
  us_core:
    pre_us_start: "13:00"
    pre_us_end: "15:00"
    us_core_trading_start: "15:00"
    us_core_trading_end: "22:00"
    min_range_ticks: 15
    max_range_ticks: 150

eia:
  impulse_window_minutes: 3
  reversion_min_retrace_fraction: 0.5
  trend_min_follow_candles: 3

default_epic: "CC.D.CL.UNC.IP"
tick_size: 0.01
```

---

## Datenmodelle

### SetupKind

Enum für die Art des Setups:

```python
class SetupKind(str, Enum):
    BREAKOUT = "BREAKOUT"
    EIA_REVERSION = "EIA_REVERSION"
    EIA_TRENDDAY = "EIA_TRENDDAY"
```

### SessionPhase

Enum für die aktuelle Marktphase:

```python
class SessionPhase(str, Enum):
    ASIA_RANGE = "ASIA_RANGE"
    LONDON_CORE = "LONDON_CORE"
    PRE_US_RANGE = "PRE_US_RANGE"
    US_CORE_TRADING = "US_CORE_TRADING"
    US_CORE = "US_CORE"  # Deprecated
    EIA_PRE = "EIA_PRE"
    EIA_POST = "EIA_POST"
    FRIDAY_LATE = "FRIDAY_LATE"
    OTHER = "OTHER"
```

### Candle

Repräsentiert eine Preis-Candle:

```python
@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    
    # Properties:
    @property
    def body_high(self) -> float: ...
    @property
    def body_low(self) -> float: ...
    @property
    def body_size(self) -> float: ...
    @property
    def is_bullish(self) -> bool: ...
    @property
    def is_bearish(self) -> bool: ...
```

### BreakoutContext

Kontext-Informationen für ein Breakout-Setup:

```python
@dataclass
class BreakoutContext:
    range_high: float       # Obere Range-Grenze
    range_low: float        # Untere Range-Grenze
    range_height: float     # Höhe der Range
    trigger_price: float    # Preis beim Breakout
    direction: str          # "LONG" oder "SHORT"
    atr: Optional[float]    # ATR (optional)
    vwap: Optional[float]   # VWAP (optional)
    volume_spike: Optional[bool]  # Volume-Spike (optional)
```

### EiaContext

Kontext-Informationen für ein EIA-Setup:

```python
@dataclass
class EiaContext:
    eia_timestamp: datetime                    # EIA-Release Zeitpunkt
    first_impulse_direction: Optional[str]     # "LONG" oder "SHORT"
    impulse_range_high: Optional[float]        # Impuls-High
    impulse_range_low: Optional[float]         # Impuls-Low
    atr: Optional[float]                       # ATR (optional)
```

### SetupCandidate

Das Hauptausgabe-Objekt der Strategy Engine:

```python
@dataclass
class SetupCandidate:
    id: str                    # Eindeutige ID
    created_at: datetime       # Erstellungszeitpunkt
    epic: str                  # Markt-Identifier (z.B. "CC.D.CL.UNC.IP")
    setup_kind: SetupKind      # Art des Setups
    phase: SessionPhase        # Phase bei Erkennung
    reference_price: float     # Referenzpreis
    direction: str             # "LONG" oder "SHORT"
    breakout: Optional[BreakoutContext]  # Breakout-Kontext
    eia: Optional[EiaContext]            # EIA-Kontext
    quality_flags: dict        # Qualitäts-Indikatoren
    schema_version: str        # Schema-Version
```

---

## MarketStateProvider

Die Strategy Engine benötigt einen `MarketStateProvider` für den Zugriff auf Marktdaten.

### Interface (Protocol)

```python
class MarketStateProvider(Protocol):
    def get_phase(self, ts: datetime) -> SessionPhase:
        """Aktuelle Marktphase für Zeitpunkt."""
        ...
    
    def get_recent_candles(
        self, epic: str, timeframe: str, limit: int
    ) -> list[Candle]:
        """Letzte Candles für einen Markt."""
        ...
    
    def get_asia_range(self, epic: str) -> Optional[tuple[float, float]]:
        """Asia-Range (high, low)."""
        ...
    
    def get_pre_us_range(self, epic: str) -> Optional[tuple[float, float]]:
        """Pre-US Range (high, low)."""
        ...
    
    def get_london_core_range(self, epic: str) -> Optional[tuple[float, float]]:
        """London Core Range (high, low)."""
        ...
    
    def get_atr(
        self, epic: str, timeframe: str, period: int
    ) -> Optional[float]:
        """ATR-Wert."""
        ...
    
    def get_eia_timestamp(self) -> Optional[datetime]:
        """EIA-Release Zeitpunkt."""
        ...
```

### BaseMarketStateProvider

Abstrakte Basisklasse mit Default-Implementierungen:

```python
from core.services.strategy import BaseMarketStateProvider

class MyProvider(BaseMarketStateProvider):
    def get_phase(self, ts: datetime) -> SessionPhase:
        # Ihre Implementierung
        ...
    
    def get_recent_candles(
        self, epic: str, timeframe: str, limit: int
    ) -> list[Candle]:
        # Ihre Implementierung
        ...
    
    # Optional überschreibbar:
    def get_asia_range(self, epic: str) -> Optional[tuple[float, float]]:
        # Default: None
        return super().get_asia_range(epic)
```

### IG Broker MarketStateProvider

Im Projekt gibt es bereits eine fertige Implementierung:

```python
from core.services.broker import IGMarketStateProvider

provider = IGMarketStateProvider(ig_broker_service)
```

---

## Diagnostik und Debugging

### Debug-Logging aktivieren

```bash
export FIONA_LOG_LEVEL=DEBUG
python manage.py runserver
```

### Log-Ausgaben verstehen

Die Strategy Engine loggt strukturierte Debug-Informationen:

```
Strategy evaluation started
  - epic: CC.D.CL.UNC.IP
  - phase: LONDON_CORE
  - current_price: 75.30
  - asia_range_high: 75.20
  - asia_range_low: 75.00
  - price_analysis:
      - asia_position: above_high
      - asia_breakout_potential: LONG

Setup candidate generated
  - setup_kind: BREAKOUT
  - direction: LONG
  - reference_price: 75.30
```

### evaluate_with_diagnostics

Für detaillierte Analyse verwenden Sie `evaluate_with_diagnostics`:

```python
from core.services.strategy import StrategyEngine

engine = StrategyEngine(provider, config)
result = engine.evaluate_with_diagnostics("CC.D.CL.UNC.IP", datetime.now(timezone.utc))

# EvaluationResult enthält:
print(f"Setups gefunden: {len(result.setups)}")
print(f"Summary: {result.summary}")

for criterion in result.criteria:
    status = "✓" if criterion.passed else "✗"
    print(f"{status} {criterion.name}: {criterion.detail}")
```

**Beispiel-Ausgabe**:

```
Setups gefunden: 1
Summary: Found 1 setup(s)

✓ Session Phase: Current phase: LONDON_CORE
✓ Phase is tradeable: LONDON_CORE is a tradeable phase
✓ Asia Range available: Range: 75.0000 - 75.2000
✓ Range size valid: Range: 20.0 ticks (valid: 10-200)
✓ Price data available: 10 candles
✓ Price broke Asia High: Price 75.3000 > Range High 75.2000
✓ Breakout candle quality (LONG): Body size: 0.1300, min fraction: 50%
```

### BreakoutRangeDiagnosticService

Für Range-spezifische Diagnose:

```python
from core.services.strategy import BreakoutRangeDiagnosticService

service = BreakoutRangeDiagnosticService(provider, config)

# Asia Range Diagnose
asia = service.get_asia_range_diagnostics(
    epic="CC.D.CL.UNC.IP",
    ts=datetime.now(timezone.utc),
    current_price=75.30
)

print(f"Range Type: {asia.range_type}")
print(f"Range: {asia.range_low} - {asia.range_high}")
print(f"Validation: {asia.range_validation}")
print(f"Price Position: {asia.price_position}")
print(f"Breakout Status: {asia.breakout_status}")
print(f"Message: {asia.diagnostic_message}")
```

### Diagnose-Enums

```python
class PricePosition(Enum):
    BELOW = "BELOW"    # Unter Range
    INSIDE = "INSIDE"  # In Range
    ABOVE = "ABOVE"    # Über Range

class BreakoutStatus(Enum):
    NO_BREAKOUT = "NO_BREAKOUT"           # Kein Breakout
    POTENTIAL_BREAKOUT = "POTENTIAL_BREAKOUT"  # Potentiell, aber Candle zu schwach
    VALID_BREAKOUT = "VALID_BREAKOUT"     # Gültiger Breakout

class RangeValidation(Enum):
    VALID = "VALID"               # Range gültig
    TOO_SMALL = "TOO_SMALL"       # Range zu klein
    TOO_LARGE = "TOO_LARGE"       # Range zu groß
    NOT_AVAILABLE = "NOT_AVAILABLE"  # Keine Daten
    INCOMPLETE = "INCOMPLETE"     # Unvollständig
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

1. **Broker Service** → liefert Marktdaten via `MarketStateProvider`
2. **Strategy Engine** → analysiert Daten, generiert `SetupCandidate`s
3. **Risk Engine** → prüft Limits, entscheidet `allowed = true/false`
4. **Execution Layer** → führt Trade aus oder erstellt Shadow-Trade
5. **Weaviate** → speichert `TradeCase` mit vollständigem Kontext

### Beispiel: Vollständiger Workflow

```python
from datetime import datetime, timezone
from core.services.broker import create_ig_broker_service, IGMarketStateProvider
from core.services.strategy import StrategyEngine, StrategyConfig
from core.services.risk import RiskEngine
from core.services.execution import ExecutionService

# 1. Broker initialisieren
broker = create_ig_broker_service()
broker.connect()

# 2. MarketStateProvider erstellen
provider = IGMarketStateProvider(broker)

# 3. Strategy Engine initialisieren
config = StrategyConfig()
strategy = StrategyEngine(provider, config)

# 4. Setups evaluieren
now = datetime.now(timezone.utc)
candidates = strategy.evaluate("CC.D.CL.UNC.IP", now)

print(f"Gefundene Setups: {len(candidates)}")

# 5. Risk Engine prüfen
risk = RiskEngine(broker)
for candidate in candidates:
    result = risk.evaluate(candidate)
    if result.allowed:
        print(f"Setup {candidate.id} freigegeben: {candidate.direction}")
        # 6. Execution Layer ausführen
        # execution.execute(candidate, result)
    else:
        print(f"Setup {candidate.id} blockiert: {result.reason}")
```

### Konfiguration pro Layer

| Layer | Konfigurationsdatei |
|-------|---------------------|
| Strategy Engine | `strategy_config.yaml` oder Code |
| Risk Engine | `core/services/risk/risk_config.yaml` |
| Execution Layer | `core/services/execution/execution_config.yaml` |
| Broker | Django Admin (IG Broker Configuration) |

---

## Beispiele

### Basis-Verwendung

```python
from datetime import datetime, timezone
from core.services.strategy import (
    StrategyEngine,
    StrategyConfig,
    SessionPhase,
    SetupKind,
)

# Eigenen Provider implementieren oder vorhandenen nutzen
class MyProvider:
    def get_phase(self, ts):
        return SessionPhase.LONDON_CORE
    
    def get_recent_candles(self, epic, timeframe, limit):
        # Candles laden...
        return candles
    
    def get_asia_range(self, epic):
        return (75.20, 75.00)  # (high, low)
    
    # ... weitere Methoden

# Engine erstellen
provider = MyProvider()
config = StrategyConfig()
engine = StrategyEngine(provider, config)

# Evaluieren
now = datetime.now(timezone.utc)
candidates = engine.evaluate("CC.D.CL.UNC.IP", now)

# Ergebnisse verarbeiten
for c in candidates:
    print(f"Setup: {c.setup_kind.value}")
    print(f"Direction: {c.direction}")
    print(f"Reference Price: {c.reference_price}")
    if c.breakout:
        print(f"Range: {c.breakout.range_low} - {c.breakout.range_high}")
```

### Konfiguration anpassen

```python
from core.services.strategy import (
    StrategyConfig,
    BreakoutConfig,
    AsiaRangeConfig,
    EiaConfig,
)

# Eigene Konfiguration
config = StrategyConfig(
    breakout=BreakoutConfig(
        asia_range=AsiaRangeConfig(
            min_range_ticks=15,  # Strenger als Default
            max_range_ticks=100,
            min_breakout_body_fraction=0.6,  # Größerer Body erforderlich
        ),
    ),
    eia=EiaConfig(
        impulse_window_minutes=5,  # Längeres Impulsfenster
        reversion_min_retrace_fraction=0.6,  # Stärkeres Retrace
    ),
    tick_size=0.01,
)

engine = StrategyEngine(provider, config)
```

### Test-Modus mit DummyProvider

```python
from datetime import datetime, timezone
from core.services.strategy import (
    StrategyEngine,
    BaseMarketStateProvider,
    SessionPhase,
    Candle,
)

class TestProvider(BaseMarketStateProvider):
    def __init__(self, phase, asia_range, candles):
        self._phase = phase
        self._asia_range = asia_range
        self._candles = candles
    
    def get_phase(self, ts):
        return self._phase
    
    def get_recent_candles(self, epic, timeframe, limit):
        return self._candles[:limit]
    
    def get_asia_range(self, epic):
        return self._asia_range

# Test-Daten
ts = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
candle = Candle(
    timestamp=ts,
    open=75.15,
    high=75.30,
    low=75.10,
    close=75.28,  # Über Asia High
)

provider = TestProvider(
    phase=SessionPhase.LONDON_CORE,
    asia_range=(75.20, 75.00),
    candles=[candle],
)

engine = StrategyEngine(provider)
candidates = engine.evaluate("CC.D.CL.UNC.IP", ts)

assert len(candidates) == 1
assert candidates[0].direction == "LONG"
```

---

## Fehlerbehebung

### Häufige Probleme

| Problem | Mögliche Ursache | Lösung |
|---------|------------------|--------|
| Keine Setups generiert | Phase nicht tradeable | Phase prüfen, Debug-Logging aktivieren |
| Range nicht verfügbar | Worker läuft noch nicht lange genug | Worker laufen lassen bis Range gebildet |
| Range zu klein/groß | Markt ungewöhnlich ruhig/volatil | Tick-Limits in Config anpassen |
| Breakout nicht erkannt | Candle-Body zu klein | `min_breakout_body_fraction` prüfen |
| EIA nicht erkannt | EIA-Timestamp nicht gesetzt | `get_eia_timestamp()` implementieren |

### Debug-Checkliste

1. ✅ Ist `FIONA_LOG_LEVEL=DEBUG` gesetzt?
2. ✅ Ist die Phase tradeable? (LONDON_CORE, US_CORE_TRADING, EIA_POST)
3. ✅ Sind Range-Daten verfügbar? (get_asia_range, get_pre_us_range)
4. ✅ Liegt die Range-Höhe im gültigen Bereich?
5. ✅ Sind Candle-Daten verfügbar?
6. ✅ Hat der Preis die Range verlassen?
7. ✅ Ist die Breakout-Candle qualitativ gut genug?

### Tests ausführen

```bash
# Alle Strategy-Tests
python manage.py test core.tests_strategy

# Spezifische Test-Klasse
python manage.py test core.tests_strategy.StrategyEngineBreakoutTest

# Mit Verbose-Output
python manage.py test core.tests_strategy -v 2
```

---

## Weiterführende Dokumentation

- [Fiona Big Picture](fiona-big-picture.md) – Gesamtarchitektur
- [Trading Setup Guide](TRADING_SETUP_GUIDE.md) – Broker & Execution
- [API Documentation](API_Documentation.md) – KIGate Integration

---

*Letzte Aktualisierung: November 2024 | Schema-Version: 1.0*
