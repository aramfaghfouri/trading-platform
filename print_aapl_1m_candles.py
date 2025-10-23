#!/usr/bin/env python3
"""
Real-time AAPL 1-minute candle aggregator.
Streams 5-second bars from IBKR and aggregates them into 1-minute candles.
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from ib_async import IB, Stock

class OneMinuteCandleAggregator:
    """Aggregates 5-second bars into 1-minute candles."""
    
    def __init__(self, symbol: str = "AAPL"):
        self.symbol = symbol.upper()
        self.ib = IB()
        self.subscription = None
        self.current_minute = None
        self.current_candle = None
        self.completed_candles = []
        
    def start(self):
        """Connect to IBKR and start streaming."""
        logger.info(f"🔌 Connecting to IBKR for {self.symbol}...")
        
        # Connect with random client ID
        import random
        client_id = random.randint(10000, 99999)
        self.ib.connect('127.0.0.1', 7497, clientId=client_id)
        
        if not self.ib.isConnected():
            raise RuntimeError("Failed to connect to IBKR")
        
        logger.info("✅ Connected to IBKR")
        
        # Create and qualify contract
        contract = Stock(self.symbol, 'SMART', 'USD')
        qualified_contracts = self.ib.qualifyContracts(contract)
        if qualified_contracts:
            contract = qualified_contracts[0]
            logger.info(f"📈 Qualified contract: {contract}")
        
        # Subscribe to 5-second bars
        logger.info("📊 Subscribing to 5-second real-time bars...")
        self.subscription = self.ib.reqRealTimeBars(
            contract,
            barSize=5,
            whatToShow='TRADES',
            useRTH=False,
            realTimeBarsOptions=[]
        )
        self.subscription.updateEvent += self._on_bar_update
        
        logger.info("🚀 Streaming started - building 1-minute candles...")
        
    def _on_bar_update(self, bars, has_new_bar):
        """Handle 5-second bar updates and aggregate into 1-minute candles."""
        if not has_new_bar or not bars:
            return
            
        latest_bar = bars[-1]
        bar_time = latest_bar.time
        
        # Print the 5-second bar
        logger.info(f"📊 5s bar: {bar_time} | O: ${latest_bar.open_:.2f} H: ${latest_bar.high:.2f} L: ${latest_bar.low:.2f} C: ${latest_bar.close:.2f} V: {latest_bar.volume}")
        
        # Get the minute start time
        minute_start = bar_time.replace(second=0, microsecond=0)
        
        # Check if we're in a new minute
        if self.current_minute != minute_start:
            # Complete the previous minute candle if it exists
            if self.current_candle is not None:
                self._complete_candle()
            
            # Start new minute candle
            self._start_new_candle(minute_start, latest_bar)
        else:
            # Update current minute candle
            self._update_current_candle(latest_bar)
    
    def _start_new_candle(self, minute_start, bar):
        """Start a new 1-minute candle."""
        self.current_minute = minute_start
        self.current_candle = {
            'timestamp': minute_start,
            'open': bar.open_,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'bar_count': 1
        }
        logger.info(f"🕐 Starting new 1-minute candle for {minute_start}")
    
    def _update_current_candle(self, bar):
        """Update the current 1-minute candle with new 5-second bar."""
        if self.current_candle is None:
            return
            
        # Update OHLC
        self.current_candle['high'] = max(self.current_candle['high'], bar.high)
        self.current_candle['low'] = min(self.current_candle['low'], bar.low)
        self.current_candle['close'] = bar.close
        self.current_candle['volume'] += bar.volume
        self.current_candle['bar_count'] += 1
    
    def _complete_candle(self):
        """Complete the current 1-minute candle."""
        if self.current_candle is None:
            return
            
        # Add to completed candles
        self.completed_candles.append(self.current_candle.copy())
        
        # Print the completed 1-minute candle
        candle = self.current_candle
        logger.info(f"🕐 COMPLETED 1-MINUTE CANDLE:")
        logger.info(f"   Time: {candle['timestamp']}")
        logger.info(f"   OHLC: O: ${candle['open']:.2f} H: ${candle['high']:.2f} L: ${candle['low']:.2f} C: ${candle['close']:.2f}")
        logger.info(f"   Volume: {candle['volume']} ({candle['bar_count']} bars)")
        logger.info("=" * 60)
        
        # Clear current candle
        self.current_candle = None
    
    def run(self):
        """Run the streaming loop."""
        try:
            while True:
                self.ib.waitOnUpdate(timeout=1)
        except KeyboardInterrupt:
            logger.info("🛑 Stopping...")
        finally:
            self.stop()
    
    def stop(self):
        """Stop streaming and disconnect."""
        if self.subscription:
            try:
                self.ib.cancelRealTimeBars(self.subscription)
            except:
                pass
        
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("🔌 Disconnected from IBKR")
        
        # Print summary
        logger.info(f"\n📊 Summary: Completed {len(self.completed_candles)} 1-minute candles")
        if self.completed_candles:
            logger.info("Last few candles:")
            for candle in self.completed_candles[-3:]:
                logger.info(f"  {candle['timestamp']}: O: ${candle['open']:.2f} H: ${candle['high']:.2f} L: ${candle['low']:.2f} C: ${candle['close']:.2f}")

def main():
    """Main function."""
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    aggregator = OneMinuteCandleAggregator("AAPL")
    
    try:
        aggregator.start()
        aggregator.run()
    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        aggregator.stop()

if __name__ == "__main__":
    main()
