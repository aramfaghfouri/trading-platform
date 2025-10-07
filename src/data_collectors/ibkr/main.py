#!/usr/bin/env python3
"""Entry point for IBKR historical data collection."""

import argparse
import asyncio
from datetime import datetime
from typing import List

from loguru import logger

from src.core.config_loader import ConfigLoader
from src.data_collectors.ibkr.collection_manager import IBKRCollectionManager


async def collect(symbols: List[str], start: str, end: str, timeframe: str) -> None:
    manager = IBKRCollectionManager()
    for symbol in symbols:
        manager.add_task(symbol, start, end, timeframe)
    stats = await manager.run_all()
    logger.info(
        "IBKR collection finished: total=%s succeeded=%s failed=%s inserted=%s",
        stats.total,
        stats.succeeded,
        stats.failed,
        stats.inserted,
    )


def default_args_from_config() -> tuple[list[str], str, str, str]:
    loader = ConfigLoader()
    cfg = loader.get_provider_setup("ibkr", "historical")
    symbols = cfg.get("symbols", ["AAPL"])
    start = cfg.get("start_date", datetime.utcnow().strftime("%Y-%m-%d"))
    end = cfg.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    timeframe = cfg.get("timeframe", "1m")
    return symbols, start, end, timeframe


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKR historical data collector")
    parser.add_argument("--symbols", nargs="*", help="Symbols to collect")
    parser.add_argument("--start", help="ISO start date", default=None)
    parser.add_argument("--end", help="ISO end date", default=None)
    parser.add_argument("--timeframe", help="Bar timeframe", default=None)
    args = parser.parse_args()

    cfg_symbols, cfg_start, cfg_end, cfg_tf = default_args_from_config()

    symbols = args.symbols if args.symbols else cfg_symbols
    start = args.start or cfg_start
    end = args.end or cfg_end
    timeframe = args.timeframe or cfg_tf

    logger.info(
        "Launching IBKR collection for symbols=%s start=%s end=%s tf=%s",
        symbols,
        start,
        end,
        timeframe,
    )
    asyncio.run(collect(symbols, start, end, timeframe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
