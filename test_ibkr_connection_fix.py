#!/usr/bin/env python3
"""Test IBKR connection fix - verify the hybrid sync/async approach works"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.brokers.ibkr.adapters import IBBroker
from src.data_collectors.ibkr.client import IBKRDataClient

def test_sync_connection():
    """Test sync connection method"""
    print("🔌 Testing sync IBKR connection...")
    
    broker = IBBroker()
    broker.client.host = "127.0.0.1"
    broker.client.port = 7497
    broker.client.client_id = 102
    
    try:
        broker.connect(timeout=30.0)
        print("✅ Sync connection successful!")
        
        # Test a simple operation
        account_summary = broker.account_summary()
        print(f"📊 Account summary items: {len(account_summary)}")
        
        broker.disconnect()
        print("✅ Sync disconnect successful!")
        return True
        
    except Exception as exc:
        print(f"❌ Sync connection failed: {exc}")
        return False

async def test_async_connection():
    """Test async connection method"""
    print("\n🔌 Testing async IBKR connection...")
    
    broker = IBBroker()
    broker.client.host = "127.0.0.1"
    broker.client.port = 7497
    broker.client.client_id = 102
    
    try:
        await asyncio.wait_for(broker.connect_async(timeout=30.0), timeout=35.0)
        print("✅ Async connection successful!")
        
        # Test a simple operation
        account_summary = broker.account_summary()
        print(f"📊 Account summary items: {len(account_summary)}")
        
        broker.disconnect()
        print("✅ Async disconnect successful!")
        return True
        
    except asyncio.TimeoutError:
        print("❌ Async connection timeout")
        return False
    except Exception as exc:
        print(f"❌ Async connection failed: {exc}")
        return False

def test_hybrid_approach():
    """Test the hybrid approach used in the fixed data collection"""
    print("\n🔌 Testing hybrid sync/async approach...")
    
    # Step 1: Establish connection synchronously (like in setup_connection)
    print("Step 1: Establishing sync connection...")
    client = IBKRDataClient()
    client.broker.client.host = "127.0.0.1"
    client.broker.client.port = 7497
    client.broker.client.client_id = 102
    
    try:
        client.broker.connect(timeout=30.0)
        client._connected = True
        print("✅ Sync connection established successfully!")
        
        # Step 2: Test that the connection persists
        print("Step 2: Testing connection persistence...")
        account_summary = client.broker.account_summary()
        print(f"📊 Account summary items: {len(account_summary)}")
        
        # Step 3: Clean up
        print("Step 3: Cleaning up...")
        client.broker.disconnect()
        client._connected = False
        print("✅ Hybrid approach successful!")
        return True
        
    except Exception as exc:
        print(f"❌ Hybrid approach failed: {exc}")
        return False

async def main():
    """Run all connection tests"""
    print("🧪 IBKR Connection Fix Test Suite")
    print("=" * 50)
    
    # Test 1: Sync connection
    sync_success = test_sync_connection()
    
    # Test 2: Async connection
    async_success = test_async_connection()
    
    # Test 3: Hybrid approach
    hybrid_success = test_hybrid_approach()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    print(f"Sync Connection:     {'✅ PASS' if sync_success else '❌ FAIL'}")
    print(f"Async Connection:    {'✅ PASS' if async_success else '❌ FAIL'}")
    print(f"Hybrid Approach:     {'✅ PASS' if hybrid_success else '❌ FAIL'}")
    
    if sync_success and hybrid_success:
        print("\n🎉 Connection fix is working! The hybrid approach should resolve the data collection issues.")
    else:
        print("\n⚠️  Connection issues persist. Further investigation needed.")
    
    return sync_success and hybrid_success

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
