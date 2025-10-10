"""
Stream real-time 5-second AAPL bars from Interactive Brokers and print them.

Run this script while TWS or IB Gateway is up:
    python test301.py
"""

from __future__ import annotations

import signal
from datetime import datetime, timezone
from typing import Optional, Union

from ib_async import IB, util
from ib_async.contract import Stock


def _as_utc(ts: Union[int, float, datetime]) -> datetime:
    """Normalize IB timestamp values to timezone-aware UTC datetimes."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


class RealTimeBarStreamer:
    """Encapsulate IBKR real-time bar streaming for a single stock symbol."""

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 99,
        symbol: str = 'AAPL',
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.symbol = symbol.upper()
        self.ib = IB()
        self.ib.disconnect()
        self.subscription: Optional[object] = None
        self._stopping = False
        self._cleanup_done = False

    def start(self) -> None:
        """Connect to IBKR and start streaming bars."""
        print(f'Connecting to IBKR at {self.host}:{self.port} (clientId={self.client_id}) ...')
        self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)
        if not self.ib.isConnected():
            raise RuntimeError('Could not connect to IBKR')
        print('Connected.')

        self.ib.reqMarketDataType(1)  # Request real-time data (if permissions allow)

        contract = Stock(self.symbol, 'SMART', 'USD')
        contract.primaryExchange = 'NASDAQ'

        print('Subscribing to 5-second real-time bars ...')
        self.subscription = self.ib.reqRealTimeBars(
            contract,
            barSize=5,
            whatToShow='TRADES',
            useRTH=False,
            realTimeBarsOptions=[],
        )
        self.subscription.updateEvent += self._on_bar_update
        self.ib.errorEvent += self._on_error

    def run(self) -> None:
        """Run the update loop until stop() is called."""
        print(f'Streaming {self.symbol} bars. Press Ctrl+C to stop.')
        try:
            while not self._stopping:
                self.ib.waitOnUpdate(timeout=1)
        finally:
            self.stop()

    def stop(self) -> None:
        """Unsubscribe from bars and disconnect."""
        if self._cleanup_done:
            return
        self._stopping = True

        try:
            if self.subscription is not None:
                try:
                    self.subscription.updateEvent -= self._on_bar_update
                except Exception:
                    pass
                try:
                    self.ib.cancelRealTimeBars(self.subscription)
                except Exception:
                    pass
        finally:
            try:
                self.ib.errorEvent -= self._on_error
            except Exception:
                pass
            if self.ib.isConnected():
                self.ib.disconnect()
            print('Disconnected.')
            self._cleanup_done = True

    def request_stop(self) -> None:
        """Signal the run loop to exit."""
        self._stopping = True

    def _on_bar_update(self, bars, has_new_bar) -> None:
        if not has_new_bar or not bars:
            return
        latest = bars[-1]
        stamp = _as_utc(latest.time)
        volume = int(getattr(latest, 'volume', 0) or 0)
        print(
            f'{stamp.isoformat()} '
            f'O:{latest.open_:.2f} H:{latest.high:.2f} '
            f'L:{latest.low:.2f} C:{latest.close:.2f} V:{volume}',
            flush=True,
        )

    @staticmethod
    def _on_error(req_id, code, msg, *_):
        print(f'IB error {code} (reqId={req_id}): {msg}')


def main() -> None:
    util.startLoop()
    streamer = RealTimeBarStreamer()

    def _handle_signal(*_):
        streamer.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)

    streamer.start()
    streamer.run()


#if __name__ == '__main__':
main()



#===============
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



#==============================================
# New
from IPython.display import display, clear_output
import matplotlib.pyplot as plt
import pandas as pd
from ib_async import *
from lightweight_charts import Chart
import threading
import time
from src.utils.heikin_ashi import HeikinAshiCalculator

util.startLoop()

ib = IB()
ib.disconnect()

ib.connect('127.0.0.1', 7497, clientId=99)

contract = Forex("EURUSD")
contract = Stock("AAPL", "SMART", "USD")
contract = Stock("AAPL", "SMART", "USD", primaryExchange="NASDAQ")

bars = ib.reqHistoricalData(
    contract,
    endDateTime="",
    durationStr="900 S",
    barSizeSetting="10 secs",
    whatToShow="MIDPOINT",
    useRTH=False,
    formatDate=1,
    keepUpToDate=True,
)

def onBarUpdate(bars, hasNewBar):
    plt.close()
    plot = util.barplot(bars)
    clear_output(wait=True)
    display(plot)




bars.updateEvent += onBarUpdate

ib.sleep(10)
ib.cancelHistoricalData(bars)


def onBarUpdate(bars, hasNewBar):
    print(bars[-1])

bars = ib.reqRealTimeBars(contract, 5, "MIDPOINT", False)
bars.updateEvent += onBarUpdate
ib.sleep(30)
ib.cancelRealTimeBars(bars)
ib.disconnect()