



# Fiona Trading System – Einrichtung & Betrieb

Dieses Dokument beschreibt die Einrichtung und den Betrieb des Trading-Systems in Fiona (IG Broker Integration).

---

## Übersicht

Das Fiona Trading-System besteht aus folgenden Kernkomponenten:

| Komponente | Beschreibung |
|------------|--------------|
| **Broker Service** | Abstrakte Schnittstelle für Broker-Integrationen |
| **IG Broker Service** | Konkrete Implementierung für IG Markets |
| **Risk Engine** | Deterministische Risikoprüfung vor jedem Trade |
| **Execution Layer** | Orchestriert Trades und Shadow-Trading |
| **Strategy Engine** | Signalgenerierung (Breakouts, EIA-Setups) |

---

## 1. Voraussetzungen

### 1.1 IG-Konto erstellen

1. Gehen Sie zu [IG Markets](https://www.ig.com/)
2. Erstellen Sie ein **Demo-Konto** (empfohlen für Tests) oder Live-Konto
3. Notieren Sie sich:
   - **Username** (Benutzername/Email)
   - **Passwort**
   
### 1.2 IG API-Key beantragen

1. Loggen Sie sich in Ihr IG-Konto ein
2. Navigieren Sie zu **My IG** → **Settings** → **API**
3. Beantragen Sie einen **API-Key**
4. Warten Sie auf die Aktivierung (kann einige Stunden dauern)
5. Notieren Sie den **API-Key**

### 1.3 System-Voraussetzungen

- Python 3.11+
- Django-Projekt läuft (`python manage.py runserver`)
- Datenbank ist migriert (`python manage.py migrate`)

---

## 2. IG Broker konfigurieren

### 2.1 Via Django Admin

1. Öffnen Sie das Admin-Interface: `http://127.0.0.1:8000/admin/`
2. Navigieren Sie zu **Core** → **IG Broker Configurations**
3. Klicken Sie auf **Add IG Broker Configuration**
4. Füllen Sie die Felder aus:

| Feld | Beschreibung | Beispiel |
|------|--------------|----------|
| **Name** | Bezeichnung der Konfiguration | "IG Demo" |
| **Account Type** | Demo oder Live | Demo |
| **API Key** | Ihr IG API-Key | `abc123xyz...` |
| **Username** | IG Benutzername/Email | `user@example.com` |
| **Password** | IG Passwort | `********` |
| **Account ID** | Optional: spezifische Account-ID | (leer lassen) |
| **API Base URL** | Optional: wird automatisch gesetzt | (leer lassen) |
| **Default Oil EPIC** | Standard-EPIC für Öl-Trading | `CC.D.CL.UNC.IP` |
| **Timeout Seconds** | Request-Timeout | `30` |
| **Is Active** | ✓ aktivieren | ✓ |

5. Speichern Sie die Konfiguration

### 2.2 Wichtige Hinweise

- **Nur eine Konfiguration** sollte `is_active = True` haben
- Bei **Demo-Konten** wird automatisch `https://demo-api.ig.com/gateway/deal` verwendet
- Bei **Live-Konten** wird automatisch `https://api.ig.com/gateway/deal` verwendet
- **Passwörter werden im Klartext gespeichert** – verwenden Sie entsprechende Datenbankschutz-Maßnahmen

---

## 3. Programmatische Nutzung

### 3.1 Broker Service erstellen

```python
from core.services.broker import create_ig_broker_service

# Automatisch aus der aktiven Konfiguration erstellen
broker = create_ig_broker_service()

# Verbindung herstellen
broker.connect()

# Verbindung prüfen
if broker.is_connected():
    print("Erfolgreich verbunden!")
```

### 3.2 Kontoinformationen abrufen

```python
# Aktueller Kontostand
state = broker.get_account_state()
print(f"Balance: {state.balance} {state.currency}")
print(f"Verfügbar: {state.available}")
print(f"Margin verwendet: {state.margin_used}")
print(f"Unrealisierter P&L: {state.unrealized_pnl}")
```

### 3.3 Marktpreise abrufen

```python
# Preis für WTI Crude Oil
price = broker.get_symbol_price("CC.D.CL.UNC.IP")
print(f"Bid: {price.bid}")
print(f"Ask: {price.ask}")
print(f"Spread: {price.spread}")
print(f"High: {price.high}")
print(f"Low: {price.low}")
```

### 3.4 Offene Positionen abrufen

```python
positions = broker.get_open_positions()
for pos in positions:
    print(f"EPIC: {pos.epic}")
    print(f"Richtung: {pos.direction}")
    print(f"Größe: {pos.size}")
    print(f"Entry: {pos.open_price}")
    print(f"P&L: {pos.unrealized_pnl}")
```

### 3.5 Order platzieren

```python
from core.services.broker import OrderRequest, OrderDirection, OrderType
from decimal import Decimal

# Market Order
order = OrderRequest(
    epic="CC.D.CL.UNC.IP",
    direction=OrderDirection.BUY,
    size=Decimal("1.0"),
    order_type=OrderType.MARKET,
    stop_loss=Decimal("74.00"),  # Optional
    take_profit=Decimal("78.00"),  # Optional
    currency="EUR",
)

result = broker.place_order(order)

if result.success:
    print(f"Order erfolgreich! Deal-ID: {result.deal_id}")
else:
    print(f"Order fehlgeschlagen: {result.reason}")
```

### 3.6 Position schließen

```python
result = broker.close_position(position_id="DEAL123ABC")

if result.success:
    print("Position geschlossen!")
else:
    print(f"Fehler: {result.reason}")
```

### 3.7 Verbindung trennen

```python
broker.disconnect()
```

---

## 4. Risk Engine konfigurieren

Die Risk Engine prüft jeden Trade gegen konfigurierbare Limits.

### 4.1 Konfigurationsdatei erstellen

Kopieren Sie die Beispielkonfiguration:

```bash
cp core/services/risk/risk_config.example.yaml core/services/risk/risk_config.yaml
```

### 4.2 Wichtige Parameter

| Parameter | Beschreibung | Standard |
|-----------|--------------|----------|
| `max_risk_per_trade_percent` | Max. Risiko pro Trade (% vom Equity) | 1.0 |
| `max_daily_loss_percent` | Max. Tagesverlust (% vom Equity) | 3.0 |
| `max_weekly_loss_percent` | Max. Wochenverlust (% vom Equity) | 6.0 |
| `max_open_positions` | Max. offene Positionen | 1 |
| `max_position_size` | Max. Positionsgröße (Kontrakte) | 5.0 |
| `deny_overnight` | Positionen über Nacht verbieten | true |
| `deny_friday_after` | Keine neuen Trades nach (CET) | "21:00" |
| `deny_eia_window_minutes` | Sperrzeit um EIA-Release | 5 |

### 4.3 Beispielkonfiguration

```yaml
# risk_config.yaml
max_risk_per_trade_percent: 1.0
max_daily_loss_percent: 3.0
max_weekly_loss_percent: 6.0
max_open_positions: 1
max_position_size: 5.0
allow_countertrend: false
sl_min_ticks: 5
tp_min_ticks: 5
deny_eia_window_minutes: 5
deny_friday_after: "21:00"
deny_overnight: true
tick_size: 0.01
tick_value: 10.0
```

---

## 5. Execution Layer konfigurieren

### 5.1 Konfigurationsdatei erstellen

```bash
cp core/services/execution/execution_config.example.yaml core/services/execution/execution_config.yaml
```

### 5.2 Wichtige Parameter

| Parameter | Beschreibung | Standard |
|-----------|--------------|----------|
| `allow_shadow_if_risk_denied` | Shadow-Trades bei Risiko-Ablehnung | true |
| `track_market_snapshot_minutes_after_exit` | Marktüberwachung nach Exit | 10 |
| `default_currency` | Standard-Währung | EUR |
| `enable_exit_polling` | Automatische Exit-Prüfung | true |
| `exit_polling_interval_seconds` | Intervall für Exit-Prüfung | 30 |

---

## 6. Betrieb

### 6.1 Trading-Workflow

1. **Strategy Engine** erkennt Setup-Kandidaten (Breakouts, EIA)
2. **Risk Engine** prüft Limits und gibt frei/blockiert
3. **Execution Layer** führt Trade aus oder erstellt Shadow-Trade
4. **Position wird überwacht** bis Exit-Bedingung erfüllt
5. **Trade-Ergebnis** wird in Weaviate/DB gespeichert

### 6.2 Shadow-Trading

Shadow-Trades werden ausgeführt wenn:
- Risk Engine den Trade blockiert
- `allow_shadow_if_risk_denied: true` konfiguriert ist

Shadow-Trades:
- Nutzen kein echtes Kapital
- Werden mit simulierten Ergebnissen geloggt
- Dienen zum Lernen und Optimieren

### 6.3 Monitoring

Überwachen Sie regelmäßig:

```python
# Kontostand prüfen
state = broker.get_account_state()
print(f"Equity: {state.equity}")
print(f"Margin verfügbar: {state.margin_available}")

# Offene Positionen
positions = broker.get_open_positions()
print(f"Offene Positionen: {len(positions)}")
```

---

## 7. Wichtige EPICs

Häufig verwendete IG Market EPICs:

| Markt | EPIC |
|-------|------|
| WTI Crude Oil | `CC.D.CL.UNC.IP` |
| Brent Crude Oil | `CC.D.LCO.UNC.IP` |
| Natural Gas | `CC.D.NG.UNC.IP` |
| Gold | `CS.D.USCGC.TODAY.IP` |
| EUR/USD | `CS.D.EURUSD.TODAY.IP` |
| DAX 40 | `IX.D.DAX.IFD.IP` |
| S&P 500 | `IX.D.SPTRD.IFD.IP` |

---

## 8. Fehlerbehandlung

### 8.1 Häufige Fehler

| Fehler | Ursache | Lösung |
|--------|---------|--------|
| `AuthenticationError` | Ungültige Credentials | API-Key, Username, Passwort prüfen |
| `ConnectionError` | Netzwerkproblem | Internetverbindung prüfen |
| `BrokerError` | API-Fehler von IG | Error-Code analysieren |
| `ImproperlyConfigured` | Keine aktive Konfiguration | `is_active` setzen |

### 8.2 Logging aktivieren

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Broker-spezifisches Logging
logger = logging.getLogger('core.services.broker')
logger.setLevel(logging.DEBUG)
```

---

## 9. Sicherheitshinweise

⚠️ **Wichtig:**

1. **Demo-Konto zuerst** – Testen Sie immer zuerst mit Demo
2. **Passwörter schützen** – Verwenden Sie Environment-Variablen in Production
3. **API-Key geheim halten** – Nicht in Git committen
4. **Risk-Limits einhalten** – Niemals Risk Engine umgehen
5. **Monitoring** – Überwachen Sie Positionen und Kontostand

### 9.1 Environment-Variablen (Empfehlung)

Statt Credentials in der DB zu speichern:

```bash
export IG_API_KEY="your-api-key"
export IG_USERNAME="your-username"
export IG_PASSWORD="your-password"
```

---

## 10. Tests ausführen

```bash
# Alle Broker-Tests
python manage.py test core.tests_broker

# Alle Tests
python manage.py test
```

---

## Weiterführende Dokumentation

- [API-Dokumentation](API_Documentation.md)
- [Fiona Big Picture](fiona-big-picture.md)
- [IG API Dokumentation](https://labs.ig.com/rest-trading-api-reference)
