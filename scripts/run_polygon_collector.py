#!/usr/bin/env python3
"""
Script to run Polygon Data Collector
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from data_collectors.polygon.main import PolygonDataService

async def main():
    """Main function"""
    # Example usage
    service = PolygonDataService()
    
    # Example 1: Collect data for specific tickers
    tickers = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
    print(f"Collecting data for tickers: {tickers}")
    data = await service.collect_ticker_data(tickers, days_back=7)
    print(f"Collected data for {len(data)} tickers")
    
    # Example 2: Get market status
    market_status = service.get_market_status()
    print(f"Market status: {market_status}")
    
    # Example 3: Generate report
    report = service.generate_report(data)
    print(f"Report: {report}")

if __name__ == "__main__":
    asyncio.run(main())
