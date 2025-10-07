from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import os
import asyncpg
from asyncpg import Pool, Connection
from loguru import logger

from src.core.config_loader import get_database_config
from src.core.config_models import DatabaseConfig


@dataclass
class StorageResult:
    success: bool
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    error: Optional[str] = None


class SourceDataStorage:
    """Generic source-aware TimescaleDB storage for OHLCV bars."""

    def __init__(self, source: str, db_config: Optional[DatabaseConfig] = None):
        self.source = source.lower()
        self.db_config = db_config or get_database_config()
        self.pool: Optional[Pool] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    async def connect(self) -> None:
        dsn = os.getenv("DATABASE_URL")
        if dsn:
            # Prefer full DSN if provided via environment
            self.pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=self.db_config.pool.min_connections,
                max_size=self.db_config.pool.max_connections,
                command_timeout=self.db_config.pool.command_timeout,
                server_settings={
                    'application_name': f'{self.source}_collector',
                    'timezone': 'UTC'
                }
            )
        else:
            self.pool = await asyncpg.create_pool(
                host=self.db_config.host,
                port=self.db_config.port,
                database=self.db_config.database,
                user=self.db_config.username,
                password=self.db_config.password,
                ssl=self.db_config.ssl_mode,
                min_size=self.db_config.pool.min_connections,
                max_size=self.db_config.pool.max_connections,
                command_timeout=self.db_config.pool.command_timeout,
                server_settings={
                    'application_name': f'{self.source}_collector',
                    'timezone': 'UTC'
                }
            )
        logger.info("Connected to TimescaleDB for source={}", self.source)

    async def disconnect(self) -> None:
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected TimescaleDB")

    async def _ensure_table(self, conn: Connection, symbol: str, timeframe: str) -> str:
        """Create or fetch source-prefixed table for symbol/timeframe."""
        # Build expected table name
        expected_table = f"{self.source}_ohlcv_{symbol.lower()}_{timeframe}"
        
        # Check if table exists directly
        table_exists = await conn.fetchval(
            "SELECT table_name FROM information_schema.tables WHERE table_name = $1",
            expected_table
        )
        
        if table_exists:
            logger.info(f"✅ Table {expected_table} already exists")
            return expected_table
        
        # Try to create the table
        logger.info(f"📝 Creating table {expected_table}")
        created = await conn.fetchval(
            "SELECT create_source_ticker_table($1,$2,$3,$4)",
            self.source, symbol, 'ohlcv', timeframe
        )
        
        if not created:
            # Check again if table was created by another process
            table_exists = await conn.fetchval(
                "SELECT table_name FROM information_schema.tables WHERE table_name = $1",
                expected_table
            )
            if table_exists:
                logger.info(f"✅ Table {expected_table} was created by another process")
                return expected_table
            raise RuntimeError(f"Failed creating table for {self.source}:{symbol}:{timeframe}")
        
        logger.info(f"✅ Successfully created table {expected_table}")
        return expected_table

    async def store_ohlcv(self, symbol: str, timeframe: str, bars: List[Dict[str, Any]]) -> StorageResult:
        if not bars:
            return StorageResult(success=True)
        try:
            async with self.pool.acquire() as conn:
                table = await self._ensure_table(conn, symbol, timeframe)
                ins, upd, skip = 0, 0, 0
                for b in bars:
                    try:
                        # Support two timestamp formats: epoch millis under 't' or naive datetime under 'timestamp'
                        if 't' in b:
                            ts = datetime.fromtimestamp(b['t'] / 1000, tz=timezone.utc)
                        else:
                            ts = b['timestamp'] if isinstance(b['timestamp'], datetime) else datetime.fromisoformat(str(b['timestamp']))
                        o = b.get('o') or b.get('open')
                        h = b.get('h') or b.get('high')
                        l = b.get('l') or b.get('low')
                        c = b.get('c') or b.get('close')
                        v = b.get('v') or b.get('volume') or 0
                        vw = b.get('vw') or b.get('vwap')
                        n = b.get('n') or b.get('transactions')
                        q = f"""
                            INSERT INTO {table} (timestamp, open, high, low, close, volume, vwap, transactions)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                            ON CONFLICT (timestamp) DO UPDATE SET
                                open=EXCLUDED.open,
                                high=EXCLUDED.high,
                                low=EXCLUDED.low,
                                close=EXCLUDED.close,
                                volume=EXCLUDED.volume,
                                vwap=EXCLUDED.vwap,
                                transactions=EXCLUDED.transactions,
                                updated_at=NOW()
                            RETURNING (xmax = 0) AS inserted
                        """
                        row = await conn.fetchrow(q, ts, o, h, l, c, v, vw, n)
                        if row['inserted']:
                            ins += 1
                        else:
                            upd += 1
                    except Exception as e:
                        logger.debug("Skip bar {} due to {}", b, e)
                        skip += 1
                logger.info("Stored {} bars for {}:{} (ins={}, upd={}, skip={})", len(bars), symbol, timeframe, ins, upd, skip)
                return StorageResult(True, ins, upd, skip)
        except asyncpg.UndefinedFunctionError as e:
            msg = "Missing TimescaleDB helper functions (get_source_ticker_table_name/create_source_ticker_table). Run docker/timescaledb/init/01-init-database.sql or recreate the container."
            logger.error(msg)
            return StorageResult(False, 0, 0, 0, msg)
        except Exception as e:
            logger.error("Storage failed: {}", e)
            return StorageResult(False, 0, 0, 0, str(e))


