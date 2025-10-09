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
try:
    from lightweight_charts import Chart
except ImportError:
    print("Installing lightweight-charts package...")
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "lightweight-charts"])
    from lightweight_charts import Chart
import threading
import time

# This is necessary for running in environments like Jupyter notebooks
util.startLoop()

ib = IB()
#ib.disconnect()
ib.connect('127.0.0.1', 7497, clientId=9)

# Define the contract
#contract = Forex('EURUSD')
symbol = 'USDJPY'
contract = Forex('USDJPY')

# This DataFrame will store all data points for the chart
chart_data = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

# No need for 1-minute bar building since we're showing 5-second bars

# Initialize the chart
chart = Chart()
chart.legend(visible=True)
chart.watermark(f'{symbol} Live Data', color='rgba(180, 180, 240, 0.7)')
chart.crosshair(mode='normal', vert_color='#FFFFFF', vert_style='dotted',
                horz_color='#FFFFFF', horz_style='dotted')

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

def onBarUpdate(bars, hasNewBar):
    """
    Adds each 5-second bar to the chart DataFrame.
    """
    global chart_data
    
    if not hasNewBar or len(bars) < 1:
        return

    latest_bar = bars[-1]
    
    from datetime import datetime, timezone
    print(f"  -- 5s bar: {latest_bar.time} | O: {latest_bar.open_} | H: {latest_bar.high} | L: {latest_bar.low} | C: {latest_bar.close}")
    print(f"   [UTC now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}]")

    # Add the 5-second bar to the chart DataFrame
    new_row = pd.DataFrame({
        'time': [pd.to_datetime(latest_bar.time)],
        'open': [latest_bar.open_],
        'high': [latest_bar.high],
        'low': [latest_bar.low],
        'close': [latest_bar.close],
        'volume': [latest_bar.volume if hasattr(latest_bar, 'volume') else 0]
    })
    chart_data = pd.concat([chart_data, new_row], ignore_index=True)
    
    print(f"Added 5s bar to chart. Total bars: {len(chart_data)}")
    
    # Update chart in a separate thread to avoid blocking
    threading.Thread(target=update_chart, daemon=True).start()

# Request the 5-second bars
realtime_bars = ib.reqRealTimeBars(contract, 5, 'MIDPOINT', False)
realtime_bars.updateEvent += onBarUpdate

print("Building live 5-second bars... Press Ctrl+C to stop.")
print("Chart will open in a separate window showing live data...")

# Show the chart in a non-blocking way
chart.show()

try:
    ib.run()
except (KeyboardInterrupt, SystemExit):
    print("\nScript stopped by user.")
finally:
    # Print a final summary when the script is stopped
    print("\n--- Final Chart Data ---")
    if not chart_data.empty:
        print(f"Total bars collected: {len(chart_data)}")
        print(chart_data.tail())
    else:
        print("No data was collected.")
    ib.disconnect()