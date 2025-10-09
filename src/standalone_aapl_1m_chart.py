"""
Standalone AAPL 1-minute real-time chart + printer using:
  - ib_insync (IBKR real-time bars @ 5s)
  - lightweight-charts (direct library API)

This file is self-contained and does not depend on the project wrappers.

Run:
  conda activate env-trading
  IBKR_HOST=127.0.0.1 IBKR_PORT=7497 IBKR_CLIENT_ID=110 python -m src.standalone_aapl_1m_chart

You can change symbol/timeframe by editing symbol/timeframe variables below.
"""

from __future__ import annotations

import signal
import sys
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Any, Optional

import pandas as pd
from ib_insync import IB, Stock
from lightweight_charts import Chart


# -------------------------- Config -------------------------- #
SYMBOL = 'AAPL'
HOST = '127.0.0.1'
PORT = 7497  # Paper: 7497, Live: 7496
CLIENT_ID = 110  # Adjust if needed to avoid collisions with other apps

TIMEFRAME = '1m'  # Only 1m here; aggregation from 5s IBKR bars
MAX_ROWS = 1000


# --------------------- Helper aggregation ------------------- #
def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


class MinuteAggregator:
    """Aggregate 5-second real-time bars into 1-minute OHLCV."""

    def __init__(self) -> None:
        self.current_start: Optional[datetime] = None
        self.o: Optional[float] = None
        self.h: Optional[float] = None
        self.l: Optional[float] = None
        self.c: Optional[float] = None
        self.v: int = 0

    def add_rtb(self, ts: datetime, open_: float, high: float, low: float, close: float, volume: int) -> Optional[Dict[str, Any]]:
        bucket = minute_floor(ts)
        if self.current_start is None:
            self.current_start = bucket
            self.o = open_
            self.h = high
            self.l = low
            self.c = close
            self.v = volume
            return None

        if bucket == self.current_start:
            # same minute, update running OHLCV
            if self.o is None:
                self.o = open_
            self.h = high if self.h is None else max(self.h, high)
            self.l = low if self.l is None else min(self.l, low)
            self.c = close
            self.v += volume
            return None

        # minute rolled over → finalize previous bar
        finalized = {
            'date': self.current_start,
            'open': float(self.o),
            'high': float(self.h),
            'low': float(self.l),
            'close': float(self.c),
            'volume': int(self.v),
        }

        # start new bucket with current tick
        self.current_start = bucket
        self.o = open_
        self.h = high
        self.l = low
        self.c = close
        self.v = volume

        return finalized


# ------------------------ Main routine ---------------------- #
def main() -> None:
    # Chart (use library directly)
    chart = Chart(toolbox=True, width=1200, height=700)
    chart.legend(True)
    chart.layout(background_color='#131722', text_color='#d1d4dc', font_size=12)
    chart.candle_style(
        up_color='#26a69a', down_color='#ef5350',
        border_up_color='#26a69a', border_down_color='#ef5350',
        wick_up_color='#26a69a', wick_down_color='#ef5350',
    )
    chart.time_scale(visible=True, time_visible=True, seconds_visible=False)
    chart.watermark(f'{SYMBOL} - 1 Minute')

    df: pd.DataFrame = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    buffer: Deque[Dict[str, Any]] = deque(maxlen=MAX_ROWS)
    agg = MinuteAggregator()

    # IBKR connect
    ib = IB()
    try:
        print(f'🔌 Connecting to IBKR {HOST}:{PORT} clientId={CLIENT_ID} ...')
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=30)
        print('✅ Connected:', ib.isConnected())
    except Exception as e:
        print('❌ Connect failed:', e)
        return

    contract = Stock(SYMBOL, 'SMART', 'USD')

    # Subscribe to 5s real-time bars
    req_id = ib.reqRealTimeBars(contract, barSize=5, whatToShow='TRADES', useRTH=False, realTimeBarsOptions=[])
    print(f'📡 Subscribed to real-time bars reqId={req_id}')

    def on_rtb(reqId: int, time_: int, o: float, h: float, l: float, c: float, v: int, wap: float, count: int):
        if reqId != req_id:
            return
        ts = datetime.fromtimestamp(time_)
        out = agg.add_rtb(ts, o, h, l, c, v)
        if out is None:
            return

        # finalized 1m bar
        buffer.append(out)
        # Update DF, keep last MAX_ROWS
        nonlocal df
        df = pd.DataFrame(list(buffer), columns=['date', 'open', 'high', 'low', 'close', 'volume'])

        # Print to console
        print(f"{out['date']} O:{out['open']} H:{out['high']} L:{out['low']} C:{out['close']} V:{out['volume']}")

        # Update chart
        try:
            if len(df) == 1:
                chart.set(df)
            else:
                chart.update(df.iloc[-1])
            try:
                chart.time_scale(fit_content=True)
            except Exception:
                pass
        except Exception as e:
            # fallback to full set if incremental fails
            try:
                chart.set(df)
            except Exception:
                print('⚠️ Chart update failed:', e)

    ib.realTimeBarUpdateEvent += on_rtb

    # graceful exit
    stop = {'flag': False}

    def _sigint(*_):
        stop['flag'] = True

    signal.signal(signal.SIGINT, _sigint)

    # Show chart (non-blocking) and run loop
    chart.show()  # non-blocking call
    print('✅ Listening for 1-minute bars. Press Ctrl+C to stop.')
    try:
        while not stop['flag']:
            ib.sleep(0.2)  # let ib_insync process events
    finally:
        try:
            ib.cancelRealTimeBars(req_id)
        except Exception:
            pass
        ib.disconnect()
        print('🔌 Disconnected')


if __name__ == '__main__':
    main()


