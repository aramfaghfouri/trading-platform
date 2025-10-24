#!/usr/bin/env python3
"""
Live updating chart that shows real-time updates within the current minute candle.
"""
import asyncio
import os
import sys
import pandas as pd
import pytz
from datetime import datetime, timezone, timedelta
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from lightweight_charts import Chart
import asyncpg
from src.core.config_loader import get_database_config

class LiveUpdatingChart:
    def __init__(self, symbol: str = 'AAPL'):
        self.symbol = symbol.upper()
        self.chart: Chart = None
        self.df = pd.DataFrame()
        self.running = False
        self.est_timezone = pytz.timezone('US/Eastern')
        self.current_minute_candle = None
        self.last_completed_minute = None
        
        # Database connection
        db_config = get_database_config()
        self.dsn = (
            f"postgresql://{db_config.username}:{db_config.password}@"
            f"{db_config.host}:{db_config.port}/{db_config.database}"
        )
        self.table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"

        logger.remove()
        logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    def _create_chart(self):
        """Create professional chart without debug mode."""
        logger.info("📊 Creating live updating chart...")
        
        # Create chart WITHOUT debug mode to avoid developer tools
        self.chart = Chart()
        
        # Professional styling
        self.chart.layout(background_color='#1e1e1e', text_color='#FFFFFF', font_size=14)
        self.chart.candle_style(up_color='#00ff55', down_color='#ed4807')
        self.chart.volume_config(up_color='#00ff55', down_color='#ed4807')
        self.chart.grid(vert_enabled=True, horz_enabled=True)
        self.chart.legend(visible=True, font_size=12)
        
        # Professional crosshair
        self.chart.crosshair(mode='normal', vert_color='#FFFFFF', vert_style='dotted',
                            horz_color='#FFFFFF', horz_style='dotted')
        
        # Simple topbar
        self.chart.topbar.textbox('symbol', self.symbol)
        self.chart.topbar.textbox('status', 'Loading...')

        logger.info("📈 Live updating chart created")

    async def _load_historical_data(self):
        """Load historical data from database."""
        logger.info(f"📊 Loading historical data for {self.symbol}...")
        
        conn = await asyncpg.connect(self.dsn)
        
        try:
            # Get last 50 1-minute candles
            rows = await conn.fetch(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {self.table_name}
                ORDER BY timestamp DESC
                LIMIT 50
            """)
            
            if rows:
                # Convert to DataFrame
                data = []
                for row in rows:
                    timestamp_est = row['timestamp'].astimezone(self.est_timezone)
                    data.append({
                        'time': timestamp_est.strftime('%Y-%m-%d %H:%M:%S'),
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': int(row['volume'])
                    })
                
                # Reverse to get chronological order
                data.reverse()
                self.df = pd.DataFrame(data)
                
                # Set initial data
                self.chart.set(self.df)
                
                # Set the last completed minute
                if len(self.df) > 0:
                    self.last_completed_minute = self.df['time'].iloc[-1]
                
                logger.info(f"✅ Loaded {len(self.df)} historical candles for {self.symbol}")
                logger.info(f"📅 Latest completed: {self.last_completed_minute}")
            else:
                logger.warning(f"⚠️  No data found in table {self.table_name}")
                
        finally:
            await conn.close()

    async def _update_chart(self):
        """Update chart with latest data from database."""
        conn = await asyncpg.connect(self.dsn)
        
        try:
            # Get the latest candle
            latest_row = await conn.fetchrow(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {self.table_name}
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            if latest_row:
                timestamp_est = latest_row['timestamp'].astimezone(self.est_timezone)
                time_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S')
                
                # Check if this is a new minute (completed candle)
                if self.last_completed_minute != time_str:
                    # This is a new completed minute candle
                    latest_candle = pd.Series({
                        'time': time_str,
                        'open': float(latest_row['open']),
                        'high': float(latest_row['high']),
                        'low': float(latest_row['low']),
                        'close': float(latest_row['close']),
                        'volume': int(latest_row['volume'])
                    })
                    
                    # Update chart with new completed candle
                    self.chart.update(latest_candle)
                    self.last_completed_minute = time_str
                    
                    logger.info(f"📊 NEW MINUTE: {time_str} O:${latest_candle['open']:.2f} H:${latest_candle['high']:.2f} L:${latest_candle['low']:.2f} C:${latest_candle['close']:.2f} V:{latest_candle['volume']:,}")
                else:
                    # This is the current minute - update the live candle
                    if self.current_minute_candle is None:
                        # Start new current minute candle
                        self.current_minute_candle = {
                            'time': time_str,
                            'open': float(latest_row['open']),
                            'high': float(latest_row['high']),
                            'low': float(latest_row['low']),
                            'close': float(latest_row['close']),
                            'volume': int(latest_row['volume'])
                        }
                    else:
                        # Update current minute candle with latest values
                        self.current_minute_candle['high'] = max(self.current_minute_candle['high'], float(latest_row['high']))
                        self.current_minute_candle['low'] = min(self.current_minute_candle['low'], float(latest_row['low']))
                        self.current_minute_candle['close'] = float(latest_row['close'])
                        self.current_minute_candle['volume'] = int(latest_row['volume'])  # Reset volume per minute
                    
                    # Update chart with current live candle
                    live_candle = pd.Series(self.current_minute_candle)
                    self.chart.update(live_candle)
                    
                    # Update status
                    self.chart.topbar.textbox('status', f'LIVE: {time_str}')
                    
                    # Log live update
                    logger.info(
                        f"📊 LIVE: {time_str} O:${self.current_minute_candle['open']:.2f} H:${self.current_minute_candle['high']:.2f} L:${self.current_minute_candle['low']:.2f} C:${self.current_minute_candle['close']:.2f} V:{self.current_minute_candle['volume']:,}"
                    )
                
        except Exception as e:
            logger.error(f"❌ Update error: {e}")
        finally:
            await conn.close()

    async def start(self):
        """Start the chart with real-time updates."""
        self.running = True
        
        # Create chart
        self._create_chart()
        
        # Load historical data
        await self._load_historical_data()
        
        # Show chart
        self.chart.show(block=False)
        
        logger.info("📊 Live updating chart started!")
        logger.info("🎯 Updating every 2 seconds with live data")
        
        # Update loop
        while self.running:
            try:
                await self._update_chart()
                await asyncio.sleep(2)  # Update every 2 seconds for live feel
            except Exception as e:
                logger.error(f"❌ Update loop error: {e}")
                await asyncio.sleep(2)

    async def stop(self):
        """Stop the chart."""
        logger.info("🔌 Stopping live updating chart...")
        self.running = False

async def main():
    chart = LiveUpdatingChart()
    try:
        await chart.start()
    except asyncio.CancelledError:
        logger.info("Chart cancelled.")
    finally:
        await chart.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrupted by user.")
