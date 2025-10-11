"""
Abstract base class for all trading strategies.

All strategies must extend this class and implement the required methods.
"""

from __future__ import annotations

import asyncpg
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from src.strategies.models import OrderSpec, SignalSpec, BarData, StrategyState
from src.core.config_loader import get_database_config


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.
    
    Strategies read market data from TimescaleDB, maintain internal state,
    and generate order specifications when conditions are met.
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        """
        Initialize strategy.
        
        Args:
            name: Unique name for this strategy instance
            config: Strategy-specific configuration parameters
            symbols: List of symbols this strategy trades
        """
        self.name = name
        self.config = config
        self.symbols = [s.upper() for s in symbols]
        
        # Database connection
        self.db_config = get_database_config()
        self.db_pool: Optional[asyncpg.Pool] = None
        
        # Strategy state
        self.state = StrategyState(strategy_name=name)
        self.is_initialized = False
        
        # Internal data cache
        self._bar_cache: Dict[str, pd.DataFrame] = {symbol: pd.DataFrame() for symbol in self.symbols}
        
        logger.info(f"Strategy '{name}' created for symbols: {', '.join(self.symbols)}")
    
    @abstractmethod
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Called when new bar data is available for a symbol.
        
        This is the main strategy logic entry point. Implement your
        trading logic here.
        
        Args:
            symbol: The symbol for which new data is available
            bar: The latest OHLCV bar data
            
        Returns:
            OrderSpec if an order should be placed, None otherwise
        """
        pass
    
    @abstractmethod
    async def get_required_lookback(self) -> int:
        """
        Return the number of historical bars needed for strategy initialization.
        
        Returns:
            Number of bars (e.g., 200 for a 200-period SMA)
        """
        pass
    
    async def initialize(self) -> None:
        """
        Initialize strategy: connect to database, load historical data, setup indicators.
        
        Override this method to add custom initialization logic, but make sure
        to call super().initialize() first.
        """
        if self.is_initialized:
            logger.warning(f"Strategy '{self.name}' already initialized")
            return
        
        # Connect to database
        await self._connect_db()
        
        # Load strategy state from database
        await self._load_state()
        
        # Load historical data for all symbols
        lookback = await self.get_required_lookback()
        for symbol in self.symbols:
            await self._load_historical_data(symbol, lookback)
        
        self.is_initialized = True
        logger.info(f"Strategy '{self.name}' initialized")
    
    async def shutdown(self) -> None:
        """
        Cleanup resources: save state, close database connections.
        
        Override to add custom cleanup logic, but call super().shutdown().
        """
        if not self.is_initialized:
            return
        
        # Save final state
        await self._save_state()
        
        # Close database connection
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
        
        self.is_initialized = False
        logger.info(f"Strategy '{self.name}' shut down")
    
    async def _connect_db(self) -> None:
        """Establish database connection pool."""
        if self.db_pool:
            return
        
        import os
        dsn = os.getenv("DATABASE_URL")
        
        if dsn:
            self.db_pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=self.db_config.pool.min_connections,
                max_size=self.db_config.pool.max_connections,
                command_timeout=self.db_config.pool.command_timeout,
                server_settings={
                    'application_name': f'strategy_{self.name}',
                    'timezone': 'UTC'
                }
            )
        else:
            self.db_pool = await asyncpg.create_pool(
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
                    'application_name': f'strategy_{self.name}',
                    'timezone': 'UTC'
                }
            )
        
        logger.info(f"Strategy '{self.name}' connected to database")
    
    async def _load_historical_data(self, symbol: str, num_bars: int) -> None:
        """
        Load historical bars from database into cache.
        
        Args:
            symbol: Symbol to load data for
            num_bars: Number of recent bars to load
        """
        if not self.db_pool:
            raise RuntimeError("Database not connected")
        
        # Determine table name (assuming IBKR 5-second bars)
        table_name = f"ibkr_ohlcv_{symbol.lower()}_5s"
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            ORDER BY timestamp DESC
            LIMIT $1
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, num_bars)
            
            if not rows:
                logger.warning(f"No historical data found for {symbol}")
                return
            
            # Convert to DataFrame and reverse (oldest first)
            df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.iloc[::-1].reset_index(drop=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            self._bar_cache[symbol] = df
            logger.info(f"Loaded {len(df)} historical bars for {symbol}")
            
        except asyncpg.UndefinedTableError:
            logger.warning(f"Table {table_name} does not exist - no historical data for {symbol}")
        except Exception as e:
            logger.error(f"Error loading historical data for {symbol}: {e}")
    
    async def get_recent_bars(
        self,
        symbol: str,
        num_bars: int,
        timeframe: str = '5s',
    ) -> List[BarData]:
        """
        Query recent bars from database.
        
        Args:
            symbol: Symbol to query
            num_bars: Number of recent bars to retrieve
            timeframe: Bar timeframe (e.g., '5s', '1m')
            
        Returns:
            List of BarData objects
        """
        if not self.db_pool:
            raise RuntimeError("Database not connected")
        
        table_name = f"ibkr_ohlcv_{symbol.lower()}_{timeframe}"
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            ORDER BY timestamp DESC
            LIMIT $1
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, num_bars)
            
            # Convert to BarData objects (reverse to oldest first)
            bars = [
                BarData(
                    timestamp=row['timestamp'],
                    open=Decimal(str(row['open'])),
                    high=Decimal(str(row['high'])),
                    low=Decimal(str(row['low'])),
                    close=Decimal(str(row['close'])),
                    volume=int(row['volume']),
                    symbol=symbol,
                )
                for row in reversed(rows)
            ]
            
            return bars
            
        except Exception as e:
            logger.error(f"Error querying bars for {symbol}: {e}")
            return []
    
    async def get_bars_since(
        self,
        symbol: str,
        since_timestamp: datetime,
        timeframe: str = '5s',
    ) -> List[BarData]:
        """
        Query bars since a specific timestamp.
        
        Args:
            symbol: Symbol to query
            since_timestamp: Get bars after this timestamp
            timeframe: Bar timeframe
            
        Returns:
            List of BarData objects
        """
        if not self.db_pool:
            raise RuntimeError("Database not connected")
        
        table_name = f"ibkr_ohlcv_{symbol.lower()}_{timeframe}"
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            WHERE timestamp > $1
            ORDER BY timestamp ASC
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, since_timestamp)
            
            bars = [
                BarData(
                    timestamp=row['timestamp'],
                    open=Decimal(str(row['open'])),
                    high=Decimal(str(row['high'])),
                    low=Decimal(str(row['low'])),
                    close=Decimal(str(row['close'])),
                    volume=int(row['volume']),
                    symbol=symbol,
                )
                for row in rows
            ]
            
            return bars
            
        except Exception as e:
            logger.error(f"Error querying bars since {since_timestamp} for {symbol}: {e}")
            return []
    
    async def _load_state(self) -> None:
        """Load strategy state from database."""
        if not self.db_pool:
            return
        
        query = """
            SELECT strategy_name, last_processed_timestamp, is_running, 
                   last_heartbeat, error_message, updated_at
            FROM strategy_state
            WHERE strategy_name = $1
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(query, self.name)
            
            if row:
                self.state = StrategyState(
                    strategy_name=row['strategy_name'],
                    last_processed_timestamp=row['last_processed_timestamp'],
                    is_running=row['is_running'],
                    last_heartbeat=row['last_heartbeat'],
                    error_message=row['error_message'],
                    updated_at=row['updated_at'],
                )
                logger.info(f"Loaded state for strategy '{self.name}'")
            
        except asyncpg.UndefinedTableError:
            logger.warning("strategy_state table does not exist - run database migrations")
        except Exception as e:
            logger.error(f"Error loading strategy state: {e}")
    
    async def _save_state(self) -> None:
        """Save strategy state to database."""
        if not self.db_pool:
            return
        
        self.state.updated_at = datetime.now(tz=timezone.utc)
        
        query = """
            INSERT INTO strategy_state 
                (strategy_name, last_processed_timestamp, is_running, last_heartbeat, 
                 error_message, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (strategy_name) DO UPDATE SET
                last_processed_timestamp = EXCLUDED.last_processed_timestamp,
                is_running = EXCLUDED.is_running,
                last_heartbeat = EXCLUDED.last_heartbeat,
                error_message = EXCLUDED.error_message,
                updated_at = EXCLUDED.updated_at
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    self.state.strategy_name,
                    self.state.last_processed_timestamp,
                    self.state.is_running,
                    self.state.last_heartbeat,
                    self.state.error_message,
                    self.state.updated_at,
                )
        except asyncpg.UndefinedTableError:
            logger.warning("strategy_state table does not exist - state not saved")
        except Exception as e:
            logger.error(f"Error saving strategy state: {e}")
    
    async def update_heartbeat(self) -> None:
        """Update strategy heartbeat timestamp in database."""
        self.state.last_heartbeat = datetime.now(tz=timezone.utc)
        self.state.is_running = True
        await self._save_state()
    
    async def log_signal(self, signal: SignalSpec) -> None:
        """
        Log a trading signal to the database.
        
        Args:
            signal: The signal to log
        """
        if not self.db_pool:
            return
        
        query = """
            INSERT INTO strategy_signals
                (strategy_name, symbol, signal_time, signal_type, confidence, metadata, order_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        
        try:
            import json
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    signal.strategy_name,
                    signal.symbol,
                    signal.signal_time,
                    signal.signal_type.value,
                    signal.confidence,
                    json.dumps(signal.metadata),
                    signal.order_id,
                )
            logger.info(f"Logged signal: {signal.signal_type.value} {signal.symbol} at {signal.signal_time}")
        except asyncpg.UndefinedTableError:
            logger.warning("strategy_signals table does not exist - signal not logged")
        except Exception as e:
            logger.error(f"Error logging signal: {e}")
    
    def get_cached_bars(self, symbol: str) -> pd.DataFrame:
        """
        Get cached bars for a symbol as a pandas DataFrame.
        
        Args:
            symbol: Symbol to get bars for
            
        Returns:
            DataFrame with OHLCV data
        """
        return self._bar_cache.get(symbol, pd.DataFrame())
    
    def update_cache(self, symbol: str, bar: BarData) -> None:
        """
        Add a new bar to the internal cache.
        
        Args:
            symbol: Symbol to update
            bar: New bar data
        """
        if symbol not in self._bar_cache:
            self._bar_cache[symbol] = pd.DataFrame()
        
        new_row = pd.DataFrame([{
            'timestamp': bar.timestamp,
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': bar.volume,
        }])
        
        self._bar_cache[symbol] = pd.concat(
            [self._bar_cache[symbol], new_row],
            ignore_index=True
        )
        
        # Keep only last 1000 bars in cache
        if len(self._bar_cache[symbol]) > 1000:
            self._bar_cache[symbol] = self._bar_cache[symbol].iloc[-1000:].reset_index(drop=True)

