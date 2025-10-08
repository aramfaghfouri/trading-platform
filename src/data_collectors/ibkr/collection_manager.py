from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger

from src.data_collectors.ibkr.client import IBKRDataClient
from src.data_collectors.ibkr.data_storage import IBKRDataStorage


@dataclass
class IBKRCollectionTask:
    symbol: str
    start_date: str
    end_date: str
    timeframe: str
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None
    completed_at: Optional[datetime] = None


@dataclass
class IBKRCollectionStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    inserted: int = 0


class IBKRCollectionManager:
    def __init__(self, max_concurrent: int = 3):
        self.client = IBKRDataClient()
        self.storage = IBKRDataStorage()
        self.max_concurrent = max_concurrent
        self.tasks: Dict[str, IBKRCollectionTask] = {}
        self.stats = IBKRCollectionStats()

    def add_task(self, symbol: str, start: str, end: str, timeframe: str) -> str:
        task_id = f"{symbol}_{start}_{end}_{timeframe}"
        self.tasks[task_id] = IBKRCollectionTask(symbol, start, end, timeframe)
        self.stats.total += 1
        return task_id

    async def execute_task(self, task_id: str) -> None:
        task = self.tasks[task_id]
        if task.completed_at:
            return
        try:
            task.attempts += 1
            df = await self.client.fetch_bars(task.symbol, task.start_date, task.end_date, task.timeframe)
            records = []
            if not df.empty:
                for ts, row in df.iterrows():
                    records.append(
                        {
                            "timestamp": ts,
                            "open": float(row.get("open")),
                            "high": float(row.get("high")),
                            "low": float(row.get("low")),
                            "close": float(row.get("close")),
                            "volume": int(row.get("volume") or 0),
                        }
                    )
            result = await self.storage.store_bars(task.symbol, records)
            if result.success:
                self.stats.succeeded += 1
                self.stats.inserted += result.records_inserted
                task.completed_at = datetime.now(timezone.utc)
                task.last_error = None
            else:
                raise RuntimeError(result.error or "storage_failed")
        except Exception as exc:
            task.last_error = str(exc)
            logger.error("IBKR task {} failed: {}", task_id, exc)
            if task.attempts >= task.max_attempts:
                task.completed_at = datetime.now(timezone.utc)
                self.stats.failed += 1

    async def run_all(self) -> IBKRCollectionStats:
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def runner(tid: str):
            async with semaphore:
                await self.execute_task(tid)

        await asyncio.gather(*(runner(tid) for tid in self.tasks))
        await self.client.close()
        return self.stats
