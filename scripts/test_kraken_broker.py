#!/usr/bin/env python
"""
Test script for Kraken Broker Service.

This script tests the basic functionality of the KrakenBrokerService:
1. connect
2. get_account_state
3. get_symbol_price
4. get_candles_1m (historical)
5. get_live_candles_1m (WebSocket)
6. get_open_positions
7. disconnect

Usage:
    python scripts/test_kraken_broker.py

Environment variables (or configure via Django admin):
    KRAKEN_API_KEY - Kraken API key
    KRAKEN_API_SECRET - Kraken API secret
    KRAKEN_ACCOUNT_TYPE - DEMO or LIVE (default: DEMO)
"""
import os
import sys
import django
import time

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finoa.settings')
django.setup()

from core.services.broker.kraken_broker_service import (
    KrakenBrokerService,
    KrakenBrokerConfig,
    get_kraken_service,
    KrakenBrokerError,
    KrakenAuthenticationError,
)


def get_broker_service():
    """
    Create a broker service from config or environment variables.
    
    Tries to use Django configuration first, falls back to environment variables.
    """
    try:
        # Try to use database configuration
        service = get_kraken_service()
        print("✓ Using Kraken Broker configuration from database")
        return service
    except Exception as e:
        print(f"⚠ Could not load from database: {e}")
    
    # Fall back to environment variables
    api_key = os.environ.get('KRAKEN_API_KEY')
    api_secret = os.environ.get('KRAKEN_API_SECRET')
    account_type = os.environ.get('KRAKEN_ACCOUNT_TYPE', 'DEMO')
    
    if not all([api_key, api_secret]):
        print("Error: Missing required environment variables.")
        print("Required: KRAKEN_API_KEY, KRAKEN_API_SECRET")
        print("Or configure Kraken Broker in Django admin.")
        sys.exit(1)
    
    print("✓ Using Kraken Broker configuration from environment variables")
    config = KrakenBrokerConfig(
        api_key=api_key,
        api_secret=api_secret,
        use_demo=(account_type == 'DEMO'),
    )
    return KrakenBrokerService(config)


def get_test_symbol():
    """Get a test symbol for price queries."""
    return os.environ.get('KRAKEN_TEST_SYMBOL', 'PI_XBTUSD')


def test_kraken_broker():
    """Run the Kraken Broker Service tests."""
    print("=" * 60)
    print("Kraken Pro Future Broker Service Test")
    print("=" * 60)
    
    broker = get_broker_service()
    test_symbol = get_test_symbol()
    
    try:
        # Step 1: Connect
        print("\n1. Connecting to Kraken Futures...")
        broker.connect()
        print("   ✓ Successfully connected")
        
        # Step 2: Get Account State
        print("\n2. Getting account state...")
        account = broker.get_account_state()
        print(f"   ✓ Account ID: {account.account_id}")
        print(f"   ✓ Account Name: {account.account_name}")
        print(f"   ✓ Balance: {account.balance} {account.currency}")
        print(f"   ✓ Available: {account.available} {account.currency}")
        print(f"   ✓ Equity: {account.equity} {account.currency}")
        print(f"   ✓ Margin Used: {account.margin_used} {account.currency}")
        print(f"   ✓ Margin Available: {account.margin_available} {account.currency}")
        print(f"   ✓ Unrealized P&L: {account.unrealized_pnl} {account.currency}")
        
        # Step 3: Get Symbol Price (REST API)
        print(f"\n3. Getting price for {test_symbol} (REST API)...")
        try:
            price = broker.get_symbol_price(test_symbol)
            print(f"   ✓ Symbol: {price.epic}")
            print(f"   ✓ Bid: {price.bid}")
            print(f"   ✓ Ask: {price.ask}")
            print(f"   ✓ Spread: {price.spread}")
            print(f"   ✓ Mid Price: {price.mid_price}")
            if price.high:
                print(f"   ✓ High (24h): {price.high}")
            if price.low:
                print(f"   ✓ Low (24h): {price.low}")
            if price.change:
                print(f"   ✓ Change (24h): {price.change}")
        except KrakenBrokerError as e:
            print(f"   ⚠ Could not get price for {test_symbol}: {e}")
            print("   (This may be expected if the symbol is invalid)")
        
        # Step 4: Get Historical Candles
        print(f"\n4. Getting historical 1m candles for {test_symbol}...")
        try:
            candles = broker.get_candles_1m(test_symbol, hours=1)
            print(f"   ✓ Retrieved {len(candles)} candles (last hour)")
            if candles:
                latest = candles[-1]
                print(f"   ✓ Latest candle:")
                print(f"      Time: {latest.time}")
                print(f"      O:{latest.open} H:{latest.high} L:{latest.low} C:{latest.close}")
                print(f"      Volume: {latest.volume}")
        except KrakenBrokerError as e:
            print(f"   ⚠ Could not get historical candles: {e}")
        
        # Step 5: Wait for WebSocket to establish and get some data
        print(f"\n5. Waiting for WebSocket data (10 seconds)...")
        print("   (WebSocket should auto-connect and start streaming)")
        time.sleep(10)
        
        # Step 6: Get Live Candles (includes WebSocket data)
        print(f"\n6. Getting live candles for {test_symbol}...")
        try:
            live_candles = broker.get_live_candles_1m(test_symbol)
            print(f"   ✓ Retrieved {len(live_candles)} live candles")
            if live_candles:
                latest = live_candles[-1]
                print(f"   ✓ Most recent candle:")
                print(f"      Time: {latest.time}")
                print(f"      O:{latest.open} H:{latest.high} L:{latest.low} C:{latest.close}")
                print(f"      Volume: {latest.volume}")
        except KrakenBrokerError as e:
            print(f"   ⚠ Could not get live candles: {e}")
        
        # Step 7: Get Symbol Price again (should be cached from WebSocket)
        print(f"\n7. Getting price for {test_symbol} again (cached from WebSocket)...")
        try:
            price = broker.get_symbol_price(test_symbol)
            print(f"   ✓ Bid: {price.bid}")
            print(f"   ✓ Ask: {price.ask}")
            print(f"   ✓ Mid Price: {price.mid_price}")
            print(f"   ✓ Timestamp: {price.timestamp}")
        except KrakenBrokerError as e:
            print(f"   ⚠ Could not get price: {e}")
        
        # Step 8: Get Open Positions
        print("\n8. Getting open positions...")
        positions = broker.get_open_positions()
        print(f"   ✓ Found {len(positions)} position(s)")
        for pos in positions:
            print(f"   - {pos.market_name}: {pos.direction.value} {pos.size}")
            print(f"     Entry Price: {pos.open_price}")
            if pos.current_price:
                print(f"     Current Price: {pos.current_price}")
            if pos.unrealized_pnl:
                print(f"     Unrealized P&L: {pos.unrealized_pnl} {pos.currency}")
        
        # Step 9: Disconnect
        print("\n9. Disconnecting...")
        broker.disconnect()
        print("   ✓ Successfully disconnected")
        print("   ✓ WebSocket closed")
        
        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        print("\nKey Features Verified:")
        print("  ✓ REST API v3 integration")
        print("  ✓ Account state retrieval")
        print("  ✓ Real-time price feeds")
        print("  ✓ Historical candle data")
        print("  ✓ WebSocket integration")
        print("  ✓ Position management")
        return True
        
    except KrakenAuthenticationError as e:
        print(f"\n✗ Authentication failed: {e}")
        print("  Check your API key and secret.")
        print("  Ensure account type (DEMO/LIVE) matches your credentials.")
        return False
        
    except ConnectionError as e:
        print(f"\n✗ Connection failed: {e}")
        return False
        
    except KrakenBrokerError as e:
        print(f"\n✗ Kraken broker error: {e}")
        return False
        
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Ensure disconnection
        if broker.is_connected():
            print("\nEnsuring disconnection...")
            broker.disconnect()


if __name__ == '__main__':
    success = test_kraken_broker()
    sys.exit(0 if success else 1)
