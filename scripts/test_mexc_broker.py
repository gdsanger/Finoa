#!/usr/bin/env python
"""
Test script for MEXC Broker Service.

This script tests the basic functionality of the MexcBrokerService:
1. connect
2. get_account_state
3. get_symbol_price
4. get_open_positions
5. disconnect

Usage:
    python scripts/test_mexc_broker.py

Environment variables (or configure via Django admin):
    MEXC_API_KEY - MEXC API key
    MEXC_API_SECRET - MEXC API secret
    MEXC_ACCOUNT_TYPE - SPOT or MARGIN (default: SPOT)
"""
import os
import sys
import django

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finoa.settings')
django.setup()

from core.services.broker import (
    MexcBrokerService,
    create_mexc_broker_service,
    get_active_mexc_broker_config,
    BrokerError,
    AuthenticationError,
)


def get_broker_service():
    """
    Create a broker service from config or environment variables.
    
    Tries to use Django configuration first, falls back to environment variables.
    """
    try:
        # Try to use database configuration
        service = create_mexc_broker_service()
        print("Using MEXC Broker configuration from database")
        return service
    except Exception:
        pass
    
    # Fall back to environment variables
    api_key = os.environ.get('MEXC_API_KEY')
    api_secret = os.environ.get('MEXC_API_SECRET')
    account_type = os.environ.get('MEXC_ACCOUNT_TYPE', 'SPOT')
    
    if not all([api_key, api_secret]):
        print("Error: Missing required environment variables.")
        print("Required: MEXC_API_KEY, MEXC_API_SECRET")
        print("Or configure MEXC Broker in Django admin.")
        sys.exit(1)
    
    print("Using MEXC Broker configuration from environment variables")
    return MexcBrokerService(
        api_key=api_key,
        api_secret=api_secret,
        account_type=account_type,
    )


def get_test_symbol():
    """Get a test symbol for price queries."""
    return os.environ.get('MEXC_TEST_SYMBOL', 'BTCUSDT')


def test_mexc_broker():
    """Run the MEXC Broker Service tests."""
    print("=" * 60)
    print("MEXC Broker Service Test")
    print("=" * 60)
    
    broker = get_broker_service()
    test_symbol = get_test_symbol()
    
    try:
        # Step 1: Connect
        print("\n1. Connecting to MEXC...")
        broker.connect()
        print("   ✓ Successfully connected")
        
        # Step 2: Get Account State
        print("\n2. Getting account state...")
        account = broker.get_account_state()
        print(f"   ✓ Account Type: {account.account_id}")
        print(f"   ✓ Account Name: {account.account_name}")
        print(f"   ✓ Balance: {account.balance} {account.currency}")
        print(f"   ✓ Available: {account.available} {account.currency}")
        print(f"   ✓ Equity: {account.equity} {account.currency}")
        
        # Step 3: Get Symbol Price
        print(f"\n3. Getting price for {test_symbol}...")
        try:
            price = broker.get_symbol_price(test_symbol)
            print(f"   ✓ Market: {price.market_name}")
            print(f"   ✓ Bid: {price.bid}")
            print(f"   ✓ Ask: {price.ask}")
            print(f"   ✓ Spread: {price.spread}")
            if price.high:
                print(f"   ✓ High: {price.high}")
            if price.low:
                print(f"   ✓ Low: {price.low}")
            if price.change_percent:
                print(f"   ✓ Change: {price.change_percent}%")
        except BrokerError as e:
            print(f"   ⚠ Could not get price for {test_symbol}: {e}")
            print("   (This may be expected if the symbol is invalid)")
        
        # Step 4: Get Historical Prices
        print(f"\n4. Getting historical prices for {test_symbol}...")
        try:
            candles = broker.get_historical_prices(test_symbol, interval="5m", limit=10)
            print(f"   ✓ Retrieved {len(candles)} candles")
            if candles:
                latest = candles[-1]
                print(f"   ✓ Latest candle - O:{latest['open']} H:{latest['high']} L:{latest['low']} C:{latest['close']}")
        except BrokerError as e:
            print(f"   ⚠ Could not get historical prices: {e}")
        
        # Step 5: Get Open Positions
        print("\n5. Getting open positions (non-zero balances)...")
        positions = broker.get_open_positions()
        print(f"   ✓ Found {len(positions)} position(s)")
        for pos in positions:
            print(f"   - {pos.market_name}: {pos.direction.value} {pos.size}")
            if pos.current_price:
                print(f"     Current Price: {pos.current_price}")
        
        # Step 6: Disconnect
        print("\n6. Disconnecting...")
        broker.disconnect()
        print("   ✓ Successfully disconnected")
        
        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        return True
        
    except AuthenticationError as e:
        print(f"\n✗ Authentication failed: {e}")
        print("  Check your API key and secret.")
        return False
        
    except ConnectionError as e:
        print(f"\n✗ Connection failed: {e}")
        return False
        
    except BrokerError as e:
        print(f"\n✗ Broker error: {e}")
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
    success = test_mexc_broker()
    sys.exit(0 if success else 1)
