#!/usr/bin/env python3
"""
Collect real market data from Polygon.io

This script collects actual market data for testing purposes.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_collectors.polygon.collection_manager import collect_and_store_data
from data_collectors.polygon.enhanced_collector import Timeframe
from loguru import logger


async def collect_sample_data():
    """Collect sample market data for testing."""
    print("🚀 Collecting Real Market Data")
    print("=" * 50)
    
    # Use a longer historical period to ensure we get data
    end_date = datetime.now(timezone.utc) - timedelta(days=7)  # Go back a week
    start_date = end_date - timedelta(days=30)  # 30 days of data
    
    # Test with popular stocks
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN"]
    
    print(f"📅 Date range: {start_date.date()} to {end_date.date()}")
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"⏱️  Timeframe: Daily bars")
    print()
    
    try:
        # Collect data
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
            print("   You can now query the database to see the data.")
        else:
            print("\n⚠️  No data was collected. This might be due to:")
            print("   - API rate limits")
            print("   - Non-trading days in the date range")
            print("   - API key limitations")
        
        return stats['total_records_stored'] > 0
        
    except Exception as e:
        print(f"❌ Data collection failed: {e}")
        return False


async def main():
    """Main function."""
    success = await collect_sample_data()
    
    if success:
        print("\n✅ Data collection completed successfully!")
        print("\nNext steps:")
        print("1. Check the database for stored data")
        print("2. Run VectorBT backtests with the collected data")
        print("3. Set up automated data collection schedules")
        return 0
    else:
        print("\n⚠️  Data collection had issues.")
        print("Check the logs above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
