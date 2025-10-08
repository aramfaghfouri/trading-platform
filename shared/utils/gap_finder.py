from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import asyncpg


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


async def fetch_sorted_timestamps(dsn: str, table_name: str) -> List[datetime]:
    """Fetch sorted timestamps from a TimescaleDB/Postgres table."""
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(f"SELECT timestamp FROM {table_name} ORDER BY timestamp ASC")
        return [r["timestamp"].replace(tzinfo=timezone.utc) for r in rows]
    finally:
        await conn.close()


def build_existing_intervals(timestamps: List[datetime], bar_seconds: int) -> List[Tuple[str, str]]:
    """Collapse sorted timestamps into contiguous intervals allowing up to 1 bar-sized gap."""
    if not timestamps:
        return []

    intervals: List[Tuple[str, str]] = []
    start = timestamps[0]
    prev = timestamps[0]
    max_gap = timedelta(seconds=bar_seconds)

    for ts in timestamps[1:]:
        if ts - prev > max_gap:
            intervals.append((start.strftime(ISO_FORMAT), prev.strftime(ISO_FORMAT)))
            start = ts
        prev = ts

    intervals.append((start.strftime(ISO_FORMAT), prev.strftime(ISO_FORMAT)))
    return intervals


def compute_missing_intervals(
    window_start: datetime,
    window_end: datetime,
    existing_intervals: List[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """Compute complement of existing intervals inside [window_start, window_end]."""
    missing: List[Tuple[str, str]] = []
    cursor = window_start

    for s_str, e_str in existing_intervals:
        s = datetime.strptime(s_str, ISO_FORMAT).replace(tzinfo=timezone.utc)
        e = datetime.strptime(e_str, ISO_FORMAT).replace(tzinfo=timezone.utc)
        if e < window_start or s > window_end:
            continue
        seg_start = max(window_start, s)
        seg_end = min(window_end, e)
        if cursor < seg_start:
            missing.append((cursor.strftime(ISO_FORMAT), seg_start.strftime(ISO_FORMAT)))
        cursor = max(cursor, seg_end)

    if cursor < window_end:
        missing.append((cursor.strftime(ISO_FORMAT), window_end.strftime(ISO_FORMAT)))

    return missing


def subtract_existing(
    chunk_start: datetime,
    chunk_end: datetime,
    existing_intervals: List[Tuple[str, str]],
    min_seconds: int = 60,
) -> List[Tuple[str, str]]:
    """Subtract existing intervals from a requested chunk, returning zero or more sub-chunks.

    Boundaries are trimmed by one second to avoid inclusive-end overlap.
    """
    remaining: List[Tuple[datetime, datetime]] = [(chunk_start, chunk_end)]
    for s_str, e_str in existing_intervals:
        exist_s = datetime.strptime(s_str, ISO_FORMAT).replace(tzinfo=timezone.utc)
        exist_e = datetime.strptime(e_str, ISO_FORMAT).replace(tzinfo=timezone.utc)
        new_remaining: List[Tuple[datetime, datetime]] = []
        for r_s, r_e in remaining:
            if r_e <= exist_s or r_s >= exist_e:
                new_remaining.append((r_s, r_e))
                continue
            left_end = min(r_e, exist_s - timedelta(seconds=1))
            if r_s < exist_s and r_s < left_end:
                new_remaining.append((r_s, left_end))
            right_start = max(r_s, exist_e + timedelta(seconds=1))
            if right_start < r_e:
                new_remaining.append((right_start, r_e))
        remaining = new_remaining
        if not remaining:
            break

    result: List[Tuple[str, str]] = []
    for r_s, r_e in remaining:
        if (r_e - r_s).total_seconds() >= min_seconds:
            result.append((r_s.strftime(ISO_FORMAT), r_e.strftime(ISO_FORMAT)))
    return result


def chunk_interval(start_dt: datetime, end_dt: datetime, max_days: int) -> List[Tuple[str, str]]:
    """Split [start_dt, end_dt] into inclusive chunks of at most max_days."""
    out: List[Tuple[str, str]] = []
    cursor = start_dt
    delta = timedelta(days=max_days)
    while cursor < end_dt:
        nxt = min(cursor + delta, end_dt)
        out.append((cursor.strftime(ISO_FORMAT), nxt.strftime(ISO_FORMAT)))
        cursor = nxt
    return out


