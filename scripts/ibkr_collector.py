#!/usr/bin/env python3
"""
Unified IBKR Data Collector

Clean, async data collector that continuously monitors and collects data from IBKR.
Uses connection pooling and proper configuration management.
"""
import asyncio
import asyncpg
import sys
import os
import signal
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import hashlib

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from loguru import logger
from src.data_collectors.ibkr.historical import IBKRHistoricalCollector


class IBKRCollector:
    """Unified async data collector for IBKR with hybrid mode support."""
    
    def __init__(self, symbols: List[str], mode: str = "hybrid"):
        self.symbols = [s.upper() for s in symbols]
        self.mode = mode  # "hybrid", "historical", or "realtime"
        self.running = False
        self.db_pool = None
        self.check_interval = 30  # seconds - collect every 30 seconds regardless of market hours
        
        # Hybrid mode components
        self.historical_collector = None
        
    async def start(self):
        """Start the data collector."""
        logger.info(f"🚀 Starting IBKR collector for symbols: {', '.join(self.symbols)} in {self.mode} mode")
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Create database connection pool
            await self._setup_database_pool()
            
            # Initialize collectors based on mode
            if self.mode in ["hybrid", "historical"]:
                self.historical_collector = IBKRHistoricalCollector()
            
            # Start collection based on mode
            self.running = True
            if self.mode == "realtime":
                await self._realtime_only_loop()
            elif self.mode == "historical":
                await self._historical_only_loop()
            else:  # hybrid
                await self._hybrid_loop()
            
        except Exception as e:
            logger.error(f"❌ Error in collector: {e}")
        finally:
            await self.stop()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"🛑 Received signal {signum}, shutting down...")
        self.running = False
    
    async def stop(self):
        """Stop the collector and cleanup resources."""
        logger.info("🔌 Stopping IBKR collector...")
        self.running = False
        
        # Close database pool
        if self.db_pool:
            await self.db_pool.close()
            logger.info("🔌 Database pool closed")
    
    async def _setup_database_pool(self):
        """Setup database connection pool."""
        dsn = self._get_database_dsn()
        self.db_pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=5,
            command_timeout=30
        )
        logger.info("✅ Database connection pool created")
    
    def _get_database_dsn(self) -> str:
        """Get database DSN from environment or config."""
        # Try environment variable first
        dsn = os.getenv("DATABASE_URL")
        if dsn:
            return dsn
        
        # Fallback to constructed DSN from config
        from src.core.config_loader import ConfigLoader
        loader = ConfigLoader()
        config = loader.get_config_value("database.yaml", "database.postgresql")
        
        return (
            f"postgresql://{config['username']}:{config['password']}"
            f"@{config['host']}:{config['port']}/{config['database']}"
        )
    
    
    async def _historical_only_loop(self):
        """Historical-only collection loop (existing behavior)."""
        logger.info("🔄 Starting historical-only collection loop...")
        
        while self.running:
            try:
                for symbol in self.symbols:
                    await self._check_and_collect_symbol(symbol)
                
                # Wait before next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                logger.info("👋 Historical collection loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in historical collection loop: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    
    async def _realtime_only_loop(self):
        """Real-time only collection loop using frequent polling."""
        logger.info("🔄 Starting real-time only collection loop...")
        
        # Use frequent polling instead of streaming to avoid event loop conflicts
        self.check_interval = 5  # Check every 5 seconds for real-time mode
        
        while self.running:
            try:
                for symbol in self.symbols:
                    await self._check_and_collect_symbol(symbol)
                
                # Wait before next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                logger.info("👋 Real-time collection loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in real-time collection loop: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    
    async def _hybrid_loop(self):
        """Hybrid collection loop with gap detection and backfill."""
        logger.info("🔄 Starting hybrid collection loop...")
        
        # First, check for and fill any existing gaps
        await self._initial_gap_check()
        
        # Use frequent polling for hybrid mode (every 10 seconds)
        self.check_interval = 10
        
        # Main hybrid loop
        while self.running:
            try:
                # Check for data gaps and collect if needed
                for symbol in self.symbols:
                    await self._check_and_collect_symbol(symbol)
                
                # Wait before next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                logger.info("👋 Hybrid collection loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in hybrid collection loop: {e}")
                await asyncio.sleep(10)
    
    async def _initial_gap_check(self):
        """Check for gaps on startup and backfill if needed."""
        logger.info("🔍 Performing initial gap check...")
        
        for symbol in self.symbols:
            try:
                latest_timestamp = await self._get_latest_timestamp(symbol)
                current_time = datetime.now(timezone.utc)
                
                if latest_timestamp:
                    time_gap = current_time - latest_timestamp
                    gap_minutes = time_gap.total_seconds() / 60
                    
                    if gap_minutes > 5:  # Significant gap
                        logger.info(f"📊 Initial gap detected for {symbol}: {gap_minutes:.1f} minutes")
                        await self._backfill_historical(symbol, latest_timestamp, current_time)
                    else:
                        logger.info(f"✅ {symbol} data is up to date (gap: {gap_minutes:.1f} minutes)")
                else:
                    logger.warning(f"⚠️  No existing data for {symbol}")
                    
            except Exception as e:
                logger.error(f"❌ Error in initial gap check for {symbol}: {e}")
    
    async def _detect_and_fill_gaps(self):
        """Detect gaps and backfill if needed."""
        logger.info("🔍 Checking for data gaps...")
        
        for symbol in self.symbols:
            try:
                latest_timestamp = await self._get_latest_timestamp(symbol)
                current_time = datetime.now(timezone.utc)
                
                if latest_timestamp:
                    time_gap = current_time - latest_timestamp
                    gap_minutes = time_gap.total_seconds() / 60
                    
                    if gap_minutes > 5:  # Significant gap
                        logger.info(f"📊 Gap detected for {symbol}: {gap_minutes:.1f} minutes")
                        await self._backfill_historical(symbol, latest_timestamp, current_time)
                    else:
                        logger.debug(f"⏳ {symbol} data is up to date (gap: {gap_minutes:.1f} minutes)")
                        
            except Exception as e:
                logger.error(f"❌ Error checking gaps for {symbol}: {e}")
    
    async def _backfill_historical(self, symbol: str, start_time: datetime, end_time: datetime):
        """Backfill historical data for a symbol."""
        try:
            client_id = self._get_client_id(symbol)
            logger.info(f"🔄 Backfilling {symbol} from {start_time} to {end_time}")
            
            result = await self.historical_collector.collect_and_store(
                symbol=symbol,
                start=start_time.strftime('%Y%m%d %H:%M:%S'),
                end=end_time.strftime('%Y%m%d %H:%M:%S'),
                timeframe='1m',
                client_id=client_id
            )
            
            if result['success'] and result['inserted'] > 0:
                logger.info(f"💾 Backfilled {result['inserted']} bars for {symbol}")
            else:
                logger.debug(f"⏳ No new data backfilled for {symbol}")
                
        except Exception as e:
            logger.error(f"❌ Error backfilling {symbol}: {e}")
    
    
    async def _check_and_collect_symbol(self, symbol: str):
        """Check for data gaps and collect if needed."""
        try:
            # Get latest timestamp from database
            latest_timestamp = await self._get_latest_timestamp(symbol)
            current_time = datetime.now(timezone.utc)
            
            if latest_timestamp:
                time_gap = current_time - latest_timestamp
                gap_minutes = time_gap.total_seconds() / 60
                
                # Collect data regardless of market hours - IBKR has extended hours data
                if gap_minutes >= 1:
                    logger.info(f"📊 Collecting {symbol} data (gap: {gap_minutes:.1f} minutes)")
                    await self._collect_historical_data(symbol, latest_timestamp, current_time)
                else:
                    logger.debug(f"⏳ {symbol} data is up to date (gap: {gap_minutes:.1f} minutes)")
            else:
                logger.warning(f"⚠️  No existing data for {symbol}")
                
        except Exception as e:
            logger.error(f"❌ Error checking data for {symbol}: {e}")
    
    async def _get_latest_timestamp(self, symbol: str) -> Optional[datetime]:
        """Get the latest timestamp from database using connection pool."""
        async with self.db_pool.acquire() as conn:
            table_name = f"ibkr_ohlcv_{symbol.lower()}_1m"
            result = await conn.fetchval(f"""
                SELECT MAX(timestamp) FROM {table_name}
            """)
            return result
    
    async def _collect_historical_data(self, symbol: str, start_time: datetime, end_time: datetime):
        """Collect historical data using IBKR."""
        try:
            # Use deterministic client ID to avoid conflicts
            client_id = self._get_client_id(symbol)
            logger.debug(f"🔗 Using client ID: {client_id}")
            
            # Log if we're collecting off-hours data
            market_status = self._get_market_status(start_time)
            if market_status != "market_hours":
                logger.info(f"🌙 Collecting {market_status} data for {symbol}")
            
            collector = IBKRHistoricalCollector()
            result = await collector.collect_and_store(
                symbol=symbol,
                start=start_time.strftime('%Y%m%d %H:%M:%S'),
                end=end_time.strftime('%Y%m%d %H:%M:%S'),
                timeframe='1m',
                client_id=client_id
            )
            
            if result['success'] and result['inserted'] > 0:
                logger.info(f"💾 Collected {result['inserted']} new bars for {symbol}")
            else:
                logger.debug(f"⏳ No new data for {symbol}")
                
        except Exception as e:
            logger.error(f"❌ Error collecting data for {symbol}: {e}")
            # Add delay to avoid overwhelming IBKR with connection attempts
            await asyncio.sleep(5)
    
    def _get_market_status(self, timestamp: datetime) -> str:
        """Determine if timestamp is during market hours, pre-market, or after-hours."""
        # Convert to EST/EDT
        est_time = timestamp.astimezone(timezone(timedelta(hours=-5)))  # EST
        hour = est_time.hour
        weekday = est_time.weekday()  # 0=Monday, 6=Sunday
        
        # Weekend
        if weekday >= 5:  # Saturday or Sunday
            return "weekend"
        
        # Pre-market (4:00 AM - 9:30 AM EST)
        if 4 <= hour < 9 or (hour == 9 and est_time.minute < 30):
            return "pre_market"
        
        # Market hours (9:30 AM - 4:00 PM EST)
        if (hour == 9 and est_time.minute >= 30) or (10 <= hour < 16):
            return "market_hours"
        
        # After-hours (4:00 PM - 8:00 PM EST)
        if 16 <= hour < 20:
            return "after_hours"
        
        # Overnight (8:00 PM - 4:00 AM EST)
        return "overnight"
    
    def _get_client_id(self, symbol: str) -> int:
        """Generate unique client ID based on symbol, process ID, and timestamp."""
        # Use hash of symbol + process ID + current time for uniqueness
        import time
        hash_input = f"{symbol}_{os.getpid()}_{int(time.time())}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest()[:8], 16)
        return (hash_value % 9000) + 1000


async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="IBKR Data Collector")
    parser.add_argument("symbol", help="Symbol to collect (e.g., AAPL)")
    parser.add_argument("--mode", choices=["hybrid", "historical", "realtime"], 
                       default="hybrid", help="Collection mode (default: hybrid)")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=args.log_level, 
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
    
    collector = IBKRCollector(symbols=[args.symbol], mode=args.mode)
    await collector.start()


if __name__ == "__main__":
    asyncio.run(main())
