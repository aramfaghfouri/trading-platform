from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
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


def segment_date_range(start: str, end: str, max_days: int = 365) -> List[Tuple[str, str]]:
    """
    Segment a date range into monthly chunks for IBKR historical data requests.
    This approach is more conservative and avoids IBKR's 365-day limit issues.
    
    Args:
        start: Start date in ISO format (YYYY-MM-DD)
        end: End date in ISO format (YYYY-MM-DD)
        max_days: Maximum days per segment (unused in monthly approach)
    
    Returns:
        List of (start_date, end_date) tuples in ISO format
    """
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    
    segments = []
    current_start = start_dt
    
    while current_start < end_dt:
        # Calculate end of current month
        if current_start.month == 12:
            next_month = current_start.replace(year=current_start.year + 1, month=1, day=1)
        else:
            next_month = current_start.replace(month=current_start.month + 1, day=1)
        
        # Segment end is last day of current month, but not beyond end_dt
        segment_end = min(next_month - timedelta(days=1), end_dt)
        
        segments.append((
            current_start.strftime("%Y-%m-%d"),
            segment_end.strftime("%Y-%m-%d")
        ))
        
        # Move to first day of next month
        current_start = next_month
    
    return segments


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
        
        # Segment the date range into monthly chunks for IBKR requests
        segments = segment_date_range(start_date, end_date)
        
        logger.info("Fetching %s data for %s in %d segments", tf, symbol, len(segments))
        
        all_bars = []
        
        # Connect only once
        if not self._connected:
            logger.info("Attempting to connect to IBKR at %s:%s (client_id: %s)", 
                       self.broker.client.host, self.broker.client.port, self.broker.client.client_id)
            
            try:
                logger.info("⏳ Connecting to IBKR (this may take a few seconds)...")
                await asyncio.wait_for(self.broker.connect_async(), timeout=5.0)
                self._connected = True
                logger.info("✅ Successfully connected to IBKR")
            except asyncio.TimeoutError:
                logger.error("❌ Connection timeout - IBKR TWS/Gateway not responding")
                logger.error("Please ensure IBKR TWS/Gateway is running on port %s", self.broker.client.port)
                raise
            except Exception as e:
                logger.error("❌ Failed to connect to IBKR: %s", e)
                logger.error("Please ensure IBKR TWS/Gateway is running on port %s", self.broker.client.port)
                raise
        
        for i, (seg_start, seg_end) in enumerate(segments, 1):
            logger.info("Processing segment %d/%d: %s to %s", i, len(segments), seg_start, seg_end)
            
            start_dt = datetime.fromisoformat(seg_start)
            end_dt = datetime.fromisoformat(seg_end)
            delta_days = max(1, (end_dt - start_dt).days or 1)
            duration = f"{delta_days} D"

            try:
                logger.info("📊 Requesting %s data for %s: %s to %s (%s)", tf, symbol, seg_start, seg_end, duration)
                bars = await asyncio.wait_for(
                    self.broker.req_historical_data_async(
                        symbol,
                        end_dt,
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
                    logger.info("Retrieved %d bars for segment %d", len(bars), i)
                else:
                    logger.warning("No bars returned for segment %d: %s to %s", i, seg_start, seg_end)
                    
            except asyncio.TimeoutError:
                logger.error("⏰ Timeout fetching segment %d (%s to %s) for %s", i, seg_start, seg_end, symbol)
                continue
            except Exception as e:
                logger.error("❌ Error fetching segment %d (%s to %s) for %s: %s", i, seg_start, seg_end, symbol, e)
                continue

        if not all_bars:
            logger.warning("IBKR returned no bars for %s across all segments", symbol)
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
        
        logger.info("Combined %d total bars for %s", len(df), symbol)
        return df

    async def close(self) -> None:
        try:
            self.broker.disconnect()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("IBKR disconnect threw: %s", exc)
