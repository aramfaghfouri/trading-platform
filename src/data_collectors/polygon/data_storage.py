"""
Data Storage Interface for Polygon.io Data

This module provides a comprehensive data storage system that integrates
with TimescaleDB for storing and retrieving market data from Polygon.io.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np
from loguru import logger
import asyncpg
from asyncpg import Connection, Pool

from core.config_loader import get_database_config, get_polygon_config
from core.config_models import DatabaseConfig, PolygonConfig
from .enhanced_collector import DataCollectionResult, Timeframe


@dataclass
class StorageResult:
    """Result of storage operation."""
    success: bool
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class PolygonDataStorage:
    """Data storage interface for Polygon.io data in TimescaleDB."""
    
    def __init__(self, db_config: Optional[DatabaseConfig] = None, polygon_config: Optional[PolygonConfig] = None):
        """
        Initialize the data storage interface.
        
        Args:
            db_config: Database configuration (if None, loads from config system)
            polygon_config: Polygon configuration (if None, loads from config system)
        """
        self.db_config = db_config or get_database_config()
        self.polygon_config = polygon_config or get_polygon_config()
        self.pool: Optional[Pool] = None
        
        logger.info("Initialized Polygon data storage interface")
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        
    async def connect(self) -> None:
        """Establish database connection pool."""
        try:
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
                    'application_name': 'polygon_data_collector',
                    'timezone': 'UTC'
                }
            )
            logger.info("Connected to TimescaleDB")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
            
    async def disconnect(self) -> None:
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected from TimescaleDB")
            
    async def store_ohlcv_data(
        self,
        symbol: str,
        data: List[Dict[str, Any]],
        timeframe: Timeframe = Timeframe.DAY_1,
        upsert: bool = True
    ) -> StorageResult:
        """
        Store OHLCV data in TimescaleDB.
        
        Args:
            symbol: Stock symbol
            data: List of OHLCV data dictionaries
            timeframe: Data timeframe
            upsert: Whether to upsert on conflict
            
        Returns:
            StorageResult with operation details
        """
        if not data:
            return StorageResult(success=True, records_inserted=0)
            
        try:
            async with self.pool.acquire() as conn:
                records_inserted = 0
                records_updated = 0
                records_skipped = 0
                
                for bar in data:
                    try:
                        # Prepare data for insertion
                        timestamp = datetime.fromtimestamp(bar['t'] / 1000, tz=timezone.utc)
                        
                        # Validate data
                        if not all(key in bar for key in ['o', 'h', 'l', 'c', 'v']):
                            records_skipped += 1
                            continue
                            
                        # Insert or update record
                        if upsert:
                            query = """
                                INSERT INTO ohlcv_data (symbol, timestamp, open, high, low, close, volume, vwap, transactions)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                                ON CONFLICT (symbol, timestamp) 
                                DO UPDATE SET
                                    open = EXCLUDED.open,
                                    high = EXCLUDED.high,
                                    low = EXCLUDED.low,
                                    close = EXCLUDED.close,
                                    volume = EXCLUDED.volume,
                                    vwap = EXCLUDED.vwap,
                                    transactions = EXCLUDED.transactions
                                RETURNING (xmax = 0) AS inserted
                            """
                            
                            result = await conn.fetchrow(
                                query,
                                symbol,
                                timestamp,
                                bar['o'],
                                bar['h'],
                                bar['l'],
                                bar['c'],
                                bar['v'],
                                bar.get('vw', None),
                                bar.get('n', None)
                            )
                            
                            if result['inserted']:
                                records_inserted += 1
                            else:
                                records_updated += 1
                        else:
                            query = """
                                INSERT INTO ohlcv_data (symbol, timestamp, open, high, low, close, volume, vwap, transactions)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                            """
                            
                            await conn.execute(
                                query,
                                symbol,
                                timestamp,
                                bar['o'],
                                bar['h'],
                                bar['l'],
                                bar['c'],
                                bar['v'],
                                bar.get('vw', None),
                                bar.get('n', None)
                            )
                            records_inserted += 1
                            
                    except Exception as e:
                        logger.warning(f"Failed to store bar for {symbol}: {e}")
                        records_skipped += 1
                        continue
                        
                logger.info(f"Stored OHLCV data for {symbol}: {records_inserted} inserted, {records_updated} updated, {records_skipped} skipped")
                
                return StorageResult(
                    success=True,
                    records_inserted=records_inserted,
                    records_updated=records_updated,
                    records_skipped=records_skipped
                )
                
        except Exception as e:
            logger.error(f"Failed to store OHLCV data for {symbol}: {e}")
            return StorageResult(
                success=False,
                error=str(e)
            )
    
    async def store_ticker_details(self, symbol: str, details: Dict[str, Any]) -> StorageResult:
        """
        Store ticker details in database.
        
        Args:
            symbol: Stock symbol
            details: Ticker details dictionary
            
        Returns:
            StorageResult with operation details
        """
        try:
            async with self.pool.acquire() as conn:
                # Create or update ticker details table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticker_details (
                        symbol VARCHAR(10) PRIMARY KEY,
                        name VARCHAR(255),
                        market VARCHAR(50),
                        locale VARCHAR(10),
                        primary_exchange VARCHAR(50),
                        type VARCHAR(50),
                        active BOOLEAN,
                        currency_name VARCHAR(10),
                        description TEXT,
                        homepage_url TEXT,
                        total_employees INTEGER,
                        list_date DATE,
                        branding JSONB,
                        share_class_shares_outstanding BIGINT,
                        weighted_shares_outstanding BIGINT,
                        market_cap BIGINT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                # Extract relevant fields
                result = details.get('results', {}) if 'results' in details else details
                
                query = """
                    INSERT INTO ticker_details (
                        symbol, name, market, locale, primary_exchange, type, active,
                        currency_name, description, homepage_url, total_employees,
                        list_date, branding, share_class_shares_outstanding,
                        weighted_shares_outstanding, market_cap, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, NOW())
                    ON CONFLICT (symbol) 
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        market = EXCLUDED.market,
                        locale = EXCLUDED.locale,
                        primary_exchange = EXCLUDED.primary_exchange,
                        type = EXCLUDED.type,
                        active = EXCLUDED.active,
                        currency_name = EXCLUDED.currency_name,
                        description = EXCLUDED.description,
                        homepage_url = EXCLUDED.homepage_url,
                        total_employees = EXCLUDED.total_employees,
                        list_date = EXCLUDED.list_date,
                        branding = EXCLUDED.branding,
                        share_class_shares_outstanding = EXCLUDED.share_class_shares_outstanding,
                        weighted_shares_outstanding = EXCLUDED.weighted_shares_outstanding,
                        market_cap = EXCLUDED.market_cap,
                        updated_at = NOW()
                """
                
                await conn.execute(
                    query,
                    symbol,
                    result.get('name'),
                    result.get('market'),
                    result.get('locale'),
                    result.get('primary_exchange'),
                    result.get('type'),
                    result.get('active'),
                    result.get('currency_name'),
                    result.get('description'),
                    result.get('total_employees'),
                    result.get('list_date'),
                    result.get('branding'),
                    result.get('share_class_shares_outstanding'),
                    result.get('weighted_shares_outstanding'),
                    result.get('market_cap')
                )
                
                logger.info(f"Stored ticker details for {symbol}")
                
                return StorageResult(
                    success=True,
                    records_inserted=1
                )
                
        except Exception as e:
            logger.error(f"Failed to store ticker details for {symbol}: {e}")
            return StorageResult(
                success=False,
                error=str(e)
            )
    
    async def store_news_data(self, symbol: str, news: List[Dict[str, Any]]) -> StorageResult:
        """
        Store news data in database.
        
        Args:
            symbol: Stock symbol
            news: List of news articles
            
        Returns:
            StorageResult with operation details
        """
        if not news:
            return StorageResult(success=True, records_inserted=0)
            
        try:
            async with self.pool.acquire() as conn:
                # Create news table if it doesn't exist
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticker_news (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(10) NOT NULL,
                        title TEXT NOT NULL,
                        author VARCHAR(255),
                        published_utc TIMESTAMPTZ NOT NULL,
                        article_url TEXT,
                        image_url TEXT,
                        description TEXT,
                        keywords TEXT[],
                        publisher JSONB,
                        tickers TEXT[],
                        amp_url TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(symbol, title, published_utc)
                    )
                """)
                
                # Create index for efficient querying
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ticker_news_symbol_published 
                    ON ticker_news (symbol, published_utc DESC)
                """)
                
                records_inserted = 0
                records_skipped = 0
                
                for article in news:
                    try:
                        # Parse published date
                        published_utc = datetime.fromisoformat(
                            article['published_utc'].replace('Z', '+00:00')
                        )
                        
                        query = """
                            INSERT INTO ticker_news (
                                symbol, title, author, published_utc, article_url,
                                image_url, description, keywords, publisher, tickers, amp_url
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            ON CONFLICT (symbol, title, published_utc) DO NOTHING
                        """
                        
                        result = await conn.execute(
                            query,
                            symbol,
                            article.get('title'),
                            article.get('author'),
                            published_utc,
                            article.get('article_url'),
                            article.get('image_url'),
                            article.get('description'),
                            article.get('keywords', []),
                            article.get('publisher'),
                            article.get('tickers', []),
                            article.get('amp_url')
                        )
                        
                        if result == "INSERT 0 1":
                            records_inserted += 1
                        else:
                            records_skipped += 1
                            
                    except Exception as e:
                        logger.warning(f"Failed to store news article for {symbol}: {e}")
                        records_skipped += 1
                        continue
                        
                logger.info(f"Stored news data for {symbol}: {records_inserted} inserted, {records_skipped} skipped")
                
                return StorageResult(
                    success=True,
                    records_inserted=records_inserted,
                    records_skipped=records_skipped
                )
                
        except Exception as e:
            logger.error(f"Failed to store news data for {symbol}: {e}")
            return StorageResult(
                success=False,
                error=str(e)
            )
    
    async def get_latest_data(
        self,
        symbol: str,
        limit: int = 100,
        timeframe: Optional[Timeframe] = None
    ) -> Optional[pd.DataFrame]:
        """
        Get latest OHLCV data for a symbol.
        
        Args:
            symbol: Stock symbol
            limit: Maximum number of records
            timeframe: Optional timeframe filter
            
        Returns:
            DataFrame with OHLCV data or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                query = """
                    SELECT timestamp, open, high, low, close, volume, vwap, transactions
                    FROM ohlcv_data
                    WHERE symbol = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                """
                
                rows = await conn.fetch(query, symbol, limit)
                
                if not rows:
                    return None
                    
                # Convert to DataFrame
                df = pd.DataFrame(rows)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)
                
                return df
                
        except Exception as e:
            logger.error(f"Failed to get latest data for {symbol}: {e}")
            return None
    
    async def get_data_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: Optional[Timeframe] = None
    ) -> Optional[pd.DataFrame]:
        """
        Get OHLCV data for a symbol within a date range.
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Optional timeframe filter
            
        Returns:
            DataFrame with OHLCV data or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                query = """
                    SELECT timestamp, open, high, low, close, volume, vwap, transactions
                    FROM ohlcv_data
                    WHERE symbol = $1
                    AND timestamp >= $2
                    AND timestamp <= $3
                    ORDER BY timestamp ASC
                """
                
                rows = await conn.fetch(query, symbol, start_date, end_date)
                
                if not rows:
                    return None
                    
                # Convert to DataFrame
                df = pd.DataFrame(rows)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                
                return df
                
        except Exception as e:
            logger.error(f"Failed to get data range for {symbol}: {e}")
            return None
    
    async def get_symbols_with_data(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[str]:
        """
        Get list of symbols that have data in the specified date range.
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            List of symbols
        """
        try:
            async with self.pool.acquire() as conn:
                if start_date and end_date:
                    query = """
                        SELECT DISTINCT symbol
                        FROM ohlcv_data
                        WHERE timestamp >= $1 AND timestamp <= $2
                        ORDER BY symbol
                    """
                    rows = await conn.fetch(query, start_date, end_date)
                else:
                    query = """
                        SELECT DISTINCT symbol
                        FROM ohlcv_data
                        ORDER BY symbol
                    """
                    rows = await conn.fetch(query)
                    
                return [row['symbol'] for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to get symbols with data: {e}")
            return []
    
    async def get_data_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics of stored data.
        
        Returns:
            Dictionary with data summary
        """
        try:
            async with self.pool.acquire() as conn:
                # Get total records
                total_records = await conn.fetchval("SELECT COUNT(*) FROM ohlcv_data")
                
                # Get unique symbols
                unique_symbols = await conn.fetchval("SELECT COUNT(DISTINCT symbol) FROM ohlcv_data")
                
                # Get date range
                date_range = await conn.fetchrow("""
                    SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest
                    FROM ohlcv_data
                """)
                
                # Get records by symbol
                symbol_counts = await conn.fetch("""
                    SELECT symbol, COUNT(*) as count
                    FROM ohlcv_data
                    GROUP BY symbol
                    ORDER BY count DESC
                    LIMIT 10
                """)
                
                return {
                    'total_records': total_records,
                    'unique_symbols': unique_symbols,
                    'earliest_date': date_range['earliest'],
                    'latest_date': date_range['latest'],
                    'top_symbols': [{'symbol': row['symbol'], 'count': row['count']} for row in symbol_counts]
                }
                
        except Exception as e:
            logger.error(f"Failed to get data summary: {e}")
            return {}
    
    async def store_collection_result(
        self,
        symbol: str,
        result: DataCollectionResult,
        timeframe: Timeframe = Timeframe.DAY_1
    ) -> StorageResult:
        """
        Store a complete DataCollectionResult.
        
        Args:
            symbol: Stock symbol
            result: DataCollectionResult from collector
            timeframe: Data timeframe
            
        Returns:
            StorageResult with operation details
        """
        if not result.success or not result.data:
            return StorageResult(success=False, error=result.error)
            
        try:
            # Store OHLCV data if present
            if 'results' in result.data and result.data['results']:
                ohlcv_result = await self.store_ohlcv_data(
                    symbol=symbol,
                    data=result.data['results'],
                    timeframe=timeframe
                )
                
                if not ohlcv_result.success:
                    return ohlcv_result
                    
            # Store ticker details if present
            if 'details' in result.data:
                details_result = await self.store_ticker_details(
                    symbol=symbol,
                    details=result.data['details']
                )
                
            # Store news data if present
            if 'news' in result.data and result.data['news']:
                news_result = await self.store_news_data(
                    symbol=symbol,
                    news=result.data['news']
                )
                
            logger.info(f"Successfully stored collection result for {symbol}")
            
            return StorageResult(
                success=True,
                records_inserted=len(result.data.get('results', [])),
                metadata=result.metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to store collection result for {symbol}: {e}")
            return StorageResult(
                success=False,
                error=str(e)
            )


# Convenience functions
async def store_symbol_data(
    symbol: str,
    data: List[Dict[str, Any]],
    timeframe: Timeframe = Timeframe.DAY_1,
    db_config: Optional[DatabaseConfig] = None
) -> StorageResult:
    """
    Convenience function to store data for a single symbol.
    
    Args:
        symbol: Stock symbol
        data: OHLCV data
        timeframe: Data timeframe
        db_config: Optional database configuration
        
    Returns:
        StorageResult
    """
    async with PolygonDataStorage(db_config) as storage:
        return await storage.store_ohlcv_data(symbol, data, timeframe)


async def get_symbol_data(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    db_config: Optional[DatabaseConfig] = None
) -> Optional[pd.DataFrame]:
    """
    Convenience function to get data for a single symbol.
    
    Args:
        symbol: Stock symbol
        start_date: Start date
        end_date: End date
        db_config: Optional database configuration
        
    Returns:
        DataFrame with OHLCV data or None
    """
    async with PolygonDataStorage(db_config) as storage:
        return await storage.get_data_range(symbol, start_date, end_date)
