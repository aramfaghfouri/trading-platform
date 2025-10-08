#!/usr/bin/env python3
"""Collect IBKR historical data for all symbols from project-setup.toml

Enhanced to be gap-aware:
 - Reads existing timestamps from the DB per symbol
 - Computes missing intervals within the configured window
 - Splits requests into chunks of at most d_max_days
 - Supports --dry-run to preview intervals
"""

import os
import argparse
import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine
import tomllib
from loguru import logger # Ensure loguru is imported and used

from src.data_collectors.ibkr.historical import IBKRHistoricalCollector
from src.data_collectors.ibkr.client import IBKRDataClient

# Reuse the gap utilities implemented in src/test100.py
from src.shared.utils.gap_finder import (
    fetch_sorted_timestamps,
    build_existing_intervals,
    compute_missing_intervals,
    subtract_existing,
    chunk_interval,
)

# Configure logger if necessary (loguru is already configured by default)
# logger.remove() # Uncomment if you want to remove default handlers
# logger.add(sys.stderr, level="DEBUG") # Example: Add specific handler

with open('project-setup.toml', 'rb') as f:
    cfg = tomllib.load(f)

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

hist = cfg.get('ibkr', {}).get('historical', cfg.get('ibkr_historical', {}))
conn = cfg.get('ibkr', {}).get('connection', {})

tf = hist.get('timeframe', '1m')
start_date_str = hist.get('start_date', '2024-10-01')
end_date_str = hist.get('end_date', '2024-10-06')
d_max_days = int(hist.get('d_max_days', 10))
useRTH = bool(hist.get('useRTH', True))
whatToShow = hist.get('what_to_show', 'TRADES')
symbols = hist.get('symbols', ['AAPL'])

host = conn.get('host', '127.0.0.1')
port = int(conn.get('port_paper', 7497))
client_id = int(conn.get('client_id', 102))

print(f"📊 Configuration:")
print(f"   Timeframe: {tf}")
print(f"   Period: {start_date_str} to {end_date_str}")
print(f"   d_max_days: {d_max_days}")
print(f"   Symbols: {len(symbols)} total")
print(f"   IBKR: {host}:{port} (client_id={client_id})")
print()


def _build_table_name(symbol: str, timeframe: str) -> str:
    naming = cfg.get('ibkr', {}).get('naming', {})
    pattern = naming.get('table_pattern', '{source}_ohlcv_{symbol}_{tf}')
    source = naming.get('source_prefix', 'ibkr')
    table = pattern.format(source=source, symbol=symbol.lower(), tf=timeframe)
    # Assume public schema
    return f"public.{table}"


def _get_dsn() -> str:
    dsn = os.getenv('DATABASE_URL')
    if dsn:
        return dsn
    # Default to local docker mapping (port 6432)
    return 'postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform'

def build_trading_sessions(
    window_start: datetime,
    window_end: datetime,
    timeframe: str,
    use_rth: bool = True,
) -> list[tuple[datetime, datetime]]:
    """Generate trading sessions between window_start and window_end.

    For minute-level data with RTH enabled, limit sessions to regular hours
    (13:30-20:00 UTC, roughly 09:30-16:00 ET). For other cases fall back to
    full-day windows.
    """

    sessions: list[tuple[datetime, datetime]] = []
    current_date = window_start.date()
    last_date = window_end.date()

    while current_date <= last_date:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() < 5:
            if use_rth and timeframe.endswith("m"):
                start_dt = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    13,
                    30,
                    0,
                    tzinfo=timezone.utc,
                )
                end_dt = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    20,
                    0,
                    0,
                    tzinfo=timezone.utc,
                )
            else:
                start_dt = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    0,
                    0,
                    0,
                    tzinfo=timezone.utc,
                )
                end_dt = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    23,
                    59,
                    59,
                    tzinfo=timezone.utc,
                )

            # Clamp session within user-provided window
            session_start = max(start_dt, window_start)
            session_end = min(end_dt, window_end)

            if session_start < session_end:
                sessions.append((session_start, session_end))

        current_date = current_date + timedelta(days=1)

    return sessions


async def monitor_coroutine(coro: Coroutine[Any, Any, Any], label: str, heartbeat: int) -> Any:
    """Emit heartbeat messages while awaiting a coroutine."""
    task = asyncio.create_task(coro)
    start = time.time()
    try:
        while True:
            try:
                return await asyncio.wait_for(task, timeout=heartbeat)
            except asyncio.TimeoutError:
                elapsed = time.time() - start
                print(f"[heartbeat] {label} still running ({elapsed:.1f}s elapsed)", flush=True)
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def main() -> None:
    print("[collect_ibkr_all] Entered main()", flush=True)

    parser = argparse.ArgumentParser(description="Gap-aware IBKR historical collector")
    parser.add_argument("--dry-run", action="store_true", help="Print planned requests without fetching")
    parser.add_argument("--gaps-limit", type=int, default=20, help="Max gaps to print per symbol (default: 20)")
    parser.add_argument("--heartbeat", type=int, default=15, help="Seconds between progress heartbeats (default: 15)")
    args = parser.parse_args()
    heartbeat = max(1, args.heartbeat)
    print(
        f"[collect_ibkr_all] Parsed args dry_run={args.dry_run}, gaps_limit={args.gaps_limit}, "
        f"heartbeat={heartbeat}",
        flush=True,
    )

    client = IBKRDataClient()
    client.broker.client.host = host
    client.broker.client.port = port
    client.broker.client.client_id = client_id
    client._connected = False
    collector = IBKRHistoricalCollector(client=client)
    print("[collect_ibkr_all] IBKR client initialized", flush=True)

    results: list[tuple[str, dict]] = []
    total_symbols = len(symbols)
    print("=" * 80)
    print(f"📊 Processing {total_symbols} symbols")
    print("=" * 80 + "\n")

    # Determine bar seconds (default to 60 for minute timeframe)
    if tf.endswith("m"):
        try:
            bar_seconds = int(tf.rstrip("m")) * 60
        except ValueError:
            bar_seconds = 60
    else:
        bar_seconds = 60

    for idx, symbol in enumerate(symbols, start=1):
        print(f"[collect_ibkr_all] ===== Symbol {idx}/{total_symbols}: {symbol} =====", flush=True)
        print("=" * 80)
        print(f"Symbol {idx}/{total_symbols}: {symbol}")
        print("=" * 80)

        window_start = datetime.strptime(f"{start_date_str}T00:00:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        window_end = datetime.strptime(f"{end_date_str}T23:59:59", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        table_name = _build_table_name(symbol, tf)
        dsn = _get_dsn()
        print(f"[collect_ibkr_all] Window: {window_start} -> {window_end}", flush=True)
        print(f"[collect_ibkr_all] Table: {table_name}", flush=True)

        try:
            print(f"📊 Reading existing data from {table_name}...")
            timestamps = await monitor_coroutine(
                fetch_sorted_timestamps(dsn, table_name),
                f"TimescaleDB fetch for {symbol}",
                heartbeat,
            )
            print(f"   Found {len(timestamps)} existing bars")
            print(f"[collect_ibkr_all] Retrieved {len(timestamps)} timestamps", flush=True)
        except Exception as exc:
            logger.warning("Failed to read timestamps for {} from {}: {}", symbol, table_name, exc)
            timestamps = []
            print("   No existing data found (table may not exist yet)")
            print(f"[collect_ibkr_all] Timestamp read failed: {exc}", flush=True)

        raw_intervals = build_existing_intervals(timestamps, bar_seconds)
        expanded_intervals: list[tuple[str, str]] = []
        extend_delta = timedelta(seconds=max(bar_seconds - 1, 0))
        for s_str, e_str in raw_intervals:
            s_dt = datetime.strptime(s_str, ISO_FORMAT).replace(tzinfo=timezone.utc)
            e_dt = datetime.strptime(e_str, ISO_FORMAT).replace(tzinfo=timezone.utc) + extend_delta
            expanded_intervals.append((s_dt.strftime(ISO_FORMAT), e_dt.strftime(ISO_FORMAT)))

        existing_intervals = expanded_intervals
        trading_sessions = build_trading_sessions(window_start, window_end, tf, useRTH)

        missing_intervals: list[tuple[str, str]] = []

        for session_start, session_end in trading_sessions:
            if session_start >= session_end:
                continue

            session_missing = subtract_existing(
                session_start,
                session_end,
                existing_intervals,
                min_seconds=bar_seconds,
            )
            if session_missing:
                missing_intervals.extend(session_missing)

        if missing_intervals:
            missing_intervals = sorted(set(missing_intervals), key=lambda pair: pair[0])

        print(f"[collect_ibkr_all] Existing interval count: {len(existing_intervals)}", flush=True)
        print(f"[collect_ibkr_all] Trading session count: {len(trading_sessions)}", flush=True)
        print(f"[collect_ibkr_all] Missing interval count: {len(missing_intervals)}", flush=True)

        total_gaps = len(missing_intervals)
        print("\n🔍 Gap Analysis:")
        if total_gaps == 0:
            print("   ✅ No gaps found for trading sessions - skipping symbol")
            results.append((symbol, {"success": True, "inserted": 0, "error": None}))
            continue

        print(f"   Total gaps found: {total_gaps}")
        show_n = min(args.gaps_limit, total_gaps)
        print(f"   Showing first {show_n} gaps:")
        for gap_idx, (gs, ge) in enumerate(missing_intervals[:show_n], start=1):
            gs_dt = datetime.strptime(gs, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            ge_dt = datetime.strptime(ge, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            duration_days = (ge_dt - gs_dt).days
            print(f"   {gap_idx:3d}. {gs} to {ge} ({duration_days} days)")
        if total_gaps > show_n:
            print(f"   ... and {total_gaps - show_n} more gaps")

        print(f"\n📦 Planning collection chunks (max {d_max_days} days per chunk)...")
        planned_chunks: list[tuple[str, str]] = []
        for s_str, e_str in missing_intervals:
            s_dt = datetime.strptime(s_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            e_dt = datetime.strptime(e_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            for c_s, c_e in chunk_interval(s_dt, e_dt, d_max_days):
                c_s_dt = datetime.strptime(c_s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                c_e_dt = datetime.strptime(c_e, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                sub_chunks = subtract_existing(c_s_dt, c_e_dt, existing_intervals)
                planned_chunks.extend(sub_chunks)
        print(f"[collect_ibkr_all] Planned chunk count: {len(planned_chunks)}", flush=True)

        print(f"   Total collection chunks: {len(planned_chunks)}")
        if planned_chunks:
            print(f"   First chunk: {planned_chunks[0][0]} to {planned_chunks[0][1]}")
            if len(planned_chunks) > 1:
                print(f"   Last chunk:  {planned_chunks[-1][0]} to {planned_chunks[-1][1]}")

        if args.dry_run:
            print(f"\n🔍 DRY RUN - Skipping actual data collection for {symbol}")
            results.append((symbol, {"success": True, "inserted": 0, "error": None}))
            print(f"[collect_ibkr_all] Dry-run completed for {symbol}", flush=True)
            continue

        if not client._connected:
            print("\n🔌 Connecting to IBKR before collection...")
            try:
                await asyncio.wait_for(client.broker.connect_async(), timeout=10.0)
                client._connected = True
                print("✅ Successfully connected to IBKR!\n")
                print("[collect_ibkr_all] IBKR connection established", flush=True)
            except asyncio.TimeoutError:
                err = "connect_timeout"
                print("❌ IBKR connection timeout - skipping collection for this symbol")
                print(f"[collect_ibkr_all] Connection timeout for {symbol}", flush=True)
                results.append((symbol, {"success": False, "inserted": 0, "error": err}))
                continue
            except Exception as exc:
                err = f"connect_failed:{exc}"
                print(f"❌ IBKR connection failed ({exc}) - skipping collection for this symbol")
                print(f"[collect_ibkr_all] Connection failure for {symbol}: {exc}", flush=True)
                results.append((symbol, {"success": False, "inserted": 0, "error": err}))
                continue

        print(f"\n📥 Collecting data for {symbol}...")
        symbol_bars_collected = 0
        symbol_errors: list[str] = []

        for chunk_idx, (seg_start, seg_end) in enumerate(planned_chunks, start=1):
            print(f"[collect_ibkr_all] Chunk {chunk_idx}/{len(planned_chunks)}: {seg_start} -> {seg_end}", flush=True)
            try:
                print(f"   Chunk {chunk_idx}/{len(planned_chunks)}: {seg_start} to {seg_end}", end=" ")
                res = await monitor_coroutine(
                    collector.collect_and_store(symbol, seg_start, seg_end, tf),
                    f"IBKR chunk {chunk_idx}/{len(planned_chunks)} for {symbol}",
                    heartbeat,
                )
                if res.get("success"):
                    bars_inserted = res.get("inserted", 0)
                    symbol_bars_collected += bars_inserted
                    print(f"✅ {bars_inserted} bars")
                else:
                    error_msg = res.get("error", "Unknown error")
                    symbol_errors.append(error_msg)
                    print(f"❌ {error_msg}")
            except Exception as exc:
                symbol_errors.append(str(exc))
                print(f"❌ {exc}")
                logger.exception("Full traceback for {} during segment {} to {}:", symbol, seg_start, seg_end)

        final_result = {
            "success": not symbol_errors,
            "inserted": symbol_bars_collected,
            "error": ", ".join(symbol_errors) if symbol_errors else None,
        }
        results.append((symbol, final_result))
        print(f"[collect_ibkr_all] Final result for {symbol}: {final_result}", flush=True)

        if final_result["success"]:
            print(f"\n✅ {symbol} completed: {final_result['inserted']:,} bars collected")
        else:
            print(f"\n❌ {symbol} failed: {final_result['error']}")

    print("\n" + "=" * 80)
    print("📊 COLLECTION SUMMARY")
    print("=" * 80)
    total_bars = sum(res[1].get("inserted", 0) for res in results)
    successes = sum(1 for _, res in results if res.get("success"))
    print(f"[collect_ibkr_all] Summary: {successes}/{total_symbols} succeeded, {total_bars} total bars", flush=True)
    print(f"✅ Successful: {successes}/{total_symbols}")
    print(f"📊 Total bars collected: {total_bars:,}")
    print()
    
    for symbol, res in results:
        print(f"[collect_ibkr_all] Summary entry {symbol}: {res}", flush=True)
        if res.get("success"):
            print(f"  ✅ {symbol:6s}: {res.get('inserted', 0):,} bars")
        else:
            print(f"  ❌ {symbol:6s}: {res.get('error', 'Unknown error')}")


if __name__ == "__main__":
    asyncio.run(main())
