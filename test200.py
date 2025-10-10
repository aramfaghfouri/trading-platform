from ib_async import IB 
from ib_async.contract import Stock
ib = IB()
ib.connect("127.0.0.1", 7497, clientId=100)
contract = Stock("AAPL", "SMART", "USD")
bars = ib.reqHistoricalData(
    contract, 
    endDateTime="",
    durationStr="1 D",
    barSizeSetting="1 min",
    whatToShow="TRADES",   
    useRTH=True
)
# Print all of the bars for bar in bars[-15:]:
for bar in bars[-15:]:
    print(
        f" {bar.date} "
        f"O={bar. open}"
        f"H={bar. high}"
        f"L={bar. low}"
        f"C={bar. close}"
        f"V={int(bar.volume)}"
        )

ib.disconnect()


#==============================================
import pandas as pd
from ib_async import *

from datetime import datetime

# This is necessary for running in environments like Jupyter notebooks
util.startLoop()

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=4)

# Define the contract
# Use a liquid contract like EURUSD for good results
contract = Forex('EURUSD')

# 1. Fetch historical data to start
# Get 1-minute bars for the last trading day to have a starting point
hist_bars = ib.reqHistoricalData(
    contract,
    endDateTime='',
    durationStr='1 D',
    barSizeSetting='1 min',
    whatToShow='MIDPOINT',
    useRTH=True,
    formatDate=1)

# Convert to a pandas DataFrame for easier manipulation
df = util.df(hist_bars)
print(f"Initial historical data received. Last bar:\n{df.iloc[-1]}")

# This will be our custom, live-updating 1-minute bar
current_bar = {
    'time': None,
    'open': None,
    'high': None,
    'low': None,
    'close': None
}

# 2. Resample 5-second bars into 1-minute bars
def onBarUpdate(bars, hasNewBar):
    global current_bar
    if not hasNewBar:
        return # Only process when a full 5-second bar has arrived

    five_sec_bar = bars[-1]
    five_sec_time = five_sec_bar.time.replace(second=0, microsecond=0)

    if current_bar['time'] is None:
        # This is the first 5-sec bar, start our 1-min bar
        current_bar['time'] = five_sec_time
        current_bar['open'] = five_sec_bar.open_
        current_bar['high'] = five_sec_bar.high
        current_bar['low'] = five_sec_bar.low
        print(f"Starting new 1-min bar at {current_bar['time']}")

    if five_sec_time == current_bar['time']:
        # This 5-sec bar belongs to the current 1-min bar, so update it
        current_bar['high'] = max(current_bar['high'], five_sec_bar.high)
        current_bar['low'] = min(current_bar['low'], five_sec_bar.low)
        current_bar['close'] = five_sec_bar.close
        print(f"Updating 1-min bar: H:{current_bar['high']}, L:{current_bar['low']}, C:{current_bar['close']}")
    else:
        # A new minute has started. The previous 1-min bar is now complete.
        print(f"**COMPLETED 1-MIN BAR**: Time: {current_bar['time']}, O:{current_bar['open']}, H:{current_bar['high']}, L:{current_bar['low']}, C:{current_bar['close']}\n")
        
        # Start the next 1-min bar
        current_bar['time'] = five_sec_time
        current_bar['open'] = five_sec_bar.open_
        current_bar['high'] = five_sec_bar.high
        current_bar['low'] = five_sec_bar.low
        current_bar['close'] = five_sec_bar.close
        print(f"Starting new 1-min bar at {current_bar['time']}")


# Request the 5-second bars
realtime_bars = ib.reqRealTimeBars(contract, 5, 'MIDPOINT', False)
realtime_bars.updateEvent += onBarUpdate

print("Building 1-minute bars from 5-second stream... Press Ctrl+C to stop.")
ib.run()
ib.disconnect()




#==============================================
from ib_async import *
import pandas as pd

# This is necessary for running in environments like Jupyter notebooks
util.startLoop()

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=7)

# Define the contract
contract = Forex('EURUSD')

# This list will store our final 1-minute datapoints
completed_datapoints = []

# This dictionary will build the current 1-minute bar in real-time
current_bar = {
    'bar_start_time': None,
    'exact_timestamp': None,
    'O': None,
    'H': None,
    'L': None,
    'C': None
}

def onBarUpdate(bars, hasNewBar):
    """
    Builds 1-minute datapoints and shows the underlying 5-second bars.
    """
    global current_bar, completed_datapoints
    
    if not hasNewBar or len(bars) < 2:
        return

    latest_bar = bars[-1]
    
    # <-- THIS IS THE NEW LINE
    print(f"  -- 5s bar: {latest_bar.time} | C: {latest_bar.close}")

    current_minute_start = latest_bar.time.replace(second=0, microsecond=0)

    # Initialize the very first bar
    if current_bar['bar_start_time'] is None:
        current_bar['bar_start_time'] = current_minute_start
        current_bar['O'] = latest_bar.open_
        current_bar['H'] = latest_bar.high
        current_bar['L'] = latest_bar.low
        print(f"-> Starting new 1-min datapoint for {current_bar['bar_start_time']}")

    # If the latest 5-sec bar belongs to the current minute, update H, L, C
    if current_minute_start == current_bar['bar_start_time']:
        current_bar['H'] = max(current_bar['H'], latest_bar.high)
        current_bar['L'] = min(current_bar['L'], latest_bar.low)
        current_bar['C'] = latest_bar.close
    else:
        # A new minute has started. The previous 1-min bar is now complete.
        last_bar_of_minute = bars[-2]
        current_bar['exact_timestamp'] = last_bar_of_minute.time
        
        completed_datapoints.append(current_bar.copy())
        
        print("*"*25, " NEW DATAPOINT ", "*"*25)
        print(f"Completed: {completed_datapoints[-1]}")
        print("*"*67, "\n")

        # Start the next 1-minute bar
        current_bar['bar_start_time'] = current_minute_start
        current_bar['O'] = latest_bar.open_
        current_bar['H'] = latest_bar.high
        current_bar['L'] = latest_bar.low
        current_bar['C'] = latest_bar.close
        current_bar['exact_timestamp'] = None
        print(f"-> Starting new 1-min datapoint for {current_bar['bar_start_time']}")

# Request the 5-second bars
realtime_bars = ib.reqRealTimeBars(contract, 5, 'MIDPOINT', False)
realtime_bars.updateEvent += onBarUpdate

print("Building live 1-minute datapoints... Press Ctrl+C to stop.")

try:
    ib.run()
except (KeyboardInterrupt, SystemExit):
    print("\nScript stopped by user.")
finally:
    # Print a final summary when the script is stopped
    print("\n--- All Completed 1-Minute Datapoints ---")
    if completed_datapoints:
        df = pd.DataFrame(completed_datapoints)
        print(df)
    else:
        print("No new 1-minute bars were completed.")
    ib.disconnect()