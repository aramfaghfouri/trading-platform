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
import threading
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
        # Dynamic check interval based on market hours
        self.check_interval = 60 if self.mode == "realtime" else 300  # 1 min for realtime, 5 min for historical
        
        # Hybrid mode components
        self.historical_collector = None
        self.gap_filler_task = None
        self.realtime_task = None
        self.gap_filled = False
        
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
        
        # Cancel async tasks
        tasks_to_cancel = [self.gap_filler_task, self.realtime_task]
        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("🔧 Async tasks cancelled")
        
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
        """Hybrid collection loop with intelligent polling and gap filling."""
        logger.info("🔄 Starting hybrid collection loop...")
        
        # Start gap filler as async task
        self.gap_filler_task = asyncio.create_task(
            self._gap_filler_loop()
        )
        logger.info("🔧 Started gap filler task")
        
        # Start real-time streaming task with proper 1-minute aggregation
        self.realtime_task = asyncio.create_task(
            self._realtime_streaming_loop()
        )
        logger.info("🔄 Started real-time streaming task")
        
        # Wait for tasks to complete or run indefinitely
        try:
            await asyncio.gather(
                self.gap_filler_task,
                self.realtime_task,
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"❌ Error in hybrid loop: {e}")
    
    async def _intelligent_polling_loop(self):
        """Intelligent polling loop that adapts frequency based on market conditions."""
        logger.info("🔄 Starting intelligent polling loop...")
        
        while self.running:
            try:
                current_time = datetime.now(timezone.utc)
                is_market_hours = self._is_market_hours(current_time)
                
                # Adaptive polling frequency
                if is_market_hours:
                    # During market hours: poll every 30 seconds for real-time data
                    poll_interval = 30
                    logger.debug("📈 Market hours - polling every 30 seconds")
                else:
                    # Off-hours: poll every 5 minutes
                    poll_interval = 300
                    logger.debug("🌙 Off-hours - polling every 5 minutes")
                
                # Check for data gaps and collect if needed
                for symbol in self.symbols:
                    await self._check_and_collect_symbol(symbol)
                
                # Wait before next check
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"❌ Error in intelligent polling: {e}")
                await asyncio.sleep(30)
    
    async def _realtime_streaming_loop(self):
        """Real-time streaming loop using the fixed MultiSymbolRealtimeStreamer."""
        logger.info("🔄 Starting real-time streaming loop...")
        
        try:
            from src.data_collectors.ibkr.realtime_stream import MultiSymbolRealtimeStreamer
            
            # Create real-time streamer with proper 1-minute aggregation
            streamer = MultiSymbolRealtimeStreamer(
                symbols=self.symbols,
                client_id=self._get_client_id(self.symbols[0]),
                aggregation_minutes=1,
                batch_size=1,  # Write each 1-minute candle immediately
                enable_chart=False
            )
            
            # Start streaming in a separate thread to avoid event loop conflicts
            import threading
            import time
            
            def run_streamer():
                try:
                    streamer.start()
                    streamer.run()
                except Exception as e:
                    logger.error(f"❌ Real-time streaming error: {e}")
            
            # Start streaming thread
            streamer_thread = threading.Thread(target=run_streamer, daemon=True)
            streamer_thread.start()
            logger.info("🚀 Real-time streaming started in background thread")
            
            # Keep the task alive
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Error starting real-time streaming: {e}")
            await asyncio.sleep(30)
    
    
    async def _gap_filler_loop(self):
        """Parallel gap filler that runs until gap is filled."""
        logger.info("🔧 Starting gap filler loop...")
        
        while self.running and not self.gap_filled:
            try:
                # Check gap for each symbol
                for symbol in self.symbols:
                    gap_info = await self._check_gap(symbol)
                    
                    if gap_info['minutes'] > 1:
                        logger.info(f"📊 Gap detected for {symbol}: {gap_info['minutes']:.1f} minutes")
                        
                        # Try to fill gap
                        success = await self._backfill_gap(symbol, gap_info)
                        if success:
                            logger.info(f"✅ Successfully filled gap for {symbol}")
                        else:
                            logger.debug(f"⏳ Gap for {symbol} not yet available in IBKR historical API")
                    else:
                        logger.info(f"✅ Gap for {symbol} is filled ({gap_info['minutes']:.1f} minutes)")
                        self.gap_filled = True
                        break
                
                # Check every 60 seconds
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error in gap filler: {e}")
                await asyncio.sleep(30)
    
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
                
                # Smart collection strategy based on gap size and market hours
                if gap_minutes >= 60:
                    # Large gap - use historical API
                    logger.info(f"📊 Collecting {symbol} data (gap: {gap_minutes:.1f} minutes)")
                    await self._collect_historical_data(symbol, latest_timestamp, current_time)
                elif gap_minutes >= 5 and self._is_market_hours(current_time):
                    # Medium gap during market hours - try historical API
                    logger.info(f"📊 Collecting {symbol} data during market hours (gap: {gap_minutes:.1f} minutes)")
                    await self._collect_historical_data(symbol, latest_timestamp, current_time)
                elif gap_minutes >= 1:
                    logger.debug(f"⏳ {symbol} data gap too recent for historical API (gap: {gap_minutes:.1f} minutes) - waiting for next market session")
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
    
    def _is_market_hours(self, timestamp: datetime) -> bool:
        """Check if the given timestamp is during market hours."""
        return self._get_market_status(timestamp) == "market_hours"
    
    async def _check_gap(self, symbol: str) -> dict:
        """Check current gap between latest DB data and now."""
        latest = await self._get_latest_timestamp(symbol)
        now = datetime.now(timezone.utc)
        gap_minutes = (now - latest).total_seconds() / 60 if latest else 999
        return {
            'start': latest,
            'end': now,
            'minutes': gap_minutes
        }
    
    async def _backfill_gap(self, symbol: str, gap_info: dict) -> bool:
        """Try to backfill gap using historical API."""
        try:
            # Use historical collector
            collector = IBKRHistoricalCollector()
            client_id = self._get_client_id(symbol)
            
            result = await collector.collect_and_store(
                symbol=symbol,
                start=gap_info['start'].strftime('%Y%m%d %H:%M:%S'),
                end=gap_info['end'].strftime('%Y%m%d %H:%M:%S'),
                timeframe='1m',
                client_id=client_id
            )
            
            return result['success'] and result['inserted'] > 0
            
        except Exception as e:
            logger.error(f"❌ Error backfilling gap for {symbol}: {e}")
            return False
    
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
