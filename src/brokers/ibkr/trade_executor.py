from __future__ import annotations
from typing import Any, Optional

from src.data_pipeline.base import TradeExecutorBase
from src.brokers.ibkr.adapters import IBBroker


class IBKRTradeExecutor(TradeExecutorBase):
    def __init__(self, broker: IBBroker | None = None):
        self.broker = broker or IBBroker()

    def place(self, symbol: str, side: str, qty: int, order_type: str,
              limit: Optional[float] = None, stop: Optional[float] = None,
              tif: str = 'DAY', meta: Optional[dict] = None) -> Any:
        return self.broker.place_order(symbol, side, qty, order_type, limit=limit, stop=stop, tif=tif, meta=meta)

    def cancel(self, order_id: Any) -> None:
        self.broker.cancel_order(order_id)

    def status(self, order_id: Any) -> dict:
        return self.broker.order_status(order_id)


