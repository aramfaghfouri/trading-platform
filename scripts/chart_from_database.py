#!/usr/bin/env python3
"""
Live Chart from Database

Reads real-time data from the database and displays it using lightweight_charts.
Supports configurable update frequency and symbol switching.
"""

import asyncio
import argparse
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


class DatabaseChart:
    """Live chart that reads data from database."""
    
    def __init__(self, symbol: str, update_freq: str = "minute"):
        self.symbol = symbol.upper()
        self.update_freq = update_freq
        self.update_interval = 10 if update_freq == "minute" else 5  # seconds
        self.chart = None
        self.df = pd.DataFrame()
        self.running = False
        
    async def start(self):
        """Start the chart with database updates."""
        logger.info(f"🚀 Starting live chart for {self.symbol} (update: {self.update_freq})")
        
        try:
            # Load initial data
            await self._load_historical_data()
            
            if self.df.empty:
                logger.error(f"❌ No data found for {self.symbol}")
                return
            
            # Create chart
            self._create_chart()
            
            # Start update loop
            self.running = True
            await self._update_loop()
            
        except KeyboardInterrupt:
            logger.info("👋 Stopping chart...")
        except Exception as e:
            logger.error(f"❌ Error in chart: {e}")
        finally:
            self.running = False
    
    async def _load_historical_data(self):
        """Load last 1000 bars from database."""
        logger.info(f"📊 Loading historical data for {self.symbol}...")
        
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            # Query for IBKR data - get the most recent 1000 bars
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            rows = await conn.fetch(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT 1000
            """)
            
            # Reverse the order to get chronological order (oldest to newest)
            rows = list(reversed(rows))
            
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
                
                logger.info(f"✅ Loaded {len(self.df)} bars for {self.symbol}")
                logger.info(f"📅 Date range: {self.df['timestamp'].min()} to {self.df['timestamp'].max()}")
            else:
                logger.warning(f"⚠️  No data found in table {table_name}")
                
        finally:
            await conn.close()
    
    def _create_chart(self):
        """Create the lightweight chart."""
        logger.info("📊 Creating chart...")
        
        # Prepare chart data
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        # Create chart
        self.chart = Chart()
        self.chart.set(chart_df)
        
        # Set chart properties
        self.chart.watermark(f"{self.symbol} - Live from Database (EST) ({self.update_freq} updates)")
        self.chart.time_scale(visible=True, time_visible=True, seconds_visible=False)
        
        logger.info(f"📈 Chart created with {len(chart_df)} data points")
        logger.info(f"💰 Price range: ${chart_df['low'].min():.2f} - ${chart_df['high'].max():.2f}")
        
        # Show chart (non-blocking)
        self.chart.show(block=False)
    
    async def _update_loop(self):
        """Main update loop."""
        logger.info(f"🔄 Starting update loop (every {self.update_interval}s)")
        
        while self.running:
            try:
                await asyncio.sleep(self.update_interval)
                
                # Check for new data
                new_data = await self._check_for_new_data()
                
                if not new_data.empty:
                    logger.info(f"📈 New data found: {len(new_data)} bars")
                    await self._update_chart(new_data)
                else:
                    logger.debug("⏳ No new data")
                    
            except Exception as e:
                logger.error(f"❌ Error in update loop: {e}")
    
    async def _check_for_new_data(self) -> pd.DataFrame:
        """Check database for new data since last update."""
        if self.df.empty:
            return pd.DataFrame()
        
        latest_timestamp = self.df['timestamp'].max()
        
        dsn = "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        conn = await asyncpg.connect(dsn)
        
        try:
            table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
            rows = await conn.fetch(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                WHERE timestamp > $1
                ORDER BY timestamp ASC
            """, latest_timestamp)
            
            if rows:
                new_df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                new_df['timestamp'] = pd.to_datetime(new_df['timestamp'])
                new_df['time'] = new_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                new_df['open'] = new_df['open'].astype(float)
                new_df['high'] = new_df['high'].astype(float)
                new_df['low'] = new_df['low'].astype(float)
                new_df['close'] = new_df['close'].astype(float)
                new_df['volume'] = new_df['volume'].astype(int)
                return new_df
            else:
                return pd.DataFrame()
                
        finally:
            await conn.close()
    
    async def _update_chart(self, new_data: pd.DataFrame):
        """Update chart with new data."""
        try:
            # Append new data
            self.df = pd.concat([self.df, new_data])
            
            # Sort by timestamp to ensure proper order
            self.df = self.df.sort_values('timestamp')
            
            # Keep last 1000 bars
            self.df = self.df.tail(1000)
            
            # Update chart
            chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
            self.chart.set(chart_df)
            
            logger.info(f"📊 Chart updated: {len(chart_df)} total bars")
            logger.info(f"📅 Date range: {self.df['timestamp'].min()} to {self.df['timestamp'].max()}")
            
        except Exception as e:
            logger.error(f"❌ Error updating chart: {e}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Live Chart from Database")
    parser.add_argument("symbol", help="Symbol to chart (e.g., AAPL)")
    parser.add_argument("--update-freq", choices=["minute", "realtime"], default="minute",
                       help="Update frequency: 'minute' (60s) or 'realtime' (5s)")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=args.log_level, 
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
    
    # Create and start chart
    chart = DatabaseChart(args.symbol, args.update_freq)
    await chart.start()


if __name__ == "__main__":
    asyncio.run(main())
