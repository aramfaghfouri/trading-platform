from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import asyncpg
from pydantic import BaseModel, Field, field_validator

try:
    import tomllib  # Python 3.11+
except Exception as _:
    tomllib = None  # type: ignore
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator

try:
    import tomllib  # Python 3.11+
except Exception as _:
    tomllib = None  # type: ignore


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


class IBKRWindowConfig(BaseModel):
    """Desired collection window and table parameters."""

    table_name: str = Field(..., description="Fully-qualified table, e.g., 'public.ibkr_ohlcv_adbe_1m'")
    timeframe_seconds: int = Field(60, description="Bar interval in seconds (e.g., 60 for 1m)")
    start_time: str = Field(..., description="Window start in 'YYYY-MM-DDTHH:MM:SS' UTC")
    end_time: str = Field(..., description="Window end in 'YYYY-MM-DDTHH:MM:SS' UTC")

    @field_validator("start_time", "end_time")
    def _validate_datetime_format(cls, v: str) -> str:
        datetime.strptime(v, ISO_FORMAT)
        return v

    def start_dt(self) -> datetime:
        return datetime.strptime(self.start_time, ISO_FORMAT).replace(tzinfo=timezone.utc)

    def end_dt(self) -> datetime:
        return datetime.strptime(self.end_time, ISO_FORMAT).replace(tzinfo=timezone.utc)


class ExistingIntervals(BaseModel):
    intervals: List[Tuple[str, str]] = Field(default_factory=list)


class MissingIntervals(BaseModel):
    intervals: List[Tuple[str, str]] = Field(default_factory=list)


async def fetch_sorted_timestamps(dsn: str, table_name: str) -> List[datetime]:
    """Fetch sorted timestamps from a TimescaleDB/Postgres table."""
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(f"SELECT timestamp FROM {table_name} ORDER BY timestamp ASC")
        return [r["timestamp"].replace(tzinfo=timezone.utc) for r in rows]
    finally:
        await conn.close()


def build_existing_intervals(timestamps: List[datetime], bar_seconds: int) -> ExistingIntervals:
    """Collapse sorted timestamps into contiguous intervals allowing up to 1 bar-sized gap."""
    if not timestamps:
        return ExistingIntervals(intervals=[])

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
    return ExistingIntervals(intervals=intervals)


def compute_missing_intervals(
    window_start: datetime,
    window_end: datetime,
    existing: ExistingIntervals,
) -> MissingIntervals:
    """Compute complement of existing intervals inside [window_start, window_end]."""
    missing: List[Tuple[str, str]] = []
    cursor = window_start

    for s_str, e_str in existing.intervals:
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

    return MissingIntervals(intervals=missing)


def load_ibkr_window_from_toml(toml_path: str) -> Tuple[str, str]:
    """Load start_date and end_date under [ibkr.historical] and expand to full-day times in UTC."""
    if tomllib is None:
        raise RuntimeError("tomllib not available; use Python 3.11+")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    ibkr_hist = data.get("ibkr", {}).get("historical", {})
    start_date = ibkr_hist.get("start_date")
    end_date = ibkr_hist.get("end_date")
    if not start_date or not end_date:
        raise ValueError("Missing ibkr.historical.start_date or end_date in project-setup.toml")
    # Expand to full-day bounds in UTC
    start_time = f"{start_date}T00:00:00"
    end_time = f"{end_date}T23:59:59"
    return start_time, end_time


async def main() -> None:
    # Parameters (modify as needed or make them CLI options)
    table_name = os.getenv("IBKR_TABLE", "public.ibkr_ohlcv_adbe_1m")
    timeframe_seconds = int(os.getenv("BAR_SECONDS", "60"))
    project_setup_path = os.getenv("PROJECT_SETUP_TOML", os.path.join(os.path.dirname(os.path.dirname(__file__)), "project-setup.toml"))

    start_time, end_time = load_ibkr_window_from_toml(project_setup_path)

    cfg = IBKRWindowConfig(
        table_name=table_name,
        timeframe_seconds=timeframe_seconds,
        start_time=start_time,
        end_time=end_time,
    )

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        # Fallback to local defaults consistent with docker-compose setup
        dsn = (
            f"postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform"
        )

    timestamps = await fetch_sorted_timestamps(dsn, cfg.table_name)
    existing = build_existing_intervals(timestamps, cfg.timeframe_seconds)
    missing = compute_missing_intervals(cfg.start_dt(), cfg.end_dt(), existing)

    print("Existing intervals (data present):")
    for s, e in existing.intervals[:10]:
        print(f"  ({s}, {e})")
    if len(existing.intervals) > 10:
        print(f"  ... and {len(existing.intervals) - 10} more")

    print("\nMissing intervals within requested window:")
    for s, e in missing.intervals:
        print(f"  ({s}, {e})")


if __name__ == "__main__":
    asyncio.run(main())
