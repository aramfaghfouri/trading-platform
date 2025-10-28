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
from src.utils.heikin_ashi import calculate_heikin_ashi


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
        self.view_mode: str = 'regular'
        self.ha_df = pd.DataFrame()

        # Async + chart tasks
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.chart_task: Optional[asyncio.Task] = None
        self.processor_task: Optional[asyncio.Task] = None
        self.update_queue: Optional[asyncio.Queue] = None

        # Data collection infrastructure
        self.ib: Optional[IB] = None
        self.collector_task: Optional[asyncio.Task] = None
        self.collector_stop_event: Optional[asyncio.Event] = None
        self.collector_running: bool = False
        self.backfill_task: Optional[asyncio.Task] = None
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
        base_client_id = getattr(self.ibkr_config.connection, "client_id", None) or 1
        self.historical_client_id = base_client_id + 100
        self.realtime_delay = timedelta(minutes=15)
        self.backfill_poll_seconds = 60

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
        self.chart.topbar.button('mode_regular', 'Regular', separator=False, func=self._set_regular_mode)
        self.chart.topbar.button('mode_ha', 'Heikin-Ashi', separator=False, func=self._set_ha_mode)

        self._update_view_mode_buttons()

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

    def _get_regular_chart_df(self) -> pd.DataFrame:
        if self.df.empty:
            return pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df_copy = self.df.copy()
        if 'volume' not in df_copy.columns:
            df_copy['volume'] = 0
        return df_copy[['time', 'open', 'high', 'low', 'close', 'volume']]

    def _refresh_heikin_ashi(self) -> None:
        if self.df.empty:
            self.ha_df = pd.DataFrame()
            return
        base = self.df[['open', 'high', 'low', 'close']].astype(float).copy()
        ha = calculate_heikin_ashi(base)
        ha.insert(0, 'time', self.df['time'].values)
        if 'volume' in self.df.columns:
            ha['volume'] = self.df['volume'].values
        else:
            ha['volume'] = 0
        self.ha_df = ha

    def _build_ha_chart_df(self) -> pd.DataFrame:
        if self.ha_df.empty:
            return pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        volume_series = (
            self.ha_df['volume']
            if 'volume' in self.ha_df.columns
            else pd.Series([0] * len(self.ha_df))
        )
        return pd.DataFrame(
            {
                'time': self.ha_df['time'],
                'open': self.ha_df['ha_open'],
                'high': self.ha_df['ha_high'],
                'low': self.ha_df['ha_low'],
                'close': self.ha_df['ha_close'],
                'volume': volume_series.values,
            }
        )

    def _latest_ha_series(self) -> Optional[pd.Series]:
        if self.ha_df.empty:
            return None
        row = self.ha_df.iloc[-1]
        volume = row['volume'] if 'volume' in self.ha_df.columns else 0
        return pd.Series(
            {
                'time': row['time'],
                'open': float(row['ha_open']),
                'high': float(row['ha_high']),
                'low': float(row['ha_low']),
                'close': float(row['ha_close']),
                'volume': float(volume),
            }
        )

    def _update_view_mode_buttons(self) -> None:
        if not self.chart:
            return
        try:
            regular_label = 'Regular ✅' if self.view_mode == 'regular' else 'Regular'
            ha_label = 'Heikin-Ashi ✅' if self.view_mode == 'ha' else 'Heikin-Ashi'
            self.chart.topbar['mode_regular'].set(regular_label)
            self.chart.topbar['mode_ha'].set(ha_label)
        except KeyError:
            pass

    def _set_regular_mode(self, chart: Chart):
        self.view_mode = 'regular'
        chart.set(self._get_regular_chart_df())
        self._update_view_mode_buttons()

    def _set_ha_mode(self, chart: Chart):
        self._refresh_heikin_ashi()
        self.view_mode = 'ha'
        chart.set(self._build_ha_chart_df())
        self._update_view_mode_buttons()

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
        self._refresh_heikin_ashi()
        self.chart.set(self._get_regular_chart_df())
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

    async def _fetch_and_store_range(self, start_utc: datetime, end_utc: datetime) -> Dict[str, Any]:
        """Fetch historical data for a range, store it, and return storage stats plus records."""
        collector = IBKRHistoricalCollector()
        try:
            result = await collector.collect_and_store(
                symbol=self.symbol,
                start=start_utc.isoformat(),
                end=end_utc.isoformat(),
                timeframe='1m',
                client_id=self.historical_client_id,
            )
            return {
                'inserted': result.get('inserted', 0),
                'updated': result.get('updated', 0),
                'skipped': result.get('skipped', 0),
                'records': result.get('records', []),
            }
        except Exception as exc:
            logger.error("❌ Historical fetch failed for {}: {}", self.symbol, exc)
            return {'inserted': 0, 'updated': 0, 'skipped': 0, 'records': []}
        finally:
            try:
                await collector.client.close()
            except Exception:
                pass

    async def _backfill_historical_gap(self) -> bool:
        """Fill missing historical data up to the real-time cutoff. Returns True if new data was stored."""
        latest_ts = await self._get_latest_db_timestamp()
        now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        target_end_utc = now_utc - self.realtime_delay

        lookback_floor = min(now_utc - timedelta(days=self.backfill_days), target_end_utc)

        start_candidates: list[datetime] = []

        if latest_ts:
            latest_ts = latest_ts.replace(second=0, microsecond=0)
            if latest_ts >= target_end_utc:
                logger.info(
                    "Historical data up to date for {} (latest {} >= target {}).",
                    self.symbol,
                    latest_ts,
                    target_end_utc,
                )
                return False

            gap_minutes = (target_end_utc - latest_ts).total_seconds() / 60
            if gap_minutes > 1:
                logger.info(
                    "📊 Gap detected: {:.1f} minutes between latest {} and target {}",
                    gap_minutes,
                    latest_ts,
                    target_end_utc,
                )
                start_candidates.append(latest_ts - timedelta(minutes=1))
        else:
            logger.info(
                "⚠️ No historical data detected; fetching lookback window of {} day(s).",
                self.backfill_days,
            )

        session_open_utc, session_close_utc = self._session_bounds_utc(now_utc)
        if session_open_utc < target_end_utc:
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
            start_candidates.append(target_end_utc - timedelta(days=self.backfill_days))

        start_utc = min(start_candidates)
        start_utc = max(lookback_floor, start_utc)

        if start_utc >= target_end_utc:
            logger.info("No historical backfill required for {}", self.symbol)
            return False

        fetch_start = start_utc
        fetch_end = target_end_utc
        attempts = 0
        max_attempts = 4
        progress_made = False

        while attempts < max_attempts:
            if fetch_end <= fetch_start:
                logger.info("ℹ️ Skipping backfill attempt; start {} >= end {}", fetch_start, fetch_end)
                break
            logger.info("🔄 Backfilling {} from {} to {}", self.symbol, fetch_start, fetch_end)
            counts = await self._fetch_and_store_range(fetch_start, fetch_end)
            inserted = counts['inserted']
            updated = counts['updated']
            records = counts.get('records', [])

            if inserted or updated:
                progress_made = True
                logger.info("💾 Backfill stored {} new / {} updated candles for {}", inserted, updated, self.symbol)
            else:
                logger.info("ℹ️ Historical backfill returned no new rows for {}", self.symbol)

            if records:
                await self._publish_historical_records(records)

            if not (inserted or updated):
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
        else:
            logger.info("✅ Historical backfill completed successfully for {}", self.symbol)
        return progress_made

    # --------------------------------------------------------------------- #
    # IBKR real-time collection & aggregation
    # --------------------------------------------------------------------- #
    def _start_collector(self) -> None:
        """Start the asyncio task that talks to IBKR for real-time data."""
        if self.collector_task and not self.collector_task.done():
            logger.warning("Collector already running")
            return
        self.collector_stop_event = asyncio.Event()
        self.collector_running = True
        self.collector_task = asyncio.create_task(self._run_streaming_async(), name="IBKRCollectorTask")
        logger.info("🚀 IBKR collector task started")

    async def _run_streaming_async(self) -> None:
        """Run the IBKR real-time stream inside the main asyncio event loop."""
        ib: Optional[IB] = None
        stop_event = self.collector_stop_event
        try:
            connection = self.ibkr_config.connection
            host = connection.host or "127.0.0.1"
            port = connection.port or 7497
            client_id = connection.client_id or random.randint(1000, 9999)

            logger.info("🔌 Connecting to IBKR (host={} port={} client_id={})", host, port, client_id)
            ib = IB()
            self.ib = ib

            await ib.connectAsync(host, port, clientId=client_id)

            if not ib.isConnected():
                raise RuntimeError("Unable to establish IBKR connection")
            logger.info("✅ Connected to IBKR, subscribing to {}", self.symbol)

            await self._subscribe_to_symbol(self.symbol)

            logger.info("🔄 Collector awaiting stop signal; real-time updates handled by ib_async loop")
            if stop_event:
                await stop_event.wait()

        except asyncio.CancelledError:
            logger.info("IBKR collector task cancelled")
            raise
        except Exception as exc:
            logger.error("❌ Collector task error: {}", exc)
            import traceback
            logger.error("Traceback:\n{}", traceback.format_exc())
        finally:
            logger.info("⏹️ Shutting down IBKR collector...")
            ib_instance = self.ib
            try:
                for sub in self.subscriptions.values():
                    try:
                        if ib_instance:
                            ib_instance.cancelRealTimeBars(sub)
                    except Exception:
                        pass
                self.subscriptions.clear()
                if ib_instance and ib_instance.isConnected():
                    ib_instance.disconnect()
                    logger.info("🔌 Disconnected from IBKR")
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("❌ Error while disconnecting IBKR: {}", exc)
            finally:
                self.collector_running = False
                self.collector_stop_event = None
                self.ib = None

    async def _subscribe_to_symbol(self, symbol: str) -> None:
        """Request 5 second real-time bars for the configured symbol."""
        if not self.ib:
            raise RuntimeError("IBKR connection not established")

        try:
            contract = Stock(symbol, 'SMART', 'USD')
            qualified = await self.ib.qualifyContractsAsync(contract)
            resolved = None
            if qualified:
                resolved = qualified[0]
                if isinstance(resolved, list):
                    resolved = next((item for item in resolved if item is not None), None)
            if resolved:
                contract = resolved
                logger.info("📈 Qualified contract for {} -> {}", symbol, contract)

            subscription = self.ib.reqRealTimeBars(
                contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=False,  # Include extended hours data
                realTimeBarsOptions=[],
            )

            subscription.updateEvent += lambda bars, has_new_bar: self._on_bar_update(symbol, bars, has_new_bar)
            self.subscriptions[symbol] = subscription
            logger.info("📡 Subscribed to {} real-time bars", symbol)
        except Exception as exc:
            logger.error("❌ Failed to subscribe {}: {}", symbol, exc)

    def _on_bar_update(self, symbol: str, bars, has_new_bar: bool) -> None:
        """Aggregate incoming 5 second bars into minute candles."""
        if not has_new_bar or not bars or not self.collector_running:
            return

        latest_bar = bars[-1]
        logger.info(f"📊 Bar received: {latest_bar.time} price=${latest_bar.close:.2f}")
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

    async def _publish_historical_records(self, records: list[Dict[str, Any]]) -> None:
        """Push stored historical records onto the update queue."""
        if not records or not self.update_queue:
            return

        sorted_records = sorted(
            (r for r in records if r.get('timestamp')),
            key=lambda r: r['timestamp'],
        )
        for record in sorted_records:
            timestamp = record['timestamp']
            if isinstance(timestamp, pd.Timestamp):
                timestamp = timestamp.to_pydatetime()
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            payload = {
                'symbol': self.symbol,
                'type': 'historical',
                'candle': {
                    'timestamp': timestamp,
                    'open': record.get('open'),
                    'high': record.get('high'),
                    'low': record.get('low'),
                    'close': record.get('close'),
                    'volume': record.get('volume', 0),
                    'bar_count': record.get('bar_count'),
                },
            }
            await self.update_queue.put(payload)

    async def _run_backfill_manager(self) -> None:
        """Continuously ensure historical data covers everything up to the real-time cutoff."""
        logger.info("🗂️ Backfill manager started")
        try:
            while self.running:
                progress = await self._backfill_historical_gap()
                if not self.running:
                    break
                if not progress:
                    await asyncio.sleep(self.backfill_poll_seconds)
        except asyncio.CancelledError:
            logger.info("Backfill manager task cancelled")
            raise
        except Exception as exc:
            logger.error("❌ Backfill manager encountered an error: {}", exc)
            import traceback
            logger.error("Traceback:\n{}", traceback.format_exc())
        finally:
            logger.info("🗂️ Backfill manager stopped")

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

            inserted_at_end = False
            existing_idx = self.df.index[self.df['time'] == time_str].tolist() if not self.df.empty else []

            if existing_idx:
                idx = existing_idx[0]
                self.df.loc[idx] = series
                inserted_at_end = idx == len(self.df) - 1
            else:
                new_row_df = series.to_frame().T
                if self.df.empty or time_str > self.df.iloc[-1]['time']:
                    self.df = pd.concat([self.df, new_row_df], ignore_index=True)
                    inserted_at_end = True
                else:
                    self.df = pd.concat([self.df, new_row_df], ignore_index=True)
                    self.df.sort_values('time', inplace=True, ignore_index=True)
                self.df = self.df.drop_duplicates(subset='time', keep='last').reset_index(drop=True)
                if len(self.df) > self.history_limit:
                    self.df = self.df.iloc[-self.history_limit :].reset_index(drop=True)

            self.last_update_time = self.df.iloc[-1]['time'] if not self.df.empty else None
            self._refresh_heikin_ashi()
            ha_series = self._latest_ha_series()

            if self.chart:
                try:
                    if update['type'] == 'historical' or not inserted_at_end:
                        if self.view_mode == 'ha':
                            self.chart.set(self._build_ha_chart_df())
                        else:
                            self.chart.set(self._get_regular_chart_df())
                    elif self.view_mode == 'ha' and ha_series is not None:
                        self.chart.update(ha_series)
                    else:
                        self.chart.update(series)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("❌ Failed updating chart: {}", exc)

            if update['type'] == 'complete':
                await self._store_candle(candle)
                logger.info(
                    "💾 SAVED: {} | O:{:.2f} H:{:.2f} L:{:.2f} C:{:.2f} V:{} ({} bars)",
                    time_str,
                    series['open'],
                    series['high'],
                    series['low'],
                    series['close'],
                    series['volume'],
                    candle.get('bar_count', 0),
                )
            elif update['type'] == 'partial':
                logger.info(f"📊 PARTIAL UPDATE: {time_str} C:{series['close']:.2f}")
            elif update['type'] == 'historical':
                logger.debug("📥 Historical candle applied for {}", time_str)

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
        self.backfill_task = asyncio.create_task(self._run_backfill_manager(), name="IBKRBackfillTask")
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
        self.collector_running = False

        if self.collector_stop_event and not self.collector_stop_event.is_set():
            self.collector_stop_event.set()

        if self.collector_task:
            try:
                await asyncio.wait_for(self.collector_task, timeout=5)
            except asyncio.TimeoutError:
                self.collector_task.cancel()
                try:
                    await self.collector_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error("❌ Collector task error during shutdown: {}", exc)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("❌ Collector task error during shutdown: {}", exc)
            finally:
                self.collector_task = None
        self.collector_stop_event = None

        if self.backfill_task:
            self.backfill_task.cancel()
            try:
                await self.backfill_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("❌ Backfill task error during shutdown: {}", exc)
            finally:
                self.backfill_task = None

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
