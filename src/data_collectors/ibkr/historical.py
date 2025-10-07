from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio

import pandas as pd
from loguru import logger
from ib_insync import Stock, util
from src.core.config_loader import ConfigLoader

from src.data_pipeline.base import HistoricalProviderBase
from src.data_collectors.ibkr.client import IBKRDataClient
from src.data_collectors.ibkr.data_storage import IBKRDataStorage


class IBKRHistoricalCollector(HistoricalProviderBase):
    """Historical collector using IBKR (note: subject to IB historical limits)."""

    def __init__(self, client: Optional[IBKRDataClient] = None, storage: Optional[IBKRDataStorage] = None):
        self.client = client or IBKRDataClient()
        self.storage = storage or IBKRDataStorage()
        self.loader = ConfigLoader()

    async def _fetch_historical(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
        adjustments: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch historical bars from IBKR for a symbol between start and end."""
        try:
            return await self.client.fetch_bars(symbol, start, end, timeframe)
        except asyncio.TimeoutError:
            logger.error("❌ Connection timeout for %s - IBKR TWS/Gateway not responding", symbol)
            raise  # Don't silently catch connection errors
        except ConnectionError as e:
            logger.error("❌ Connection error for %s: %s", symbol, e)
            raise  # Don't silently catch connection errors
        except Exception as e:
            logger.error("❌ IBKR historical fetch failed for %s: %s", symbol, e)
            logger.exception("Full traceback:")
            return pd.DataFrame()

    async def collect_and_store(self, symbol: str, start: str, end: str, timeframe: str) -> dict:
        """Scaffold method: when implemented, will store to ibkr_ohlcv_<symbol>_<tf>."""
        logger.info("🔄 Starting collection for %s (%s to %s, %s)", symbol, start, end, timeframe)
        df = await self._fetch_historical(symbol, start, end, timeframe)
        records: List[Dict[str, Any]] = []
        if not df.empty:
            logger.info("📊 Processing %d bars for %s", len(df), symbol)
            for ts, row in df.iterrows():
                records.append({
                    'timestamp': ts,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row.get('volume', 0)),
                    'vwap': float(row.get('vwap')) if 'vwap' in row else None,
                    'transactions': int(row.get('transactions', 0)) if 'transactions' in row else None,
                })
        else:
            logger.warning("⚠️  No data retrieved for %s", symbol)
            
        async with self.storage as storage:
            res = await storage.store_ohlcv(symbol, timeframe, records)
            logger.info("💾 Storage result for %s: %s", symbol, res)
            return {
                'success': res.success,
                'inserted': res.records_inserted,
                'updated': res.records_updated,
                'skipped': res.records_skipped,
                'error': res.error,
            }


