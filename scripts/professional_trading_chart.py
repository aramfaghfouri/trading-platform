#!/usr/bin/env python3
"""
Professional TradingView-style chart with OHLCV data panel in top-left corner.
Matches the professional trading interface with live data display.
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
import tkinter as tk
from tkinter import ttk

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from lightweight_charts import Chart
from loguru import logger
from ib_async import IB, Stock

class ProfessionalTradingChart:
    """Professional TradingView-style chart with data panel."""
    
    def __init__(self, symbol: str = "AAPL"):
        self.symbol = symbol.upper()
        self.chart = None
        self.df = pd.DataFrame()
        self.running = False
        self.current_minute_candle = None
        self.ib = None
        self.subscription = None
        
        # Tkinter GUI for data panel
        self.root = None
        self.data_frame = None
        self.price_label = None
        self.ohlcv_labels = {}
        self.volume_label = None
        
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
                LIMIT 50
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
    
    def _create_data_panel(self):
        """Create professional data panel in top-left corner."""
        self.root = tk.Tk()
        self.root.title(f"{self.symbol} - Professional Trading Chart")
        self.root.geometry("1200x800")
        self.root.configure(bg='#1e1e1e')
        
        # Create data panel frame
        self.data_frame = tk.Frame(self.root, bg='#2d2d2d', relief='raised', bd=1)
        self.data_frame.place(x=10, y=10, width=300, height=120)
        
        # Stock symbol and exchange
        symbol_label = tk.Label(
            self.data_frame, 
            text=f"Q {self.symbol}", 
            font=('Arial', 12, 'bold'), 
            fg='white', 
            bg='#2d2d2d'
        )
        symbol_label.place(x=10, y=5)
        
        company_label = tk.Label(
            self.data_frame, 
            text="Apple Inc. 1 NASDAQ", 
            font=('Arial', 9), 
            fg='#cccccc', 
            bg='#2d2d2d'
        )
        company_label.place(x=10, y=25)
        
        # Current price (large, prominent)
        self.price_label = tk.Label(
            self.data_frame, 
            text="$259.34", 
            font=('Arial', 16, 'bold'), 
            fg='white', 
            bg='#2d2d2d'
        )
        self.price_label.place(x=10, y=45)
        
        # OHLCV data
        ohlcv_data = [
            ("O", "259.34"),
            ("H", "259.34"), 
            ("L", "259.28"),
            ("C", "259.34"),
            ("Vol", "1.92 K")
        ]
        
        x_pos = 10
        for i, (label, value) in enumerate(ohlcv_data):
            if i == 2:  # Move to second row
                x_pos = 10
                y_pos = 70
            else:
                y_pos = 45
            
            # Label
            label_widget = tk.Label(
                self.data_frame,
                text=f"{label}:",
                font=('Arial', 9),
                fg='#cccccc',
                bg='#2d2d2d'
            )
            label_widget.place(x=x_pos, y=y_pos + 15)
            
            # Value
            value_widget = tk.Label(
                self.data_frame,
                text=value,
                font=('Arial', 9, 'bold'),
                fg='white',
                bg='#2d2d2d'
            )
            value_widget.place(x=x_pos + 20, y=y_pos + 15)
            
            self.ohlcv_labels[label] = value_widget
            x_pos += 60
        
        # Change indicator
        self.change_label = tk.Label(
            self.data_frame,
            text="0.00 (0.00%)",
            font=('Arial', 9),
            fg='#00ff00',
            bg='#2d2d2d'
        )
        self.change_label.place(x=10, y=85)
        
        # Trading buttons
        sell_btn = tk.Button(
            self.data_frame,
            text="SELL\n259.15\n0.04",
            font=('Arial', 8, 'bold'),
            fg='white',
            bg='#ff4444',
            relief='flat',
            bd=0
        )
        sell_btn.place(x=200, y=45, width=40, height=50)
        
        buy_btn = tk.Button(
            self.data_frame,
            text="BUY\n259.19",
            font=('Arial', 8, 'bold'),
            fg='white',
            bg='#4444ff',
            relief='flat',
            bd=0
        )
        buy_btn.place(x=250, y=45, width=40, height=50)
        
        # Timeframe buttons
        timeframes = ["1s", "10s", "15s", "30s", "1m", "3m", "5m", "9m", "10m", "15m", "30m", "1h", "2h", "4h", "8h", "9h", "D", "3D", "W", "2W", "M"]
        tf_frame = tk.Frame(self.root, bg='#1e1e1e')
        tf_frame.place(x=10, y=140, width=600, height=30)
        
        for i, tf in enumerate(timeframes):
            btn = tk.Button(
                tf_frame,
                text=tf,
                font=('Arial', 8),
                fg='white' if tf != '1m' else '#00ff00',
                bg='#333333' if tf != '1m' else '#2d2d2d',
                relief='flat',
                bd=1,
                command=lambda t=tf: self._on_timeframe_click(t)
            )
            btn.place(x=i*25, y=0, width=25, height=25)
    
    def _on_timeframe_click(self, timeframe):
        """Handle timeframe button clicks."""
        logger.info(f"📊 Timeframe changed to: {timeframe}")
        # Here you would update the chart data based on timeframe
    
    def _create_chart(self):
        """Create the professional chart."""
        logger.info("📊 Creating professional chart...")
        
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        self.chart = Chart()
        self.chart.set(chart_df)
        self.chart.watermark(f"{self.symbol} - Professional Trading Data")
        self.chart.time_scale(visible=True, time_visible=True, seconds_visible=False)
        
        logger.info(f"📈 Professional chart created with {len(chart_df)} data points")
        self.chart.show(block=False)
    
    def _update_data_panel(self):
        """Update the data panel with current candle data."""
        if self.current_minute_candle is None:
            return
        
        candle = self.current_minute_candle
        
        # Update price
        self.price_label.config(text=f"${candle['close']:.2f}")
        
        # Update OHLCV
        self.ohlcv_labels['O'].config(text=f"{candle['open']:.2f}")
        self.ohlcv_labels['H'].config(text=f"{candle['high']:.2f}")
        self.ohlcv_labels['L'].config(text=f"{candle['low']:.2f}")
        self.ohlcv_labels['C'].config(text=f"{candle['close']:.2f}")
        self.ohlcv_labels['Vol'].config(text=f"{candle['volume']/1000:.1f} K")
        
        # Calculate and update change
        if len(self.df) > 1:
            prev_close = self.df.iloc[-2]['close']
            change = candle['close'] - prev_close
            change_pct = (change / prev_close) * 100
            
            color = '#00ff00' if change >= 0 else '#ff4444'
            self.change_label.config(
                text=f"{change:+.2f} ({change_pct:+.2f}%)",
                fg=color
            )
    
    def _on_bar_update(self, bars, has_new_bar):
        """Handle real-time 5-second bar updates."""
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
        else:
            # Update current minute candle
            self.current_minute_candle['high'] = max(self.current_minute_candle['high'], latest_bar.high)
            self.current_minute_candle['low'] = min(self.current_minute_candle['low'], latest_bar.low)
            self.current_minute_candle['close'] = latest_bar.close
            self.current_minute_candle['volume'] += latest_bar.volume
            self.current_minute_candle['bar_count'] += 1
        
        # Update data panel
        self._update_data_panel()
        
        # Update chart
        self._update_chart_with_live_candle()
        
        # Log update
        candle = self.current_minute_candle
        logger.info(f"📊 LIVE: {candle['time']} O:${candle['open']:.2f} H:${candle['high']:.2f} L:${candle['low']:.2f} C:${candle['close']:.2f} V:{candle['volume']:,}")
    
    def _update_chart_with_live_candle(self):
        """Update chart with the current live minute candle."""
        if self.current_minute_candle is None:
            return
        
        # Create updated DataFrame
        if not self.df.empty:
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
                
                # Keep only last 50 candles
                if len(self.df) > 50:
                    self.df = self.df.tail(50).reset_index(drop=True)
        
        # Update chart
        chart_df = self.df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        self.chart.set(chart_df)
    
    def _start_ibkr_streaming(self):
        """Start IBKR real-time streaming."""
        def streaming_loop():
            try:
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
                
                self.subscription.updateEvent += self._on_bar_update
                logger.info(f"📊 Subscribed to {self.symbol} real-time bars")
                
                while self.running:
                    self.ib.waitOnUpdate(timeout=1)
                    
            except Exception as e:
                logger.error(f"❌ IBKR streaming error: {e}")
            finally:
                if self.ib and self.ib.isConnected():
                    self.ib.disconnect()
                    logger.info("🔌 Disconnected from IBKR")
        
        stream_thread = threading.Thread(target=streaming_loop, daemon=True)
        stream_thread.start()
        logger.info("🔄 Started IBKR real-time streaming thread")
    
    async def start(self):
        """Start the professional trading chart."""
        logger.info(f"🚀 Starting professional trading chart for {self.symbol}")
        
        # Load historical data
        await self._load_historical_data()
        
        if self.df.empty:
            logger.error("❌ No historical data found. Cannot start chart.")
            return
        
        # Create data panel
        self._create_data_panel()
        
        # Create chart
        self._create_chart()
        
        # Start real-time streaming
        self.running = True
        self._start_ibkr_streaming()
        
        logger.info(f"📊 Professional trading chart started!")
        
        # Start GUI main loop
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("🛑 Chart stopped by user")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the chart."""
        self.running = False
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        if self.root:
            self.root.quit()
        logger.info("🔌 Professional trading chart stopped")

async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Professional Trading Chart")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to chart (default: AAPL)")
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    chart = ProfessionalTradingChart(args.symbol)
    
    try:
        await chart.start()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    finally:
        chart.stop()

if __name__ == "__main__":
    asyncio.run(main())
