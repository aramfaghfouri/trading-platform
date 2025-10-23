#!/usr/bin/env python3
"""
Real-time IBKR Data Collector

Collects real-time 5-second bars from IBKR and aggregates them to 1-minute bars.
This is designed to work alongside the historical collector for a complete hybrid system.
"""

import asyncio
import sys
import os
import signal
from datetime import datetime, timezone
from typing import List

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from loguru import logger
from src.data_collectors.ibkr.realtime_stream import MultiSymbolRealtimeStreamer


class IBKRRealtimeCollector:
    """Real-time data collector using IBKR streaming."""
    
    def __init__(self, symbols: List[str]):
        self.symbols = [s.upper() for s in symbols]
        self.running = False
        self.streamer = None
        
    async def start(self):
        """Start real-time data collection."""
        logger.info(f"🚀 Starting real-time IBKR collector for symbols: {', '.join(self.symbols)}")
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Create real-time streamer
            self.streamer = MultiSymbolRealtimeStreamer(
                symbols=self.symbols,
                host='127.0.0.1',
                port=7497,
                client_id=200,  # Use different client ID to avoid conflicts
                aggregation_minutes=1,
                batch_size=12,
                enable_chart=False  # We have a separate chart
            )
            
            self.running = True
            
            # Start streaming
            await self.streamer.start()
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Real-time collector error: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the collector."""
        logger.info("🛑 Stopping real-time collector...")
        self.running = False
        
        if self.streamer:
            try:
                await self.streamer.stop()
            except Exception as e:
                logger.error(f"Error stopping streamer: {e}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"📡 Received signal {signum}, shutting down...")
        asyncio.create_task(self.stop())


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Real-time IBKR Data Collector")
    parser.add_argument("symbol", help="Symbol to collect (e.g., AAPL)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    collector = IBKRRealtimeCollector(symbols=[args.symbol])
    await collector.start()


if __name__ == "__main__":
    asyncio.run(main())
