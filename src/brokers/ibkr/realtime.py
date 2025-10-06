from __future__ import annotations
from typing import Callable, Any

from src.data_pipeline.base import RealtimeProviderBase
from src.brokers.ibkr.client import IBClient


class IBKRRealtimeProvider(RealtimeProviderBase):
    def __init__(self, client: IBClient | None = None):
        self.client = client or IBClient()

    def subscribe(self, symbols: list[str], on_event: Callable[[dict], None]) -> Any:
        self.client.connect()
        handles = []
        for s in symbols:
            t = self.client.subscribe_ticks(s)
            handles.append((s, t))
        return handles

    def unsubscribe(self, handle: Any) -> None:
        for s, _ in handle:
            self.client.cancel_ticks(s)
        self.client.disconnect()


