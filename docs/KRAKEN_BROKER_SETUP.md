# Kraken Pro Future Broker Setup Guide

## Overview

This guide explains how to set up and configure the Kraken Pro Future broker integration for trading with Finoa.

Kraken Pro Future provides a robust futures trading platform with:
- **REST API v3** for account management and order execution
- **Charts API** for historical candle data
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
- **Charts Base URL**: For historical data
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

2. **Trade Data for Charting** (`trade` feed):
   - Individual trade execution data
   - Automatic 1-minute candle aggregation
   - Historical candle data from Charts API

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

### Charts API
- `GET /trade/{symbol}/1m` - Historical 1-minute candles

### WebSocket v1
- Subscribe to `ticker_lite` - Real-time prices
- Subscribe to `trade` - Trade execution data

## Security Best Practices

1. **Never commit API credentials** to version control
2. **Use Demo account** for testing and development
3. **Limit API key permissions** to only what's needed
4. **Regularly rotate** API keys
5. **Monitor API usage** for unusual activity
6. **Use IP whitelisting** if available on Kraken
7. **Start with small positions** when testing on Live account

## Additional Resources

- [Kraken Futures API Documentation](https://docs.futures.kraken.com/)
- [Kraken Support](https://support.kraken.com/)
- Finoa Trading Setup Guide: `docs/TRADING_SETUP_GUIDE.md`

## Changelog

- **2024-12-06**: Initial Kraken Pro Future integration
  - Added support for REST API v3
  - Implemented WebSocket integration for real-time data
  - Created KrakenBrokerConfig model
  - Added comprehensive admin interface
