"""
Live EURUSD Data Visualization with Interactive Brokers and Lightweight Charts

This script:
1. Connects to Interactive Brokers and receives real-time 5-second bars for EURUSD
2. Aggregates 5-second bars into 1-minute candles
3. Displays live data in a real-time chart using lightweight-charts-python
4. Shows both 5-second bars (green line) and 1-minute candles (red line)

Requirements:
- ib_async package for Interactive Brokers connection
- lightweight-charts package for charting (auto-installed if missing)
- pandas for data manipulation
"""

import pandas as pd
from ib_async import *
from lightweight_charts import Chart
import threading
import time
from src.utils.heikin_ashi import HeikinAshiCalculator

#--------------------------------
def onBarUpdate(bars, hasNewBar):
    """
    This function is called for every new 5-second bar and builds the 1-minute datapoints.
    """
    global current_bar, completed_datapoints
    
    if not hasNewBar:
        return  # Only process when a full 5-second bar has arrived

    five_sec_bar = bars[-1]
    # Standardize the timestamp to the start of the minute for easy comparison
    current_minute = five_sec_bar.time.replace(second=0, microsecond=0)

    # If this is the very first 5-sec bar, start building our first 1-min bar
    if current_bar['timestamp'] is None:
        current_bar['timestamp'] = current_minute
        current_bar['O'] = five_sec_bar.open_
        current_bar['H'] = five_sec_bar.high
        current_bar['L'] = five_sec_bar.low
        print(f"-> Starting new 1-min datapoint at {current_bar['timestamp']}")

    # If the 5-sec bar belongs to the current minute, update the H, L, and C
    if current_minute == current_bar['timestamp']:
        current_bar['H'] = max(current_bar['H'], five_sec_bar.high)
        current_bar['L'] = min(current_bar['L'], five_sec_bar.low)
        current_bar['C'] = five_sec_bar.close
    else:
        # A new minute has started, so the previous 1-min bar is now complete.
        
        # 1. ✅ Store the completed datapoint
        completed_datapoints.append(current_bar.copy())
        
        # 2. Print the final data point clearly
        print("*"*25, " NEW DATAPOINT ", "*"*25)
        print(f"Completed: {completed_datapoints[-1]}")
        print("*"*67, "\n")

        # 3. Start the next 1-minute bar
        current_bar['timestamp'] = current_minute
        current_bar['O'] = five_sec_bar.open_
        current_bar['H'] = five_sec_bar.high
        current_bar['L'] = five_sec_bar.low
        current_bar['C'] = five_sec_bar.close
        print(f"-> Starting new 1-min datapoint at {current_bar['timestamp']}")


# This is necessary for running in environments like Jupyter notebooks
util.startLoop()

ib = IB()
ib.disconnect()
#ib.disconnect()
ib.connect('127.0.0.1', 7497, clientId=99)
# Define the contract
#contract = Forex('EURUSD')
symbol = 'USDJPY'
contract = Forex('USDJPY')

symbol = 'AAPL'
contract = Stock('AAPL', 'SMART', 'USD')
ib.isConnected()
ib.reqMarketDataType(1)
contract = Stock(
    symbol=symbol, 
    exchange="SMART", 
    primaryExchange='NASDAQ', 
    currency='USD')

realtime_bars = ib.reqRealTimeBars(
            contract,
            barSize=5,
            #whatToShow='TRADES',
            whatToShow='MIDPOINT',
            useRTH=False,
            realTimeBarsOptions=[],
            
)

realtime_bars.updateEvent += onBarUpdate
ib.run()


realtime_bars = ib.reqRealTimeBars(contract, 5, 'MIDPOINT', False)

# This DataFrame will store all data points for the chart
chart_data = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

# Initialize Heikin-Ashi calculator for real-time conversion
ha_calculator = HeikinAshiCalculator()

# Fixed-size DataFrames for efficient data storage (100,000 rows each)
MAX_BARS = 100000
regular_data = pd.DataFrame(
    index=range(MAX_BARS), 
    columns=['time', 'open', 'high', 'low', 'close', 'volume'])
ha_data = pd.DataFrame(
    index=range(MAX_BARS), 
    columns=['time', 'open', 'high', 'low', 'close', 'volume'])

# Pointers to track current position in each DataFrame
regular_pointer = 0
ha_pointer = 0

# Chart display mode: 'regular' or 'heikin_ashi'
chart_mode = 'regular'

# No need for 1-minute bar building since we're showing 5-second bars

# Initialize the chart
chart = Chart()
chart.legend(visible=True)
chart.watermark(f'{symbol} Live Data', color='rgba(180, 180, 240, 0.7)')
chart.crosshair(mode='normal', vert_color='#FFFFFF', vert_style='dotted',
                horz_color='#FFFFFF', horz_style='dotted')

# Add TradingView-style chart type selector
def on_switcher_change(option):
    """Handle switcher change events."""
    print(f"🔄 Switcher changed to: {option}")
    if option == 'Heikin-Ashi':
        toggle_chart_mode('heikin_ashi')
    else:
        toggle_chart_mode('regular')

try:
    # Try to add a switcher widget
    chart.topbar.switcher(
        'candle_type',
        options=['Regular', 'Heikin-Ashi'],
        default='Regular',
        func=on_switcher_change
    )
    print("✅ Chart controls added to topbar")
except Exception as e:
    print(f"⚠️  Topbar controls not available: {e}")
    print("Using console-based controls instead")
    
    # Fallback: Add text display
    try:
        chart.topbar.textbox('mode_display', 'Mode: Regular')
        print("✅ Added mode display textbox")
    except Exception as e2:
        print(f"⚠️  Textbox also not available: {e2}")

# Add keyboard shortcuts for toggling
print("\n=== Chart Controls ===")
print("To toggle chart type:")
print("  - Type 'r' in console for Regular candles")
print("  - Type 'h' in console for Heikin-Ashi candles")
print("  - Type 't' to test toggle functionality")
print("  - Or use the topbar switcher if available")
print("=====================\n")

# Test function for debugging
def test_toggle():
    """Test function to verify toggle works."""
    print("🧪 Testing toggle functionality...")
    current_mode = chart_mode
    new_mode = 'heikin_ashi' if current_mode == 'regular' else 'regular'
    print(f"Current mode: {current_mode}, switching to: {new_mode}")
    print(f"Regular pointer: {regular_pointer}, HA pointer: {ha_pointer}")
    toggle_chart_mode(new_mode)
    print(f"✅ Toggle test complete. New mode: {chart_mode}")

# Chart update lock for thread safety
chart_lock = threading.Lock()

def update_chart():
    """
    Updates the chart with the current DataFrame data.
    """
    global chart_data, chart, chart_lock
    
    with chart_lock:
        if not chart_data.empty:
            chart.set(chart_data)

def toggle_chart_mode(new_mode):
    """
    Toggle between regular and Heikin-Ashi candles.
    """
    global chart_mode, chart_data, regular_data, ha_data, regular_pointer, ha_pointer
    
    chart_mode = new_mode
    
    # Update chart_data based on new mode (get valid data up to current pointer)
    if chart_mode == 'regular':
        if regular_pointer == 0:
            chart_data = regular_data.iloc[:1].copy()  # Handle empty case
        else:
            chart_data = regular_data.iloc[:regular_pointer].copy()
        print(f"🔄 Switched to REGULAR candles ({regular_pointer} bars)")
        # Update textbox if it exists
        try:
            chart.topbar.textbox('mode_display', 'Mode: Regular')
        except:
            pass
    else:
        if ha_pointer == 0:
            chart_data = ha_data.iloc[:1].copy()  # Handle empty case
        else:
            chart_data = ha_data.iloc[:ha_pointer].copy()
        print(f"🔄 Switched to HEIKIN-ASHI candles ({ha_pointer} bars)")
        # Update textbox if it exists
        try:
            chart.topbar.textbox('mode_display', 'Mode: Heikin-Ashi')
        except:
            pass
    
    # Update chart
    update_chart()

def onBarUpdate(bars, hasNewBar):
    """
    Adds each 5-second bar to both regular and Heikin-Ashi DataFrames using fixed-size arrays.
    """
    global chart_data, regular_data, ha_data, chart_mode, regular_pointer, ha_pointer
    
    if not hasNewBar or len(bars) < 1:
        return

    latest_bar = bars[-1]
    
    from datetime import datetime, timezone
    print(f"  -- 5s bar: {latest_bar.time} | O: {latest_bar.open_} | H: {latest_bar.high} | L: {latest_bar.low} | C: {latest_bar.close}")
    print(f"   [UTC now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}]")

    # Store regular candle at current pointer position
    regular_data.iloc[regular_pointer] = {
        'time': pd.to_datetime(latest_bar.time),
        'open': latest_bar.open_,
        'high': latest_bar.high,
        'low': latest_bar.low,
        'close': latest_bar.close,
        'volume': latest_bar.volume if hasattr(latest_bar, 'volume') else 0
    }
    regular_pointer = (regular_pointer + 1) % MAX_BARS
    
    # Calculate Heikin-Ashi candle
    ha_bar = ha_calculator.update_from_bar(
        timestamp=latest_bar.time,
        open_price=latest_bar.open_,
        high_price=latest_bar.high,
        low_price=latest_bar.low,
        close_price=latest_bar.close
    )
    
    # Store HA candle at current pointer position
    ha_data.iloc[ha_pointer] = {
        'time': pd.to_datetime(ha_bar['timestamp']),
        'open': ha_bar['ha_open'],
        'high': ha_bar['ha_high'],
        'low': ha_bar['ha_low'],
        'close': ha_bar['ha_close'],
        'volume': latest_bar.volume if hasattr(latest_bar, 'volume') else 0
    }
    ha_pointer = (ha_pointer + 1) % MAX_BARS
    
    # Update chart_data based on current mode (get valid data up to current pointer)
    if chart_mode == 'regular':
        if regular_pointer == 0:
            chart_data = regular_data.iloc[:1].copy()  # Handle empty case
        else:
            chart_data = regular_data.iloc[:regular_pointer].copy()
    else:
        if ha_pointer == 0:
            chart_data = ha_data.iloc[:1].copy()  # Handle empty case
        else:
            chart_data = ha_data.iloc[:ha_pointer].copy()
    
    # Add trend indicator for HA mode
    if chart_mode == 'heikin_ashi':
        trend = "🟢 Bullish" if ha_bar['ha_close'] > ha_bar['ha_open'] else "🔴 Bearish"
        print(f"   HA Trend: {trend}")
    
    print(f"Added bar to chart. Mode: {chart_mode}, Regular bars: {regular_pointer}, HA bars: {ha_pointer}")
    
    # Update chart in a separate thread to avoid blocking
    threading.Thread(target=update_chart, daemon=True).start()

# Request the 5-second bars
realtime_bars = ib.reqRealTimeBars(contract, 5, 'MIDPOINT', False)
realtime_bars.updateEvent += onBarUpdate

print("Building live 5-second bars... Press Ctrl+C to stop.")
print("Chart will open in a separate window showing live data...")

# Show the chart in a non-blocking way
chart.show()

# Add console input handler for keyboard shortcuts
def handle_console_input():
    """Handle console input for chart controls."""
    while True:
        try:
            user_input = input().strip().lower()
            if user_input == 'r':
                toggle_chart_mode('regular')
            elif user_input == 'h':
                toggle_chart_mode('heikin_ashi')
            elif user_input == 't':
                test_toggle()
            elif user_input == 'q':
                print("Exiting...")
                break
            else:
                print("Commands: 'r' = Regular, 'h' = Heikin-Ashi, 't' = Test, 'q' = Quit")
        except EOFError:
            break
        except KeyboardInterrupt:
            break

# Start console input handler in a separate thread
console_thread = threading.Thread(target=handle_console_input, daemon=True)
console_thread.start()

try:
    ib.run()
except (KeyboardInterrupt, SystemExit):
    print("\nScript stopped by user.")
finally:
    # Print a final summary when the script is stopped
    print("\n--- Final Chart Data ---")
    if not chart_data.empty:
        print(f"Total bars collected: {len(chart_data)}")
        print(f"Regular bars: {regular_pointer}")
        print(f"Heikin-Ashi bars: {ha_pointer}")
        print(f"Current mode: {chart_mode}")
        print(f"DataFrame size: {MAX_BARS} (fixed-size arrays)")
        print(chart_data.tail())
    else:
        print("No data was collected.")
        ib.disconnect()