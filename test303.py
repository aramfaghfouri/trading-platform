"""
Stream real-time 5-second AAPL bars from Interactive Brokers and print them.

Run this script while TWS or IB Gateway is up:
    python test301.py
"""

from __future__ import annotations

import signal
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from ib_async import IB, util
from ib_async.contract import Stock

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    ZoneInfo = None  # type: ignore

# Import chart functionality
try:
    from src.visualization.lightweight_chart import LightweightRealtimeChart
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False
    print("Warning: Chart functionality not available. Install required dependencies.")


# === Runtime configuration ===
BUFFER_SIZE = 100_000              # Maximum number of rows stored per DataFrame buffer.
PRINT_5S_BARS = True               # Print each 5-second bar as it arrives.
PRINT_AGGREGATE_CANDLES = True     # Print completed aggregated candles (requires AGGREGATE_MINUTES > 0).
PRINT_AGGREGATE_HA_CANDLES = True  # Print Heikin-Ashi candles derived from aggregate bars.
SHOW_TIMESTAMPS_IN_EST = True      # Convert timestamps to America/New_York if True.
AGGREGATE_MINUTES = 1              # Aggregate real-time bars into this many-minute candles (0 disables).
ENABLE_CHART = True                # Enable real-time chart display using lightweight_charts.
SYMBOL = 'AAPL'

def _make_empty_bar_df() -> pd.DataFrame:
    """Pre-create a fixed-size DataFrame to act as a circular buffer for bar data."""
    return pd.DataFrame(
        {
            'timestamp': pd.Series(np.full(BUFFER_SIZE, np.datetime64('NaT', 'ns')), dtype='datetime64[ns]'),
            'open': pd.Series(np.full(BUFFER_SIZE, np.nan), dtype='float64'),
            'high': pd.Series(np.full(BUFFER_SIZE, np.nan), dtype='float64'),
            'low': pd.Series(np.full(BUFFER_SIZE, np.nan), dtype='float64'),
            'close': pd.Series(np.full(BUFFER_SIZE, np.nan), dtype='float64'),
            'volume': pd.Series(np.full(BUFFER_SIZE, np.nan), dtype='float64'),
        }
    )


class RealTimeBarStreamer:
    """Encapsulate IBKR real-time bar streaming for a single stock symbol."""

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 99,
        symbol: Optional[str] = None,
        print_bars: bool = True,
        print_aggregate: bool = True,
        print_aggregate_ha: bool = True,
        show_est: bool = False,
        aggregate_minutes: int = 0,
        enable_chart: bool = False,
    ) -> None:
        if not symbol:
            symbol = SYMBOL
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
        self.print_aggregate_ha = print_aggregate_ha
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
        self.raw_bars = _make_empty_bar_df()
        self.agg_bars = _make_empty_bar_df()
        self.ha_bars = _make_empty_bar_df()
        self._raw_idx = 0
        self._agg_idx = 0
        self._ha_idx = 0
        self._ha_prev_open: Optional[float] = None
        self._ha_prev_close: Optional[float] = None
        
        # Chart functionality
        self.enable_chart = enable_chart and CHART_AVAILABLE
        self.chart: Optional[LightweightRealtimeChart] = None
        self.chart_thread: Optional[threading.Thread] = None

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
            completed = self._agg_state.copy()
            self._finalize_aggregate_candle(completed, complete=True)
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

    def _record_bar(
        self,
        df: pd.DataFrame,
        idx_attr: str,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Store a bar in the circular buffer DataFrame."""
        idx = getattr(self, idx_attr)
        df.at[idx, 'timestamp'] = self._normalize_timestamp(timestamp)
        df.at[idx, 'open'] = float(open_)
        df.at[idx, 'high'] = float(high)
        df.at[idx, 'low'] = float(low)
        df.at[idx, 'close'] = float(close)
        df.at[idx, 'volume'] = float(volume)
        setattr(self, idx_attr, (idx + 1) % BUFFER_SIZE)

    @staticmethod
    def _normalize_timestamp(ts: datetime) -> pd.Timestamp:
        """Convert datetimes to timezone-naive UTC pandas timestamps for storage."""
        ts_pd = pd.Timestamp(ts)
        if ts_pd.tz is not None:
            ts_pd = ts_pd.tz_convert('UTC').tz_localize(None)
        return ts_pd

    def _finalize_aggregate_candle(self, state: dict[str, Any], *, complete: bool) -> None:
        """Handle output and storage for an aggregated candle."""
        if complete:
            self._record_bar(
                self.agg_bars,
                '_agg_idx',
                state['start'],
                state['open'],
                state['high'],
                state['low'],
                state['close'],
                float(state['volume']),
            )
            self._update_heikin_ashi(state)
            
            # Update chart with completed candle
            if self.enable_chart:
                bar_data = {
                    'timestamp': state['start'],
                    'open': state['open'],
                    'high': state['high'],
                    'low': state['low'],
                    'close': state['close'],
                    'volume': state['volume']
                }
                # Add a small delay to ensure chart is fully initialized
                import time
                time.sleep(0.05)
                self._update_chart(bar_data)

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

    def _update_heikin_ashi(self, state: dict[str, Any]) -> None:
        """Derive a Heikin-Ashi candle from a completed aggregate bar."""
        open_ = float(state['open'])
        high = float(state['high'])
        low = float(state['low'])
        close = float(state['close'])
        volume = float(state['volume'])

        ha_close = (open_ + high + low + close) / 4.0
        if self._ha_prev_open is None or self._ha_prev_close is None:
            ha_open = (open_ + close) / 2.0
        else:
            ha_open = (self._ha_prev_open + self._ha_prev_close) / 2.0
        ha_high = max(high, ha_open, ha_close)
        ha_low = min(low, ha_open, ha_close)

        timestamp = state['start']
        self._record_bar(
            self.ha_bars,
            '_ha_idx',
            timestamp,
            ha_open,
            ha_high,
            ha_low,
            ha_close,
            volume,
        )
        self._ha_prev_open = ha_open
        self._ha_prev_close = ha_close

        if not self.print_aggregate_ha:
            return

        stamp = timestamp
        if self.show_est and self._est_zone is not None:
            stamp = stamp.astimezone(self._est_zone)
        label = f'{self.aggregate_minutes}m-HA'
        print(
            f'HA[{label}] {stamp.isoformat()} '
            f'O:{ha_open:.2f} H:{ha_high:.2f} '
            f'L:{ha_low:.2f} C:{ha_close:.2f} '
            f'V:{int(volume)}',
            flush=True,
        )

    def _update_chart(self, bar_data: dict[str, Any]) -> None:
        """Update the chart with new bar data if chart is enabled."""
        if not self.enable_chart or not self.chart:
            return
        
        try:
            # Convert bar data to the format expected by the chart
            chart_bar = {
                'timestamp': bar_data['timestamp'],  # Chart's _on_timeframe_update expects 'timestamp'
                'symbol': self.symbol,
                'open': bar_data['open'],
                'high': bar_data['high'],
                'low': bar_data['low'],
                'close': bar_data['close'],
                'volume': bar_data['volume']
            }
            
            # Use the chart's built-in timeframe update method
            self.chart._on_timeframe_update(chart_bar, '1m')
                
        except Exception as exc:
            print(f'Error updating chart: {exc!r}')

    def _flush_aggregate(self, *, complete: bool) -> None:
        """Flush and optionally emit the current aggregated candle."""
        if self.aggregate_minutes <= 0 or self._agg_state is None:
            return
        state = self._agg_state.copy()
        self._finalize_aggregate_candle(state, complete=complete)
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
        
        # Start chart if enabled
        if self.enable_chart:
            self._start_chart()

    def _start_chart(self) -> None:
        """Start the chart in a separate thread."""
        if not self.enable_chart or not CHART_AVAILABLE:
            print(f'Chart not started: enable_chart={self.enable_chart}, CHART_AVAILABLE={CHART_AVAILABLE}')
            return
            
        try:
            print('Starting real-time chart...')
            self.chart = LightweightRealtimeChart(
                symbol=self.symbol,
                initial_timeframe='1m'
            )
            print(f'Chart instance created successfully')
            
            # Don't let the chart connect to IBKR - we'll feed it data manually
            self.chart.is_connected = False  # Prevent IBKR connection
            
            # Start chart in a separate thread
            def run_chart():
                try:
                    print('Chart thread starting...')
                    # Create the chart UI but don't connect to IBKR
                    self.chart._create_chart()
                    # Set chart type to 'ha' AFTER chart is created
                    self.chart.chart_type = 'ha'
                    print(f'Chart type set to: {self.chart.chart_type}')
                    # Add some sample data initially
                    self.chart._add_sample_data()
                    # Add a small delay to ensure chart is fully initialized
                    import time
                    time.sleep(1.0)
                    # Show the chart
                    self.chart.chart.show(block=True)
                except Exception as exc:
                    print(f'Chart error: {exc!r}')
                    import traceback
                    traceback.print_exc()
            
            self.chart_thread = threading.Thread(target=run_chart, daemon=True)
            self.chart_thread.start()
            print('Chart started successfully.')
            
        except Exception as exc:
            print(f'Failed to start chart: {exc!r}')
            import traceback
            traceback.print_exc()
            self.enable_chart = False

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
            
            # Clean up chart
            if self.enable_chart and self.chart:
                try:
                    self.chart.disconnect_from_ibkr()
                    print('Chart disconnected.')
                except Exception as exc:
                    print(f'Error disconnecting chart: {exc!r}')
            
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
            open_val = self._bar_value(latest, 'open')
            high_val = self._bar_value(latest, 'high')
            low_val = self._bar_value(latest, 'low')
            close_val = self._bar_value(latest, 'close')
            volume = float(getattr(latest, 'volume', 0) or 0)
            self._record_bar(
                self.raw_bars,
                '_raw_idx',
                stamp_utc,
                open_val,
                high_val,
                low_val,
                close_val,
                volume,
            )
            if not self.print_bars:
                return
            stamp = stamp_utc
            if self.show_est and self._est_zone is not None:
                stamp = stamp.astimezone(self._est_zone)
            print(
                f'{stamp.isoformat()} '
                f'O:{open_val:.2f} '
                f'H:{high_val:.2f} '
                f'L:{low_val:.2f} '
                f'C:{close_val:.2f} '
                f'V:{int(volume)}',
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
    print_aggregate_ha = bool(PRINT_AGGREGATE_HA_CANDLES) and aggregate_minutes > 0
    symbol = (SYMBOL or 'AAPL').upper()

    print(
        'Runtime configuration -> '
        f'symbol: {symbol}, '
        f'5s bars: {"on" if print_bars else "off"}, '
        f'aggregate: {"on" if print_aggregate else "off"}, '
        f'agg-HA: {"on" if print_aggregate_ha else "off"} '
        f'(interval={aggregate_minutes}m)'
    )
    if not any((print_bars, print_aggregate, print_aggregate_ha)):
        print('All real-time prints are disabled; enable one of the PRINT_* toggles to see output.')

    util.startLoop()
    enable_chart = bool(ENABLE_CHART) and CHART_AVAILABLE
    if ENABLE_CHART and not CHART_AVAILABLE:
        print('Chart functionality requested but not available. Continuing without chart.')
    
    streamer = RealTimeBarStreamer(
        print_bars=print_bars,
        print_aggregate=print_aggregate,
        print_aggregate_ha=print_aggregate_ha,
        show_est=show_est,
        aggregate_minutes=aggregate_minutes,
        symbol=symbol,
        enable_chart=enable_chart,
    )

    def _handle_signal(*_):
        streamer.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)

    streamer.start()
    streamer.run()


#if __name__ == '__main__':
main()
