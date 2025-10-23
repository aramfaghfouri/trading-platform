#!/usr/bin/env python3
"""
Live AAPL chart that reads 1-minute candles from the database and displays them in real-time.
"""
import asyncio
import asyncpg
import pandas as pd
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import pytz

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from lightweight_charts import Chart
from loguru import logger

class LiveAAPLChart:
    """Live chart that reads 1-minute candles from database and displays them."""
    
    def __init__(self, symbol: str = "AAPL", update_interval: int = 10):
        self.symbol = symbol.upper()
        self.update_interval = update_interval  # seconds
        self.chart = None
        self.df = pd.DataFrame()
        self.running = False
        self.last_timestamp = None
        
    async def _load_historical_data(self):
        """Load last 1000 1-minute candles from database."""
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
                LIMIT 1000
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
                
                logger.info(f"✅ Loaded {len(self.df)} 1-minute candles for {self.symbol}")
                logger.info(f"📅 Date range: {self.df['timestamp'].min()} to {self.df['timestamp'].max()}")
            else:
                logger.warning(f"⚠️  No data found in table {table_name}")
                
        finally:
            await conn.close()
    
    def _create_chart(self):
        """Create the lightweight chart."""
        logger.info("📊 Creating live chart...")
        
        # Prepare chart data
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        # Create chart
        self.chart = Chart()
        self.chart.set(chart_df)
        
        # Set chart properties
        self.chart.watermark(f"{self.symbol} - Live from Database (EST) - 1m candles")
        self.chart.time_scale(visible=True, time_visible=True, seconds_visible=False)
        
        logger.info(f"📈 Chart created with {len(chart_df)} data points")
        if not chart_df.empty:
            logger.info(f"💰 Price range: ${chart_df['low'].min():.2f} - ${chart_df['high'].max():.2f}")
        
        # Show chart (non-blocking)
        self.chart.show(block=False)
    
    async def _update_chart(self):
        """Update chart with new data from database."""
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            
            # Get new data since last timestamp
            if self.last_timestamp:
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {table_name}
                    WHERE timestamp > $1
                    ORDER BY timestamp ASC
                """
                rows = await conn.fetch(query, self.last_timestamp)
            else:
                # Get latest 10 records if no last timestamp
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {table_name}
                    ORDER BY timestamp DESC
                    LIMIT 10
                """
                rows = await conn.fetch(query)
            
            if rows:
                # Convert to DataFrame
                new_df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                new_df['timestamp'] = pd.to_datetime(new_df['timestamp'])
                
                # Convert UTC to EST
                est = pytz.timezone('US/Eastern')
                new_df['timestamp_est'] = new_df['timestamp'].dt.tz_convert(est)
                new_df['time'] = new_df['timestamp_est'].dt.strftime('%Y-%m-%d %H:%M:%S')
                new_df['open'] = new_df['open'].astype(float)
                new_df['high'] = new_df['high'].astype(float)
                new_df['low'] = new_df['low'].astype(float)
                new_df['close'] = new_df['close'].astype(float)
                new_df['volume'] = new_df['volume'].astype(int)
                
                # Append new data
                self.df = pd.concat([self.df, new_df], ignore_index=True)
                self.df = self.df.sort_values('timestamp')
                
                # Keep only last 1000 records
                if len(self.df) > 1000:
                    self.df = self.df.tail(1000).reset_index(drop=True)
                
                # Update chart
                chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
                self.chart.set(chart_df)
                
                # Update last timestamp
                self.last_timestamp = self.df['timestamp'].max()
                
                # Log new data
                for _, row in new_df.iterrows():
                    logger.info(f"📈 New 1m candle: {row['time']} O:${row['open']:.2f} H:${row['high']:.2f} L:${row['low']:.2f} C:${row['close']:.2f} V:{row['volume']}")
                
        finally:
            await conn.close()
    
    async def start(self):
        """Start the live chart."""
        logger.info(f"🚀 Starting live chart for {self.symbol}")
        
        # Load historical data
        await self._load_historical_data()
        
        if self.df.empty:
            logger.error("❌ No historical data found. Cannot start chart.")
            return
        
        # Create chart
        self._create_chart()
        
        # Start update loop
        self.running = True
        logger.info(f"📊 Live chart started. Updating every {self.update_interval} seconds...")
        
        try:
            while self.running:
                await self._update_chart()
                await asyncio.sleep(self.update_interval)
        except KeyboardInterrupt:
            logger.info("🛑 Chart stopped by user")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the chart."""
        self.running = False
        logger.info("🔌 Chart stopped")

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Live AAPL Chart")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to chart (default: AAPL)")
    parser.add_argument("--update-interval", type=int, default=10, help="Update interval in seconds (default: 10)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    chart = LiveAAPLChart(args.symbol, args.update_interval)
    
    try:
        await chart.start()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    finally:
        chart.stop()

if __name__ == "__main__":
    asyncio.run(main())
