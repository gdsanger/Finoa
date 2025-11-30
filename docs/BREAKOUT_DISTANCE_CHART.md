# Breakout Distance Chart - Dokumentation

## Übersicht

Das **Breakout Distance Chart** ist ein Echtzeit-Chart zur Visualisierung von Breakout-Setups. Es zeigt Candlestick-Daten zusammen mit Session-Ranges und Breakout-Levels für die aktive Asset-Trading-Strategie.

### Features

- **Broker-agnostisch**: Unterstützt sowohl IG als auch MEXC Broker
- **Echtzeit-Streaming**: Live-Datenaktualisierung alle 30 Sekunden
- **Redis-Backed Persistence**: Candle-Daten werden in Redis gespeichert und überleben Neustarts
- **Konfigurierbare Zeitfenster**: 1h, 3h, 6h, 8h, 12h, 24h, 48h, 72h
- **Unterstützte Timeframes**: 1m, 5m, 15m, 1h
- **Status-Indikator**: Zeigt an, ob Daten live gestreamt, gepollt oder aus dem Cache geladen werden

---

## Architektur

### Market Data Layer

Das Breakout Distance Chart verwendet den neuen **Market Data Layer** (`core/services/market_data/`), der folgende Komponenten umfasst:

```
core/services/market_data/
├── __init__.py                   # Modul-Exports
├── candle_models.py              # Candle, CandleStreamStatus, CandleDataResponse
├── candle_stream.py              # CandleStream (In-Memory Ring Buffer)
├── market_data_config.py         # Konfiguration (Timeframes, Windows)
├── market_data_stream_manager.py # MarketDataStreamManager (Singleton)
└── redis_candle_store.py         # RedisCandleStore (Persistenz)
```

### Datenfluss

1. **Frontend** ruft `/trading/api/breakout-distance-candles` auf
2. **MarketDataStreamManager** prüft, ob Daten im Stream-Buffer sind
3. Falls Daten fehlen oder veraltet sind: Abruf vom **Broker** (IG/MEXC)
4. Candles werden im **In-Memory Ring Buffer** gehalten
5. Candles werden parallel in **Redis** persistiert
6. **Frontend** erhält Candles + Status (LIVE/POLL/CACHED/OFFLINE)

---

## Systemanforderungen

### Redis-Server

Redis ist für die persistente Candle-Speicherung erforderlich:

```bash
# Installation (Ubuntu/Debian)
sudo apt update
sudo apt install redis-server

# Starten
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Status prüfen
redis-cli ping
# Erwartete Antwort: PONG
```

### Redis-Konfiguration

Die Standardkonfiguration verwendet `localhost:6379`. Anpassungen können über Umgebungsvariablen erfolgen:

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
```

### Broker-Konfiguration

Mindestens ein Broker muss konfiguriert sein:

#### IG Broker (für CFDs, Indizes, Rohstoffe)
1. Navigiere zu **Admin → Core → IG Broker Configs**
2. Erstelle eine neue Konfiguration mit:
   - API Key
   - Username
   - Password
   - Account ID
   - `is_active = True`

#### MEXC Broker (für Krypto)
1. Navigiere zu **Admin → Core → MEXC Broker Configs**
2. Erstelle eine neue Konfiguration mit:
   - API Key
   - API Secret
   - `is_active = True`

---

## API-Endpunkte

### Breakout Distance Candles

```http
GET /fiona/api/breakout-distance-candles
```

**Parameter:**
| Name      | Typ    | Pflicht | Beschreibung                                |
|-----------|--------|---------|---------------------------------------------|
| asset_id  | int    | Ja      | ID des TradingAsset                         |
| timeframe | string | Nein    | Candle-Intervall (1m, 5m, 15m, 1h). Default: 1m |
| window    | float  | Nein    | Zeitfenster in Stunden. Default: 6          |

**Response:**
```json
{
  "success": true,
  "asset": "CL",
  "timeframe": "1m",
  "window_hours": 6.0,
  "candle_count": 360,
  "candles": [
    {"time": 1700000000, "open": 75.5, "high": 75.75, "low": 75.25, "close": 75.6},
    ...
  ],
  "status": {
    "status": "LIVE",
    "last_update": "2025-11-30T10:00:00Z",
    "candle_count": 360,
    "broker": "IG",
    "error": null
  }
}
```

### Market Data Status

```http
GET /fiona/api/market-data/status
```

**Response:**
```json
{
  "success": true,
  "total_streams": 2,
  "streams": [
    {
      "asset_id": "CL",
      "timeframe": "1m",
      "status": "LIVE",
      "candle_count": 360,
      "broker": "IG"
    }
  ]
}
```

---

## Status-Indikatoren

Das Chart zeigt einen Status-Indikator mit folgenden Zuständen:

| Status   | Farbe | Bedeutung                                |
|----------|-------|------------------------------------------|
| LIVE     | Grün  | Echtzeit-Stream aktiv                    |
| POLL     | Blau  | Fallback auf REST-Polling                |
| CACHED   | Gelb  | Daten aus Redis-Cache                    |
| OFFLINE  | Rot   | Keine Daten / Verbindungsfehler          |

---

## Konfiguration

### Zeitfenster pro Asset-Kategorie

Verschiedene Asset-Kategorien können unterschiedliche Standard-Zeitfenster haben:

```python
# core/services/market_data/market_data_config.py

DEFAULT_WINDOWS = {
    'commodity': [1, 3, 6, 8, 12, 24],     # Rohstoffe
    'crypto': [1, 3, 6, 12, 24, 48, 72],   # Krypto (24/7)
    'index': [1, 3, 6, 8, 12, 24],         # Indizes
    'forex': [1, 3, 6, 12, 24],            # Forex
}
```

### Redis-Speicherung

Candles werden in Redis unter folgendem Key-Schema gespeichert:

```
market:candles:{asset_id}:{timeframe}
```

Beispiel: `market:candles:CL:1m`

---

## Troubleshooting

### Problem: Keine Candle-Daten

**Symptom:** Chart zeigt "Keine Kerzen-Daten verfügbar"

**Lösungen:**
1. Prüfe, ob ein Broker konfiguriert und aktiv ist
2. Prüfe die Broker-Verbindung im Admin-Panel
3. Prüfe, ob das Asset den richtigen Broker zugeordnet hat

### Problem: Status "OFFLINE"

**Symptom:** Status-Badge zeigt "OFFLINE"

**Lösungen:**
1. Prüfe die Broker-API-Credentials
2. Prüfe die Netzwerkverbindung zum Broker
3. Prüfe die Logs: `tail -f logs/trading.log`

### Problem: Nur wenige Candles angezeigt

**Symptom:** Es werden weniger Candles angezeigt als erwartet

**Lösungen:**
1. Prüfe, ob Redis läuft: `redis-cli ping`
2. Erhöhe das Zeitfenster (z.B. 12h oder 24h)
3. Warte, bis genügend Daten gesammelt wurden

### Problem: Redis nicht verfügbar

**Symptom:** Log zeigt "Failed to connect to Redis"

**Lösungen:**
1. Starte Redis: `sudo systemctl start redis-server`
2. Prüfe Redis-Port: `netstat -tlnp | grep 6379`
3. Das System fällt auf In-Memory-Fallback zurück (keine Persistenz)

---

## Entwicklung

### Tests ausführen

```bash
# Alle Market Data Tests
python manage.py test trading.tests.MarketDataStatusAPITest \
                      trading.tests.BreakoutDistanceCandlesAPITest \
                      trading.tests.CandleModelTest \
                      trading.tests.RedisCandleStoreTest \
                      --verbosity=2

# Alle Chart Tests
python manage.py test trading.tests.BreakoutDistanceChartViewTest \
                      trading.tests.ChartCandlesAPITest \
                      --verbosity=2
```

### Manuell Candles hinzufügen (für Tests)

```python
from core.services.market_data import get_stream_manager, Candle
import time

manager = get_stream_manager()
candle = Candle(
    timestamp=int(time.time()),
    open=75.5,
    high=75.75,
    low=75.25,
    close=75.6,
    volume=1000,
)
manager.append_candle('CL', '1m', candle)
```

---

## Changelog

### Version 2.0 (2025-11-30)
- **Neu:** Market Data Layer mit Redis-Persistenz
- **Neu:** Broker-agnostische Datenabfrage (IG + MEXC)
- **Neu:** Konfigurierbare Zeitfenster (kein hartes 24h-Limit mehr)
- **Neu:** Status-Indikator (LIVE/POLL/CACHED/OFFLINE)
- **Neu:** Auto-Refresh alle 30 Sekunden
- **Fix:** Frontend verwendet jetzt neuen API-Endpunkt
- **Fix:** Korrektes Asset-ID Handling

### Version 1.0
- Initiale Implementierung mit 5-Minuten-Candles
- Festes 24h-Limit
- Nur IG-Broker Support
