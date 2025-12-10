# MEXC SPOT Market Live Trading - Anleitung

## Übersicht

Das Fiona Trading System unterstützt jetzt vollständigen Live-Handel auf dem MEXC SPOT Markt. Der Handel erfolgt nur, wenn das `auto_trade` Flag im Asset aktiviert ist und die Risk Engine den Trade genehmigt.

## Voraussetzungen

### 1. MEXC API Zugang einrichten

1. MEXC Account erstellen: https://www.mexc.com
2. API Key und Secret generieren:
   - Einloggen → Account → API Management
   - Neuen API Key erstellen
   - **Wichtig**: Spot Trading Berechtigung aktivieren
   - API Key und Secret sicher speichern

### 2. MEXC Broker in Fiona konfigurieren

1. Django Admin Panel öffnen: `/admin/`
2. Zu "MEXC Broker Configs" navigieren
3. Neue Konfiguration erstellen:
   - **Name**: z.B. "MEXC SPOT Live"
   - **API Key**: Ihr MEXC API Key
   - **API Secret**: Ihr MEXC API Secret
   - **Account Type**: **SPOT** (wichtig!)
   - **Is Active**: ✓ Häkchen setzen
4. Speichern

### 3. Trading Asset für MEXC konfigurieren

1. Django Admin Panel → "Trading Assets"
2. Neues Asset erstellen oder bestehendes bearbeiten:
   - **Name**: z.B. "Bitcoin/USDT"
   - **Symbol**: z.B. "BTC"
   - **Epic**: MEXC Symbol, z.B. "BTCUSDT"
   - **Broker**: **MEXC** auswählen
   - **Quote Currency**: USDT
   - **Is Active**: ✓ Häkchen setzen
   - **Auto Trade**: ⚠️ **NUR aktivieren wenn Sie Live-Trading wünschen!**

## Funktionsweise

### Auto-Trade Ablauf

Wenn ein Signal generiert wird:

1. **Strategy Engine** erkennt Setup (z.B. Breakout)
2. **Risk Engine** evaluiert das Risiko
3. **Wenn `auto_trade = True` und Risk Status = ALLOWED:**
   - Worker ruft automatisch `_execute_auto_trade()` auf
   - Order wird an MEXC SPOT API gesendet
   - Trade wird in der Datenbank gespeichert
   - Signal Status wird auf "EXECUTED" gesetzt

4. **Wenn `auto_trade = False`:**
   - Signal wird mit Status "ACTIVE" gespeichert
   - Benutzer kann im UI entscheiden ob Trade ausgeführt wird

### SPOT vs FUTURES

Das System unterstützt beide MEXC Account-Typen:

- **SPOT Account**:
  - Verwendet API: `https://api.mexc.com/api/v3/order`
  - BUY/SELL Orders
  - Direkte Asset-Käufe (z.B. BTC kaufen mit USDT)

- **FUTURES Account**:
  - Verwendet API: `https://contract.mexc.com/api/v1/private/order/submit`
  - Open Long/Short Positionen
  - Leverage Trading

**Für diese Anpassung: Nur SPOT wird verwendet!**

## Sicherheitshinweise

### ⚠️ WICHTIG: auto_trade Flag

- **Default: False** - System führt KEINE automatischen Trades aus
- **Nur aktivieren wenn:**
  - API Keys korrekt konfiguriert sind
  - Risk Engine konfiguriert ist
  - Sie automatischen Handel wünschen
  - Ausreichend USDT im MEXC Account vorhanden ist

### API Berechtigungen

Stellen Sie sicher dass der MEXC API Key folgende Berechtigungen hat:
- ✓ Spot Trading
- ✓ Read Account Information
- ✗ Withdrawals (NICHT notwendig und sollte DEAKTIVIERT sein!)

### Test vor Live-Trading

1. Testen Sie zuerst mit `auto_trade = False`
2. Überprüfen Sie Signals im UI
3. Manuell einen Test-Trade durchführen
4. Erst dann `auto_trade = True` setzen

## Beispiel-Konfiguration

### MEXC SPOT Trading für BTC/USDT

```python
# TradingAsset Konfiguration
asset = TradingAsset.objects.create(
    name="Bitcoin/USDT",
    symbol="BTC",
    epic="BTCUSDT",  # MEXC Symbol
    broker="MEXC",
    broker_symbol="BTCUSDT",  # Optional, wenn anders als epic
    quote_currency="USDT",
    category="crypto",
    strategy_type="breakout_event",
    is_active=True,
    auto_trade=False,  # Zuerst False für Tests!
    # ... weitere Felder
)
```

## Monitoring

### Logs überprüfen

Wenn auto_trade aktiviert ist, zeigt der Worker:

```
✓ Signal created: <signal_id>
  Status: ACTIVE
  Risk: GREEN
  Direction: LONG
  Entry: 50000.00
  SL: 49500.00
  TP: 51000.00
  Size: 0.001
  → Auto-Trade enabled and risk allowed, executing trade automatically...
    → Placing order at broker...
    ✓ Order placed successfully! Order ID: <order_id>
    ✓ Trade created: <trade_id>
    → Signal status updated to: EXECUTED
```

### Error Handling

Bei Fehlern:
- Order Rejection: Signal bleibt ACTIVE, kann manuell retried werden
- Broker Error: Signal bleibt ACTIVE, Fehler wird geloggt
- Signal bleibt immer erhalten für manuelle Überprüfung

## Technische Details

### Code-Pfade

- **Broker Service**: `/core/services/broker/mexc_broker_service.py`
- **Execution Service**: `/core/services/execution/execution_service.py`
- **Worker Auto-Trade**: `/core/management/commands/run_fiona_worker.py`
- **Broker Registry**: `/core/services/broker/config.py`

### Order Flow

```
Worker Cycle
  → Strategy Engine detects setup
  → Risk Engine evaluates
  → Signal created with status=ACTIVE
  → IF auto_trade=True AND risk_allowed=True:
      → _execute_auto_trade()
      → BrokerRegistry.get_broker_for_asset(asset)
      → MexcBrokerService.place_order(order)
      → _place_spot_order() [for SPOT accounts]
      → POST https://api.mexc.com/api/v3/order
      → Trade record created
      → Signal.status = EXECUTED
```

## Troubleshooting

### "No active MEXC Broker configuration found"
- Gehen Sie zu Admin Panel → MEXC Broker Configs
- Erstellen Sie neue Config mit `is_active=True`

### "Authentication failed"
- Überprüfen Sie API Key und Secret
- Stellen Sie sicher dass API Key aktiv ist
- Überprüfen Sie IP Whitelist in MEXC (falls aktiviert)

### "Order rejected: Insufficient balance"
- Überprüfen Sie USDT Balance im MEXC SPOT Account
- Reduzieren Sie Position Size
- Passen Sie Risk Engine Parameter an

### Signal bleibt ACTIVE trotz auto_trade=True
- Überprüfen Sie Risk Status (muss GREEN oder YELLOW sein)
- Überprüfen Sie Worker Logs für Fehler
- Broker muss connected sein

## Testing

Ein Testskript ist verfügbar:

```bash
python scripts/test_mexc_broker.py
```

Dies testet:
- Connection zu MEXC
- Account State abrufen
- Symbol Price abrufen
- Historical Data abrufen

**Hinweis**: Für Live-Trading Tests mit `place_order()` verwenden Sie ein Test-Account oder sehr kleine Mengen!

## Fazit

Das System ist vollständig für MEXC SPOT Live-Trading bereit:
- ✅ Keine Mocks oder Fake-Daten
- ✅ Echte MEXC API Integration
- ✅ Auto-Trade nur wenn explizit aktiviert
- ✅ Risk Engine Integration
- ✅ Vollständige Fehlerbehandlung
- ✅ Logging und Monitoring

**Viel Erfolg beim Trading! 🚀**
