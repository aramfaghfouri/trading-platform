#!/usr/bin/env python3
"""
Market Data Collection CLI
Main entry point for collecting market data from various sources
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_collectors.polygon import collect_and_store_data_working_approach
from loguru import logger

async def main():
    """Main entry point for market data collection"""
    try:
        logger.info("Starting market data collection...")
        
        # Run the working approach collection
        await collect_and_store_data_working_approach()
        
        logger.info("Market data collection completed successfully!")
        
    except Exception as e:
        logger.error(f"Market data collection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
