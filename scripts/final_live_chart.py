#!/usr/bin/env python3
"""
Unified IBKR live data collector and chart.

This script:
  * Loads recent historical candles from TimescaleDB (after backfilling gaps)
  * Streams 5 second real-time bars from IBKR, aggregates them into 1 minute candles
  * Updates the chart immediately as new bar data arrives (partial + completed minutes)
  * Persists completed 1 minute candles back to TimescaleDB so other services stay in sync
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import threading
from datetime import datetime, timezone, timedelta, time
from typing import Any, Dict, Optional, Tuple

import asyncpg
import pandas as pd
import pytz
from loguru import logger

# Ensure project modules resolve
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from lightweight_charts import Chart
from ib_async import IB, Stock

from src.data_collectors.common.source_storage import SourceDataStorage
from src.data_collectors.ibkr.historical import IBKRHistoricalCollector
from src.core.config_loader import get_database_config, get_ibkr_config


class FinalLiveChart:
    """Unified chart that handles historical load, real-time collection, and persistence."""

    def __init__(self, symbol: str = 'AAPL', history_limit: int = 5000, backfill_days: int = 7):
        self.symbol = symbol.upper()
        self.history_limit = history_limit
        self.backfill_days = backfill_days

        # Chart state
        self.chart: Optional[Chart] = None
        self.df = pd.DataFrame()
        self.est_timezone = pytz.timezone('US/Eastern')
        self.running = False
        self.last_update_time: Optional[str] = None

        # Async + chart tasks
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.chart_task: Optional[asyncio.Task] = None
        self.processor_task: Optional[asyncio.Task] = None
        self.update_queue: Optional[asyncio.Queue] = None

        # Data collection infrastructure
        self.ib: Optional[IB] = None
        self.collector_thread: Optional[threading.Thread] = None
        self.collector_running = threading.Event()
        self.current_candles: Dict[str, Dict[str, Any]] = {}
        self.subscriptions: Dict[str, Any] = {}

        # Storage
        self.storage: Optional[SourceDataStorage] = None

        # Configuration
        db_config = get_database_config()
        self.dsn = (
            f"postgresql://{db_config.username}:{db_config.password}@"
            f"{db_config.host}:{db_config.port}/{db_config.database}"
        )
        self.table_name = f"ibkr_ohlcv_{self.symbol.lower()}_1m"
        self.ibkr_config = get_ibkr_config()

        logger.remove()
        logger.add(
            sys.stderr,
            level="INFO",
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        )

    # --------------------------------------------------------------------- #
    # Chart bootstrap helpers
    # --------------------------------------------------------------------- #
    def _create_chart(self) -> None:
        """Instantiate and style the chart window."""
        logger.info("📊 Creating live chart window...")
        self.chart = Chart()

        self.chart.layout(background_color='#1e1e1e', text_color='#FFFFFF', font_size=14)
        self.chart.candle_style(up_color='#00ff55', down_color='#ed4807')
        self.chart.volume_config(up_color='#00ff55', down_color='#ed4807')
        self.chart.grid(vert_enabled=True, horz_enabled=True)
        self.chart.legend(visible=True, font_size=12)

        self.chart.topbar.textbox('symbol', self.symbol)
        self.chart.topbar.button('close_button', 'Close', func=self._on_close_clicked)

        logger.info("📈 Chart instantiated.")

    def _on_close_clicked(self, chart: Optional[Chart] = None, *_args):
        """Topbar close button callback."""
        logger.info("🔌 Close requested from chart UI.")
        self.running = False
        chart_instance = chart or self.chart
        if chart_instance:
            try:
                chart_instance.exit()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("❌ Failed closing chart window: {}", exc)

    async def _load_historical_data(self) -> None:
        """Seed the chart with recent historical candles."""
        logger.info("📥 Loading historical data for {}", self.symbol)
        conn = await asyncpg.connect(self.dsn)
        try:
            rows = await conn.fetch(
                f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {self.table_name}
                ORDER BY timestamp DESC
                LIMIT {self.history_limit}
                """
            )
        finally:
            await conn.close()

        if not rows:
            logger.warning("⚠️ No historical rows found in {}", self.table_name)
            return

        data = []
        for row in reversed(rows):
            timestamp_est = row['timestamp'].astimezone(self.est_timezone)
            data.append(
                {
                    'time': timestamp_est.strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume']),
                }
            )

        self.df = pd.DataFrame(data)
        self.chart.set(self.df)
        if not self.df.empty:
            self.last_update_time = self.df.iloc[-1]['time']
            logger.info("✅ Seeded chart with {} candles (latest {})", len(self.df), self.last_update_time)

    async def _get_latest_db_timestamp(self) -> Optional[datetime]:
        """Fetch the most recent timestamp present in the TimescaleDB table."""
        conn = await asyncpg.connect(self.dsn)
        try:
            exists = await conn.fetchval("SELECT to_regclass($1)", self.table_name)
            if not exists:
                return None
            latest = await conn.fetchval(f"SELECT MAX(timestamp) FROM {self.table_name}")
            return latest
        finally:
            await conn.close()

    async def _get_earliest_timestamp_for_range(self, start: datetime, end: datetime) -> Optional[datetime]:
        """Return the earliest timestamp within a UTC window."""
        conn = await asyncpg.connect(self.dsn)
        try:
            exists = await conn.fetchval("SELECT to_regclass($1)", self.table_name)
            if not exists:
                return None
            return await conn.fetchval(
                f"""
                SELECT MIN(timestamp)
                FROM {self.table_name}
                WHERE timestamp >= $1 AND timestamp < $2
                """,
                start,
                end,
            )
        finally:
            await conn.close()

    def _session_bounds_utc(self, reference_utc: datetime) -> Tuple[datetime, datetime]:
        """Return the current trading day's [session_open, session_close) in UTC."""
        est_now = reference_utc.astimezone(self.est_timezone)
        session_open_est = est_now.replace(hour=4, minute=0, second=0, microsecond=0)
        session_close_est = est_now.replace(hour=16, minute=0, second=0, microsecond=0)

        # If we're before 4:00 ET, use previous trading day
        if est_now.time() < time(4, 0):
            session_open_est -= timedelta(days=1)
            session_close_est -= timedelta(days=1)

        return (
            session_open_est.astimezone(timezone.utc),
            session_close_est.astimezone(timezone.utc),
        )

    async def _fetch_and_store_range(self, start_utc: datetime, end_utc: datetime) -> Dict[str, int]:
        """Fetch historical data for a range and store it, returning insert/update counts."""
        collector = IBKRHistoricalCollector()
        try:
            result = await collector.collect_and_store(
                symbol=self.symbol,
                start=start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                end=end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                timeframe='1m',
            )
            return {
                'inserted': result.get('inserted', 0),
                'updated': result.get('updated', 0),
                'skipped': result.get('skipped', 0),
            }
        except Exception as exc:
            logger.error("❌ Historical fetch failed for {}: {}", self.symbol, exc)
            return {'inserted': 0, 'updated': 0, 'skipped': 0}
        finally:
            try:
                await collector.client.close()
            except Exception:
                pass

    async def _backfill_historical_gap(self) -> None:
        """Fill any missing historical data between the DB and current time."""
        latest_ts = await self._get_latest_db_timestamp()
        now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        lookback_floor = now_utc - timedelta(days=self.backfill_days)

        start_candidates = []

        if latest_ts:
            latest_ts = latest_ts.replace(second=0, microsecond=0)
            gap_minutes = (now_utc - latest_ts).total_seconds() / 60
            if gap_minutes > 2:
                start_candidates.append(latest_ts - timedelta(minutes=1))
        else:
            logger.info("⚠️ No historical data detected; fetching lookback window of {} day(s).", self.backfill_days)

        session_open_utc, session_close_utc = self._session_bounds_utc(now_utc)
        if session_open_utc < now_utc:
            earliest_today = await self._get_earliest_timestamp_for_range(session_open_utc, session_close_utc)
            if earliest_today is None or earliest_today > (session_open_utc + timedelta(minutes=1)):
                logger.info(
                    "📉 Session gap detected: earliest bar for {} is {} (expected ≥ {})",
                    self.symbol,
                    earliest_today,
                    session_open_utc,
                )
                start_candidates.append(session_open_utc)

        if not start_candidates:
            start_candidates.append(now_utc - timedelta(days=self.backfill_days))

        start_utc = min(start_candidates)
        start_utc = max(lookback_floor, start_utc)

        if start_utc >= now_utc - timedelta(minutes=1):
            logger.info("No historical backfill required for {}", self.symbol)
            return

        fetch_start = start_utc
        fetch_end = now_utc
        attempts = 0
        max_attempts = 4

        while attempts < max_attempts:
            if fetch_end <= fetch_start:
                logger.info("ℹ️ Skipping backfill attempt; start {} >= end {}", fetch_start, fetch_end)
                break
            logger.info("🔄 Backfilling {} from {} to {}", self.symbol, fetch_start, fetch_end)
            counts = await self._fetch_and_store_range(fetch_start, fetch_end)
            inserted = counts['inserted']
            updated = counts['updated']

            if inserted or updated:
                logger.info("💾 Backfill stored {} new / {} updated candles for {}", inserted, updated, self.symbol)
            else:
                logger.info("ℹ️ Historical backfill returned no new rows for {}", self.symbol)
                break

            earliest_now = await self._get_earliest_timestamp_for_range(session_open_utc, session_close_utc)
            if earliest_now and earliest_now <= session_open_utc + timedelta(minutes=1):
                break

            if earliest_now:
                if earliest_now >= fetch_end - timedelta(minutes=1):
                    logger.info("ℹ️ No earlier data received (earliest {} >= previous end {}).", earliest_now, fetch_end)
                    break
                fetch_end = earliest_now
            else:
                break

            if fetch_end <= session_open_utc:
                break

            fetch_start = max(session_open_utc, fetch_end - timedelta(hours=6))
            attempts += 1

        final_earliest = await self._get_earliest_timestamp_for_range(session_open_utc, session_close_utc)
        if final_earliest and final_earliest > session_open_utc + timedelta(minutes=1):
            logger.warning(
                "⚠️ Historical backfill incomplete for {}. Earliest bar today: {} (target >= {}).",
                self.symbol,
                final_earliest,
                session_open_utc,
            )

    # --------------------------------------------------------------------- #
    # IBKR real-time collection & aggregation
    # --------------------------------------------------------------------- #
    def _start_collector(self) -> None:
        """Spin up the background thread that talks to IBKR."""
        if self.collector_thread and self.collector_thread.is_alive():
            return
        self.collector_running.set()
        self.collector_thread = threading.Thread(
            target=self._run_streaming,
            name="IBKRCollectorThread",
            daemon=True,
        )
        self.collector_thread.start()

    def _run_streaming(self) -> None:
        """Run the IBKR event loop in a background thread."""
        connection = self.ibkr_config.connection
        host = connection.host or "127.0.0.1"
        port = connection.port or 7497
        client_id = connection.client_id or random.randint(1000, 9999)

        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)
        ib = IB()
        self.ib = ib

        try:
            logger.info("🔌 Connecting to IBKR (host={} port={} client_id={})", host, port, client_id)
            ib.connect(host, port, clientId=client_id)
            if not ib.isConnected():
                raise RuntimeError("Unable to establish IBKR connection")
            logger.info("✅ Connected to IBKR, subscribing to {}", self.symbol)

            self._subscribe_to_symbol(self.symbol)

            while self.collector_running.is_set():
                ib.waitOnUpdate(timeout=1)
        except Exception as exc:
            logger.error("❌ Collector error: {}", exc)
        finally:
            logger.info("⏹️ Shutting down IBKR collector...")
            try:
                for sub in self.subscriptions.values():
                    try:
                        ib.cancelRealTimeBars(sub)
                    except Exception:
                        pass
                self.subscriptions.clear()
                if ib.isConnected():
                    ib.disconnect()
                    logger.info("🔌 Disconnected from IBKR")
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("❌ Error while disconnecting IBKR: {}", exc)
            finally:
                self.ib = None
                try:
                    thread_loop.close()
                except Exception:
                    pass

    def _subscribe_to_symbol(self, symbol: str) -> None:
        """Request 5 second real-time bars for the configured symbol."""
        try:
            if not self.ib:
                raise RuntimeError("IBKR connection not established")
            contract = Stock(symbol, 'SMART', 'USD')
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                contract = qualified[0]
                logger.info("📈 Qualified contract for {} -> {}", symbol, contract)

            subscription = self.ib.reqRealTimeBars(
                contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=False,
                realTimeBarsOptions=[],
            )

            subscription.updateEvent += lambda bars, has_new_bar: self._on_bar_update(symbol, bars, has_new_bar)
            self.subscriptions[symbol] = subscription
            logger.info("📡 Subscribed to {} real-time bars", symbol)
        except Exception as exc:
            logger.error("❌ Failed to subscribe {}: {}", symbol, exc)

    def _on_bar_update(self, symbol: str, bars, has_new_bar: bool) -> None:
        """Aggregate incoming 5 second bars into minute candles."""
        if not has_new_bar or not bars or not self.collector_running.is_set():
            return

        latest_bar = bars[-1]
        bar_time = latest_bar.time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        else:
            bar_time = bar_time.astimezone(timezone.utc)

        minute_start = bar_time.replace(second=0, microsecond=0)
        active = self.current_candles.get(symbol)

        if active and active['minute_start'] != minute_start:
            self._complete_candle(symbol)
            active = None

        if not active:
            self._start_new_candle(symbol, minute_start, latest_bar)
        else:
            self._update_current_candle(symbol, latest_bar)

    def _start_new_candle(self, symbol: str, minute_start: datetime, bar) -> None:
        candle = {
            'minute_start': minute_start,
            'open': float(bar.open_),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': int(bar.volume or 0),
            'bar_count': 1,
        }
        self.current_candles[symbol] = candle
        self._queue_update(symbol, candle, update_type='partial')

    def _update_current_candle(self, symbol: str, bar) -> None:
        candle = self.current_candles.get(symbol)
        if not candle:
            return

        candle['high'] = max(candle['high'], float(bar.high))
        candle['low'] = min(candle['low'], float(bar.low))
        candle['close'] = float(bar.close)
        candle['volume'] += int(bar.volume or 0)
        candle['bar_count'] += 1
        self._queue_update(symbol, candle, update_type='partial')

    def _complete_candle(self, symbol: str) -> None:
        candle = self.current_candles.get(symbol)
        if not candle:
            return
        self._queue_update(symbol, candle, update_type='complete')
        del self.current_candles[symbol]

    def _queue_update(self, symbol: str, candle: Dict[str, Any], update_type: str) -> None:
        """Push an aggregated candle event onto the asyncio queue."""
        if not self.loop or not self.update_queue or not self.loop.is_running():
            return

        payload = {
            'symbol': symbol,
            'type': update_type,
            'candle': {
                'timestamp': candle['minute_start'],
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle['volume'],
                'bar_count': candle['bar_count'],
            },
        }

        try:
            asyncio.run_coroutine_threadsafe(self.update_queue.put(payload), self.loop)
        except RuntimeError as exc:
            logger.error("❌ Failed queuing candle update: {}", exc)

    # --------------------------------------------------------------------- #
    # Queue processor + persistence
    # --------------------------------------------------------------------- #
    async def _process_updates(self) -> None:
        """Consume queued candle updates, update chart, and persist completed bars."""
        logger.info("🧵 Started chart update processor")
        while self.running:
            update = await self.update_queue.get()
            if update is None:
                break

            candle = update['candle']
            timestamp_est = candle['timestamp'].astimezone(self.est_timezone)
            time_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S')
            series = pd.Series(
                {
                    'time': time_str,
                    'open': float(candle['open']),
                    'high': float(candle['high']),
                    'low': float(candle['low']),
                    'close': float(candle['close']),
                    'volume': int(candle.get('volume', 0)),
                }
            )

            if self.chart:
                try:
                    self.chart.update(series)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("❌ Failed updating chart: {}", exc)

            if self.df.empty or self.df.iloc[-1]['time'] != time_str:
                self.df = pd.concat([self.df, series.to_frame().T], ignore_index=True)
                if len(self.df) > self.history_limit:
                    self.df = self.df.iloc[-self.history_limit :].reset_index(drop=True)
            else:
                self.df.iloc[-1] = series

            self.last_update_time = time_str
            if update['type'] == 'complete':
                await self._store_candle(candle)
                logger.info(
                    "📊 {} | O:{:.2f} H:{:.2f} L:{:.2f} C:{:.2f} V:{} ({} bars)",
                    time_str,
                    series['open'],
                    series['high'],
                    series['low'],
                    series['close'],
                    series['volume'],
                    candle.get('bar_count', 0),
                )

        logger.info("🧵 Chart update processor stopped")

    async def _store_candle(self, candle: Dict[str, Any]) -> None:
        """Persist completed candle back to TimescaleDB."""
        if not self.storage:
            return

        payload = {
            'timestamp': candle['timestamp'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume'],
        }

        result = await self.storage.store_ohlcv(self.symbol, '1m', [payload])
        if not result.success:
            logger.error("❌ Failed storing candle for {}: {}", self.symbol, result.error)

    # --------------------------------------------------------------------- #
    # Lifecycle management
    # --------------------------------------------------------------------- #
    async def start(self) -> None:
        """Entry point: set up chart, load history, and launch collector."""
        if self.running:
            logger.warning("Chart already running.")
            return

        self.running = True
        self.loop = asyncio.get_running_loop()
        self.update_queue = asyncio.Queue()

        self._create_chart()

        self.storage = SourceDataStorage(source='ibkr')
        await self.storage.connect()

        await self._backfill_historical_gap()
        await self._load_historical_data()

        # Show chart window (non-blocking)
        if not self.chart_task:
            try:
                self.chart_task = asyncio.create_task(self.chart.show_async())
            except RuntimeError:
                logger.warning("⚠️ Event loop unavailable, rendering chart in helper thread.")
                await asyncio.to_thread(self.chart.show, block=True)

        # Start background tasks
        self.processor_task = asyncio.create_task(self._process_updates())
        self._start_collector()

        logger.info("🚀 Live chart + collector running for {}", self.symbol)

        try:
            while self.running:
                if not self.chart:
                    break
                if hasattr(self.chart, '_window') and self.chart._window and not self.chart._window.visible:
                    logger.info("🪟 Chart window closed by user.")
                    break
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard interrupt received.")
        finally:
            self.running = False

    async def stop(self) -> None:
        """Tear down collector, queue processor, chart, and database connections."""
        logger.info("🔻 Stopping live chart...")
        self.running = False
        self.collector_running.clear()

        if self.collector_thread and self.collector_thread.is_alive():
            await asyncio.to_thread(self.collector_thread.join, 5)
        self.collector_thread = None

        if self.update_queue:
            await self.update_queue.put(None)

        if self.processor_task:
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("❌ Update processor error: {}", exc)
            finally:
                self.processor_task = None

        if self.chart_task:
            if not self.chart_task.done():
                self.chart_task.cancel()
            try:
                await self.chart_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("❌ Chart task error: {}", exc)
            finally:
                self.chart_task = None

        if self.chart:
            try:
                self.chart.exit()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("❌ Error while closing chart window: {}", exc)
            self.chart = None

        if self.storage:
            await self.storage.disconnect()
            self.storage = None

        self.update_queue = None
        self.loop = None
        self.current_candles.clear()
        logger.info("✅ Live chart stopped cleanly.")


async def main():
    args = parse_args()
    chart = FinalLiveChart(
        symbol=args.symbol,
        history_limit=args.history_limit,
        backfill_days=args.backfill_days,
    )
    try:
        await chart.start()
    finally:
        await chart.stop()


def parse_args():
    parser = argparse.ArgumentParser(description="Unified IBKR live chart (historical + real-time aggregator).")
    parser.add_argument(
        "symbol",
        nargs="?",
        default="AAPL",
        help="Ticker symbol to chart (default: AAPL).",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=5000,
        help="Number of recent candles to display initially (default: 5000).",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=7,
        help="Lookback window (in days) when no data exists (default: 7).",
    )
    return parser.parse_args()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrupted by user.")
