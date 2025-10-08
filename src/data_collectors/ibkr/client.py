from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import math
from typing import Optional, List, Tuple

import pandas as pd
from loguru import logger

from src.brokers.ibkr.adapters import IBBroker
from src.core.config_loader import ConfigLoader


BAR_SIZE_MAP = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "30m": "30 mins",
    "1h": "1 hour",
    "1d": "1 day",
}


def segment_date_range(start: str, end: str, max_days: int = 10) -> List[Tuple[datetime, datetime]]:
    """Split a date/time range into chunks <= max_days while preserving intraday bounds."""

    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    if start_dt >= end_dt:
        return [(start_dt, end_dt)]

    segments: List[Tuple[datetime, datetime]] = []
    cursor = start_dt
    max_delta = timedelta(days=max_days)

    while cursor < end_dt:
        next_cursor = min(cursor + max_delta, end_dt)
        if next_cursor <= cursor:
            break
        segments.append((cursor, next_cursor))
        cursor = next_cursor

    return segments


def _format_ib_duration(start_dt: datetime, end_dt: datetime) -> str:
    """Format a duration string acceptable by IBKR based on the interval length."""

    delta = end_dt - start_dt
    total_seconds = max(int(delta.total_seconds()), 60)

    if total_seconds <= 12 * 3600:
        return f"{total_seconds} S"
    if total_seconds <= 30 * 86400:
        days = max(1, math.ceil(total_seconds / 86400))
        return f"{days} D"
    weeks = max(1, math.ceil(total_seconds / (7 * 86400)))
    return f"{weeks} W"


class IBKRDataClient:
    """Lightweight async client for fetching historical bars from IBKR."""

    def __init__(self, broker: Optional[IBBroker] = None):
        self.broker = broker or IBBroker()
        self.loader = ConfigLoader()
        self._connected = False

    async def fetch_bars(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
    ) -> pd.DataFrame:
        hist_cfg = self.loader.get_provider_setup("ibkr", "historical")

        tf = timeframe or hist_cfg.get("timeframe", "1m")
        bar_size = BAR_SIZE_MAP.get(tf, "1 min")

        start_date = start or hist_cfg.get("start_date")
        end_date = end or hist_cfg.get("end_date")

        segments = segment_date_range(
            start_date,
            end_date,
            hist_cfg.get("d_max_days", 10),
        )

        logger.info("Fetching {} data for {} in {} segments", tf, symbol, len(segments))
        
        all_bars = []
        
        # Connect only once
        if not self._connected:
            logger.info(
                "Attempting to connect to IBKR at {}:{} (client_id: {})",
                self.broker.client.host,
                self.broker.client.port,
                self.broker.client.client_id,
            )
            
            try:
                logger.info("⏳ Connecting to IBKR (this may take a few seconds)...")
                await asyncio.wait_for(self.broker.connect_async(), timeout=5.0)
                self._connected = True
                logger.info("✅ Successfully connected to IBKR")
            except asyncio.TimeoutError:
                logger.error("❌ Connection timeout - IBKR TWS/Gateway not responding")
                logger.error("Please ensure IBKR TWS/Gateway is running on port {}", self.broker.client.port)
                raise
            except Exception as e:
                logger.error("❌ Failed to connect to IBKR: {}", e)
                logger.error("Please ensure IBKR TWS/Gateway is running on port {}", self.broker.client.port)
                raise
        
        for i, (seg_start_dt, seg_end_dt) in enumerate(segments, 1):
            if seg_end_dt <= seg_start_dt:
                logger.debug("Skipping empty segment {} -> {}", seg_start_dt, seg_end_dt)
                continue

            duration = _format_ib_duration(seg_start_dt, seg_end_dt)
            logger.info(
                "Processing segment {}/{}: {} to {} (duration {})",
                i,
                len(segments),
                seg_start_dt.isoformat(),
                seg_end_dt.isoformat(),
                duration,
            )

            # IB requires endDateTime to be the end of the interval; add a small buffer to ensure inclusivity
            request_end_dt = seg_end_dt + timedelta(seconds=30)

            try:
                logger.info(
                    "📊 Requesting {} data for {}: {} to {} ({})",
                    tf,
                    symbol,
                    seg_start_dt.isoformat(),
                    seg_end_dt.isoformat(),
                    duration,
                )
                bars = await asyncio.wait_for(
                    self.broker.req_historical_data_async(
                        symbol,
                        request_end_dt,
                        duration,
                        bar_size,
                        str(hist_cfg.get("what_to_show", "TRADES")),
                        bool(hist_cfg.get("useRTH", True)),
                        1,
                    ),
                    timeout=30.0
                )
                
                if bars:
                    all_bars.extend(bars)
                    logger.info("Retrieved {} bars for segment {}", len(bars), i)
                else:
                    logger.warning(
                        "No bars returned for segment {}: {} to {}",
                        i,
                        seg_start_dt.isoformat(),
                        seg_end_dt.isoformat(),
                    )

            except asyncio.TimeoutError:
                logger.error(
                    "⏰ Timeout fetching segment {} ({} to {}) for {}",
                    i,
                    seg_start_dt.isoformat(),
                    seg_end_dt.isoformat(),
                    symbol,
                )
                continue
            except Exception as e:
                logger.error(
                    "❌ Error fetching segment {} ({} to {}) for {}: {}",
                    i,
                    seg_start_dt.isoformat(),
                    seg_end_dt.isoformat(),
                    symbol,
                    e,
                )
                continue

        if not all_bars:
            logger.warning("IBKR returned no bars for {} across all segments", symbol)
            return pd.DataFrame()

        # Combine all bars from all segments
        df = pd.DataFrame([b.__dict__ for b in all_bars]) if not isinstance(all_bars[0], dict) else pd.DataFrame(all_bars)
        if df.empty:
            return df

        if "date" in df.columns:
            df.rename(columns={"date": "timestamp"}, inplace=True)
        df.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
            inplace=True,
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        
        # Remove duplicates and sort by timestamp
        df = df[~df.index.duplicated(keep='last')].sort_index()
        
        logger.info("Combined {} total bars for {}", len(df), symbol)
        return df

    async def close(self) -> None:
        try:
            self.broker.disconnect()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("IBKR disconnect threw: {}", exc)
