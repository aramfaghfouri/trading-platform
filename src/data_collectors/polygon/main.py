#!/usr/bin/env python3
"""
Main entry point for Polygon Data Collector
Consolidated from multiple entry points for simplicity
"""

import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_collectors.polygon.collect_data import collect_and_store_data_working_approach
from data_collectors.polygon.enhanced_collector import PolygonDataCollector, Timeframe
from data_collectors.polygon.data_storage import PolygonDataStorage
from data_collectors.polygon.collection_manager import collect_and_store_data
from loguru import logger


async def collect_market_data():
    """Main data collection function using the working approach."""
    try:
        logger.info("Starting market data collection...")
        
        # Use the working approach that handles table creation and database integration
        success = await collect_and_store_data_working_approach()
        
        if success:
            logger.info("Market data collection completed successfully!")
            return True
        else:
            logger.error("Market data collection failed!")
            return False
            
    except Exception as e:
        logger.error(f"Market data collection failed: {e}")
        return False


async def collect_sample_data(symbols: List[str] = None, days_back: int = 30):
    """Collect sample data for testing purposes."""
    if symbols is None:
        symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN"]
    
    print("🚀 Collecting Sample Market Data")
    print("=" * 50)
    
    # Use a longer historical period to ensure we get data
    end_date = datetime.now(timezone.utc) - timedelta(days=7)  # Go back a week
    start_date = end_date - timedelta(days=days_back)
    
    print(f"📅 Date range: {start_date.date()} to {end_date.date()}")
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"⏱️  Timeframe: Daily bars")
    print()
    
    try:
        # Collect data using collection manager
        stats = await collect_and_store_data(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=Timeframe.DAY_1,
            max_concurrent=3  # Limit concurrent requests
        )
        
        print("\n📊 Collection Results:")
        print(f"   Total tasks: {stats['total_tasks']}")
        print(f"   Completed: {stats['completed_tasks']}")
        print(f"   Failed: {stats['failed_tasks']}")
        print(f"   Success rate: {stats['success_rate']:.1%}")
        print(f"   Records collected: {stats['total_records_collected']:,}")
        print(f"   Records stored: {stats['total_records_stored']:,}")
        
        if stats['total_records_stored'] > 0:
            print("\n🎉 Successfully collected and stored market data!")
            return True
        else:
            print("\n⚠️  No data was collected. This might be due to:")
            print("   - API rate limits")
            print("   - Non-trading days in the date range")
            print("   - API key limitations")
            return False
            
    except Exception as e:
        print(f"❌ Data collection failed: {e}")
        return False


async def debug_collector():
    """Debug the enhanced collector step by step."""
    print("🔍 Debugging Enhanced Collector")
    print("=" * 40)
    
    async with PolygonDataCollector() as collector:
        print("✅ Collector initialized")
        
        # Test parameters
        symbol = "AAPL"
        multiplier = 1
        timespan = Timeframe.DAY_1
        from_date = "2024-09-01"
        to_date = "2024-09-30"
        
        print(f"📊 Test parameters:")
        print(f"  Symbol: {symbol}")
        print(f"  From: {from_date}")
        print(f"  To: {to_date}")
        print(f"  Timespan: {timespan.value}")
        
        # Test data collection
        result = await collector.get_aggregates(
            symbol=symbol,
            multiplier=multiplier,
            timespan=timespan,
            from_date=from_date,
            to_date=to_date
        )
        
        print(f"✅ Data collection completed")
        print(f"  Result success: {result.success}")
        print(f"  Result error: {result.error}")
        if result.data and 'results' in result.data:
            print(f"  Records collected: {len(result.data['results'])}")
        else:
            print("  No data collected")


async def check_database_status():
    """Check database status and show data summary."""
    print("🗄️  Checking Database Status")
    print("=" * 40)
    
    try:
        async with PolygonDataStorage() as storage:
            print("✅ Database connection successful")
            
            # Get data summary
            summary = await storage.get_data_summary()
            if summary:
                print(f"📊 Database Summary:")
                print(f"   Total records: {summary.get('total_records', 0):,}")
                print(f"   Unique symbols: {summary.get('unique_symbols', 0)}")
                print(f"   Date range: {summary.get('earliest_date', 'N/A')} to {summary.get('latest_date', 'N/A')}")
                
                if summary.get('top_symbols'):
                    print(f"   Top symbols: {', '.join([s['symbol'] for s in summary['top_symbols'][:5]])}")
            else:
                print("⚠️  No data found in database")
                
    except Exception as e:
        print(f"❌ Database check failed: {e}")


async def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(description='Polygon Data Collector')
    parser.add_argument('command', nargs='?', default='collect',
                       choices=['collect', 'sample', 'debug', 'status'],
                       help='Command to run (default: collect)')
    parser.add_argument('--symbols', nargs='+', 
                       help='Ticker symbols to collect data for (for sample command)')
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days back to collect data (for sample command)')
    
    args = parser.parse_args()
    
    if args.command == 'collect':
        # Main data collection using project configuration
        success = await collect_market_data()
        return 0 if success else 1
        
    elif args.command == 'sample':
        # Sample data collection for testing
        success = await collect_sample_data(args.symbols, args.days)
        return 0 if success else 1
        
    elif args.command == 'debug':
        # Debug collector functionality
        await debug_collector()
        return 0
        
    elif args.command == 'status':
        # Check database status
        await check_database_status()
        return 0
        
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))