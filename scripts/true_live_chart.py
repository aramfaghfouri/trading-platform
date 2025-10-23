#!/usr/bin/env python3
"""
True live chart that gets real-time 5-second bars and shows the current minute candle updating live.
"""
import asyncio
import asyncpg
import pandas as pd
import sys
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import pytz

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from lightweight_charts import Chart
from loguru import logger
from ib_async import IB, Stock

class TrueLiveChart:
    """True live chart with real-time 5-second bar aggregation."""
    
    def __init__(self, symbol: str = "AAPL", update_interval: int = 1):
        self.symbol = symbol.upper()
        self.update_interval = update_interval
        self.chart = None
        self.df = pd.DataFrame()
        self.running = False
        self.current_minute_candle = None
        self.ib = None
        self.subscription = None
        
    async def _load_historical_data(self):
        """Load last 200 1-minute candles from database."""
        logger.info(f"📊 Loading historical data for {self.symbol}...")
        
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            rows = await conn.fetch(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT 200
            """)
            
            if rows:
                self.df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
                self.df = self.df.sort_values('timestamp')
                
                # Convert UTC to EST
                est = pytz.timezone('US/Eastern')
                self.df['timestamp_est'] = self.df['timestamp'].dt.tz_convert(est)
                self.df['time'] = self.df['timestamp_est'].dt.strftime('%Y-%m-%d %H:%M:%S')
                self.df['open'] = self.df['open'].astype(float)
                self.df['high'] = self.df['high'].astype(float)
                self.df['low'] = self.df['low'].astype(float)
                self.df['close'] = self.df['close'].astype(float)
                self.df['volume'] = self.df['volume'].astype(int)
                
                logger.info(f"✅ Loaded {len(self.df)} 1-minute candles for {self.symbol}")
            else:
                logger.warning(f"⚠️  No data found in table {table_name}")
                
        finally:
            await conn.close()
    
    def _create_chart(self):
        """Create the live chart."""
        logger.info("📊 Creating live chart...")
        
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        self.chart = Chart()
        self.chart.set(chart_df)
        self.chart.watermark(f"{self.symbol} - Live Real-time Data (EST)")
        self.chart.time_scale(visible=True, time_visible=True, seconds_visible=False)
        
        logger.info(f"📈 Chart created with {len(chart_df)} data points")
        self.chart.show(block=False)
    
    def _on_bar_update(self, bars, has_new_bar):
        """Handle real-time 5-second bar updates and update current minute candle."""
        if not has_new_bar or not bars:
            return
        
        latest_bar = bars[-1]
        bar_time = latest_bar.time
        
        # Get the minute start time
        minute_start = bar_time.replace(second=0, microsecond=0)
        minute_start_est = minute_start.astimezone(pytz.timezone('US/Eastern'))
        time_str = minute_start_est.strftime('%Y-%m-%d %H:%M:%S')
        
        # Initialize or update current minute candle
        if self.current_minute_candle is None or self.current_minute_candle['minute_start'] != minute_start:
            # Start new minute candle
            self.current_minute_candle = {
                'minute_start': minute_start,
                'time': time_str,
                'open': latest_bar.open_,
                'high': latest_bar.high,
                'low': latest_bar.low,
                'close': latest_bar.close,
                'volume': latest_bar.volume,
                'bar_count': 1
            }
            logger.info(f"🕐 Starting new live minute candle: {time_str}")
        else:
            # Update current minute candle
            self.current_minute_candle['high'] = max(self.current_minute_candle['high'], latest_bar.high)
            self.current_minute_candle['low'] = min(self.current_minute_candle['low'], latest_bar.low)
            self.current_minute_candle['close'] = latest_bar.close
            self.current_minute_candle['volume'] += latest_bar.volume
            self.current_minute_candle['bar_count'] += 1
        
        # Update chart with live data
        self._update_chart_with_live_candle()
        
        # Log live update
        candle = self.current_minute_candle
        logger.info(f"📊 LIVE: {candle['time']} O:${candle['open']:.2f} H:${candle['high']:.2f} L:${candle['low']:.2f} C:${candle['close']:.2f} V:{candle['volume']:,} ({candle['bar_count']} bars)")
    
    def _update_chart_with_live_candle(self):
        """Update chart with the current live minute candle."""
        if self.current_minute_candle is None:
            return
        
        # Create updated DataFrame
        if not self.df.empty:
            # Check if we need to add new candle or update existing
            current_time = self.current_minute_candle['time']
            last_time = self.df.iloc[-1]['time']
            
            if current_time == last_time:
                # Update the last row
                self.df.iloc[-1] = {
                    'time': self.current_minute_candle['time'],
                    'open': self.current_minute_candle['open'],
                    'high': self.current_minute_candle['high'],
                    'low': self.current_minute_candle['low'],
                    'close': self.current_minute_candle['close'],
                    'volume': self.current_minute_candle['volume']
                }
            else:
                # Add new candle
                new_row = pd.DataFrame([{
                    'time': self.current_minute_candle['time'],
                    'open': self.current_minute_candle['open'],
                    'high': self.current_minute_candle['high'],
                    'low': self.current_minute_candle['low'],
                    'close': self.current_minute_candle['close'],
                    'volume': self.current_minute_candle['volume']
                }])
                self.df = pd.concat([self.df, new_row], ignore_index=True)
                
                # Keep only last 200 candles
                if len(self.df) > 200:
                    self.df = self.df.tail(200).reset_index(drop=True)
        else:
            # Create new DataFrame
            self.df = pd.DataFrame([{
                'time': self.current_minute_candle['time'],
                'open': self.current_minute_candle['open'],
                'high': self.current_minute_candle['high'],
                'low': self.current_minute_candle['low'],
                'close': self.current_minute_candle['close'],
                'volume': self.current_minute_candle['volume']
            }])
        
        # Update chart
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        self.chart.set(chart_df)
    
    def _start_ibkr_streaming(self):
        """Start IBKR real-time streaming in background thread."""
        def streaming_loop():
            try:
                # Connect to IBKR
                self.ib = IB()
                client_id = int(time.time()) % 9000 + 1000
                logger.info(f"🔌 Connecting to IBKR (client_id: {client_id})...")
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
                
                # Subscribe to 5-second real-time bars
                self.subscription = self.ib.reqRealTimeBars(
                    contract,
                    barSize=5,
                    whatToShow='TRADES',
                    useRTH=False,
                    realTimeBarsOptions=[]
                )
                
                # Set up callback
                self.subscription.updateEvent += self._on_bar_update
                
                logger.info(f"📊 Subscribed to {self.symbol} real-time bars")
                
                # Run streaming loop
                while self.running:
                    self.ib.waitOnUpdate(timeout=1)
                    
            except Exception as e:
                logger.error(f"❌ IBKR streaming error: {e}")
            finally:
                if self.ib and self.ib.isConnected():
                    self.ib.disconnect()
                    logger.info("🔌 Disconnected from IBKR")
        
        # Start streaming thread
        stream_thread = threading.Thread(target=streaming_loop, daemon=True)
        stream_thread.start()
        logger.info("🔄 Started IBKR real-time streaming thread")
    
    async def start(self):
        """Start the true live chart."""
        logger.info(f"🚀 Starting true live chart for {self.symbol}")
        
        # Load historical data
        await self._load_historical_data()
        
        if self.df.empty:
            logger.error("❌ No historical data found. Cannot start chart.")
            return
        
        # Create chart
        self._create_chart()
        
        # Start real-time streaming
        self.running = True
        self._start_ibkr_streaming()
        
        logger.info(f"📊 True live chart started!")
        logger.info(f"🎯 Real-time 5-second bars → 1-minute candles")
        
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Chart stopped by user")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the chart."""
        self.running = False
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        logger.info("🔌 True live chart stopped")

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="True Live Chart")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to chart (default: AAPL)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    chart = TrueLiveChart(args.symbol)
    
    try:
        await chart.start()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    finally:
        chart.stop()

if __name__ == "__main__":
    asyncio.run(main())
