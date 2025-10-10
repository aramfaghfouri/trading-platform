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
from zoneinfo import ZoneInfo


# PRINT_BARS_DEFAULT: Default answers for the interactive prompts:
# SHOW_EST_DEFAULTTrue keeps bar output enabled; False keeps timestamps in UTC.
PRINT_BARS_DEFAULT = True
SHOW_EST_DEFAULT = True


class RealTimeBarStreamer:
    """Encapsulate IBKR real-time bar streaming for a single stock symbol."""

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 99,
        symbol: str = 'AAPL',
        print_bars: bool = True,
        show_est: bool = False,
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
        self.show_est = show_est
        if self.show_est:
            if ZoneInfo is None:
                raise RuntimeError('EST timestamps requested but zoneinfo module is unavailable.')
            self._est_zone = ZoneInfo('America/New_York')
        else:
            self._est_zone = None

    @staticmethod
    def _prompt_bool(prompt: str, default: bool) -> bool:
        """Prompt the user for a yes/no response, returning a bool."""
        suffix = 'Y/n' if default else 'y/N'
        while True:
            response = input(f'{prompt} [{suffix}]: ').strip().lower()
            if not response:
                return default
            if response in {'y', 'yes', 'true', 't', '1', 'on'}:
                return True
            if response in {'n', 'no', 'false', 'f', '0', 'off'}:
                return False
            print('Please respond with yes or no.')

    @staticmethod
    def _as_utc(ts: Union[int, float, datetime]) -> datetime:
        """Normalize IB timestamp values to timezone-aware UTC datetimes."""
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)

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
        if not self.print_bars:
            return
        latest = bars[-1]
        stamp = self._as_utc(latest.time)
        if self.show_est and self._est_zone is not None:
            stamp = stamp.astimezone(self._est_zone)
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
    print_bars = RealTimeBarStreamer._prompt_bool('Print each 5-second bar?', PRINT_BARS_DEFAULT)
    show_est = RealTimeBarStreamer._prompt_bool('Show timestamps in America/New_York (EST)?', SHOW_EST_DEFAULT)
    if show_est and ZoneInfo is None:
        print('zoneinfo module not available; using UTC timestamps instead.')
        show_est = False

    util.startLoop()
    streamer = RealTimeBarStreamer(
        print_bars=print_bars,
        show_est=show_est,
    )

    def _handle_signal(*_):
        streamer.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)

    streamer.start()
    streamer.run()


#if __name__ == '__main__':
main()
