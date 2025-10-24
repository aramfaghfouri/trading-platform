#!/usr/bin/env python3
"""
Proper professional TradingView-style chart with correct candlestick display.
Uses lightweight-charts-python advanced features for professional appearance.
"""
import asyncio
import os
import random
import threading
import sys
from datetime import datetime, timezone, timedelta
from collections import deque
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import pytz
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from ib_async import IB, Stock, util
from lightweight_charts import Chart

class ProperProfessionalChart:
    def __init__(self, symbol: str = 'AAPL', host: str = '127.0.0.1', port: int = 7497):
        self.symbol = symbol.upper()
        self.host = host
        self.port = port
        self.client_id = random.randint(10000, 99999)
        self.ib = IB()
        self.chart: Optional[Chart] = None
        self.df = pd.DataFrame() # DataFrame for chart data
        self.current_minute_candle: Optional[Dict[str, Any]] = None
        self.running = False
        self.raw_bars_count = 0
        self.est_timezone = pytz.timezone('US/Eastern')

        logger.remove()
        logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    def _as_utc(self, ts: Union[int, float, datetime]) -> datetime:
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)

    def _create_proper_chart(self):
        """Create proper professional chart with correct candlestick display."""
        logger.info("📊 Creating proper professional chart...")
        
        # Create realistic sample data for proper candlestick display
        now = datetime.now(self.est_timezone)
        sample_data = []
        
        # Generate realistic candlestick data with proper OHLC relationships
        base_prices = [259.0, 259.2, 259.1, 259.3, 259.4, 259.2, 259.5, 259.6, 259.4, 259.7, 259.8, 259.6, 259.9, 260.0, 259.8, 260.1, 260.2, 260.0, 260.3, 260.4]
        
        for i, base_price in enumerate(base_prices):
            timestamp = now - timedelta(minutes=len(base_prices)-i)
            time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            
            # Create proper OHLC relationships for candlesticks
            open_price = base_price
            close_price = base_price + (0.1 if i % 2 == 0 else -0.1)
            high_price = max(open_price, close_price) + 0.05
            low_price = min(open_price, close_price) - 0.05
            volume = 1000 + i * 100
            
            sample_data.append({
                'time': time_str,
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume
            })
        
        self.df = pd.DataFrame(sample_data)
        
        # Create chart with professional features
        self.chart = Chart(debug=True, toolbox=True)
        
        # Professional layout styling
        self.chart.layout(background_color='#090008', text_color='#FFFFFF', font_size=16,
                         font_family='Helvetica')
        
        # Professional candlestick styling
        self.chart.candle_style(up_color='#00ff55', down_color='#ed4807',
                               border_up_color='#FFFFFF', border_down_color='#FFFFFF',
                               wick_up_color='#FFFFFF', wick_down_color='#FFFFFF')
        
        # Volume configuration
        self.chart.volume_config(up_color='#00ff55', down_color='#ed4807')
        
        
        # Professional crosshair
        self.chart.crosshair(mode='normal', vert_color='#FFFFFF', vert_style='dotted',
                            horz_color='#FFFFFF', horz_style='dotted')
        
        # Enable grid for professional look
        self.chart.grid(vert_enabled=True, horz_enabled=True)
        
        # Enable legend
        self.chart.legend(visible=True, font_size=14)
        
        # Time scale configuration
        self.chart.time_scale(
            visible=True, 
            time_visible=True, 
            seconds_visible=False
        )
        
        # Professional topbar elements
        self.chart.topbar.textbox('symbol', self.symbol)
        self.chart.topbar.textbox('price_change', '0.00 (0.00%)')
        self.chart.topbar.switcher('timeframe_switcher', ('1s', '10s', '15s', '30s', '1m', '3m', '5m', '9m', '10m', '15m', '30m', '1h', '2h', '4h', '8h', '9h', 'D', '3D', 'W', '2W', 'M'), default='1m')
        
        # Set initial data with proper candlestick format
        self.chart.set(self.df)

        logger.info(f"📈 Proper professional chart created with {len(self.df)} candlesticks")

        self.chart.show(block=False)

    def _on_bar_update(self, bars, has_new_bar) -> None:
        if not has_new_bar or not bars:
            return

        latest_bar = bars[-1]
        timestamp = self._as_utc(latest_bar.time)
        self.raw_bars_count += 1

        minute_start = timestamp.replace(second=0, microsecond=0)
        time_str_est = minute_start.astimezone(self.est_timezone).strftime('%Y-%m-%d %H:%M:%S')

        # Check if we're in a new minute
        if self.current_minute_candle and self.current_minute_candle['minute_start'] != minute_start:
            # Complete the previous minute candle and add to DataFrame
            completed_candle = self.current_minute_candle.copy()
            completed_candle['timestamp'] = self.current_minute_candle['minute_start']
            completed_candle['time'] = completed_candle['timestamp'].astimezone(self.est_timezone).strftime('%Y-%m-%d %H:%M:%S')
            
            new_row = pd.DataFrame([{
                'time': completed_candle['time'],
                'open': completed_candle['open'],
                'high': completed_candle['high'],
                'low': completed_candle['low'],
                'close': completed_candle['close'],
                'volume': completed_candle['volume']
            }])
            self.df = pd.concat([self.df, new_row], ignore_index=True)
            
            # Keep only last 50 candles
            if len(self.df) > 50:
                self.df = self.df.tail(50).reset_index(drop=True)
            
            self.current_minute_candle = None # Reset for new minute

        # Start new minute candle if needed
        if self.current_minute_candle is None:
            self.current_minute_candle = {
                'minute_start': minute_start,
                'open': float(latest_bar.open_),
                'high': float(latest_bar.high),
                'low': float(latest_bar.low),
                'close': float(latest_bar.close),
                'volume': int(latest_bar.volume or 0),  # Start with current bar's volume
                'bar_count': 1
            }
        else:
            # Update current minute candle
            self.current_minute_candle['high'] = max(self.current_minute_candle['high'], float(latest_bar.high))
            self.current_minute_candle['low'] = min(self.current_minute_candle['low'], float(latest_bar.low))
            self.current_minute_candle['close'] = float(latest_bar.close)
            # Reset volume to current bar's volume (not accumulate)
            self.current_minute_candle['volume'] = int(latest_bar.volume or 0)
            self.current_minute_candle['bar_count'] += 1

        # Update the chart with the current minute candle (live update)
        if self.chart:
            current_candle_for_chart = {
                'time': time_str_est,
                'open': self.current_minute_candle['open'],
                'high': self.current_minute_candle['high'],
                'low': self.current_minute_candle['low'],
                'close': self.current_minute_candle['close'],
                'volume': self.current_minute_candle['volume']
            }
            # Update the chart with the current live candle
            self.chart.update(current_candle_for_chart)
            
            # Also update the DataFrame to keep it in sync
            if len(self.df) > 0 and self.df.iloc[-1]['time'] == time_str_est:
                # Update the last row if it's the same minute
                self.df.iloc[-1] = current_candle_for_chart
            else:
                # Add new row if it's a new minute
                new_row = pd.DataFrame([current_candle_for_chart])
                self.df = pd.concat([self.df, new_row], ignore_index=True)
                # Keep only last 50 candles
                if len(self.df) > 50:
                    self.df = self.df.tail(50).reset_index(drop=True)
            
            # Update topbar info (removed OHLCV display as requested)
            
            # Calculate price change
            if len(self.df) > 0:
                prev_close = self.df.iloc[-1]['close'] if self.df.iloc[-1]['time'] != time_str_est else (self.df.iloc[-2]['close'] if len(self.df) > 1 else self.current_minute_candle['open'])
                change = self.current_minute_candle['close'] - prev_close
                change_pct = (change / prev_close) * 100 if prev_close != 0 else 0
                change_color = 'green' if change >= 0 else 'red'
                self.chart.topbar.textbox('price_change', f'{change:+.2f} ({change_pct:+.2f}%)', color=change_color)
            
            # Log live update
            logger.info(
                f"📊 LIVE: {time_str_est} O:${self.current_minute_candle['open']:.2f} H:${self.current_minute_candle['high']:.2f} L:${self.current_minute_candle['low']:.2f} C:${self.current_minute_candle['close']:.2f} V:{self.current_minute_candle['volume']:,}"
            )

    def _on_error(self, req_id, code, msg, *_):
        if code in (2104, 2106, 2158): # Informational messages
            logger.debug(f"IBKR info [{code}]: {msg}")
        else:
            logger.error(f"IBKR error [{code}] (reqId={req_id}): {msg}")

    def _run_ibkr_loop(self):
        """Run IBKR event loop in a separate thread."""
        util.startLoop()
        self.ib.run()

    async def start(self):
        self.running = True
        self._create_proper_chart()

        logger.info(f"🔌 Connecting to IBKR (client_id: {self.client_id})...")
        try:
            await self.ib.connectAsync(self.host, self.port, clientId=self.client_id, timeout=30)
            logger.info("✅ Connected to IBKR")
        except asyncio.TimeoutError:
            logger.error("❌ Connection timeout - IBKR TWS/Gateway not responding")
            logger.error(f"Please ensure IBKR TWS/Gateway is running on port {self.port}")
            self.running = False
            return
        except Exception as e:
            logger.error(f"❌ Failed to connect to IBKR: {e}")
            logger.error(f"Please ensure IBKR TWS/Gateway is running on port {self.port}")
            self.running = False
            return

        self.ib.reqMarketDataType(1) # Request real-time data
        self.ib.errorEvent += self._on_error

        contract = Stock(self.symbol, 'SMART', 'USD')
        logger.info("📈 Qualifying contract...")
        qualified_contracts = await self.ib.qualifyContractsAsync(contract)
        if qualified_contracts:
            contract = qualified_contracts[0]
            logger.info(f"📈 Qualified contract: {contract}")
        else:
            logger.error("❌ Failed to qualify contract")
            self.running = False
            return

        logger.info("📊 Subscribing to AAPL real-time bars")
        self.ib.reqRealTimeBars(
            contract,
            barSize=5,
            whatToShow='TRADES',
            useRTH=False,
            realTimeBarsOptions=[],
        ).updateEvent += self._on_bar_update
        
        # Start IBKR event loop in a separate thread
        self.ibkr_thread = threading.Thread(target=self._run_ibkr_loop, daemon=True)
        self.ibkr_thread.start()
        logger.info("🔄 Started IBKR real-time streaming thread")

        logger.info("📊 Proper professional trading chart started!")
        logger.info("🎯 Real-time updates every 5 seconds (within current minute candle)")
        logger.info("📈 Chart displays live OHLCV data with professional styling")
        logger.info("🔧 Debug mode enabled, toolbox available, grid enabled")

        while self.running:
            await asyncio.sleep(1) # Keep the main event loop alive

    async def stop(self):
        logger.info("🔌 Stopping proper professional chart...")
        self.running = False
        if self.ib.isConnected():
            self.ib.disconnect()
        logger.info("🔌 Disconnected from IBKR")
        logger.info(f"Total 5-second bars received: {self.raw_bars_count}")

async def main():
    chart = ProperProfessionalChart()
    try:
        await chart.start()
    except asyncio.CancelledError:
        logger.info("Chart streaming cancelled.")
    finally:
        await chart.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrupted by user.")