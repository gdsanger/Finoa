# Execution Layer – Dokumentation

## Übersicht

Der **Execution Layer** ist die zentrale Schicht für die Ausführung und Verwaltung von Trades im Fiona Trading-System. Er orchestriert die Signale von Strategy Engine, KI Layer und Risk Engine, präsentiert Trade-Vorschläge dem Benutzer und führt Trades aus oder simuliert sie als Shadow-Trades.

> ⚠️ **Wichtig**: In v1.0 gibt es **kein vollautomatisches Trading** – jeder echte Trade erfordert eine explizite Benutzerbestätigung. Shadow-Trades werden automatisch erstellt, wenn ein Trade vom Risk Engine abgelehnt wird oder der Benutzer sich dagegen entscheidet.

---

## Inhaltsverzeichnis

1. [Architektur](#architektur)
2. [Execution-States](#execution-states)
3. [Order-Sizing und Positionsberechnung](#order-sizing-und-positionsberechnung)
4. [Stop Loss und Take Profit](#stop-loss-und-take-profit)
5. [Broker-Integration](#broker-integration)
6. [Shadow Trading](#shadow-trading)
7. [Positions-Überwachung](#positions-überwachung)
8. [Konfiguration](#konfiguration)
9. [Datenmodelle](#datenmodelle)
10. [Integration mit anderen Layern](#integration-mit-anderen-layern)
11. [Beispiele](#beispiele)
12. [Fehlerbehebung](#fehlerbehebung)

---

## Architektur

### Komponenten des Execution Layer

```
core/services/execution/
├── __init__.py              # Modul-Exporte
├── models.py                # Datenmodelle (ExecutionSession, ExecutionConfig, etc.)
├── execution_service.py     # Hauptlogik des Execution Layer
├── shadow_trader_service.py # Shadow-Trade Verwaltung
├── execution_config.yaml    # Produktions-Konfiguration
└── execution_config.example.yaml  # Beispiel-Konfiguration
```

### Datenfluss

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Strategy Engine   │────▶│      KI Layer       │────▶│    Risk Engine      │
│   (SetupCandidate)  │     │  (KiEvaluationResult)│     │ (RiskEvaluationResult)│
└─────────────────────┘     └─────────────────────┘     └──────────┬──────────┘
                                                                   │
                                                                   ▼
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│      Weaviate       │◀────│   Execution Layer   │◀────│    Benutzer UI      │
│   (Persistierung)   │     │  (ExecutionSession) │     │ (Trade-Entscheidung)│
└─────────────────────┘     └──────────┬──────────┘     └─────────────────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │   Broker Service    │
                            │  (Order-Ausführung) │
                            └─────────────────────┘
```

---

## Execution-States

Der Execution Layer verwendet eine State Machine zur Verwaltung des Trade-Lebenszyklus.

### State-Übersicht

| State | Beschreibung | Nächste States |
|-------|--------------|----------------|
| `NEW_SIGNAL` | Neues Signal empfangen | KI_EVALUATED |
| `KI_EVALUATED` | KI-Evaluation abgeschlossen | RISK_APPROVED, RISK_REJECTED |
| `RISK_APPROVED` | Risiko genehmigt | WAITING_FOR_USER |
| `RISK_REJECTED` | Risiko abgelehnt | SHADOW_ONLY |
| `WAITING_FOR_USER` | Wartet auf Benutzer-Entscheidung | USER_ACCEPTED, USER_SHADOW, USER_REJECTED |
| `SHADOW_ONLY` | Nur Shadow-Trade möglich | USER_SHADOW, USER_REJECTED |
| `USER_ACCEPTED` | Benutzer hat Live-Trade bestätigt | LIVE_TRADE_OPEN |
| `USER_SHADOW` | Benutzer hat Shadow-Trade gewählt | SHADOW_TRADE_OPEN |
| `USER_REJECTED` | Benutzer hat abgelehnt | DROPPED |
| `LIVE_TRADE_OPEN` | Live-Trade ist offen | EXITED |
| `SHADOW_TRADE_OPEN` | Shadow-Trade ist offen | EXITED |
| `EXITED` | Trade wurde geschlossen | (Terminal) |
| `DROPPED` | Signal wurde verworfen | (Terminal) |

### State-Flow-Diagramm

```
                    ┌────────────────┐
                    │   NEW_SIGNAL   │
                    └───────┬────────┘
                            │
                            ▼
                    ┌────────────────┐
                    │  KI_EVALUATED  │
                    └───────┬────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
    ┌────────────────┐          ┌────────────────┐
    │ RISK_APPROVED  │          │ RISK_REJECTED  │
    └───────┬────────┘          └───────┬────────┘
            │                           │
            ▼                           ▼
    ┌────────────────┐          ┌────────────────┐
    │WAITING_FOR_USER│          │  SHADOW_ONLY   │
    └───────┬────────┘          └───────┬────────┘
            │                           │
    ┌───────┴───────┐           ┌───────┴───────┐
    │       │       │           │               │
    ▼       ▼       ▼           ▼               ▼
┌──────┐┌──────┐┌──────┐   ┌──────┐        ┌──────┐
│ACCEPT││SHADOW││REJECT│   │SHADOW│        │REJECT│
└──┬───┘└──┬───┘└──┬───┘   └──┬───┘        └──┬───┘
   │       │       │          │               │
   ▼       ▼       ▼          ▼               ▼
┌──────┐┌──────┐┌──────┐   ┌──────┐        ┌──────┐
│ LIVE ││SHADOW││DROPPED│  │SHADOW│        │DROPPED│
│ OPEN ││ OPEN │└──────┘   │ OPEN │        └──────┘
└──┬───┘└──┬───┘           └──┬───┘
   │       │                  │
   └───────┴──────────────────┘
                │
                ▼
         ┌────────────┐
         │   EXITED   │
         └────────────┘
```

### Benutzer-Aktionen

Der Benutzer hat folgende Optionen, wenn ein Trade-Vorschlag präsentiert wird:

| Button | Aktion | State-Übergang |
|--------|--------|----------------|
| **Trade ausführen** | Live-Trade platzieren | WAITING_FOR_USER → USER_ACCEPTED → LIVE_TRADE_OPEN |
| **Nur Schatten-Trade** | Shadow-Trade erstellen | WAITING_FOR_USER → USER_SHADOW → SHADOW_TRADE_OPEN |
| **Verwerfen** | Signal ignorieren | WAITING_FOR_USER → USER_REJECTED → DROPPED |

---

## Order-Sizing und Positionsberechnung

### Wie wird die Positionsgröße berechnet?

Die Positionsgröße wird durch das Zusammenspiel von **KI Layer**, **Risk Engine** und **Execution Layer** bestimmt:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        POSITIONSGRÖSSENBERECHNUNG                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. KI Layer liefert Trade-Parameter:                                       │
│     ┌───────────────────────────────────────┐                               │
│     │ size: 2.0 (Kontrakte)                 │                               │
│     │ sl: 74.50 (Stop Loss Level)           │                               │
│     │ tp: 76.00 (Take Profit Level)         │                               │
│     └───────────────────────────────────────┘                               │
│                                                                             │
│  2. Risk Engine prüft und passt an:                                         │
│     ┌───────────────────────────────────────┐                               │
│     │ Max Risk per Trade: 1% des Equity     │                               │
│     │ Max Position Size: 5 Kontrakte        │                               │
│     │ → Adjusted Size: min(2.0, 5.0)        │                               │
│     └───────────────────────────────────────┘                               │
│                                                                             │
│  3. Execution Layer verwendet effektive Order:                              │
│     ┌───────────────────────────────────────┐                               │
│     │ effective_order = adjusted_order ??   │                               │
│     │                   proposed_order      │                               │
│     └───────────────────────────────────────┘                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Risiko-basierte Positionsberechnung (Risk Engine)

Die Risk Engine berechnet die optimale Positionsgröße nach der Formel:

```
                    Max Risk Amount (EUR)
Position Size = ─────────────────────────────────
                 SL Distance (Ticks) × Tick Value
```

**Beispiel**:
```
Account Equity:      10.000 EUR
Max Risk per Trade:  1% = 100 EUR
Stop Loss Distance:  10 Ticks
Tick Value:          10 EUR

Position Size = 100 EUR / (10 × 10 EUR) = 1.0 Kontrakt
```

### Konfigurationsparameter für Sizing

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `max_risk_per_trade_percent` | Decimal | 1.0% | Max. Risiko pro Trade als % des Equity |
| `max_position_size` | Decimal | 5.0 | Maximale Positionsgröße (Kontrakte) |
| `tick_size` | Decimal | 0.01 | Tick-Größe des Instruments |
| `tick_value` | Decimal | 10.0 | Wert eines Ticks in Kontowährung |

### Order-Erstellung im Detail

```python
def _build_order_from_signals(
    self,
    setup: SetupCandidate,
    ki_eval: Optional[KiEvaluationResult],
) -> OrderRequest:
    """
    Erstellt eine Order aus Setup und KI-Evaluation.
    
    Priorität:
    1. KI-Evaluation Parameter (wenn is_tradeable())
    2. Default-Werte
    """
    # Richtung aus Setup
    direction = OrderDirection.BUY if setup.direction == "LONG" else OrderDirection.SELL
    
    # Parameter aus KI-Evaluation
    if ki_eval and ki_eval.is_tradeable():
        params = ki_eval.get_trade_parameters()
        size = Decimal(params.get('size', 1.0))
        stop_loss = Decimal(params.get('sl')) if params.get('sl') else None
        take_profit = Decimal(params.get('tp')) if params.get('tp') else None
    else:
        size = Decimal('1.0')
        stop_loss = None
        take_profit = None
    
    return OrderRequest(
        epic=setup.epic,
        direction=direction,
        size=size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        currency=self._config.default_currency,
    )
```

---

## Stop Loss und Take Profit

### Wie werden SL und TP festgelegt?

Stop Loss und Take Profit werden primär durch den **KI Layer** bestimmt und durch die **Risk Engine** validiert:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SL/TP BESTIMMUNGSPROZESS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. KI Layer berechnet SL/TP basierend auf:                                 │
│     • ATR (Average True Range)                                              │
│     • Range-Grenzen (Breakout-Kontext)                                      │
│     • Risiko-Rendite-Verhältnis (z.B. 1:2)                                  │
│     • Setup-Art (BREAKOUT, EIA_REVERSION, EIA_TRENDDAY)                     │
│                                                                             │
│  2. Risk Engine validiert:                                                  │
│     ┌───────────────────────────────────────┐                               │
│     │ SL Distanz >= sl_min_ticks (5)        │                               │
│     │ TP Distanz >= tp_min_ticks (5)        │                               │
│     │ SL ist PFLICHT                        │                               │
│     └───────────────────────────────────────┘                               │
│                                                                             │
│  3. Bei Ablehnung:                                                          │
│     • Trade wird blockiert                                                  │
│     • Nur Shadow-Trade möglich (wenn konfiguriert)                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Typische SL/TP Strategien

| Setup-Art | SL-Berechnung | TP-Berechnung |
|-----------|---------------|---------------|
| **BREAKOUT LONG** | Unter Range-Low | 2× Risiko-Distanz |
| **BREAKOUT SHORT** | Über Range-High | 2× Risiko-Distanz |
| **EIA_REVERSION** | Hinter Impuls-Extrem | Retrace-Level |
| **EIA_TRENDDAY** | Unter/Über Impuls-Range | Trend-Fortsetzung |

### Validierung durch Risk Engine

```python
def _check_sltp_validity(self, order: OrderRequest) -> Optional[str]:
    """Prüft SL/TP Mindestanforderungen."""
    
    # Stop Loss ist PFLICHT
    if order.stop_loss is None:
        return "Trade denied: Stop loss is required"
    
    # Minimale SL-Distanz wird in _check_position_risk geprüft
    return None

def _check_position_risk(self, account, order, setup):
    """Prüft Positionsrisiko und SL-Distanz."""
    
    # SL-Distanz berechnen
    entry_price = Decimal(str(setup.reference_price))
    sl_distance = abs(entry_price - order.stop_loss)
    sl_ticks = sl_distance / self.config.tick_size
    
    # Minimum SL-Distanz prüfen
    if sl_ticks < self.config.sl_min_ticks:
        return f"Trade denied: SL distance ({sl_ticks:.1f} ticks) " \
               f"below minimum ({self.config.sl_min_ticks} ticks)"
```

---

## Broker-Integration

### Unterstützte Broker

Das System unterstützt mehrere Broker durch ein abstraktes Interface:

| Broker | Service-Klasse | Märkte | Status |
|--------|----------------|--------|--------|
| **IG Markets** | `IgBrokerService` | CFDs, Spread Betting | ✅ Produktiv |
| **MEXC** | `MexcBrokerService` | Spot, Futures | ✅ Produktiv |

### Broker Registry

Der Execution Layer kann verschiedene Broker pro Asset verwenden:

```python
# Broker Registry Setup
from core.services.broker import BrokerRegistry

registry = BrokerRegistry()
registry.register("CC.D.CL.UNC.IP", ig_broker_service)  # Crude Oil bei IG
registry.register("BTCUSDT", mexc_broker_service)        # Bitcoin bei MEXC

# Execution Service mit Registry
execution_service.set_broker_registry(registry, shadow_only=False)
```

### Broker Service Interface

Alle Broker implementieren das `BrokerService` Interface:

```python
class BrokerService(ABC):
    @abstractmethod
    def connect(self) -> None:
        """Verbindung herstellen."""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Verbindung trennen."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Prüft Verbindungsstatus."""
        pass
    
    @abstractmethod
    def get_account_state(self) -> AccountState:
        """Aktueller Kontostand."""
        pass
    
    @abstractmethod
    def get_open_positions(self) -> List[Position]:
        """Offene Positionen."""
        pass
    
    @abstractmethod
    def get_symbol_price(self, epic: str) -> SymbolPrice:
        """Aktueller Marktpreis."""
        pass
    
    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Order platzieren."""
        pass
    
    @abstractmethod
    def close_position(self, position_id: str) -> OrderResult:
        """Position schließen."""
        pass
```

### Order-Ausführung

```python
def confirm_live_trade(self, session_id: str) -> ExecutedTrade:
    """
    Live-Trade ausführen.
    
    1. Session validieren (muss WAITING_FOR_USER sein)
    2. State auf USER_ACCEPTED setzen
    3. Effektive Order ermitteln (adjusted oder proposed)
    4. Order beim Broker platzieren
    5. ExecutedTrade erstellen und persistieren
    6. State auf LIVE_TRADE_OPEN setzen
    """
    session = self._get_session(session_id)
    
    # State-Validierung
    if session.state != ExecutionState.WAITING_FOR_USER:
        raise ExecutionError(
            f"Cannot execute: session is {session.state.value}",
            code="INVALID_STATE"
        )
    
    # Broker erforderlich
    if self._broker is None:
        raise ExecutionError(
            "Broker not configured",
            code="NO_BROKER"
        )
    
    # State-Transition
    session.transition_to(ExecutionState.USER_ACCEPTED)
    
    # Effektive Order (adjusted falls vorhanden)
    order = session.get_effective_order()
    
    # Broker-Aufruf
    result = self._broker.place_order(order)
    
    if not result.success:
        session.state = ExecutionState.WAITING_FOR_USER  # Rollback
        raise ExecutionError(f"Order rejected: {result.reason}")
    
    # Trade erstellen
    trade = ExecutedTrade(
        id=str(uuid.uuid4()),
        broker_deal_id=result.deal_id,
        epic=order.epic,
        direction=order.direction,
        size=order.size,
        entry_price=self._get_entry_price(order.epic),
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        status=TradeStatus.OPEN,
        # ...
    )
    
    # Persistieren
    self._weaviate.store_trade(trade)
    
    # Finaler State
    session.transition_to(ExecutionState.LIVE_TRADE_OPEN)
    
    return trade
```

### AccountState Modell

```python
@dataclass
class AccountState:
    account_id: str           # Konto-ID
    account_name: str         # Kontoname
    balance: Decimal          # Kontostand
    available: Decimal        # Verfügbar für Trading
    equity: Decimal           # Gesamtwert inkl. offener Positionen
    margin_used: Decimal      # Verwendete Margin
    margin_available: Decimal # Verfügbare Margin
    unrealized_pnl: Decimal   # Unrealisierter Gewinn/Verlust
    realized_pnl: Decimal     # Realisierter Gewinn/Verlust
    currency: str             # Kontowährung (z.B. "EUR")
    timestamp: datetime       # Zeitstempel
```

### Margin-Berechnung

Die Margin wird vom Broker verwaltet:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MARGIN-ÜBERSICHT                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Equity = Balance + Unrealized P&L                                          │
│                                                                             │
│  Margin Used = Summe aller offenen Positionen × Margin-Rate                 │
│                                                                             │
│  Margin Available = Equity - Margin Used                                    │
│                                                                             │
│  Margin Level = (Equity / Margin Used) × 100%                               │
│                                                                             │
│  ⚠️ WARNUNG: Margin Call bei < 100% Margin Level                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Shadow Trading

### Was ist Shadow Trading?

Shadow-Trades sind simulierte Trades, die:
- **Nicht** am Markt ausgeführt werden
- Den gleichen Lifecycle wie echte Trades durchlaufen
- Exit-Bedingungen (SL/TP) simulieren
- Performance-Tracking ermöglichen

### Wann werden Shadow-Trades erstellt?

1. **Risk Engine lehnt ab** und `allow_shadow_if_risk_denied = true`
2. **Benutzer wählt** "Nur Schatten-Trade"
3. **Kein Broker konfiguriert** (Shadow-Only Modus)

### ShadowTraderService

```python
class ShadowTraderService:
    """
    Verwaltet Shadow-Trades:
    - Erstellt Shadow-Trades aus vorgeschlagenen Orders
    - Simuliert Trade-Lifecycle basierend auf Marktpreisen
    - Trackt simulierte Exits (SL/TP, Zeit-Exit)
    - Zeichnet Performance für Analyse auf
    """
    
    def open_shadow_trade(
        self,
        setup: SetupCandidate,
        ki_eval: Optional[KiEvaluationResult],
        order: OrderRequest,
        skip_reason: Optional[str] = None,
    ) -> ShadowTrade:
        """Shadow-Trade öffnen."""
        ...
    
    def poll_shadow_trades(self) -> list[ShadowTrade]:
        """
        Prüft alle offenen Shadow-Trades auf Exit-Bedingungen.
        Schließt automatisch bei SL/TP.
        """
        ...
    
    def close_shadow_trade(
        self,
        trade_id: str,
        exit_price: Optional[Decimal] = None,
        exit_reason: str = "MANUAL",
    ) -> ShadowTrade:
        """Manuelles Schließen eines Shadow-Trades."""
        ...
```

### Exit-Bedingungen

```python
def _check_exit_conditions(
    self,
    shadow: ShadowTrade,
    current_price: Decimal,
) -> Optional[str]:
    """
    Prüft ob SL oder TP erreicht wurde.
    
    Returns:
        Exit-Reason oder None wenn noch offen.
    """
    if shadow.direction == TradeDirection.LONG:
        # Long Position
        if shadow.stop_loss and current_price <= shadow.stop_loss:
            return ExitReason.SL_HIT.value
        if shadow.take_profit and current_price >= shadow.take_profit:
            return ExitReason.TP_HIT.value
    else:
        # Short Position
        if shadow.stop_loss and current_price >= shadow.stop_loss:
            return ExitReason.SL_HIT.value
        if shadow.take_profit and current_price <= shadow.take_profit:
            return ExitReason.TP_HIT.value
    
    return None
```

### Exit-Gründe

```python
class ExitReason(str, Enum):
    SL_HIT = "SL_HIT"           # Stop Loss erreicht
    TP_HIT = "TP_HIT"           # Take Profit erreicht
    MANUAL = "MANUAL"           # Manuell geschlossen
    TIME_EXIT = "TIME_EXIT"     # Zeit-basierter Exit
    SIGNAL_EXIT = "SIGNAL_EXIT" # Gegensignal
    MARGIN_CALL = "MARGIN_CALL" # Margin Call
```

---

## Positions-Überwachung

### Wie werden Positionen überwacht?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      POSITIONS-MONITORING                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. POLLING (konfigurierbar)                                                │
│     ┌───────────────────────────────────────┐                               │
│     │ enable_exit_polling: true             │                               │
│     │ exit_polling_interval_seconds: 30     │                               │
│     └───────────────────────────────────────┘                               │
│                                                                             │
│  2. PRO POLLING-ZYKLUS:                                                     │
│     a) Aktuelle Preise vom Broker abrufen                                   │
│     b) SL/TP-Bedingungen prüfen                                             │
│     c) Bei Trigger: Exit ausführen und persistieren                         │
│                                                                             │
│  3. MARKET SNAPSHOTS (optional)                                             │
│     ┌───────────────────────────────────────┐                               │
│     │ track_market_snapshot_minutes_after_exit: 10                          │
│     │ track_snapshot_interval_seconds: 60   │                               │
│     └───────────────────────────────────────┘                               │
│     → Marktdaten nach Exit für Analyse speichern                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Session-Verwaltung

```python
# Aktive Sessions abrufen
active_sessions = execution_service.get_active_sessions()

# Alle Sessions (inkl. beendete)
all_sessions = execution_service.get_all_sessions()

# Sessions mit offenen Trades
open_trade_sessions = execution_service.get_open_trades()

# Spezifische Session
session = execution_service.get_session(session_id)
```

### Position-Tracking via Broker

```python
# Offene Positionen vom Broker abrufen
positions = broker_service.get_open_positions()

for pos in positions:
    print(f"Epic: {pos.epic}")
    print(f"Direction: {pos.direction.value}")
    print(f"Size: {pos.size}")
    print(f"Entry: {pos.open_price}")
    print(f"Current: {pos.current_price}")
    print(f"P&L: {pos.unrealized_pnl}")
    print(f"SL: {pos.stop_loss}")
    print(f"TP: {pos.take_profit}")
```

---

## Konfiguration

### ExecutionConfig Struktur

```python
@dataclass
class ExecutionConfig:
    allow_shadow_if_risk_denied: bool = True
    track_market_snapshot_minutes_after_exit: int = 10
    track_snapshot_interval_seconds: int = 60
    default_currency: str = 'EUR'
    enable_exit_polling: bool = True
    exit_polling_interval_seconds: int = 30
```

### Konfigurationsdatei (YAML)

**execution_config.yaml**:

```yaml
execution:
  # Allow shadow trades when risk engine denies the trade
  allow_shadow_if_risk_denied: true
  
  # Minutes to track market snapshots after trade exit
  track_market_snapshot_minutes_after_exit: 10
  
  # Interval between market snapshots (in seconds)
  track_snapshot_interval_seconds: 60
  
  # Default currency for trades
  default_currency: EUR
  
  # Enable automatic polling for exit conditions
  enable_exit_polling: true
  
  # Interval between exit condition checks (in seconds)
  exit_polling_interval_seconds: 30
```

### Konfiguration laden

```python
from core.services.execution import ExecutionConfig

# Aus YAML-Datei
config = ExecutionConfig.from_yaml('execution_config.yaml')

# Aus Dictionary
config = ExecutionConfig.from_dict({
    'allow_shadow_if_risk_denied': True,
    'default_currency': 'EUR',
})

# Zu YAML exportieren
yaml_string = config.to_yaml()
```

### Konfigurationsparameter

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `allow_shadow_if_risk_denied` | bool | true | Shadow-Trades bei Risk-Ablehnung erlauben |
| `track_market_snapshot_minutes_after_exit` | int | 10 | Minuten für Market-Tracking nach Exit |
| `track_snapshot_interval_seconds` | int | 60 | Intervall zwischen Snapshots |
| `default_currency` | str | EUR | Standard-Währung für Trades |
| `enable_exit_polling` | bool | true | Exit-Polling aktivieren |
| `exit_polling_interval_seconds` | int | 30 | Polling-Intervall in Sekunden |

---

## Datenmodelle

### ExecutionSession

Das zentrale Modell für Trade-Vorschläge:

```python
@dataclass
class ExecutionSession:
    id: str                    # Eindeutige Session-ID
    setup_id: str              # Referenz zum SetupCandidate
    ki_evaluation_id: str      # Referenz zur KI-Evaluation (optional)
    risk_result_id: str        # Referenz zum Risk-Result (optional)
    state: ExecutionState      # Aktueller State
    created_at: datetime       # Erstellungszeitpunkt
    last_update: datetime      # Letzte Änderung
    proposed_order: OrderRequest  # Ursprüngliche Order
    adjusted_order: OrderRequest  # Vom Risk Engine angepasste Order (optional)
    trade_id: str              # ID des ExecutedTrade/ShadowTrade (nach Ausführung)
    is_shadow: bool            # Shadow-Trade?
    comment: str               # Kommentar (z.B. Risk-Ablehnung)
    meta: dict                 # Zusätzliche Metadaten
    schema_version: str        # Schema-Version
```

### OrderRequest

```python
@dataclass
class OrderRequest:
    epic: str                  # Markt-Identifier
    direction: OrderDirection  # BUY oder SELL
    size: Decimal              # Positionsgröße
    order_type: OrderType      # MARKET, LIMIT, STOP, etc.
    limit_price: Decimal       # Limit-Preis (optional)
    stop_price: Decimal        # Stop-Preis (optional)
    stop_loss: Decimal         # Stop Loss Level
    take_profit: Decimal       # Take Profit Level
    guaranteed_stop: bool      # Garantierter Stop (gegen Gebühr)
    trailing_stop: bool        # Trailing Stop aktiv
    trailing_stop_distance: Decimal  # Trailing Stop Distanz
    currency: str              # Währung
```

### OrderResult

```python
@dataclass
class OrderResult:
    success: bool              # Erfolgreich?
    deal_id: str               # Deal-ID vom Broker
    deal_reference: str        # Referenz für Tracking
    status: OrderStatus        # OPEN, CLOSED, PENDING, REJECTED, etc.
    reason: str                # Ablehnungsgrund (wenn nicht erfolgreich)
    affected_deals: list       # Betroffene Deal-IDs
    timestamp: datetime        # Zeitstempel
```

### ExecutedTrade

```python
@dataclass
class ExecutedTrade:
    id: str                    # Trade-ID
    created_at: datetime       # Erstellungszeitpunkt
    setup_id: str              # Referenz zum Setup
    ki_evaluation_id: str      # Referenz zur KI-Evaluation
    risk_evaluation_id: str    # Referenz zum Risk-Result
    broker_deal_id: str        # Deal-ID vom Broker
    broker_order_id: str       # Order-ID vom Broker
    epic: str                  # Markt-Identifier
    direction: TradeDirection  # LONG oder SHORT
    size: Decimal              # Positionsgröße
    entry_price: Decimal       # Einstiegspreis
    stop_loss: Decimal         # Stop Loss
    take_profit: Decimal       # Take Profit
    status: TradeStatus        # OPEN, CLOSED
    opened_at: datetime        # Öffnungszeitpunkt
    closed_at: datetime        # Schließungszeitpunkt (optional)
    exit_price: Decimal        # Ausstiegspreis (optional)
    exit_reason: str           # Exit-Grund (optional)
    realized_pnl: Decimal      # Realisierter P&L (optional)
    currency: str              # Währung
    meta: dict                 # Zusätzliche Daten
```

### ShadowTrade

```python
@dataclass
class ShadowTrade:
    id: str                    # Trade-ID
    created_at: datetime       # Erstellungszeitpunkt
    setup_id: str              # Referenz zum Setup
    ki_evaluation_id: str      # Referenz zur KI-Evaluation
    risk_evaluation_id: str    # Referenz zum Risk-Result
    epic: str                  # Markt-Identifier
    direction: TradeDirection  # LONG oder SHORT
    size: Decimal              # Positionsgröße
    entry_price: Decimal       # Simulierter Einstiegspreis
    stop_loss: Decimal         # Stop Loss
    take_profit: Decimal       # Take Profit
    status: TradeStatus        # OPEN, CLOSED
    opened_at: datetime        # Öffnungszeitpunkt
    closed_at: datetime        # Schließungszeitpunkt (optional)
    exit_price: Decimal        # Ausstiegspreis (optional)
    exit_reason: str           # Exit-Grund (optional)
    skip_reason: str           # Warum Shadow statt Live
    theoretical_pnl: Decimal   # Theoretischer P&L
    theoretical_pnl_percent: float  # Theoretischer P&L in %
    meta: dict                 # Zusätzliche Daten
```

---

## Integration mit anderen Layern

### Kompletter Datenfluss

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           FIONA TRADING WORKFLOW                               │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  1. STRATEGY ENGINE                                                            │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ Input:  MarketStateProvider (Candles, Ranges, ATR)  │                    │
│     │ Output: SetupCandidate                              │                    │
│     │         - setup_kind (BREAKOUT, EIA_*)              │                    │
│     │         - direction (LONG/SHORT)                    │                    │
│     │         - reference_price                           │                    │
│     │         - breakout/eia context                      │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                              │                                                 │
│                              ▼                                                 │
│  2. KI LAYER                                                                   │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ Input:  SetupCandidate                              │                    │
│     │ Output: KiEvaluationResult                          │                    │
│     │         - is_tradeable()                            │                    │
│     │         - get_trade_parameters()                    │                    │
│     │           → size, sl, tp                            │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                              │                                                 │
│                              ▼                                                 │
│  3. RISK ENGINE                                                                │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ Input:  AccountState, Positions, Order, Setup       │                    │
│     │ Output: RiskEvaluationResult                        │                    │
│     │         - allowed (true/false)                      │                    │
│     │         - reason                                    │                    │
│     │         - adjusted_order (wenn Size angepasst)      │                    │
│     │         - violations[]                              │                    │
│     │         - risk_metrics{}                            │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                              │                                                 │
│                              ▼                                                 │
│  4. EXECUTION LAYER                                                            │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ Input:  SetupCandidate, KiEvaluationResult,         │                    │
│     │         RiskEvaluationResult                        │                    │
│     │ Output: ExecutionSession → ExecutedTrade/ShadowTrade│                    │
│     │                                                     │                    │
│     │ Aktionen:                                           │                    │
│     │   - propose_trade() → Session erstellen             │                    │
│     │   - confirm_live_trade() → Broker Order             │                    │
│     │   - confirm_shadow_trade() → Simulation             │                    │
│     │   - reject_trade() → Verwerfen                      │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                              │                                                 │
│                              ▼                                                 │
│  5. BROKER SERVICE                                                             │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ - place_order()                                     │                    │
│     │ - get_symbol_price()                                │                    │
│     │ - get_open_positions()                              │                    │
│     │ - close_position()                                  │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                              │                                                 │
│                              ▼                                                 │
│  6. WEAVIATE (Persistierung)                                                   │
│     ┌─────────────────────────────────────────────────────┐                    │
│     │ - store_trade()                                     │                    │
│     │ - store_shadow_trade()                              │                    │
│     │ - store_market_snapshot()                           │                    │
│     └─────────────────────────────────────────────────────┘                    │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Konfiguration pro Layer

| Layer | Konfigurationsdatei | Beschreibung |
|-------|---------------------|--------------|
| Strategy Engine | `strategy_config.yaml` | Breakout/EIA Parameter |
| Risk Engine | `risk_config.yaml` | Limits und Regeln |
| Execution Layer | `execution_config.yaml` | Shadow/Polling Settings |
| Broker | Django Admin | API Credentials |

### Beispiel: Vollständiger Workflow

```python
from datetime import datetime, timezone
from core.services.broker import IgBrokerService, IGMarketStateProvider
from core.services.strategy import StrategyEngine, StrategyConfig
from core.services.risk import RiskEngine, RiskConfig
from core.services.execution import ExecutionService, ExecutionConfig
from fiona.ki.services import KiService

# 1. Services initialisieren
broker = IgBrokerService.from_config(ig_config)
broker.connect()

provider = IGMarketStateProvider(broker)
strategy = StrategyEngine(provider, StrategyConfig())
risk = RiskEngine(RiskConfig.from_yaml('risk_config.yaml'))
execution = ExecutionService(
    broker_service=broker,
    config=ExecutionConfig.from_yaml('execution_config.yaml')
)
ki = KiService()

# 2. Setup evaluieren
now = datetime.now(timezone.utc)
candidates = strategy.evaluate("CC.D.CL.UNC.IP", now)

if not candidates:
    print("Keine Setups gefunden")
else:
    setup = candidates[0]
    print(f"Setup: {setup.setup_kind.value} {setup.direction}")
    
    # 3. KI-Evaluation
    ki_eval = ki.evaluate(setup)
    
    # 4. Risk-Evaluation
    account = broker.get_account_state()
    positions = broker.get_open_positions()
    order = execution._build_order_from_signals(setup, ki_eval)
    
    risk_result = risk.evaluate(
        account=account,
        positions=positions,
        setup=setup,
        order=order,
        now=now,
    )
    
    print(f"Risk: {'✓' if risk_result.allowed else '✗'} {risk_result.reason}")
    
    # 5. Trade-Vorschlag erstellen
    session = execution.propose_trade(
        setup=setup,
        ki_eval=ki_eval,
        risk_eval=risk_result
    )
    
    print(f"Session: {session.id}")
    print(f"State: {session.state.value}")
    
    # 6. Benutzer-Entscheidung simulieren
    if session.state == ExecutionState.WAITING_FOR_USER:
        # Live-Trade
        trade = execution.confirm_live_trade(session.id)
        print(f"Trade ausgeführt: {trade.id}")
    elif session.state == ExecutionState.SHADOW_ONLY:
        # Shadow-Trade
        shadow = execution.confirm_shadow_trade(session.id)
        print(f"Shadow-Trade erstellt: {shadow.id}")
```

---

## Beispiele

### Basis-Verwendung

```python
from core.services.execution import ExecutionService, ExecutionConfig
from core.services.broker import IgBrokerService

# Service erstellen
broker = IgBrokerService.from_config(config)
broker.connect()

execution = ExecutionService(
    broker_service=broker,
    config=ExecutionConfig(),
)

# Trade-Vorschlag aus Signalen
session = execution.propose_trade(
    setup=setup_candidate,
    ki_eval=ki_evaluation_result,
    risk_eval=risk_evaluation_result,
)

# Benutzer-Aktionen
if session.state == ExecutionState.WAITING_FOR_USER:
    # Option 1: Live-Trade
    trade = execution.confirm_live_trade(session.id)
    
    # Option 2: Shadow-Trade
    shadow = execution.confirm_shadow_trade(session.id)
    
    # Option 3: Verwerfen
    execution.reject_trade(session.id)
```

### Shadow-Only Modus

```python
# Execution ohne Broker (nur Shadow-Trades)
execution = ExecutionService(
    broker_service=None,  # Kein Broker
    config=ExecutionConfig(),
    shadow_only=True,
)

# Alle Trades werden als Shadow-Trades ausgeführt
session = execution.propose_trade(setup, ki_eval, risk_eval)

# State ist automatisch SHADOW_ONLY
assert session.state == ExecutionState.SHADOW_ONLY

# Nur Shadow-Trade möglich
shadow = execution.confirm_shadow_trade(session.id)
```

### Sessions verwalten

```python
# Alle aktiven Sessions
active = execution.get_active_sessions()
print(f"Aktive Sessions: {len(active)}")

# Offene Trades
open_trades = execution.get_open_trades()
print(f"Offene Trades: {len(open_trades)}")

# Spezifische Session
session = execution.get_session(session_id)
if session:
    print(f"State: {session.state.value}")
    print(f"Order Size: {session.proposed_order.size}")
```

### Error Handling

```python
from core.services.execution import ExecutionService, ExecutionError

try:
    trade = execution.confirm_live_trade(session_id)
except ExecutionError as e:
    print(f"Fehler: {e}")
    print(f"Code: {e.code}")
    print(f"Details: {e.details}")
    
    # Typische Fehler:
    # - INVALID_STATE: Session nicht in erwartetem State
    # - SESSION_NOT_FOUND: Session-ID nicht gefunden
    # - NO_BROKER: Broker nicht konfiguriert
    # - BROKER_ERROR: Broker-API Fehler
    # - ORDER_REJECTED: Order vom Broker abgelehnt
```

---

## Fehlerbehebung

### Häufige Probleme

| Problem | Mögliche Ursache | Lösung |
|---------|------------------|--------|
| "Session not found" | Ungültige Session-ID | Session-ID prüfen |
| "Invalid state" | State-Übergang nicht erlaubt | State-Diagramm prüfen |
| "No broker configured" | Broker nicht gesetzt | Broker Service konfigurieren |
| "Order rejected" | Broker-Ablehnung | Broker-Logs prüfen, Order-Parameter validieren |
| Shadow statt Live | Risk Engine hat abgelehnt | Risk-Violations prüfen |

### Debug-Logging

```python
import logging

# Execution Layer Debug-Logs aktivieren
logging.getLogger('core.services.execution').setLevel(logging.DEBUG)
```

### Log-Beispiel

```
Trade proposal session created
  - session_id: abc-123
  - setup_id: setup-456
  - initial_state: WAITING_FOR_USER
  - proposed_size: 2.0
  - proposed_sl: 74.50
  - proposed_tp: 76.00
  - adjusted_size: 1.5 (vom Risk Engine)
  - risk_comment: Position size reduced to fit risk limits

Live trade executed successfully
  - session_id: abc-123
  - trade_id: trade-789
  - epic: CC.D.CL.UNC.IP
  - direction: LONG
  - size: 1.5
  - entry_price: 75.10
  - broker_deal_id: IG-DEAL-123
```

---

## Weiterführende Dokumentation

- [Strategy Engine Dokumentation](STRATEGY_ENGINE.md) – Signalgenerierung
- [Trading Setup Guide](TRADING_SETUP_GUIDE.md) – Broker-Konfiguration
- [Fiona Big Picture](fiona-big-picture.md) – Gesamtarchitektur
- [API Documentation](API_Documentation.md) – REST API

---

*Letzte Aktualisierung: November 2024 | Schema-Version: 1.0*
