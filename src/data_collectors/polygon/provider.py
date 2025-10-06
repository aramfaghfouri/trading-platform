from __future__ import annotations
from typing import Optional, Callable, Any
import pandas as pd

from src.data_pipeline.base import HistoricalProviderBase, RealtimeProviderBase
from src.data_collectors.polygon.enhanced_collector import PolygonDataCollector
from src.core.config_loader import ConfigLoader


class PolygonHistoricalProvider(HistoricalProviderBase):
    def __init__(self):
        self.collector = PolygonDataCollector()
        self.loader = ConfigLoader()

    def get_historical(self, symbol: str, start: str, end: str,
                       timeframe: str, adjustments: Optional[str] = None) -> pd.DataFrame:
        # Pull defaults from project-setup.toml if not provided
        if not timeframe:
            timeframe = self.loader.get_provider_setup('polygon', 'data_collection').get('time_interval', 'minute')
        # Delegate to existing collector utilities
        df = self.collector.get_aggregates_df(symbol, start, end, timeframe, adjustments)
        return df


class PolygonRealtimeProvider(RealtimeProviderBase):
    def subscribe(self, symbols: list[str], on_event: Callable[[dict], None]) -> Any:
        # Placeholder: implement Polygon WebSocket if needed
        raise NotImplementedError("Polygon realtime provider not yet implemented")

    def unsubscribe(self, handle: Any) -> None:
        pass


