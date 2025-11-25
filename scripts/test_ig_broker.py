#!/usr/bin/env python
"""
Test script for IG Broker Service.

This script tests the basic functionality of the IgBrokerService:
1. connect
2. get_account_state
3. get_symbol_price
4. get_open_positions
5. disconnect

Usage:
    python scripts/test_ig_broker.py

Environment variables (or configure via Django admin):
    IG_API_KEY - IG API key
    IG_USERNAME - IG account username
    IG_PASSWORD - IG account password
    IG_ACCOUNT_TYPE - DEMO or LIVE (default: DEMO)
    IG_ACCOUNT_ID - Specific account ID (optional)
    OIL_EPIC - EPIC code for oil market (optional)
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
    IgBrokerService,
    create_ig_broker_service,
    get_active_ig_broker_config,
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
        service = create_ig_broker_service()
        print("Using IG Broker configuration from database")
        return service
    except Exception:
        pass
    
    # Fall back to environment variables
    api_key = os.environ.get('IG_API_KEY')
    username = os.environ.get('IG_USERNAME')
    password = os.environ.get('IG_PASSWORD')
    account_type = os.environ.get('IG_ACCOUNT_TYPE', 'DEMO')
    account_id = os.environ.get('IG_ACCOUNT_ID')
    
    if not all([api_key, username, password]):
        print("Error: Missing required environment variables.")
        print("Required: IG_API_KEY, IG_USERNAME, IG_PASSWORD")
        print("Or configure IG Broker in Django admin.")
        sys.exit(1)
    
    print("Using IG Broker configuration from environment variables")
    return IgBrokerService(
        api_key=api_key,
        username=username,
        password=password,
        account_type=account_type,
        account_id=account_id,
    )


def get_oil_epic():
    """Get the EPIC code for oil market."""
    try:
        config = get_active_ig_broker_config()
        if config.default_oil_epic:
            return config.default_oil_epic
    except Exception:
        pass
    
    # Fall back to environment variable or default
    return os.environ.get('OIL_EPIC', 'CC.D.CL.UNC.IP')  # Default: WTI Crude Oil


def test_ig_broker():
    """Run the IG Broker Service tests."""
    print("=" * 60)
    print("IG Broker Service Test")
    print("=" * 60)
    
    broker = get_broker_service()
    oil_epic = get_oil_epic()
    
    try:
        # Step 1: Connect
        print("\n1. Connecting to IG...")
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
        print(f"   ✓ Unrealized P&L: {account.unrealized_pnl} {account.currency}")
        
        # Step 3: Get Symbol Price
        print(f"\n3. Getting price for {oil_epic}...")
        try:
            price = broker.get_symbol_price(oil_epic)
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
            print(f"   ⚠ Could not get price for {oil_epic}: {e}")
            print("   (This may be expected if the market is closed or EPIC is invalid)")
        
        # Step 4: Get Open Positions
        print("\n4. Getting open positions...")
        positions = broker.get_open_positions()
        print(f"   ✓ Found {len(positions)} open position(s)")
        for pos in positions:
            print(f"   - {pos.market_name}: {pos.direction.value} {pos.size} @ {pos.open_price}")
            print(f"     Current: {pos.current_price}, P&L: {pos.unrealized_pnl}")
        
        # Step 5: Disconnect
        print("\n5. Disconnecting...")
        broker.disconnect()
        print("   ✓ Successfully disconnected")
        
        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        return True
        
    except AuthenticationError as e:
        print(f"\n✗ Authentication failed: {e}")
        print("  Check your API key, username, and password.")
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
    success = test_ig_broker()
    sys.exit(0 if success else 1)
