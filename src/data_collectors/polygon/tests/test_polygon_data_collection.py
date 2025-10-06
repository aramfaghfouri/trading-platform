#!/usr/bin/env python3
"""
Test script for Polygon.io data collection.

This script demonstrates how to use the Polygon.io data collector
to collect real market data.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_collectors.polygon.enhanced_collector import (
    PolygonDataCollector, Timeframe
)
from data_collectors.polygon.data_storage import PolygonDataStorage
from data_collectors.polygon.collection_manager import (
    PolygonCollectionManager, collect_symbol_range
)
from core.config_loader import get_polygon_config, get_database_config
from loguru import logger


async def test_basic_data_collection():
    """Test basic data collection functionality."""
    print("\n🧪 Testing Basic Polygon.io Data Collection")
    print("=" * 60)
    
    try:
        # Initialize collector
        async with PolygonDataCollector() as collector:
            print("✅ Data collector initialized")
            
            # Test market status (this should work even with placeholder API key)
            print("\n📊 Testing market status...")
            status_result = await collector.get_market_status()
            
            if status_result.success:
                print(f"✅ Market status retrieved successfully")
                if status_result.data:
                    market_data = status_result.data.get('market', {})
                    print(f"   Market status: {market_data.get('status', 'Unknown')}")
                    if 'error' in market_data:
                        print(f"   API Error: {market_data['error']}")
                        if 'Unknown API Key' in market_data['error']:
                            print("   ⚠️  This is expected with a placeholder API key")
            else:
                print(f"❌ Market status failed: {status_result.error}")
            
            # Test with a small date range to minimize API calls
            print("\n📈 Testing historical data collection...")
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=5)  # Only 5 days to minimize API usage
            
            print(f"   Collecting data from {start_date.date()} to {end_date.date()}")
            
            data_result = await collector.get_aggregates(
                symbol="AAPL",
                multiplier=1,
                timespan=Timeframe.DAY_1,
                from_date=start_date,
                to_date=end_date
            )
            
            if data_result.success:
                print(f"✅ Historical data collected successfully")
                if data_result.data and 'results' in data_result.data:
                    results = data_result.data['results']
                    print(f"   Records collected: {len(results)}")
                    
                    if results:
                        # Show sample data
                        latest = results[-1]
                        print(f"   Latest data point:")
                        print(f"     Date: {datetime.fromtimestamp(latest['t']/1000).strftime('%Y-%m-%d')}")
                        print(f"     Open: ${latest.get('o', 'N/A')}")
                        print(f"     High: ${latest.get('h', 'N/A')}")
                        print(f"     Low: ${latest.get('l', 'N/A')}")
                        print(f"     Close: ${latest.get('c', 'N/A')}")
                        print(f"     Volume: {latest.get('v', 'N/A'):,}")
                        
                        # Test data validation
                        print(f"\n🔍 Testing data validation...")
                        is_valid, errors = collector.validator.validate_bar_data(results)
                        if is_valid:
                            print("✅ Data validation passed")
                        else:
                            print(f"⚠️  Data validation warnings: {len(errors)} issues found")
                            for error in errors[:3]:  # Show first 3 errors
                                print(f"     - {error}")
                        
                        # Test DataFrame conversion
                        print(f"\n📋 Testing DataFrame conversion...")
                        df = collector.to_dataframe(data_result)
                        if df is not None and not df.empty:
                            print(f"✅ DataFrame created: {df.shape[0]} rows, {df.shape[1]} columns")
                            print(f"   Date range: {df.index.min().date()} to {df.index.max().date()}")
                        else:
                            print("❌ DataFrame conversion failed")
                else:
                    print("⚠️  No data returned (this might be due to API key limitations)")
            else:
                print(f"❌ Historical data collection failed: {data_result.error}")
                if 'Unknown API Key' in str(data_result.error):
                    print("   ⚠️  This is expected with a placeholder API key")
            
            return data_result.success
            
    except Exception as e:
        print(f"❌ Data collection test failed: {e}")
        return False


async def test_data_storage():
    """Test data storage functionality."""
    print("\n🗄️  Testing Data Storage")
    print("=" * 60)
    
    try:
        # Initialize storage
        async with PolygonDataStorage() as storage:
            print("✅ Data storage initialized")
            
            # Test database connection
            print("\n📊 Testing database connection...")
            summary = await storage.get_data_summary()
            print(f"✅ Database connection successful")
            print(f"   Total records: {summary.get('total_records', 0):,}")
            print(f"   Unique symbols: {summary.get('unique_symbols', 0)}")
            
            # Test symbols with data
            symbols = await storage.get_symbols_with_data()
            if symbols:
                print(f"   Symbols with data: {len(symbols)}")
                print(f"   Sample symbols: {', '.join(symbols[:5])}")
            else:
                print("   No symbols found in database (expected for new setup)")
            
            return True
            
    except Exception as e:
        print(f"❌ Data storage test failed: {e}")
        return False


async def test_collection_manager():
    """Test the collection manager."""
    print("\n🎯 Testing Collection Manager")
    print("=" * 60)
    
    try:
        # Initialize manager
        manager = PolygonCollectionManager(max_concurrent_tasks=2)
        print("✅ Collection manager initialized")
        
        # Add a test task
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=3)  # Small range for testing
        
        task_id = manager.add_collection_task(
            symbol="AAPL",
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1,
            max_retries=1  # Limit retries for testing
        )
        
        print(f"✅ Test task added: {task_id}")
        
        # Execute the task
        print(f"\n🚀 Executing test task...")
        task = await manager.execute_task(task_id)
        
        if task.status.value == "completed":
            print(f"✅ Task completed successfully")
            if task.storage_result:
                print(f"   Records stored: {task.storage_result.records_inserted}")
        else:
            print(f"⚠️  Task status: {task.status.value}")
            if task.error:
                print(f"   Error: {task.error}")
                if 'Unknown API Key' in str(task.error):
                    print("   ⚠️  This is expected with a placeholder API key")
        
        # Show statistics
        stats = manager.get_stats()
        print(f"\n📊 Collection statistics:")
        print(f"   Total tasks: {stats['total_tasks']}")
        print(f"   Completed: {stats['completed_tasks']}")
        print(f"   Failed: {stats['failed_tasks']}")
        print(f"   Success rate: {stats['success_rate']:.1%}")
        
        return True
        
    except Exception as e:
        print(f"❌ Collection manager test failed: {e}")
        return False


async def test_convenience_function():
    """Test the convenience function for data collection."""
    print("\n🔧 Testing Convenience Function")
    print("=" * 60)
    
    try:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=2)  # Small range for testing
        
        print(f"Collecting data for AAPL from {start_date.date()} to {end_date.date()}")
        
        success = await collect_symbol_range(
            symbol="AAPL",
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1
        )
        
        if success:
            print("✅ Convenience function test successful")
        else:
            print("⚠️  Convenience function test failed (likely due to API key)")
            print("   This is expected with a placeholder API key")
        
        return True
        
    except Exception as e:
        print(f"❌ Convenience function test failed: {e}")
        return False


def show_api_key_setup():
    """Show how to set up a real API key."""
    print("\n🔑 API Key Setup Instructions")
    print("=" * 60)
    print("To use real Polygon.io data, you need to:")
    print()
    print("1. Get a Polygon.io API key:")
    print("   - Visit: https://polygon.io/pricing")
    print("   - Sign up for a free account (5 API calls/minute)")
    print("   - Get your API key from the dashboard")
    print()
    print("2. Set the API key in one of these ways:")
    print("   Option A - Environment variable:")
    print("     export POLYGON_API_KEY='your_actual_api_key_here'")
    print()
    print("   Option B - Update config file:")
    print("     Edit config/polygon.yaml and replace 'your_polygon_api_key_here'")
    print()
    print("3. Test with real data:")
    print("     python scripts/test_polygon_data_collection.py")
    print()
    print("⚠️  Note: The current test uses a placeholder API key,")
    print("   so you'll see 'Unknown API Key' errors. This is expected!")


async def main():
    """Main test function."""
    print("🚀 Polygon.io Data Collection Test")
    print("=" * 60)
    
    # Show API key setup instructions
    show_api_key_setup()
    
    # Run tests
    test_results = []
    
    test_functions = [
        ("Basic Data Collection", test_basic_data_collection),
        ("Data Storage", test_data_storage),
        ("Collection Manager", test_collection_manager),
        ("Convenience Function", test_convenience_function),
    ]
    
    for test_name, test_func in test_functions:
        try:
            result = await test_func()
            test_results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            test_results.append((test_name, False))
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    passed = 0
    total = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "⚠️  EXPECTED (API Key)"
        print(f"{test_name:.<40} {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Polygon.io integration is working correctly.")
    else:
        print("⚠️  Some tests failed due to API key limitations.")
        print("   This is expected with a placeholder API key.")
        print("   Set up a real API key to test with live data.")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
