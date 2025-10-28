"""
Backtesting Engine

Test strategies on historical data to validate performance before live trading.
"""

from __future__ import annotations

import asyncio
import asyncpg
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from loguru import logger
import pandas as pd
import numpy as np

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, BarData, OrderAction, OrderType
from src.brokers.paper.paper_executor import PaperTradeExecutor, Trade, AccountBalance
from src.core.config_loader import get_database_config


@dataclass
class BacktestResult:
    """Results of a backtest run."""
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_return: Decimal  # Percentage
    annualized_return: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    sharpe_ratio: Optional[Decimal] = None
    sortino_ratio: Optional[Decimal] = None
    win_rate: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_duration: Optional[timedelta] = None
    volatility: Optional[Decimal] = None
    calmar_ratio: Optional[Decimal] = None
    equity_curve: List[Tuple[datetime, Decimal]] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'initial_capital': float(self.initial_capital),
            'final_capital': float(self.final_capital),
            'total_return': float(self.total_return),
            'annualized_return': float(self.annualized_return) if self.annualized_return else None,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown else None,
            'sharpe_ratio': float(self.sharpe_ratio) if self.sharpe_ratio else None,
            'sortino_ratio': float(self.sortino_ratio) if self.sortino_ratio else None,
            'win_rate': float(self.win_rate) if self.win_rate else None,
            'profit_factor': float(self.profit_factor) if self.profit_factor else None,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'avg_trade_duration': str(self.avg_trade_duration) if self.avg_trade_duration else None,
            'volatility': float(self.volatility) if self.volatility else None,
            'calmar_ratio': float(self.calmar_ratio) if self.calmar_ratio else None,
            'equity_curve': [(dt.isoformat(), float(equity)) for dt, equity in self.equity_curve],
            'trades': [trade.__dict__ for trade in self.trades],
            'created_at': self.created_at.isoformat(),
        }


class BacktestEngine:
    """
    Backtesting engine for testing strategies on historical data.
    
    Features:
    - Load historical bars from TimescaleDB
    - Replay bars chronologically to strategy
    - Track simulated trades and performance metrics
    - Generate performance report
    - Support multiple strategies simultaneously
    """
    
    def __init__(self):
        """Initialize backtesting engine."""
        self.db_config = get_database_config()
        self.db_pool: Optional[asyncpg.Pool] = None
        
        logger.info("Backtesting engine initialized")
    
    async def initialize(self) -> None:
        """Initialize database connection."""
        if self.db_pool:
            return
        
        import os
        dsn = os.getenv("DATABASE_URL")
        
        if dsn:
            self.db_pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=5,
                command_timeout=60,
                server_settings={
                    'application_name': 'backtest_engine',
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
                min_size=1,
                max_size=5,
                command_timeout=60,
                server_settings={
                    'application_name': 'backtest_engine',
                    'timezone': 'UTC'
                }
            )
        
        logger.info("Backtesting engine connected to database")
    
    async def shutdown(self) -> None:
        """Close database connection."""
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
        logger.info("Backtesting engine shut down")
    
    async def run_backtest(
        self,
        strategy: BaseStrategy,
        start_date: datetime,
        end_date: datetime,
        initial_capital: Decimal = Decimal('100000'),
        commission_per_share: Decimal = Decimal('0.005')
    ) -> BacktestResult:
        """
        Run a backtest for a strategy.
        
        Args:
            strategy: Strategy instance to test
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_capital: Starting capital
            commission_per_share: Commission per share traded
            
        Returns:
            BacktestResult with performance metrics
        """
        if not self.db_pool:
            await self.initialize()
        
        logger.info(
            f"Starting backtest for '{strategy.name}' on {strategy.symbols[0]} "
            f"from {start_date.date()} to {end_date.date()}"
        )
        
        # Initialize strategy
        await strategy.initialize()
        
        # Create paper trading executor for simulation
        paper_executor = PaperTradeExecutor(
            initial_capital=initial_capital,
            commission_per_share=commission_per_share,
            account_id=f"backtest_{strategy.name}_{start_date.strftime('%Y%m%d')}"
        )
        await paper_executor.initialize()
        
        # Load historical data
        symbol = strategy.symbols[0]  # Assume single symbol for now
        bars = await self._load_historical_bars(symbol, start_date, end_date)
        
        if not bars:
            raise ValueError(f"No historical data found for {symbol} in date range")
        
        logger.info(f"Loaded {len(bars)} bars for backtesting")
        
        # Initialize strategy state
        strategy.state.last_processed_timestamp = None
        
        # Track equity curve
        equity_curve = []
        start_equity = initial_capital
        
        # Process bars chronologically
        for i, bar in enumerate(bars):
            # Update strategy cache
            strategy.update_cache(symbol, bar)
            
            # Call strategy logic
            order_spec = await strategy.on_bar_update(symbol, bar)
            
            # Update strategy state
            strategy.state.last_processed_timestamp = bar.timestamp
            
            # Execute order if generated
            if order_spec:
                try:
                    result = await paper_executor.place_order(order_spec)
                    if result.status == 'FILLED':
                        logger.debug(
                            f"Backtest trade: {result.action.value} {result.filled_quantity} "
                            f"{result.symbol} @ ${result.avg_fill_price}"
                        )
                except Exception as e:
                    logger.error(f"Error executing backtest order: {e}")
            
            # Update equity curve (every 10 bars to avoid too much data)
            if i % 10 == 0:
                balance = await paper_executor.get_account_balance()
                equity_curve.append((bar.timestamp, balance.total_equity))
        
        # Get final account balance
        final_balance = await paper_executor.get_account_balance()
        trades = await paper_executor.get_trade_history()
        
        # Calculate performance metrics
        total_return = ((final_balance.total_equity - initial_capital) / initial_capital) * 100
        
        # Calculate additional metrics
        metrics = self._calculate_metrics(
            initial_capital, final_balance, trades, equity_curve, start_date, end_date
        )
        
        # Create result
        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=final_balance.total_equity,
            total_return=total_return,
            **metrics,
            equity_curve=equity_curve,
            trades=trades
        )
        
        # Save result to database
        await self._save_backtest_result(result)
        
        # Shutdown
        await paper_executor.shutdown()
        await strategy.shutdown()
        
        logger.info(f"Backtest completed: {total_return:.2f}% return, {len(trades)} trades")
        
        return result
    
    async def _load_historical_bars(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[BarData]:
        """Load historical bars from database."""
        if not self.db_pool:
            raise RuntimeError("Database not connected")
        
        table_name = f"ibkr_ohlcv_{symbol.lower()}_1m"
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp ASC
        """
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, start_date, end_date)
            
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
            logger.error(f"Error loading historical bars for {symbol}: {e}")
            return []
    
    def _calculate_metrics(
        self,
        initial_capital: Decimal,
        final_balance: AccountBalance,
        trades: List[Trade],
        equity_curve: List[Tuple[datetime, Decimal]],
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Calculate performance metrics."""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': Decimal('0'),
                'profit_factor': Decimal('0'),
                'max_drawdown': Decimal('0'),
                'sharpe_ratio': Decimal('0'),
                'sortino_ratio': Decimal('0'),
                'volatility': Decimal('0'),
                'calmar_ratio': Decimal('0'),
                'annualized_return': Decimal('0'),
                'avg_trade_duration': None
            }
        
        # Basic trade metrics
        total_trades = len(trades)
        winning_trades = sum(1 for trade in trades if trade.pnl and trade.pnl > 0)
        losing_trades = sum(1 for trade in trades if trade.pnl and trade.pnl < 0)
        win_rate = Decimal(str(winning_trades / total_trades)) if total_trades > 0 else Decimal('0')
        
        # Profit factor
        gross_profit = sum(trade.pnl or Decimal('0') for trade in trades if trade.pnl and trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl or Decimal('0') for trade in trades if trade.pnl and trade.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal('0')
        
        # Calculate returns and volatility from equity curve
        if len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                prev_equity = equity_curve[i-1][1]
                curr_equity = equity_curve[i][1]
                if prev_equity > 0:
                    ret = (curr_equity - prev_equity) / prev_equity
                    returns.append(float(ret))
            
            if returns:
                returns_array = np.array(returns)
                volatility = Decimal(str(np.std(returns_array) * np.sqrt(252)))  # Annualized
                
                # Sharpe ratio (assuming risk-free rate of 0)
                if volatility > 0:
                    mean_return = np.mean(returns_array) * 252  # Annualized
                    sharpe_ratio = Decimal(str(mean_return / (np.std(returns_array) * np.sqrt(252))))
                else:
                    sharpe_ratio = Decimal('0')
                
                # Sortino ratio (downside deviation)
                downside_returns = returns_array[returns_array < 0]
                if len(downside_returns) > 0:
                    downside_std = np.std(downside_returns) * np.sqrt(252)
                    if downside_std > 0:
                        sortino_ratio = Decimal(str(mean_return / downside_std))
                    else:
                        sortino_ratio = Decimal('0')
                else:
                    sortino_ratio = Decimal('0')
            else:
                volatility = Decimal('0')
                sharpe_ratio = Decimal('0')
                sortino_ratio = Decimal('0')
        else:
            volatility = Decimal('0')
            sharpe_ratio = Decimal('0')
            sortino_ratio = Decimal('0')
        
        # Max drawdown
        max_drawdown = self._calculate_max_drawdown(equity_curve)
        
        # Annualized return
        days = (end_date - start_date).days
        years = days / 365.25
        if years > 0:
            annualized_return = ((final_balance.total_equity / initial_capital) ** (1 / years) - 1) * 100
        else:
            annualized_return = Decimal('0')
        
        # Calmar ratio
        calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else Decimal('0')
        
        # Average trade duration
        if trades:
            durations = []
            for trade in trades:
                # This is simplified - in reality you'd track entry/exit times
                durations.append(timedelta(hours=1))  # Assume 1 hour average
            avg_trade_duration = sum(durations, timedelta()) / len(durations)
        else:
            avg_trade_duration = None
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'volatility': volatility,
            'calmar_ratio': calmar_ratio,
            'annualized_return': annualized_return,
            'avg_trade_duration': avg_trade_duration
        }
    
    def _calculate_max_drawdown(self, equity_curve: List[Tuple[datetime, Decimal]]) -> Decimal:
        """Calculate maximum drawdown from equity curve."""
        if len(equity_curve) < 2:
            return Decimal('0')
        
        peak = equity_curve[0][1]
        max_dd = Decimal('0')
        
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            else:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        
        return max_dd * 100  # Convert to percentage
    
    async def _save_backtest_result(self, result: BacktestResult) -> None:
        """Save backtest result to database."""
        if not self.db_pool:
            return
        
        try:
            query = """
                INSERT INTO backtest_results 
                (strategy_name, symbol, start_date, end_date, initial_capital, final_capital,
                 total_return, annualized_return, max_drawdown, sharpe_ratio, sortino_ratio,
                 win_rate, profit_factor, total_trades, volatility, calmar_ratio)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            """
            
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    result.strategy_name,
                    result.symbol,
                    result.start_date,
                    result.end_date,
                    float(result.initial_capital),
                    float(result.final_capital),
                    float(result.total_return),
                    float(result.annualized_return) if result.annualized_return else None,
                    float(result.max_drawdown) if result.max_drawdown else None,
                    float(result.sharpe_ratio) if result.sharpe_ratio else None,
                    float(result.sortino_ratio) if result.sortino_ratio else None,
                    float(result.win_rate) if result.win_rate else None,
                    float(result.profit_factor) if result.profit_factor else None,
                    result.total_trades,
                    float(result.volatility) if result.volatility else None,
                    float(result.calmar_ratio) if result.calmar_ratio else None
                )
            
            logger.info("Backtest result saved to database")
            
        except Exception as e:
            logger.error(f"Error saving backtest result: {e}")
    
    async def get_backtest_results(
        self, 
        strategy_name: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 10
    ) -> List[BacktestResult]:
        """Get historical backtest results."""
        if not self.db_pool:
            await self.initialize()
        
        query = """
            SELECT strategy_name, symbol, start_date, end_date, initial_capital, final_capital,
                   total_return, annualized_return, max_drawdown, sharpe_ratio, sortino_ratio,
                   win_rate, profit_factor, total_trades, volatility, calmar_ratio, created_at
            FROM backtest_results
            WHERE 1=1
        """
        params = []
        param_count = 0
        
        if strategy_name:
            param_count += 1
            query += f" AND strategy_name = ${param_count}"
            params.append(strategy_name)
        
        if symbol:
            param_count += 1
            query += f" AND symbol = ${param_count}"
            params.append(symbol)
        
        query += " ORDER BY created_at DESC LIMIT $1"
        params.insert(0, limit)
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            results = []
            for row in rows:
                result = BacktestResult(
                    strategy_name=row['strategy_name'],
                    symbol=row['symbol'],
                    start_date=row['start_date'],
                    end_date=row['end_date'],
                    initial_capital=Decimal(str(row['initial_capital'])),
                    final_capital=Decimal(str(row['final_capital'])),
                    total_return=Decimal(str(row['total_return'])),
                    annualized_return=Decimal(str(row['annualized_return'])) if row['annualized_return'] else None,
                    max_drawdown=Decimal(str(row['max_drawdown'])) if row['max_drawdown'] else None,
                    sharpe_ratio=Decimal(str(row['sharpe_ratio'])) if row['sharpe_ratio'] else None,
                    sortino_ratio=Decimal(str(row['sortino_ratio'])) if row['sortino_ratio'] else None,
                    win_rate=Decimal(str(row['win_rate'])) if row['win_rate'] else None,
                    profit_factor=Decimal(str(row['profit_factor'])) if row['profit_factor'] else None,
                    total_trades=row['total_trades'],
                    volatility=Decimal(str(row['volatility'])) if row['volatility'] else None,
                    calmar_ratio=Decimal(str(row['calmar_ratio'])) if row['calmar_ratio'] else None,
                    created_at=row['created_at']
                )
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting backtest results: {e}")
            return []
