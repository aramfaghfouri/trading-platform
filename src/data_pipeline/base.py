from __future__ import annotations
from typing import Protocol, Optional, Callable, Any
import pandas as pd


class HistoricalProviderBase(Protocol):
    def get_historical(self, symbol: str, start: str, end: str,
                       timeframe: str, adjustments: Optional[str] = None) -> pd.DataFrame: ...


class RealtimeProviderBase(Protocol):
    def subscribe(self, symbols: list[str], on_event: Callable[[dict], None]) -> Any: ...
    def unsubscribe(self, handle: Any) -> None: ...


class TradeExecutorBase(Protocol):
    def place(self, symbol: str, side: str, qty: int, order_type: str,
              limit: Optional[float] = None, stop: Optional[float] = None,
              tif: str = 'DAY', meta: Optional[dict] = None) -> Any: ...
    def cancel(self, order_id: Any) -> None: ...
    def status(self, order_id: Any) -> dict: ...


