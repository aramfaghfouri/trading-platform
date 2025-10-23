from __future__ import annotations
from typing import Any, Optional
import pandas as pd
from ib_async import util

from src.brokers.base import BrokerBase
from src.brokers.ibkr.client import IBClient


class IBBroker(BrokerBase):
    def __init__(self, client: Optional[IBClient] = None):
        self.client = client or IBClient()

    def connect(self) -> None:
        self.client.connect()

    def disconnect(self) -> None:
        self.client.disconnect()

    async def connect_async(self) -> None:
        await self.client.connect_async()

    def account_summary(self) -> Any:
        return self.client.account_summary()

    def positions(self) -> Any:
        return self.client.positions()

    def get_historical(self, symbol: str, start: str, end: str,
                       timeframe: str, adjustments: Optional[str] = None) -> pd.DataFrame:
        # IB historical path TBD; for now return empty df (Polygon covers history)
        return pd.DataFrame()

    def subscribe_ticks(self, symbols: list[str], on_tick: Optional[callable] = None) -> Any:
        handles = []
        for s in symbols:
            t = self.client.subscribe_ticks(s)
            handles.append((s, t))
        return handles

    def unsubscribe(self, handle: Any) -> None:
        for s, _ in handle:
            self.client.cancel_ticks(s)

    async def req_historical_data_async(
        self,
        symbol: str,
        end_datetime,
        duration: str,
        bar_size: str,
        what_to_show: str,
        use_rth: bool = True,
        format_date: int = 1,
    ):
        return await self.client.req_historical_data_async(
            symbol,
            end_datetime,
            duration,
            bar_size,
            what_to_show,
            use_rth,
            format_date,
        )

    def place_order(self, symbol: str, side: str, qty: int, order_type: str,
                    limit: Optional[float] = None, stop: Optional[float] = None,
                    tif: str = 'DAY', meta: Optional[dict] = None) -> Any:
        action = 'BUY' if side.lower() == 'buy' else 'SELL'
        return self.client.place_order(symbol, action, qty, limit)

    def cancel_order(self, order_id: Any) -> None:
        # ib_async cancel could be wired if we stored trade refs; omitted for brevity
        pass

    def order_status(self, order_id: Any) -> dict:
        return {}


