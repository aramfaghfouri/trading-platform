"""
Real-time Heiken-Ashi chart using lightweight-charts-python.

Provides a TradingView-like interface for real-time market data visualization
with Heiken-Ashi candles and multiple timeframes.
"""

import pandas as pd
import numpy as np
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import deque

from lightweight_charts import Chart
from src.brokers.ibkr.realtime_bars import IBKRRealtimeBarStream
from src.utils.heikin_ashi import calculate_heikin_ashi, HeikinAshiCalculator
from src.utils.timeframes import (
    get_supported_timeframes,
    get_timeframe_display_name,
    TIMEFRAME_GROUPS
)


class LightweightRealtimeChart:
    """Real-time chart using lightweight-charts-python."""
    
    def __init__(self, symbol: str = "EURUSD", initial_timeframe: str = "1m"):
        self.symbol = symbol
        self.current_timeframe = initial_timeframe
        
        # Data storage
        self.bars_data: Dict[str, deque] = {}  # timeframe -> deque of bars
        self.max_bars = 500
        
        # Chart state
        self.chart_type = "ha"  # Start with Heikin-Ashi
        self.overlays = []  # List of active overlays
        
        # IBKR connection
        self.bar_stream: Optional[IBKRRealtimeBarStream] = None
        self.is_connected = False
        
        # Auto-refresh
        self.auto_refresh = False
        self.refresh_timer = None
        
        # Initialize data storage
        for tf in get_supported_timeframes():
            self.bars_data[tf] = deque(maxlen=self.max_bars)
        
        # Chart instance
        self.chart = None
        self.ha_line = None
        self.sma_lines = {}
        self._ha_rt = HeikinAshiCalculator()
        
    def _create_chart(self):
        """Create the lightweight chart with controls."""
        # Create chart with toolbox for drawing tools
        self.chart = Chart(toolbox=True, width=1400, height=800)
        
        # Set up the chart with minimal configuration
        self.chart.layout(
            background_color='#131722',
            text_color='#d1d4dc',
            font_size=12
        )
        
        # Configure time scale to ensure it's visible
        self.chart.time_scale(
            visible=True,
            time_visible=True,
            seconds_visible=False
        )
        
        # Configure candlestick style
        self.chart.candle_style(
            up_color='#26a69a',
            down_color='#ef5350',
            border_up_color='#26a69a',
            border_down_color='#ef5350',
            wick_up_color='#26a69a',
            wick_down_color='#ef5350'
        )
        
        # Add watermark
        self.chart.watermark(f'{self.symbol} - {get_timeframe_display_name(self.current_timeframe)}')
        
        # Add legend
        self.chart.legend(visible=True)
        
        # Set up topbar controls
        self._setup_topbar()
        
        # Set up event handlers
        self._setup_events()
        
    def _setup_topbar(self):
        """Set up the top toolbar with controls."""
        # Symbol input
        self.chart.topbar.textbox('symbol', self.symbol)
        
        # Timeframe selector
        timeframe_options = []
        for group_name, timeframes in TIMEFRAME_GROUPS.items():
            for tf in timeframes:
                timeframe_options.append(tf)
        
        self.chart.topbar.switcher(
            'timeframe', 
            timeframe_options, 
            default=self.current_timeframe,
            func=self._on_timeframe_change
        )
        
        # Chart type selector
        self.chart.topbar.switcher(
            'chart_type',
            ('Candlestick', 'Heiken-Ashi'),
            default='Heiken-Ashi',
            func=self._on_chart_type_change
        )
        
        # Add manual update button for testing
        self.chart.topbar.button('update', 'Update Chart', func=self._manual_update)
        
        # Add auto-refresh timer
        self.chart.topbar.button('refresh', 'Auto Refresh', func=self._toggle_auto_refresh)
        
        # Overlay selector
        self.chart.topbar.switcher(
            'overlays',
            ('None', 'Volume', 'SMA20', 'SMA50', 'Volume+SMA20', 'Volume+SMA50'),
            default='None',
            func=self._on_overlay_change
        )
        
        # Connection status
        self.chart.topbar.textbox('status', 'Disconnected')
        
    def _setup_events(self):
        """Set up event handlers."""
        # Search event for symbol changes
        self.chart.events.search += self._on_symbol_search
        
    def _on_symbol_search(self, chart, searched_string):
        """Handle symbol search."""
        if searched_string and searched_string.upper() != self.symbol:
            self.symbol = searched_string.upper()
            chart.topbar['symbol'].set(self.symbol)
            self._reconnect_to_ibkr()
            
    def _on_timeframe_change(self, chart):
        """Handle timeframe change."""
        new_timeframe = chart.topbar['timeframe'].value
        if new_timeframe != self.current_timeframe:
            self.current_timeframe = new_timeframe
            self._update_watermark()
            self._reconnect_to_ibkr()
            
    def _on_chart_type_change(self, chart):
        """Handle chart type change."""
        try:
            chart_type = chart.topbar['chart_type'].value
            print(f"🔄 Chart type button clicked: {chart_type}")
            
            if chart_type == "Heiken-Ashi":
                self.chart_type = "ha"
            elif chart_type == "Candlestick":
                self.chart_type = "ohlc"
            elif chart_type == "Both":
                self.chart_type = "both"
            else:
                self.chart_type = "ha"  # default
                
            print(f"🔄 Switching to {chart_type} chart type (internal: {self.chart_type})")
            
            # Clear any existing overlays first
            self.overlays = []
            self._update_overlays()
            
            # Update the chart data with new type
            self._update_chart_data()
        except Exception as e:
            print(f"❌ Error in chart type change: {e}")
            import traceback
            traceback.print_exc()
        
    def _on_overlay_change(self, chart):
        """Handle overlay change."""
        try:
            overlay = chart.topbar['overlays'].value
            print(f"🔄 Overlay button clicked: {overlay}")
            
            if overlay == 'None':
                self.overlays = []
            elif overlay == 'Volume':
                self.overlays = ['volume']
            elif overlay == 'SMA20':
                self.overlays = ['sma20']
            elif overlay == 'SMA50':
                self.overlays = ['sma50']
            elif overlay == 'Volume+SMA20':
                self.overlays = ['volume', 'sma20']
            elif overlay == 'Volume+SMA50':
                self.overlays = ['volume', 'sma50']
            
            print(f"🔄 Overlay changed to: {overlay}, overlays: {self.overlays}")
            self._update_overlays()
        except Exception as e:
            print(f"❌ Error in overlay change: {e}")
            import traceback
            traceback.print_exc()
        
    def _update_watermark(self):
        """Update the chart watermark."""
        self.chart.watermark(f'{self.symbol} - {get_timeframe_display_name(self.current_timeframe)}')
        
    def _update_chart_data(self):
        """Update the chart with current data."""
        bars = list(self.bars_data.get(self.current_timeframe, []))
        if not bars:
            print("⚠️  No data available for chart update")
            return
            
        print(f"📊 Updating chart with {len(bars)} bars, type: {self.chart_type}")
        
        # Convert to DataFrame
        df = pd.DataFrame(bars)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        print(f"📊 DataFrame shape: {df.shape}")
        print(f"📊 DataFrame columns: {df.columns.tolist()}")
        print(f"📊 Sample data:\n{df.head()}")
        
        # Prepare data based on chart type
        try:
            print(f"🔄 Preparing chart data with type: {self.chart_type}")
            if self.chart_type == "ha":
                print("🔄 Calculating Heikin-Ashi from original data...")
                print(f"📊 Original data sample:\n{df[['open', 'high', 'low', 'close']].head()}")
                print(f"📊 Original price range: {df['close'].min():.2f} - {df['close'].max():.2f}")
                
                df_ha = calculate_heikin_ashi(df)
                print(f"📊 HA data sample:\n{df_ha[['ha_open', 'ha_high', 'ha_low', 'ha_close']].head()}")
                print(f"📊 HA price range: {df_ha['ha_close'].min():.2f} - {df_ha['ha_close'].max():.2f}")
                
                chart_data = df_ha[['timestamp', 'ha_open', 'ha_high', 'ha_low', 'ha_close', 'volume']].copy()
                chart_data.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
                # Use ISO strings for maximum compatibility
                chart_data['time'] = pd.to_datetime(chart_data['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
                print("✅ Using Heiken-Ashi data")
                print(f"📊 Chart data shape: {chart_data.shape}")
                print(f"📊 Chart data sample:\n{chart_data.head()}")
                print(f"📊 Final HA price range: {chart_data['close'].min():.2f} - {chart_data['close'].max():.2f}")
                # Set data on main series
                self.chart.set(chart_data)
                
            elif self.chart_type == "ohlc":
                chart_data = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
                chart_data.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
                chart_data['time'] = pd.to_datetime(chart_data['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
                print("✅ Using regular OHLC data")
                print(f"📊 Chart data shape: {chart_data.shape}")
                print(f"📊 Chart data sample:\n{chart_data.head()}")
                self.chart.set(chart_data)
                
            elif self.chart_type == "both":
                # Show both regular and Heiken-Ashi as line charts
                print("✅ Showing both regular and Heiken-Ashi")
                
                # First set regular OHLC as candlesticks
                chart_data = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
                chart_data.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
                chart_data['time'] = pd.to_datetime(chart_data['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
                self.chart.set(chart_data)
                
                # Add Heiken-Ashi as a line overlay
                df_ha = calculate_heikin_ashi(df)
                ha_line_data = pd.DataFrame({
                    'time': pd.to_datetime(df_ha['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'Heiken-Ashi': df_ha['ha_close']
                })
                
                # Create or update the Heiken-Ashi line
                if not hasattr(self, 'ha_line') or self.ha_line is None:
                    self.ha_line = self.chart.create_line('Heiken-Ashi', color='#ff9800', width=2)
                self.ha_line.set(ha_line_data)
                
            # Fit time scale so data is visible
            try:
                self.chart.time_scale(fit_content=True)
            except Exception:
                pass

            print("✅ Chart data updated successfully")
            
        except Exception as e:
            print(f"❌ Error updating chart: {e}")
            import traceback
            traceback.print_exc()
        
        # Update overlays only if chart is initialized
        if self.chart:
            self._update_overlays()
        
    def _update_overlays(self):
        """Update chart overlays."""
        bars = list(self.bars_data.get(self.current_timeframe, []))
        if not bars:
            return
            
        # Only update overlays if chart is properly initialized
        if not self.chart:
            return
            
        df = pd.DataFrame(bars)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Remove ALL existing overlay lines safely
        for line in self.sma_lines.values():
            if line:
                try:
                    line.delete()
                except Exception as e:
                    print(f"Warning: Could not delete SMA line: {e}")
        self.sma_lines.clear()
        
        # Remove Heikin-Ashi line if it exists
        if hasattr(self, 'ha_line') and self.ha_line:
            try:
                self.ha_line.delete()
            except Exception as e:
                print(f"Warning: Could not delete HA line: {e}")
            finally:
                self.ha_line = None
        
        # If overlays is empty, we're done - no need to add new overlays
        if not self.overlays:
            print("✅ All overlays removed")
            return
        
        print(f"🔄 Updating overlays: {self.overlays}")
        
        # Add new overlays
        if 'sma20' in self.overlays:
            sma20 = df['close'].rolling(window=20).mean()
            sma_data = pd.DataFrame({
                'time': df['timestamp'],
                'SMA20': sma20
            }).dropna()
            
            line = self.chart.create_line('SMA20', color='#ff9800', width=1)
            line.set(sma_data)
            self.sma_lines['sma20'] = line
            
        if 'sma50' in self.overlays:
            sma50 = df['close'].rolling(window=50).mean()
            sma_data = pd.DataFrame({
                'time': df['timestamp'],
                'SMA50': sma50
            }).dropna()
            
            line = self.chart.create_line('SMA50', color='#2196f3', width=1)
            line.set(sma_data)
            self.sma_lines['sma50'] = line
            
    def _on_bar_update(self, bar_data: Dict[str, Any]) -> None:
        """Handle new bar data from IBKR."""
        # This will be called by the bar stream when new data arrives
        pass
    
    def _on_timeframe_update(self, bar_data: Dict[str, Any], timeframe: str) -> None:
        """Handle new aggregated bar data."""
        # Add to appropriate timeframe buffer
        if timeframe in self.bars_data:
            self.bars_data[timeframe].append(bar_data)
            
        # Update chart if this is the current timeframe
        if timeframe == self.current_timeframe:
            # Build update payload
            ts = pd.to_datetime(bar_data['timestamp'])
            if self.chart_type == 'ha':
                ha_bar = self._ha_rt.update_from_bar(
                    timestamp=ts,
                    open_price=bar_data['open'],
                    high_price=bar_data['high'],
                    low_price=bar_data['low'],
                    close_price=bar_data['close'],
                )
                update_series = {
                    'time': ha_bar['timestamp'],
                    'open': ha_bar['ha_open'],
                    'high': ha_bar['ha_high'],
                    'low': ha_bar['ha_low'],
                    'close': ha_bar['ha_close'],
                }
            else:
                update_series = {
                    'time': ts,
                    'open': bar_data['open'],
                    'high': bar_data['high'],
                    'low': bar_data['low'],
                    'close': bar_data['close'],
                }
            try:
                # Incremental update for smooth real-time rendering
                self.chart.update(pd.Series(update_series))
            except Exception as e:
                print(f"⚠️  Incremental update failed, falling back to full refresh: {e}")
                self._update_chart_data()
    
    def _reconnect_to_ibkr(self):
        """Reconnect to IBKR with new symbol/timeframe."""
        if self.bar_stream:
            self.bar_stream.stop_streaming()
            
        # Reset RT HA state when timeframe changes
        self._ha_rt.reset()
        self.connect_to_ibkr()
        
    def connect_to_ibkr(self) -> None:
        """Connect to IBKR and start streaming."""
        try:
            print(f"🔌 Attempting to connect to IBKR for {self.symbol}...")
            
            # Use the existing IBKR realtime bar stream
            self.bar_stream = IBKRRealtimeBarStream()
            self.bar_stream.connect()
            
            # Start streaming with aggregation for the current timeframe
            print(f"📡 Starting real-time bars for {self.symbol} → {self.current_timeframe}")
            self.bar_stream.start_streaming(self.symbol, [self.current_timeframe])

            # Register callback AFTER start_streaming initializes timeframe structures
            self.bar_stream.add_timeframe_callback(self.current_timeframe, self._on_timeframe_update)

            # Seed chart with any already aggregated bars (backfill)
            seed_bars = self.bar_stream.get_bars(self.current_timeframe, count=300)
            if seed_bars:
                print(f"🌱 Backfilling chart with {len(seed_bars)} bars")
                self.bars_data[self.current_timeframe].clear()
                for b in seed_bars:
                    self.bars_data[self.current_timeframe].append(b)
                self._ha_rt.reset()
                self._update_chart_data()
            
            self.is_connected = True
            self.chart.topbar['status'].set('Connected')
            print(f"✅ Connected to IBKR and streaming {self.symbol}")
            
        except Exception as e:
            print(f"❌ Failed to connect to IBKR: {e}")
            print("📊 Falling back to sample data for demonstration")
            self.is_connected = False
            self.chart.topbar['status'].set('Demo Mode')
            self._add_sample_data()
    
    
    def _manual_update(self, chart):
        """Manual update button for testing."""
        print("🔄 Manual chart update triggered")
        self._update_chart_data()
    
    def _toggle_auto_refresh(self, chart):
        """Toggle auto-refresh functionality."""
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            print("🔄 Auto-refresh enabled")
            self._start_auto_refresh()
        else:
            print("⏸️  Auto-refresh disabled")
            self._stop_auto_refresh()
    
    def _start_auto_refresh(self):
        """Start auto-refresh timer."""
        if self.refresh_timer:
            self.refresh_timer.cancel()
        
        def refresh_loop():
            while self.auto_refresh:
                try:
                    self._update_chart_data()
                    time.sleep(2)  # Update every 2 seconds
                except Exception as e:
                    print(f"❌ Auto-refresh error: {e}")
                    break
        
        self.refresh_timer = threading.Thread(target=refresh_loop, daemon=True)
        self.refresh_timer.start()
    
    def _stop_auto_refresh(self):
        """Stop auto-refresh timer."""
        self.auto_refresh = False
        if self.refresh_timer:
            self.refresh_timer = None
    
    def disconnect_from_ibkr(self) -> None:
        """Disconnect from IBKR."""
        self.is_connected = False
        
        if hasattr(self, 'bar_stream') and self.bar_stream:
            try:
                self.bar_stream.stop_streaming()
                self.bar_stream.disconnect()
                print("🔌 Disconnected from IBKR")
            except Exception as e:
                print(f"⚠️  Error disconnecting from IBKR: {e}")
        
        self.chart.topbar['status'].set('Disconnected')
    
    def _add_sample_data(self):
        """Add sample data for demonstration when IBKR is not available."""
        print("📊 Adding sample data for demonstration...")
        
        # Create sample OHLC data (use larger ranges so candles are clearly visible)
        base_price = 200.0  # Stock-like base price for visibility (AAPL-like range)
        # Use market hours (9:30 AM - 4:00 PM EST) for more realistic timestamps
        current_time = datetime.now().replace(hour=16, minute=0, second=0, microsecond=0)  # End of market day
        
        sample_bars = []
        for i in range(100):
            # Generate more realistic price movement
            if i == 0:
                # First bar - start with realistic values
                open_price = base_price
                high_price = base_price + 1.0
                low_price = base_price - 0.5
                close_price = base_price + 0.5
            else:
                # Subsequent bars - use previous close as base
                base_price = sample_bars[-1]['close']
                price_change = np.random.normal(0, 0.5)  # More realistic price changes
                open_price = base_price
                close_price = base_price + price_change
                high_price = max(open_price, close_price) + abs(np.random.normal(0, 0.3))
                low_price = min(open_price, close_price) - abs(np.random.normal(0, 0.3))
            
            # Debug: print first few bars to see values
            if i < 5:
                print(f"Sample bar {i}: O={open_price:.2f}, H={high_price:.2f}, L={low_price:.2f}, C={close_price:.2f}")
            
            bar_data = {
                'timestamp': current_time - timedelta(minutes=100-i),
                'symbol': self.symbol,
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': np.random.randint(10000, 50000)
            }
            
            sample_bars.append(bar_data)
            base_price = close_price
        
        # Add to buffer
        for bar in sample_bars:
            self.bars_data[self.current_timeframe].append(bar)
        
        print(f"✅ Added {len(sample_bars)} sample bars to {self.current_timeframe}")
        
        # Update chart
        self._update_chart_data()
        self.chart.topbar['status'].set('Demo Mode')
        print("✅ Sample data loaded - Chart should now be visible!")
    
    def run(self) -> None:
        """Run the chart application."""
        print(f"🚀 Starting real-time Heiken-Ashi chart for {self.symbol}")
        print(f"📊 Initial timeframe: {self.current_timeframe}")
        print(f"📈 Chart type: {'Heiken-Ashi' if self.chart_type == 'ha' else 'Candlestick'}")
        print("=" * 60)
        
        # Create the chart
        self._create_chart()
        
        # Add sample data immediately so chart isn't blank
        print("📊 Adding initial sample data...")
        self._add_sample_data()
        
        # Connect to IBKR in a separate thread
        def connect_thread():
            time.sleep(2)  # Wait for chart to initialize
            try:
                self.connect_to_ibkr()
            except Exception as e:
                print(f"❌ Connection error: {e}")
                print("📊 Continuing with sample data...")
        
        threading.Thread(target=connect_thread, daemon=True).start()
        
        # Show the chart (this blocks until closed)
        try:
            self.chart.show(block=True)
        except KeyboardInterrupt:
            print("\n👋 Chart stopped by user")
        finally:
            self.disconnect_from_ibkr()


def launch_lightweight_chart(symbol: str = "EURUSD", timeframe: str = "1m"):
    """
    Launch the real-time chart using lightweight-charts-python.
    
    Args:
        symbol: Symbol to chart
        timeframe: Initial timeframe
    """
    app = LightweightRealtimeChart(symbol=symbol, initial_timeframe=timeframe)
    app.run()


if __name__ == "__main__":
    # For direct execution
    launch_lightweight_chart()
