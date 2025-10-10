"""
Stream real-time 5-second AAPL bars from Interactive Brokers and print them.

Run this script while TWS or IB Gateway is up:
    python test301.py
"""

from __future__ import annotations

import signal
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Union

from ib_async import IB, util
from ib_async.contract import Stock

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    ZoneInfo = None  # type: ignore


# === Runtime configuration ===
PRINT_5S_BARS = True           # Print each 5-second bar as it arrives.
PRINT_AGGREGATE_CANDLES = True # Print completed aggregated candles (requires AGGREGATE_MINUTES > 0).
SHOW_TIMESTAMPS_IN_EST = True  # Convert timestamps to America/New_York if True.
AGGREGATE_MINUTES = 1          # Aggregate real-time bars into this many-minute candles (0 disables).


class RealTimeBarStreamer:
    """Encapsulate IBKR real-time bar streaming for a single stock symbol."""

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 99,
        symbol: str = 'AAPL',
        print_bars: bool = True,
        print_aggregate: bool = True,
        show_est: bool = False,
        aggregate_minutes: int = 0,
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
        self.print_bars = print_bars
        self.print_aggregate = print_aggregate
        self.show_est = show_est
        if self.show_est:
            if ZoneInfo is None:
                raise RuntimeError('EST timestamps requested but zoneinfo module is unavailable.')
            self._est_zone = ZoneInfo('America/New_York')
        else:
            self._est_zone = None
        self.aggregate_minutes = max(int(aggregate_minutes or 0), 0)
        self._agg_state: Optional[dict[str, Any]] = None
        self._agg_period_seconds = self.aggregate_minutes * 60 if self.aggregate_minutes else 0

    @staticmethod
    def _as_utc(ts: Union[int, float, datetime]) -> datetime:
        """Normalize IB timestamp values to timezone-aware UTC datetimes."""
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)

    def _update_aggregate(self, stamp_utc: datetime, bar: Any) -> None:
        """Update or emit an aggregated minute candle composed from 5-second bars."""
        if self.aggregate_minutes <= 0 or not self._agg_period_seconds:
            return

        if self._agg_state is not None and stamp_utc >= self._agg_state['end']:
            self._emit_aggregate_candle(self._agg_state, complete=True)
            self._agg_state = None

        if self._agg_state is None:
            period_start_epoch = (int(stamp_utc.timestamp()) // self._agg_period_seconds) * self._agg_period_seconds
            period_start = datetime.fromtimestamp(period_start_epoch, tz=timezone.utc)
            period_end = period_start + timedelta(seconds=self._agg_period_seconds)
            volume = int(getattr(bar, 'volume', 0) or 0)
            self._agg_state = {
                'start': period_start,
                'end': period_end,
                'open': self._bar_value(bar, 'open'),
                'high': self._bar_value(bar, 'high'),
                'low': self._bar_value(bar, 'low'),
                'close': self._bar_value(bar, 'close'),
                'volume': volume,
            }
            return

        state = self._agg_state
        volume = int(getattr(bar, 'volume', 0) or 0)
        state['high'] = max(state['high'], self._bar_value(bar, 'high'))
        state['low'] = min(state['low'], self._bar_value(bar, 'low'))
        state['close'] = self._bar_value(bar, 'close')
        state['volume'] += volume

    @staticmethod
    def _bar_value(bar: Any, name: str) -> float:
        """Return a float attribute from the bar, handling open/open_ naming."""
        value = getattr(bar, f'{name}_', None)
        if value is None:
            value = getattr(bar, name)
        return float(value)

    def _emit_aggregate_candle(self, state: dict[str, Any], *, complete: bool) -> None:
        """Print an aggregated candle, optionally marking it partial."""
        if not self.print_aggregate:
            return
        stamp = state['start']
        if self.show_est and self._est_zone is not None:
            stamp = stamp.astimezone(self._est_zone)
        label = f'{self.aggregate_minutes}m'
        status = '' if complete else ' (partial)'
        print(
            f'AGG[{label}] {stamp.isoformat()} '
            f'O:{state["open"]:.2f} H:{state["high"]:.2f} '
            f'L:{state["low"]:.2f} C:{state["close"]:.2f} '
            f'V:{int(state["volume"])}{status}',
            flush=True,
        )

    def _flush_aggregate(self, *, complete: bool) -> None:
        """Flush and optionally emit the current aggregated candle."""
        if self.aggregate_minutes <= 0 or self._agg_state is None:
            return
        self._emit_aggregate_candle(self._agg_state, complete=complete)
        self._agg_state = None

    def start(self) -> None:
        """Connect to IBKR and start streaming bars."""
        print(f'Connecting to IBKR at {self.host}:{self.port} (clientId={self.client_id}) ...')
        self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)
        if not self.ib.isConnected():
            raise RuntimeError('Could not connect to IBKR')
        print('Connected.')

        self.ib.reqMarketDataType(1)  # Request real-time data (if permissions allow)

        contract = Stock(
            symbol=self.symbol, 
            exchange='SMART', 
            currency='USD',
            primaryExchange='NASDAQ'
        )
        #contract.primaryExchange = 'NASDAQ'

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
            self._flush_aggregate(complete=False)
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
        try:
            latest = bars[-1]
            stamp_utc = self._as_utc(latest.time)
            self._update_aggregate(stamp_utc, latest)
            if not self.print_bars:
                return
            stamp = stamp_utc
            if self.show_est and self._est_zone is not None:
                stamp = stamp.astimezone(self._est_zone)
            volume = int(getattr(latest, 'volume', 0) or 0)
            print(
                f'{stamp.isoformat()} '
                f'O:{self._bar_value(latest, "open"):.2f} '
                f'H:{self._bar_value(latest, "high"):.2f} '
                f'L:{self._bar_value(latest, "low"):.2f} '
                f'C:{self._bar_value(latest, "close"):.2f} '
                f'V:{volume}',
                flush=True,
            )
        except Exception as exc:
            print(f'Error processing bar update: {exc!r}')

    @staticmethod
    def _on_error(req_id, code, msg, *_):
        print(f'IB error {code} (reqId={req_id}): {msg}')


def main() -> None:
    print_bars = bool(PRINT_5S_BARS)
    show_est = bool(SHOW_TIMESTAMPS_IN_EST)
    if show_est and ZoneInfo is None:
        print('zoneinfo module not available; using UTC timestamps instead.')
        show_est = False
    aggregate_minutes = max(int(AGGREGATE_MINUTES or 0), 0)
    print_aggregate = bool(PRINT_AGGREGATE_CANDLES) and aggregate_minutes > 0

    print(
        'Runtime configuration -> '
        f'5s bars: {"on" if print_bars else "off"}, '
        f'aggregate: {"on" if print_aggregate else "off"} '
        f'(interval={aggregate_minutes}m)'
    )
    if not print_bars and not print_aggregate:
        print('Both real-time prints are disabled; enable PRINT_5S_BARS or aggregate settings to see output.')

    util.startLoop()
    streamer = RealTimeBarStreamer(
        print_bars=print_bars,
        print_aggregate=print_aggregate,
        show_est=show_est,
        aggregate_minutes=aggregate_minutes,
    )

    def _handle_signal(*_):
        streamer.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)

    streamer.start()
    streamer.run()


#if __name__ == '__main__':
main()
