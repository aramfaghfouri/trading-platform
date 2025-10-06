#!/usr/bin/env python3
"""
Debug script for enhanced collector
"""

import sys
import asyncio
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_collectors.polygon.enhanced_collector import PolygonDataCollector, Timeframe
from loguru import logger


async def debug_enhanced_collector():
    """Debug the enhanced collector step by step."""
    print("🔍 Debugging Enhanced Collector")
    print("=" * 40)
    
    async with PolygonDataCollector() as collector:
        print("✅ Collector initialized")
        
        # Test parameters
        symbol = "AAPL"
        multiplier = 1
        timespan = Timeframe.DAY_1
        from_date = "2025-09-01"
        to_date = "2025-09-30"
        adjusted = True
        sort = "asc"
        limit = 50000
        
        print(f"📊 Test parameters:")
        print(f"  Symbol: {symbol}")
        print(f"  From: {from_date}")
        print(f"  To: {to_date}")
        print(f"  Timespan: {timespan.value}")
        
        # Step 1: Test rate limiter
        print(f"\n⏱️  Step 1: Testing rate limiter...")
        await collector.rate_limiter.wait_if_needed()
        print("✅ Rate limiter passed")
        
        # Step 2: Test direct API call
        print(f"\n🌐 Step 2: Testing direct API call...")
        response = collector.stocks_client.get_aggregate_bars(
            symbol=symbol,
            multiplier=multiplier,
            timespan=timespan.value,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
            sort=sort,
            limit=limit
        )
        print(f"✅ API call successful")
        print(f"  Response type: {type(response)}")
        print(f"  Response keys: {list(response.keys()) if isinstance(response, dict) else 'Not a dict'}")
        
        # Step 3: Test response processing
        print(f"\n🔧 Step 3: Testing response processing...")
        if not response:
            print("❌ Response is empty")
            return
        
        # Extract results
        if isinstance(response, dict):
            results = response.get('results', [])
        else:
            results = response.results if hasattr(response, 'results') else []
        
        print(f"✅ Results extracted")
        print(f"  Results type: {type(results)}")
        print(f"  Results count: {len(results)}")
        
        if results:
            print(f"  First result: {results[0]}")
            print(f"  Last result: {results[-1]}")
        
        # Step 4: Test data validation
        print(f"\n🔍 Step 4: Testing data validation...")
        if collector.config.quality.validate_data and results:
            is_valid, errors = collector.validator.validate_bar_data(results)
            print(f"✅ Data validation completed")
            print(f"  Is valid: {is_valid}")
            if errors:
                print(f"  Errors: {errors[:3]}...")  # Show first 3 errors
        else:
            print("⚠️  Skipping data validation (no results or disabled)")
        
        # Step 5: Test data preparation
        print(f"\n📋 Step 5: Testing data preparation...")
        if isinstance(response, dict):
            data = {
                'symbol': symbol,
                'results': results,
                'count': len(results),
                'next_url': response.get('next_url'),
                'request_id': response.get('request_id')
            }
        else:
            data = {
                'symbol': symbol,
                'results': results,
                'count': len(results),
                'next_url': getattr(response, 'next_url', None),
                'request_id': getattr(response, 'request_id', None)
            }
        
        print(f"✅ Data prepared")
        print(f"  Data keys: {list(data.keys())}")
        print(f"  Data count: {data['count']}")
        
        # Step 6: Test full method
        print(f"\n🚀 Step 6: Testing full get_aggregates method...")
        result = await collector.get_aggregates(
            symbol=symbol,
            multiplier=multiplier,
            timespan=timespan,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
            sort=sort,
            limit=limit
        )
        
        print(f"✅ Full method completed")
        print(f"  Result success: {result.success}")
        print(f"  Result error: {result.error}")
        if result.data:
            print(f"  Result data keys: {list(result.data.keys())}")
            if 'results' in result.data:
                print(f"  Result results count: {len(result.data['results'])}")
        else:
            print("  Result data: None")


async def main():
    """Main function."""
    await debug_enhanced_collector()


if __name__ == "__main__":
    asyncio.run(main())
