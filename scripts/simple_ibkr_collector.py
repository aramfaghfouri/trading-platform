#!/usr/bin/env python3
"""
Simple IBKR data collector that uses the proven 1-minute candle aggregation.
This replaces the complex hybrid system with a straightforward approach.
"""
import asyncio
import sys
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from ib_async import IB, Stock
from src.data_collectors.common.source_storage import SourceDataStorage

class SimpleIBKRCollector:
    """Simple IBKR collector with proven 1-minute candle aggregation."""
    
    def __init__(self, symbols: List[str]):
        self.symbols = [s.upper() for s in symbols]
        self.ib = IB()
        self.subscriptions = {}
        self.storage = None
        self.running = False
        
        # 1-minute candle aggregation state
        self.current_candles = {}
        self.completed_candles = []
        
    async def start(self):
        """Start the collector."""
        logger.info(f"🚀 Starting simple IBKR collector for {', '.join(self.symbols)}")
        
        # Connect to database
        self.storage = SourceDataStorage(source='ibkr')
        await self.storage.connect()
        logger.info("✅ Connected to database")
        
        # Start real-time streaming in background thread
        self.running = True
        stream_thread = threading.Thread(target=self._run_streaming, daemon=True)
        stream_thread.start()
        logger.info("🔄 Started real-time streaming thread")
        
        # Keep main thread alive
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Stopping collector...")
            self.running = False
    
    def _run_streaming(self):
        """Run real-time streaming in background thread."""
        try:
            # Connect to IBKR
            client_id = int(time.time()) % 9000 + 1000  # Unique client ID
            logger.info(f"🔌 Connecting to IBKR (client_id: {client_id})...")
            self.ib.connect('127.0.0.1', 7497, clientId=client_id)
            
            if not self.ib.isConnected():
                raise RuntimeError("Failed to connect to IBKR")
            
            logger.info("✅ Connected to IBKR")
            
            # Subscribe to each symbol
            for symbol in self.symbols:
                self._subscribe_to_symbol(symbol)
            
            logger.info("📊 Subscribed to all symbols, streaming real-time data...")
            
            # Run the streaming loop
            while self.running:
                self.ib.waitOnUpdate(timeout=1)
                
        except Exception as e:
            logger.error(f"❌ Streaming error: {e}")
        finally:
            if self.ib.isConnected():
                self.ib.disconnect()
                logger.info("🔌 Disconnected from IBKR")
    
    def _subscribe_to_symbol(self, symbol: str):
        """Subscribe to real-time bars for a symbol."""
        try:
            # Create and qualify contract
            contract = Stock(symbol, 'SMART', 'USD')
            qualified_contracts = self.ib.qualifyContracts(contract)
            if qualified_contracts:
                contract = qualified_contracts[0]
                logger.info(f"📈 Qualified contract for {symbol}: {contract}")
            
            # Subscribe to 5-second real-time bars
            subscription = self.ib.reqRealTimeBars(
                contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=False,
                realTimeBarsOptions=[]
            )
            
            # Set up callback for bar updates
            subscription.updateEvent += lambda bars, has_new_bar: self._on_bar_update(symbol, bars, has_new_bar)
            
            self.subscriptions[symbol] = subscription
            logger.info(f"📊 Subscribed to {symbol} real-time bars")
            
        except Exception as e:
            logger.error(f"❌ Failed to subscribe to {symbol}: {e}")
    
    def _on_bar_update(self, symbol: str, bars, has_new_bar):
        """Handle real-time bar updates and aggregate into 1-minute candles."""
        if not has_new_bar or not bars:
            return
        
        latest_bar = bars[-1]
        bar_time = latest_bar.time
        
        # Log the 5-second bar
        logger.debug(f"[{symbol}] 5s bar: {bar_time} | O: ${latest_bar.open_:.2f} H: ${latest_bar.high:.2f} L: ${latest_bar.low:.2f} C: ${latest_bar.close:.2f} V: {latest_bar.volume}")
        
        # Get the minute start time for aggregation
        minute_start = bar_time.replace(second=0, microsecond=0)
        
        # Check if we're in a new minute
        if symbol in self.current_candles and self.current_candles[symbol]['minute_start'] != minute_start:
            # Complete the previous minute candle
            self._complete_candle(symbol)
        
        # Start new minute candle if needed
        if symbol not in self.current_candles or self.current_candles[symbol]['minute_start'] != minute_start:
            self._start_new_candle(symbol, minute_start, latest_bar)
        else:
            # Update current minute candle
            self._update_current_candle(symbol, latest_bar)
    
    def _start_new_candle(self, symbol: str, minute_start, bar):
        """Start a new 1-minute candle."""
        self.current_candles[symbol] = {
            'minute_start': minute_start,
            'open': bar.open_,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'bar_count': 1
        }
        logger.info(f"[{symbol}] 🕐 Starting new 1-minute candle for {minute_start}")
    
    def _update_current_candle(self, symbol: str, bar):
        """Update the current 1-minute candle with new 5-second bar."""
        if symbol not in self.current_candles:
            return
        
        candle = self.current_candles[symbol]
        candle['high'] = max(candle['high'], bar.high)
        candle['low'] = min(candle['low'], bar.low)
        candle['close'] = bar.close
        candle['volume'] += bar.volume
        candle['bar_count'] += 1
    
    def _complete_candle(self, symbol: str):
        """Complete the current 1-minute candle and store it."""
        if symbol not in self.current_candles:
            return
        
        candle = self.current_candles[symbol]
        
        # Create completed candle data
        completed_candle = {
            'timestamp': candle['minute_start'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume']
        }
        
        # Log the completed 1-minute candle
        logger.info(f"[{symbol}] 🕐 COMPLETED 1-MINUTE CANDLE:")
        logger.info(f"   Time: {completed_candle['timestamp']}")
        logger.info(f"   OHLC: O: ${completed_candle['open']:.2f} H: ${completed_candle['high']:.2f} L: ${completed_candle['low']:.2f} C: ${completed_candle['close']:.2f}")
        logger.info(f"   Volume: {completed_candle['volume']} ({candle['bar_count']} bars)")
        logger.info("=" * 60)
        
        # Store in database asynchronously
        asyncio.create_task(self._store_candle(symbol, completed_candle))
        
        # Clear current candle
        del self.current_candles[symbol]
    
    async def _store_candle(self, symbol: str, candle_data):
        """Store completed 1-minute candle to database."""
        try:
            # Create a new storage instance for each write to avoid connection conflicts
            storage = SourceDataStorage(source='ibkr')
            await storage.connect()
            
            result = await storage.store_ohlcv(symbol, '1m', [candle_data])
            if result.success:
                logger.info(f"[{symbol}] 💾 Stored 1-minute candle to database")
            else:
                logger.error(f"[{symbol}] ❌ Failed to store candle: {result.error}")
            
            await storage.disconnect()
        except Exception as e:
            logger.error(f"[{symbol}] ❌ Database storage error: {e}")
    
    async def stop(self):
        """Stop the collector."""
        logger.info("🔌 Stopping simple IBKR collector...")
        self.running = False
        
        # Cancel subscriptions
        for symbol, subscription in self.subscriptions.items():
            try:
                self.ib.cancelRealTimeBars(subscription)
            except:
                pass
        
        # Disconnect from IBKR
        if self.ib.isConnected():
            self.ib.disconnect()
        
        # Close database connection
        if self.storage:
            await self.storage.disconnect()
        
        logger.info("✅ Collector stopped")

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Simple IBKR Data Collector")
    parser.add_argument("symbols", nargs="+", help="Symbols to collect (e.g., AAPL MSFT)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    collector = SimpleIBKRCollector(args.symbols)
    
    try:
        await collector.start()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    finally:
        await collector.stop()

if __name__ == "__main__":
    asyncio.run(main())
