"""
Print AAPL 1-minute real-time bars from IBKR (no chart).

Run:
  conda activate env-trading
  IBKR_HOST=127.0.0.1 IBKR_PORT=7497 IBKR_CLIENT_ID=120 python -m src.print_aapl_1m
"""

from __future__ import annotations

import signal
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from ib_async import IB, Stock


def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


class MinuteAgg:
    def __init__(self) -> None:
        self.bucket: Optional[datetime] = None
        self.o: Optional[float] = None
        self.h: Optional[float] = None
        self.l: Optional[float] = None
        self.c: Optional[float] = None
        self.v: int = 0

    def add(self, ts: datetime, o: float, h: float, l: float, c: float, v: int) -> Optional[Dict[str, Any]]:
        b = minute_floor(ts)
        if self.bucket is None:
            self.bucket, self.o, self.h, self.l, self.c, self.v = b, o, h, l, c, v
            return None
        if b == self.bucket:
            self.h = max(self.h, h) if self.h is not None else h
            self.l = min(self.l, l) if self.l is not None else l
            self.c = c
            self.v += v
            return None
        out = {
            'date': self.bucket,
            'open': float(self.o),
            'high': float(self.h),
            'low': float(self.l),
            'close': float(self.c),
            'volume': int(self.v),
        }
        self.bucket, self.o, self.h, self.l, self.c, self.v = b, o, h, l, c, v
        return out


def main() -> None:
    host = os.getenv('IBKR_HOST', '127.0.0.1')
    port = int(os.getenv('IBKR_PORT', '7497'))
    client_id = int(os.getenv('IBKR_CLIENT_ID', '120'))
    symbol = os.getenv('IBKR_SYMBOL', 'AAPL').upper()

    ib = IB()
    print(f'🔌 Connecting to IBKR {host}:{port} clientId={client_id} ...')
    ib.connect(host, port, clientId=client_id, timeout=30)
    print('✅ Connected:', ib.isConnected())

    market_data_type = int(os.getenv('IBKR_MARKET_DATA_TYPE', '1'))
    ib.reqMarketDataType(market_data_type)
    type_label = {1: 'real-time', 2: 'frozen', 3: 'delayed', 4: 'delayed-frozen'}.get(market_data_type, str(market_data_type))
    print(f'🛈 Market data type set to {type_label}')

    primary = os.getenv('IBKR_PRIMARY_EXCHANGE', 'NASDAQ')
    contract = Stock(symbol, 'SMART', 'USD')
    contract.primaryExchange = primary
    subscription = ib.reqRealTimeBars(
        contract,
        barSize=5,
        whatToShow='TRADES',
        useRTH=bool(os.getenv('IBKR_RTH_ONLY', 'false').lower() in {'1', 'true', 'yes'}),
        realTimeBarsOptions=[],
    )
    print('📡 Subscribed to 5s bars (aggregating to 1m)')

    agg = MinuteAgg()
    stop = {'flag': False}

    def on_rtb(b):
        ts = b.time if isinstance(b.time, datetime) else datetime.fromtimestamp(b.time, tz=timezone.utc)
        bar = agg.add(ts, b.open, b.high, b.low, b.close, int(b.volume))
        if bar is None:
            return
        stamp = bar['date'] if isinstance(bar['date'], datetime) else datetime.fromisoformat(str(bar['date']))
        print(
            f"{stamp.isoformat()} O:{bar['open']:.2f} H:{bar['high']:.2f} "
            f"L:{bar['low']:.2f} C:{bar['close']:.2f} V:{bar['volume']}"
        )

    subscription.updateEvent += on_rtb

    def on_error(req_id: int, code: int, msg: str, *_):
        print(f"⚠️ IB error {code} (reqId={req_id}): {msg}")
        if code in {10089, 354}:
            print("ℹ️ Check that your market-data subscriptions are active for this symbol/timeframe.")
        if code in {10167}:
            print("ℹ️ Market data is not available yet; retry in regular trading hours or with delayed data.")

    ib.errorEvent += on_error

    def _sigint(*_):
        stop['flag'] = True

    signal.signal(signal.SIGINT, _sigint)
    print('✅ Printing AAPL 1-minute bars. Press Ctrl+C to stop.')
    try:
        while not stop['flag']:
            ib.sleep(0.2)
    finally:
        try:
            ib.cancelRealTimeBars(subscription)
        except Exception:
            pass
        try:
            ib.errorEvent -= on_error
        except Exception:
            pass
        ib.disconnect()
        print('🔌 Disconnected')


if __name__ == '__main__':
    main()
