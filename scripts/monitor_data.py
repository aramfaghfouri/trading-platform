#!/usr/bin/env python3
"""
Monitor database for new data points and print them in real-time.
"""
import asyncio
import asyncpg
import sys
import os
from datetime import datetime, timezone
from typing import Optional

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from loguru import logger

class DataMonitor:
    """Monitor database for new data points."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.last_timestamp: Optional[datetime] = None
        self.running = False
        
    async def start(self):
        """Start monitoring for new data."""
        logger.info(f"🔍 Starting data monitor for {self.symbol}")
        
        try:
            # Get initial timestamp
            await self._get_initial_timestamp()
            
            # Start monitoring loop
            self.running = True
            while self.running:
                await self._check_for_new_data()
                await asyncio.sleep(5)  # Check every 5 seconds
                
        except KeyboardInterrupt:
            logger.info("👋 Stopping monitor...")
        except Exception as e:
            logger.error(f"❌ Error in monitor: {e}")
        finally:
            self.running = False
    
    async def _get_initial_timestamp(self):
        """Get the latest timestamp to start monitoring from."""
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            result = await conn.fetchval(f"""
                SELECT MAX(timestamp) FROM {table_name}
            """)
            
            if result:
                self.last_timestamp = result
                logger.info(f"📅 Starting monitor from: {self.last_timestamp}")
            else:
                logger.warning(f"⚠️  No existing data for {self.symbol}")
                
        finally:
            await conn.close()
    
    async def _check_for_new_data(self):
        """Check for new data points since last check."""
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            
            if self.last_timestamp:
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {table_name}
                    WHERE timestamp > $1
                    ORDER BY timestamp ASC
                """
                rows = await conn.fetch(query, self.last_timestamp)
            else:
                # Get the latest 5 records
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {table_name}
                    ORDER BY timestamp DESC
                    LIMIT 5
                """
                rows = await conn.fetch(query)
                rows = list(reversed(rows))  # Reverse to get chronological order
            
            if rows:
                logger.info(f"📊 Found {len(rows)} new data points:")
                for row in rows:
                    timestamp, open_price, high, low, close, volume = row
                    logger.info(f"  📈 {timestamp} | O:${open_price:.2f} H:${high:.2f} L:${low:.2f} C:${close:.2f} V:{volume:,}")
                    
                    # Update last timestamp
                    if timestamp > self.last_timestamp:
                        self.last_timestamp = timestamp
            else:
                current_time = datetime.now(timezone.utc)
                if self.last_timestamp:
                    time_diff = current_time - self.last_timestamp
                    logger.debug(f"⏳ No new data (last: {time_diff.total_seconds()/60:.1f} min ago)")
                else:
                    logger.debug("⏳ No data available")
                    
        except Exception as e:
            logger.error(f"❌ Error checking data: {e}")
        finally:
            await conn.close()

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor database for new data points")
    parser.add_argument("symbol", help="Symbol to monitor (e.g., AAPL)")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=args.log_level, 
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    monitor = DataMonitor(symbol=args.symbol)
    await monitor.start()

if __name__ == "__main__":
    asyncio.run(main())
