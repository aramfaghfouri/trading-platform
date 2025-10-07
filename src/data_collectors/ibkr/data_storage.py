from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.data_collectors.common.source_storage import SourceDataStorage, StorageResult
from src.core.config_models import DatabaseConfig


@dataclass
class IBKRStorageConfig:
    source: str = "ibkr"
    timeframe: str = "1m"


class IBKRDataStorage(SourceDataStorage):
    """IBKR-specific storage facade over SourceDataStorage."""

    def __init__(self, config: Optional[IBKRStorageConfig] = None, db_config: Optional[DatabaseConfig] = None):
        cfg = config or IBKRStorageConfig()
        super().__init__(source=cfg.source, db_config=db_config)
        self._default_timeframe = cfg.timeframe

    async def store_bars(self, symbol: str, records) -> StorageResult:
        return await self.store_ohlcv(symbol, self._default_timeframe, records)
