from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio

import pandas as pd
from loguru import logger
from ib_insync import Stock, util

from src.brokers.ibkr.adapters import IBBroker
from src.data_pipeline.base import HistoricalProviderBase
from src.data_collectors.common.source_storage import SourceDataStorage


class IBKRHistoricalCollector(HistoricalProviderBase):
    """Historical collector using IBKR (note: subject to IB historical limits)."""

    def __init__(self, broker: Optional[IBBroker] = None):
        self.broker = broker or IBBroker()

    def get_historical(self, symbol: str, start: str, end: str,
                       timeframe: str, adjustments: Optional[str] = None) -> pd.DataFrame:
        """Fetch historical bars from IBKR for a symbol between start and end.

        start/end: ISO dates (YYYY-MM-DD or with time). timeframe: '1m','5m','1d'.
        """
        try:
            # Map timeframe
            bar_map = {'1m': '1 min', '5m': '5 mins', '1d': '1 day'}
            bar_size = bar_map.get(timeframe, '1 min')
            # Compute duration (IB expects like '30 D')
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            delta_days = max(1, (end_dt - start_dt).days or 1)
            duration = f"{delta_days} D"

            # IB requires endDateTime; use end_dt
            self.broker.connect()
            ib = self.broker.client.ib
            contract = Stock(symbol, 'SMART', 'USD')
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_dt,
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            self.broker.disconnect()
            if not bars:
                return pd.DataFrame()
            df = util.df(bars)
            if not df.empty:
                df.rename(columns={
                    'date': 'timestamp',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume'
                }, inplace=True)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"IBKR historical fetch failed: {e}")
            try:
                self.broker.disconnect()
            except Exception:
                pass
            return pd.DataFrame()

    async def collect_and_store(self, symbol: str, start: str, end: str, timeframe: str) -> dict:
        """Scaffold method: when implemented, will store to ibkr_ohlcv_<symbol>_<tf>."""
        df = self.get_historical(symbol, start, end, timeframe)
        records: List[Dict[str, Any]] = []
        if not df.empty:
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
        async with SourceDataStorage('ibkr') as storage:
            res = await storage.store_ohlcv(symbol, timeframe, records)
            return {
                'success': res.success,
                'inserted': res.records_inserted,
                'updated': res.records_updated,
                'skipped': res.records_skipped,
                'error': res.error,
            }


