#!/usr/bin/env python3
"""Simple test to read timestamps and print gaps for a symbol."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
import tomllib
import asyncpg


async def test_gaps_for_symbol(symbol: str = "DIS"):
    """Read timestamps from DB and print gaps."""
    
    # 1. Read project-setup.toml
    print(f"📖 Reading project-setup.toml...")
    with open('project-setup.toml', 'rb') as f:
        cfg = tomllib.load(f)
    
    ibkr_hist = cfg.get('ibkr', {}).get('historical', {})
    start_date = ibkr_hist.get('start_date')
    end_date = ibkr_hist.get('end_date')
    
    print(f"   Window: {start_date} to {end_date}")
    
    # 2. Build table name for symbol
    symbol_lower = symbol.lower()
    table_name = f"public.ibkr_ohlcv_{symbol_lower}_1m"
    print(f"   Table: {table_name}")
    
    # 3. Read and sort timestamps from table
    dsn = os.getenv("DATABASE_URL", "postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform")
    print(f"\n📊 Reading timestamps from {table_name}...")
    
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(f"SELECT timestamp FROM {table_name} ORDER BY timestamp ASC")
        timestamps = [r["timestamp"].replace(tzinfo=timezone.utc) for r in rows]
        print(f"   Found {len(timestamps)} timestamps")
    except Exception as e:
        print(f"   ❌ Error reading table: {e}")
        await conn.close()
        return
    finally:
        await conn.close()
    
    if not timestamps:
        print("   ⚠️  No data found in table")
        return
    
    # 4. Build existing intervals (collapse contiguous timestamps)
    print(f"\n🔍 Building existing intervals...")
    intervals = []
    start = timestamps[0]
    prev = timestamps[0]
    max_gap = timedelta(minutes=1)
    
    for ts in timestamps[1:]:
        if ts - prev > max_gap:
            intervals.append((start, prev))
            start = ts
        prev = ts
    intervals.append((start, prev))
    
    print(f"   Existing intervals: {len(intervals)}")
    print("\n📅 Existing data intervals (first 10):")
    for i, (s, e) in enumerate(intervals[:10]):
        print(f"   {i+1}. {s.strftime('%Y-%m-%d %H:%M:%S')} to {e.strftime('%Y-%m-%d %H:%M:%S')}")
    if len(intervals) > 10:
        print(f"   ... and {len(intervals) - 10} more")
    
    # 5. Compute missing intervals within window
    print(f"\n🔎 Computing missing intervals...")
    window_start = datetime.strptime(f"{start_date}T00:00:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    window_end = datetime.strptime(f"{end_date}T23:59:59", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    
    missing = []
    cursor = window_start
    
    for s, e in intervals:
        if e < window_start or s > window_end:
            continue
        seg_start = max(window_start, s)
        seg_end = min(window_end, e)
        if cursor < seg_start:
            missing.append((cursor, seg_start))
        cursor = max(cursor, seg_end)
    
    if cursor < window_end:
        missing.append((cursor, window_end))
    
    print(f"   Missing intervals: {len(missing)}")
    print("\n⚠️  GAPS (missing data):")
    for i, (s, e) in enumerate(missing):
        days = (e - s).days
        print(f"   {i+1}. {s.strftime('%Y-%m-%d %H:%M:%S')} to {e.strftime('%Y-%m-%d %H:%M:%S')} ({days} days)")
    
    if not missing:
        print("   ✅ No gaps found - data is complete!")


if __name__ == "__main__":
    asyncio.run(test_gaps_for_symbol("DIS"))

