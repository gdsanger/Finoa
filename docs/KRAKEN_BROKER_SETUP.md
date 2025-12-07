# Kraken Pro Future Broker Setup Guide

## Overview

This guide explains how to set up and configure the Kraken Pro Future broker integration for trading with Finoa.

Kraken Pro Future provides a robust futures trading platform with:
- **REST API v3** for account management and order execution
- **Charts API v1** for historical 1-minute OHLC candle data
- **WebSocket v1** for real-time price feeds and trade data

## Prerequisites

1. A Kraken Futures account (Live or Demo)
2. API credentials from Kraken:
   - API Key
   - API Secret

## Getting API Credentials

### For Demo Account:
1. Visit [https://demo-futures.kraken.com](https://demo-futures.kraken.com)
2. Create a demo account
3. Navigate to Settings → API Keys
4. Create a new API key with appropriate permissions:
   - Account Information (Read)
   - Trading (Read & Write)
5. Save the API Key and API Secret securely

### For Live Account:
1. Visit [https://futures.kraken.com](https://futures.kraken.com)
2. Log in to your account
3. Navigate to Settings → API Keys
4. Create a new API key with appropriate permissions:
   - Account Information (Read)
   - Trading (Read & Write)
5. Save the API Key and API Secret securely

⚠️ **Security Note**: Never share your API credentials or commit them to version control!

## Configuration in Finoa

### 1. Access Django Admin

Navigate to the Django admin interface at `/admin/` and log in with your admin credentials.

### 2. Add Kraken Broker Configuration

1. Go to **Core → Kraken Broker Configurations**
2. Click **Add Kraken Broker Configuration**
3. Fill in the required fields:

#### Basic Information
- **Name**: A descriptive name for this configuration (e.g., "Kraken Demo", "Kraken Live BTC")
- **Is Active**: Check this box to make this the active Kraken configuration
- **Account Type**: Select either:
  - `Demo` - For testing with demo funds
  - `Live` - For real trading (use with caution!)

#### Authentication
- **API Key**: Your Kraken API Key
- **API Secret**: Your Kraken API Secret

#### Connection Settings (Optional)
Leave these empty for auto-detection, or override with custom URLs:
- **REST Base URL**: Default is auto-detected based on account type
  - Demo: `https://demo-futures.kraken.com/derivatives`
  - Live: `https://futures.kraken.com/derivatives`
- **Charts Base URL**: For historical candle data (auto-detected)
  - Demo: `https://demo-futures.kraken.com/api/charts/v1`
  - Live: `https://futures.kraken.com/api/charts/v1`
- **WebSocket URL**: For real-time data
  - Demo: `wss://demo-futures.kraken.com/ws/v1`
  - Live: `wss://futures.kraken.com/ws/v1`
- **Timeout Seconds**: Default is 30 seconds

#### Trading Defaults
- **Default Symbol**: The default trading symbol (default: `PI_XBTUSD` for Bitcoin)
  - Common symbols:
    - `PI_XBTUSD` - Bitcoin Perpetual
    - `PI_ETHUSD` - Ethereum Perpetual
    - `FI_XBTUSD_YYMMDD` - Bitcoin Fixed Maturity (replace with actual date)

4. Click **Save**

### 3. Configure Trading Asset

1. Go to **Trading → Trading Assets**
2. Create a new trading asset or edit an existing one
3. Set the following fields:
   - **Broker**: Select `Kraken`
   - **Broker Symbol**: The Kraken-specific symbol (e.g., `PI_XBTUSD`)
   - **Epic**: The symbol identifier used in your system
   - **Quote Currency**: Set to `USD` or `USDT`
4. Click **Save**

## Features

### Account State
The Kraken integration provides real-time account information:
- Balance and equity
- Available margin
- Margin used
- Unrealized P&L
- Multi-collateral support (USDT, USDC, etc.)

### Order Types Supported
- **Market Orders**: Immediate execution at best available price
- **Limit Orders**: Execute at specified price or better
- **Stop Orders**: Trigger when price reaches specified level

### Real-Time Data via WebSocket

The Kraken integration automatically connects to WebSocket feeds for:

1. **Live Price Updates** (`ticker_lite` feed):
   - Real-time bid/ask prices
   - Mark price updates
   - Automatic cache management

2. **Trade Data for Charting**:
   - Historical 1-minute candles fetched from Charts API v1
   - Real-time trade data via WebSocket (`trade` feed)
   - Candles cached for the last 6 hours

### Position Management
- View open positions
- Get real-time position P&L
- Close positions with market orders
- Reduce-only orders for safe position closing

## Example Usage

Once configured, the Kraken broker will be used automatically by the trading system:

```python
from core.services.broker.kraken_broker_service import get_kraken_service

# Get the active Kraken service instance
service = get_kraken_service()

# Get account state
account = service.get_account_state()
print(f"Balance: {account.balance} {account.currency}")
print(f"Available Margin: {account.margin_available}")

# Get current price
price = service.get_symbol_price("PI_XBTUSD")
print(f"BTC/USD: Bid={price.bid}, Ask={price.ask}")

# Get 1-minute candles (last 6 hours)
candles = service.get_candles_1m("PI_XBTUSD", hours=6)
print(f"Retrieved {len(candles)} candles")

# Fetch candles from Charts API
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
from_time = now - timedelta(hours=6)
candles = service.fetch_candles_from_charts_api(
    symbol="PI_XBTUSD",
    resolution="1m",
    from_timestamp=int(from_time.timestamp() * 1000),
    to_timestamp=int(now.timestamp() * 1000),
)
print(f"Fetched {len(candles)} candles from Charts API")

# Get live candles (includes current forming candle)
live_candles = service.get_live_candles_1m("PI_XBTUSD")
```

## WebSocket Integration

The WebSocket connection is automatically managed:

- **Automatic Connection**: Established when the service starts
- **Reconnection**: Automatic reconnection on connection loss
- **Multiple Symbols**: Subscribe to multiple symbols simultaneously
- **Caching**: Price and candle data cached for quick access

### Configuring Symbols for WebSocket

By default, the service subscribes to the `default_symbol`. To subscribe to multiple symbols:

1. The service will automatically subscribe to symbols when you request data for them
2. All active trading assets with broker set to `KRAKEN` will be monitored

## Troubleshooting

### Connection Issues

**Problem**: "KrakenBrokerService is not connected"
- **Solution**: Ensure the service is connected by calling `service.connect()`

**Problem**: "No active Kraken broker configured"
- **Solution**: Ensure you have created a KrakenBrokerConfig with `is_active=True`

**Problem**: "Kraken authentication failed"
- **Solution**: 
  - Verify your API Key and API Secret are correct
  - Ensure the account type (Demo/Live) matches your credentials
  - Check that your API key has the required permissions

### WebSocket Issues

**Problem**: WebSocket not receiving data
- **Solution**: 
  - Check internet connectivity
  - Verify WebSocket URL is correct for your account type
  - Check server logs for connection errors

**Problem**: "Module 'websocket' not found"
- **Solution**: Install websocket-client: `pip install websocket-client>=1.6.0`

### Trading Issues

**Problem**: Orders rejected with "Unauthorized"
- **Solution**: Ensure your API key has trading permissions enabled

**Problem**: "Insufficient margin"
- **Solution**: Check your account balance and available margin

## API Endpoints Used

### REST API v3
- `GET /api/v3/accounts` - Account information
- `GET /api/v3/tickers` - Price data
- `GET /api/v3/openpositions` - Open positions
- `POST /api/v3/sendorder` - Place orders

### Charts API v1 (Public, No Authentication Required)
- `GET /api/charts/v1/trade/{symbol}/{resolution}` - Historical OHLC candle data
  - Supported resolutions: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
  - Finoa uses `1m` resolution for breakout trading
  - Optional query parameters: `from` (timestamp in ms), `to` (timestamp in ms)

### WebSocket v1
- Subscribe to `ticker_lite` - Real-time prices
- Subscribe to `trade` - Trade execution data for real-time monitoring

## Security Best Practices

1. **Never commit API credentials** to version control
2. **Use Demo account** for testing and development
3. **Limit API key permissions** to only what's needed
4. **Regularly rotate** API keys
5. **Monitor API usage** for unusual activity
6. **Use IP whitelisting** if available on Kraken
7. **Start with small positions** when testing on Live account

## Running the Market Data Worker

The Kraken Market Data Worker is a continuous service that fetches 1-minute candle data from the Charts API v1 and builds session ranges for breakout trading.

### Starting the Worker

```bash
# Run with default settings (60 second polling interval)
python manage.py run_kraken_market_data_worker

# Run with custom polling interval (in seconds)
python manage.py run_kraken_market_data_worker --interval 60
```

### What the Worker Does

1. **Fetches Candle Data**: Polls the Charts API v1 every minute (configurable) for active assets
2. **Retrieves OHLC Data**: Gets complete 1-minute candles:
   - **Open**: First trade price in the minute
   - **High**: Maximum price in the minute
   - **Low**: Minimum price in the minute
   - **Close**: Last trade price in the minute
   - **Volume**: Cumulative volume traded
3. **Stores Data**: Persists candles to Redis for chart display and analysis
4. **Builds Ranges**: Calculates and updates session phase ranges for breakout trading
   - Updates existing range record per session (not creating duplicates)

### Data Retention

- **In-Memory**: Last 6 hours of candles for fast access
- **Redis**: Persistent storage with configurable TTL (default: 72 hours)
- **Only Active Assets**: Processes only assets marked as `is_active=True` with `broker=KRAKEN`

### Running as a Service

For production, run the worker as a system service:

**Using systemd (Linux)**:
```bash
# Create service file: /etc/systemd/system/kraken-market-data.service
[Unit]
Description=Kraken Market Data Worker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/finoa
ExecStart=/path/to/venv/bin/python manage.py run_kraken_market_data_worker
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# Enable and start the service
sudo systemctl enable kraken-market-data
sudo systemctl start kraken-market-data
sudo systemctl status kraken-market-data
```

**Using Docker**:
```dockerfile
# Add to your docker-compose.yml
services:
  kraken-worker:
    build: .
    command: python manage.py run_kraken_market_data_worker
    restart: unless-stopped
    depends_on:
      - redis
      - postgres
```

### Monitoring

Check worker logs for:
- WebSocket connection status
- Candle aggregation progress
- Range building updates
- Error messages

```bash
# View systemd logs
sudo journalctl -u kraken-market-data -f

# View Docker logs
docker-compose logs -f kraken-worker
```

## Additional Resources

- [Kraken Futures API Documentation](https://docs.futures.kraken.com/)
- [Kraken Support](https://support.kraken.com/)
- Finoa Trading Setup Guide: `docs/TRADING_SETUP_GUIDE.md`

## Important Notes

### Candle Data Availability
Kraken provides historical OHLC/candle data via the Charts API v1:

- **Public Endpoint**: No authentication required for Charts API
- **Historical Data**: Access to historical 1-minute candles
- **Worker Polling**: Market data worker fetches candles once per minute
- **Redis Storage**: Candles persisted to Redis for chart display
- **Session Ranges**: Worker updates (not duplicates) range records per session

### Best Practices
1. Keep the worker running continuously to maintain up-to-date candle data
2. Worker polls Charts API every 60 seconds (configurable) for new candles
3. Configure Redis properly for persistent candle storage
4. Use the worker as a system service for production deployments
5. Monitor worker logs to ensure Charts API connectivity

## Changelog

- **2025-12-07**: Charts API v1 integration for candle data
  - Added support for Kraken Charts API v1 to fetch historical OHLC data
  - Changed market data worker from WebSocket aggregation to Charts API polling
  - Implemented `fetch_candles_from_charts_api()` method for direct candle retrieval
  - Updated worker to poll Charts API once per minute (configurable)
  - Enhanced range persistence to update existing records instead of creating duplicates
  - Added charts_base_url configuration field with auto-detection
  - Public endpoint - no authentication required for Charts API
  - Added comprehensive tests for Charts API integration

- **2025-12-06**: Trade count tracking added to 1m candles
  - Added `trade_count` field to track number of trades per minute
  - Enhanced market data quality for analysis and debugging
  - Updated Candle1m and Candle models to support trade count
  - Added comprehensive tests for trade count tracking
  
- **2025-12-06**: Initial Kraken Pro Future integration
  - Added support for REST API v3
  - Implemented WebSocket integration for real-time data
  - Created KrakenBrokerConfig model
  - Added comprehensive admin interface
  - Created market data worker service
  - Redis persistence for candle history across restarts
