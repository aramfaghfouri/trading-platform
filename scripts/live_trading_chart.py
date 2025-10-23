#!/usr/bin/env python3
"""
Professional live trading chart with real-time candle updates.
Matches the professional trading interface look with live OHLCV updates.
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

class LiveTradingChart:
    """Professional live trading chart with real-time updates."""
    
    def __init__(self, symbol: str = "AAPL", update_interval: int = 1):
        self.symbol = symbol.upper()
        self.update_interval = update_interval  # seconds
        self.chart = None
        self.df = pd.DataFrame()
        self.running = False
        self.last_timestamp = None
        self.current_candle = None
        self.live_data_thread = None
        
    async def _load_historical_data(self):
        """Load last 500 1-minute candles from database."""
        logger.info(f"📊 Loading historical data for {self.symbol}...")
        
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            # Query for IBKR 1-minute data
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            rows = await conn.fetch(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT 500
            """)
            
            if rows:
                # Convert to DataFrame
                self.df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
                self.df = self.df.sort_values('timestamp')
                
                # Convert UTC to EST for chart display
                est = pytz.timezone('US/Eastern')
                self.df['timestamp_est'] = self.df['timestamp'].dt.tz_convert(est)
                
                # Prepare for chart (use EST time)
                self.df['time'] = self.df['timestamp_est'].dt.strftime('%Y-%m-%d %H:%M:%S')
                self.df['open'] = self.df['open'].astype(float)
                self.df['high'] = self.df['high'].astype(float)
                self.df['low'] = self.df['low'].astype(float)
                self.df['close'] = self.df['close'].astype(float)
                self.df['volume'] = self.df['volume'].astype(int)
                
                # Set last timestamp for updates
                self.last_timestamp = self.df['timestamp'].max()
                
                # Initialize current candle with latest data
                if not self.df.empty:
                    latest = self.df.iloc[-1]
                    self.current_candle = {
                        'timestamp': latest['timestamp'],
                        'time': latest['time'],
                        'open': latest['open'],
                        'high': latest['high'],
                        'low': latest['low'],
                        'close': latest['close'],
                        'volume': latest['volume']
                    }
                
                logger.info(f"✅ Loaded {len(self.df)} 1-minute candles for {self.symbol}")
                logger.info(f"📅 Date range: {self.df['timestamp'].min()} to {self.df['timestamp'].max()}")
            else:
                logger.warning(f"⚠️  No data found in table {table_name}")
                
        finally:
            await conn.close()
    
    def _create_professional_chart(self):
        """Create a professional trading chart with custom styling."""
        logger.info("📊 Creating professional trading chart...")
        
        # Prepare chart data
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        # Create chart with professional styling
        self.chart = Chart()
        self.chart.set(chart_df)
        
        # Professional chart styling
        self.chart.watermark(f"{self.symbol} - Live Trading Data (EST)")
        self.chart.time_scale(
            visible=True, 
            time_visible=True, 
            seconds_visible=False
        )
        
        logger.info(f"📈 Professional chart created with {len(chart_df)} data points")
        if not chart_df.empty:
            logger.info(f"💰 Price range: ${chart_df['low'].min():.2f} - ${chart_df['high'].max():.2f}")
        
        # Show chart (non-blocking)
        self.chart.show(block=False)
    
    async def _update_live_candle(self):
        """Update the current live candle with real-time data."""
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            # Get the latest 1-minute candle
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            latest_row = await conn.fetchrow(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            if latest_row:
                # Convert to EST
                est = pytz.timezone('US/Eastern')
                timestamp_est = latest_row['timestamp'].astimezone(est)
                time_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S')
                
                # Update current candle
                self.current_candle = {
                    'timestamp': latest_row['timestamp'],
                    'time': time_str,
                    'open': float(latest_row['open']),
                    'high': float(latest_row['high']),
                    'low': float(latest_row['low']),
                    'close': float(latest_row['close']),
                    'volume': int(latest_row['volume'])
                }
                
                # Calculate price change
                if len(self.df) > 1:
                    prev_close = self.df.iloc[-2]['close']
                    change = self.current_candle['close'] - prev_close
                    change_pct = (change / prev_close) * 100
                    
                    # Display live OHLCV data
                    change_color = "🟢" if change >= 0 else "🔴"
                    logger.info(f"📊 LIVE {self.symbol}: {change_color} O:${self.current_candle['open']:.2f} H:${self.current_candle['high']:.2f} L:${self.current_candle['low']:.2f} C:${self.current_candle['close']:.2f} V:{self.current_candle['volume']:,} | {change:+.2f} ({change_pct:+.2f}%)")
                else:
                    logger.info(f"📊 LIVE {self.symbol}: O:${self.current_candle['open']:.2f} H:${self.current_candle['high']:.2f} L:${self.current_candle['low']:.2f} C:${self.current_candle['close']:.2f} V:{self.current_candle['volume']:,}")
                
                # Update chart with latest data
                self._update_chart_display()
                
        finally:
            await conn.close()
    
    def _update_chart_display(self):
        """Update the chart display with current data."""
        if self.current_candle is None:
            return
        
        # Create updated DataFrame with current candle
        if not self.df.empty:
            # Check if we need to add a new candle or update the existing one
            current_time = self.current_candle['time']
            last_time = self.df.iloc[-1]['time']
            
            if current_time == last_time:
                # Update the last row with current candle data
                self.df.iloc[-1] = {
                    'time': self.current_candle['time'],
                    'open': self.current_candle['open'],
                    'high': self.current_candle['high'],
                    'low': self.current_candle['low'],
                    'close': self.current_candle['close'],
                    'volume': self.current_candle['volume']
                }
            else:
                # Add new candle
                new_row = pd.DataFrame([{
                    'time': self.current_candle['time'],
                    'open': self.current_candle['open'],
                    'high': self.current_candle['high'],
                    'low': self.current_candle['low'],
                    'close': self.current_candle['close'],
                    'volume': self.current_candle['volume']
                }])
                self.df = pd.concat([self.df, new_row], ignore_index=True)
                
                # Keep only last 500 candles
                if len(self.df) > 500:
                    self.df = self.df.tail(500).reset_index(drop=True)
        else:
            # Create new DataFrame with current candle
            self.df = pd.DataFrame([{
                'time': self.current_candle['time'],
                'open': self.current_candle['open'],
                'high': self.current_candle['high'],
                'low': self.current_candle['low'],
                'close': self.current_candle['close'],
                'volume': self.current_candle['volume']
            }])
        
        # Update chart with live data
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        self.chart.set(chart_df)
        
        # Force chart refresh
        try:
            self.chart.show(block=False)
        except:
            pass
    
    def _start_live_data_thread(self):
        """Start background thread for live data updates."""
        def live_data_loop():
            while self.running:
                try:
                    # Run async update in thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self._update_live_candle())
                    loop.close()
                except Exception as e:
                    logger.error(f"❌ Live data update error: {e}")
                time.sleep(self.update_interval)
        
        self.live_data_thread = threading.Thread(target=live_data_loop, daemon=True)
        self.live_data_thread.start()
        logger.info(f"🔄 Started live data thread (updating every {self.update_interval}s)")
    
    async def start(self):
        """Start the live trading chart."""
        logger.info(f"🚀 Starting professional live chart for {self.symbol}")
        
        # Load historical data
        await self._load_historical_data()
        
        if self.df.empty:
            logger.error("❌ No historical data found. Cannot start chart.")
            return
        
        # Create professional chart
        self._create_professional_chart()
        
        # Start live updates
        self.running = True
        self._start_live_data_thread()
        
        logger.info(f"📊 Professional live chart started!")
        logger.info(f"🎯 Real-time updates every {self.update_interval} seconds")
        logger.info(f"📈 Chart displays live OHLCV data with professional styling")
        
        try:
            # Keep main thread alive
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Chart stopped by user")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the chart."""
        self.running = False
        if self.live_data_thread:
            self.live_data_thread.join(timeout=2)
        logger.info("🔌 Professional chart stopped")

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Professional Live Trading Chart")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to chart (default: AAPL)")
    parser.add_argument("--update-interval", type=int, default=1, help="Update interval in seconds (default: 1)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    chart = LiveTradingChart(args.symbol, args.update_interval)
    
    try:
        await chart.start()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    finally:
        chart.stop()

if __name__ == "__main__":
    asyncio.run(main())
