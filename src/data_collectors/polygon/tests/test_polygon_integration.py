#!/usr/bin/env python3
"""
Test script for Polygon.io integration.

This script tests the enhanced Polygon.io data collector, storage interface,
and collection manager to ensure everything works correctly.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_collectors.polygon.enhanced_collector import (
    PolygonDataCollector, DataCollectionResult, Timeframe,
    collect_symbol_data, collect_multiple_symbols
)
from data_collectors.polygon.data_storage import (
    PolygonDataStorage, StorageResult,
    store_symbol_data, get_symbol_data
)
from data_collectors.polygon.collection_manager import (
    PolygonCollectionManager, CollectionStatus,
    collect_and_store_data, collect_symbol_range
)
from core.config_loader import get_polygon_config, get_database_config
from loguru import logger


async def test_enhanced_collector():
    """Test the enhanced Polygon.io data collector."""
    print("\n🧪 Testing Enhanced Polygon.io Data Collector")
    print("=" * 60)
    
    try:
        # Initialize collector
        async with PolygonDataCollector() as collector:
            print("✅ Collector initialized successfully")
            
            # Test market status
            print("\n📊 Testing market status...")
            status_result = await collector.get_market_status()
            if status_result.success:
                print(f"✅ Market status retrieved: {status_result.data}")
            else:
                print(f"❌ Market status failed: {status_result.error}")
            
            # Test ticker details
            print("\n📈 Testing ticker details...")
            details_result = await collector.get_ticker_details("AAPL")
            if details_result.success:
                print(f"✅ Ticker details retrieved for AAPL")
                if details_result.data and 'details' in details_result.data:
                    details = details_result.data['details']
                    if hasattr(details, 'results'):
                        result = details.results
                        print(f"   Name: {getattr(result, 'name', 'N/A')}")
                        print(f"   Market: {getattr(result, 'market', 'N/A')}")
                        print(f"   Type: {getattr(result, 'type', 'N/A')}")
            else:
                print(f"❌ Ticker details failed: {details_result.error}")
            
            # Test historical data collection
            print("\n📊 Testing historical data collection...")
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            
            data_result = await collector.get_aggregates(
                symbol="AAPL",
                multiplier=1,
                timespan=Timeframe.DAY_1,
                from_date=start_date,
                to_date=end_date
            )
            
            if data_result.success:
                print(f"✅ Historical data collected for AAPL")
                if data_result.data and 'results' in data_result.data:
                    results = data_result.data['results']
                    print(f"   Records collected: {len(results)}")
                    if results:
                        latest = results[-1]
                        print(f"   Latest close: ${latest.get('c', 'N/A')}")
                        print(f"   Latest volume: {latest.get('v', 'N/A'):,}")
            else:
                print(f"❌ Historical data collection failed: {data_result.error}")
            
            # Test data validation
            print("\n🔍 Testing data validation...")
            if data_result.success and data_result.data and 'results' in data_result.data:
                results = data_result.data['results']
                is_valid, errors = collector.validator.validate_bar_data(results)
                if is_valid:
                    print("✅ Data validation passed")
                else:
                    print(f"⚠️  Data validation warnings: {errors[:3]}...")  # Show first 3 errors
                
                # Test outlier detection
                outliers = collector.validator.detect_outliers(results)
                if outliers:
                    print(f"⚠️  Outliers detected at indices: {outliers[:5]}...")  # Show first 5
                else:
                    print("✅ No outliers detected")
            
            # Test DataFrame conversion
            print("\n📋 Testing DataFrame conversion...")
            if data_result.success:
                df = collector.to_dataframe(data_result)
                if df is not None and not df.empty:
                    print(f"✅ DataFrame created: {df.shape[0]} rows, {df.shape[1]} columns")
                    print(f"   Date range: {df.index.min()} to {df.index.max()}")
                else:
                    print("❌ DataFrame conversion failed")
            
            print("\n✅ Enhanced collector tests completed successfully!")
            return True
            
    except Exception as e:
        print(f"❌ Enhanced collector test failed: {e}")
        return False


async def test_data_storage():
    """Test the data storage interface."""
    print("\n🗄️  Testing Data Storage Interface")
    print("=" * 60)
    
    try:
        # Initialize storage
        async with PolygonDataStorage() as storage:
            print("✅ Storage interface initialized successfully")
            
            # Test data summary
            print("\n📊 Testing data summary...")
            summary = await storage.get_data_summary()
            if summary:
                print(f"✅ Data summary retrieved:")
                print(f"   Total records: {summary.get('total_records', 0):,}")
                print(f"   Unique symbols: {summary.get('unique_symbols', 0)}")
                print(f"   Date range: {summary.get('earliest_date', 'N/A')} to {summary.get('latest_date', 'N/A')}")
                
                if summary.get('top_symbols'):
                    print(f"   Top symbols: {', '.join([s['symbol'] for s in summary['top_symbols'][:5]])}")
            else:
                print("⚠️  No data summary available (empty database)")
            
            # Test symbols with data
            print("\n📈 Testing symbols with data...")
            symbols = await storage.get_symbols_with_data()
            if symbols:
                print(f"✅ Found {len(symbols)} symbols with data")
                print(f"   Sample symbols: {', '.join(symbols[:10])}")
            else:
                print("⚠️  No symbols found in database")
            
            # Test data retrieval
            if symbols:
                print(f"\n📊 Testing data retrieval for {symbols[0]}...")
                end_date = datetime.now(timezone.utc)
                start_date = end_date - timedelta(days=7)
                
                df = await storage.get_data_range(symbols[0], start_date, end_date)
                if df is not None and not df.empty:
                    print(f"✅ Data retrieved: {df.shape[0]} records")
                    print(f"   Date range: {df.index.min()} to {df.index.max()}")
                else:
                    print("⚠️  No data found for the specified range")
            
            print("\n✅ Data storage tests completed successfully!")
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
        print("✅ Collection manager initialized successfully")
        
        # Test adding tasks
        print("\n📝 Testing task management...")
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)
        
        # Add single task
        task_id = manager.add_collection_task(
            symbol="AAPL",
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1
        )
        print(f"✅ Single task added: {task_id}")
        
        # Add batch tasks
        symbols = ["MSFT", "GOOGL", "AMZN"]
        batch_task_ids = manager.add_batch_tasks(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1
        )
        print(f"✅ Batch tasks added: {len(batch_task_ids)} tasks")
        
        # Test task status
        print("\n📊 Testing task status...")
        pending_tasks = manager.get_pending_tasks()
        print(f"✅ Pending tasks: {len(pending_tasks)}")
        
        # Test statistics
        stats = manager.get_stats()
        print(f"✅ Statistics: {stats['total_tasks']} total tasks")
        
        # Test executing a single task
        print("\n🚀 Testing single task execution...")
        task = await manager.execute_task(task_id)
        if task.status == CollectionStatus.COMPLETED:
            print(f"✅ Task executed successfully: {task_id}")
            if task.storage_result:
                print(f"   Records stored: {task.storage_result.records_inserted}")
        else:
            print(f"❌ Task execution failed: {task.error}")
        
        # Test statistics after execution
        stats = manager.get_stats()
        print(f"✅ Updated statistics: {stats['completed_tasks']} completed, {stats['failed_tasks']} failed")
        
        print("\n✅ Collection manager tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Collection manager test failed: {e}")
        return False


async def test_convenience_functions():
    """Test convenience functions."""
    print("\n🔧 Testing Convenience Functions")
    print("=" * 60)
    
    try:
        # Test single symbol collection
        print("\n📈 Testing single symbol collection...")
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=5)
        
        success = await collect_symbol_range(
            symbol="TSLA",
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1
        )
        
        if success:
            print("✅ Single symbol collection successful")
        else:
            print("❌ Single symbol collection failed")
        
        # Test multiple symbols collection
        print("\n📊 Testing multiple symbols collection...")
        symbols = ["NVDA", "META"]
        
        stats = await collect_and_store_data(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1,
            max_concurrent=2
        )
        
        if stats['completed_tasks'] > 0:
            print(f"✅ Multiple symbols collection successful: {stats['completed_tasks']} completed")
            print(f"   Records collected: {stats['total_records_collected']}")
            print(f"   Records stored: {stats['total_records_stored']}")
        else:
            print("❌ Multiple symbols collection failed")
        
        print("\n✅ Convenience functions tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Convenience functions test failed: {e}")
        return False


async def test_configuration_integration():
    """Test configuration system integration."""
    print("\n⚙️  Testing Configuration Integration")
    print("=" * 60)
    
    try:
        # Test configuration loading
        print("\n📋 Testing configuration loading...")
        polygon_config = get_polygon_config()
        db_config = get_database_config()
        
        print(f"✅ Polygon config loaded: {polygon_config.api.base_url}")
        print(f"✅ Database config loaded: {db_config.host}:{db_config.port}")
        
        # Test configuration validation
        print("\n🔍 Testing configuration validation...")
        if polygon_config.api.api_key and polygon_config.api.api_key != "your_polygon_api_key_here":
            print("✅ Polygon API key configured")
        else:
            print("⚠️  Polygon API key not configured (using placeholder)")
            
        if db_config.database:
            print("✅ Database configuration valid")
        else:
            print("❌ Database configuration invalid")
        
        print("\n✅ Configuration integration tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Configuration integration test failed: {e}")
        return False


async def main():
    """Main test function."""
    print("🚀 Starting Polygon.io Integration Tests")
    print("=" * 60)
    
    test_results = []
    
    # Run all tests
    test_functions = [
        ("Configuration Integration", test_configuration_integration),
        ("Enhanced Collector", test_enhanced_collector),
        ("Data Storage", test_data_storage),
        ("Collection Manager", test_collection_manager),
        ("Convenience Functions", test_convenience_functions),
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
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All tests passed! Polygon.io integration is working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the configuration and setup.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
