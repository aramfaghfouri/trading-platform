"""
Strategy Performance Tracker

Tracks and analyzes strategy performance over time.
Calculates key metrics like Sharpe ratio, Sortino ratio, max drawdown, win rate, etc.
"""

from __future__ import annotations

import asyncio
import asyncpg
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from loguru import logger
import pandas as pd
import numpy as np

from src.brokers.paper.paper_executor import Trade, AccountBalance
from src.core.config_loader import get_database_config


@dataclass
class PerformanceMetrics:
    """Daily performance metrics for a strategy."""
    strategy_name: str
    symbol: str
    date: date
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal('0')
    total_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    sharpe_ratio: Decimal = Decimal('0')
    sortino_ratio: Decimal = Decimal('0')
    avg_trade_pnl: Decimal = Decimal('0')
    best_trade: Decimal = Decimal('0')
    worst_trade: Decimal = Decimal('0')
    profit_factor: Decimal = Decimal('0')
    recovery_factor: Decimal = Decimal('0')
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'date': self.date.isoformat(),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': float(self.win_rate),
            'total_pnl': float(self.total_pnl),
            'realized_pnl': float(self.realized_pnl),
            'unrealized_pnl': float(self.unrealized_pnl),
            'max_drawdown': float(self.max_drawdown),
            'sharpe_ratio': float(self.sharpe_ratio),
            'sortino_ratio': float(self.sortino_ratio),
            'avg_trade_pnl': float(self.avg_trade_pnl),
            'best_trade': float(self.best_trade),
            'worst_trade': float(self.worst_trade),
            'profit_factor': float(self.profit_factor),
            'recovery_factor': float(self.recovery_factor),
            'created_at': self.created_at.isoformat(),
        }


@dataclass
class EquityCurve:
    """Equity curve data point."""
    timestamp: datetime
    equity: Decimal
    drawdown: Decimal = Decimal('0')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'equity': float(self.equity),
            'drawdown': float(self.drawdown),
        }


class StrategyPerformanceTracker:
    """
    Tracks and analyzes strategy performance over time.
    
    Features:
    - Calculate key metrics: Sharpe ratio, Sortino ratio, max drawdown, win rate
    - Track equity curve over time
    - Store metrics to database
    - Generate performance reports
    """
    
    def __init__(self):
        """Initialize performance tracker."""
        self.db_config = get_database_config()
        self.db_pool: Optional[asyncpg.Pool] = None
        
        logger.info("Strategy performance tracker initialized")
    
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
                command_timeout=30,
                server_settings={
                    'application_name': 'strategy_performance_tracker',
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
                command_timeout=30,
                server_settings={
                    'application_name': 'strategy_performance_tracker',
                    'timezone': 'UTC'
                }
            )
        
        logger.info("Strategy performance tracker connected to database")
    
    async def shutdown(self) -> None:
        """Close database connection."""
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
        logger.info("Strategy performance tracker shut down")
    
    async def calculate_daily_metrics(
        self,
        strategy_name: str,
        symbol: str,
        target_date: date,
        trades: List[Trade],
        equity_curve: List[Tuple[datetime, Decimal]]
    ) -> PerformanceMetrics:
        """
        Calculate daily performance metrics for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            symbol: Symbol being traded
            target_date: Date to calculate metrics for
            trades: List of trades for the day
            equity_curve: Equity curve data points
            
        Returns:
            PerformanceMetrics object
        """
        if not trades:
            return PerformanceMetrics(
                strategy_name=strategy_name,
                symbol=symbol,
                date=target_date
            )
        
        # Basic trade metrics
        total_trades = len(trades)
        winning_trades = sum(1 for trade in trades if trade.pnl and trade.pnl > 0)
        losing_trades = sum(1 for trade in trades if trade.pnl and trade.pnl < 0)
        win_rate = Decimal(str(winning_trades / total_trades)) if total_trades > 0 else Decimal('0')
        
        # P&L metrics
        total_pnl = sum(trade.pnl or Decimal('0') for trade in trades)
        realized_pnl = sum(trade.pnl or Decimal('0') for trade in trades if trade.pnl)
        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else Decimal('0')
        
        # Best and worst trades
        pnl_values = [trade.pnl for trade in trades if trade.pnl is not None]
        best_trade = max(pnl_values) if pnl_values else Decimal('0')
        worst_trade = min(pnl_values) if pnl_values else Decimal('0')
        
        # Profit factor
        gross_profit = sum(trade.pnl or Decimal('0') for trade in trades if trade.pnl and trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl or Decimal('0') for trade in trades if trade.pnl and trade.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal('0')
        
        # Calculate risk metrics from equity curve
        if len(equity_curve) > 1:
            returns = self._calculate_returns(equity_curve)
            max_drawdown = self._calculate_max_drawdown(equity_curve)
            sharpe_ratio = self._calculate_sharpe_ratio(returns)
            sortino_ratio = self._calculate_sortino_ratio(returns)
            recovery_factor = self._calculate_recovery_factor(total_pnl, max_drawdown)
        else:
            max_drawdown = Decimal('0')
            sharpe_ratio = Decimal('0')
            sortino_ratio = Decimal('0')
            recovery_factor = Decimal('0')
        
        return PerformanceMetrics(
            strategy_name=strategy_name,
            symbol=symbol,
            date=target_date,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=Decimal('0'),  # Will be updated from account balance
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            avg_trade_pnl=avg_trade_pnl,
            best_trade=best_trade,
            worst_trade=worst_trade,
            profit_factor=profit_factor,
            recovery_factor=recovery_factor
        )
    
    def _calculate_returns(self, equity_curve: List[Tuple[datetime, Decimal]]) -> List[float]:
        """Calculate returns from equity curve."""
        if len(equity_curve) < 2:
            return []
        
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i-1][1]
            curr_equity = equity_curve[i][1]
            if prev_equity > 0:
                ret = float((curr_equity - prev_equity) / prev_equity)
                returns.append(ret)
        
        return returns
    
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
    
    def _calculate_sharpe_ratio(self, returns: List[float]) -> Decimal:
        """Calculate Sharpe ratio from returns."""
        if not returns or len(returns) < 2:
            return Decimal('0')
        
        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)
        
        if std_return > 0:
            # Annualized Sharpe ratio (assuming 252 trading days)
            sharpe = (mean_return / std_return) * np.sqrt(252)
            return Decimal(str(sharpe))
        else:
            return Decimal('0')
    
    def _calculate_sortino_ratio(self, returns: List[float]) -> Decimal:
        """Calculate Sortino ratio from returns."""
        if not returns or len(returns) < 2:
            return Decimal('0')
        
        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        
        # Calculate downside deviation
        downside_returns = returns_array[returns_array < 0]
        if len(downside_returns) > 0:
            downside_std = np.std(downside_returns)
            if downside_std > 0:
                # Annualized Sortino ratio
                sortino = (mean_return / downside_std) * np.sqrt(252)
                return Decimal(str(sortino))
        
        return Decimal('0')
    
    def _calculate_recovery_factor(self, total_pnl: Decimal, max_drawdown: Decimal) -> Decimal:
        """Calculate recovery factor."""
        if max_drawdown > 0:
            return total_pnl / max_drawdown
        else:
            return Decimal('0')
    
    async def save_performance_metrics(self, metrics: PerformanceMetrics) -> None:
        """Save performance metrics to database."""
        if not self.db_pool:
            await self.initialize()
        
        try:
            query = """
                INSERT INTO strategy_performance 
                (strategy_name, symbol, date, total_trades, winning_trades, losing_trades,
                 win_rate, total_pnl, realized_pnl, unrealized_pnl, max_drawdown,
                 sharpe_ratio, sortino_ratio, avg_trade_pnl, best_trade, worst_trade,
                 profit_factor, recovery_factor, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (strategy_name, symbol, date) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    winning_trades = EXCLUDED.winning_trades,
                    losing_trades = EXCLUDED.losing_trades,
                    win_rate = EXCLUDED.win_rate,
                    total_pnl = EXCLUDED.total_pnl,
                    realized_pnl = EXCLUDED.realized_pnl,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    max_drawdown = EXCLUDED.max_drawdown,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    sortino_ratio = EXCLUDED.sortino_ratio,
                    avg_trade_pnl = EXCLUDED.avg_trade_pnl,
                    best_trade = EXCLUDED.best_trade,
                    worst_trade = EXCLUDED.worst_trade,
                    profit_factor = EXCLUDED.profit_factor,
                    recovery_factor = EXCLUDED.recovery_factor,
                    created_at = EXCLUDED.created_at
            """
            
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    metrics.strategy_name,
                    metrics.symbol,
                    metrics.date,
                    metrics.total_trades,
                    metrics.winning_trades,
                    metrics.losing_trades,
                    float(metrics.win_rate),
                    float(metrics.total_pnl),
                    float(metrics.realized_pnl),
                    float(metrics.unrealized_pnl),
                    float(metrics.max_drawdown),
                    float(metrics.sharpe_ratio),
                    float(metrics.sortino_ratio),
                    float(metrics.avg_trade_pnl),
                    float(metrics.best_trade),
                    float(metrics.worst_trade),
                    float(metrics.profit_factor),
                    float(metrics.recovery_factor),
                    metrics.created_at
                )
            
            logger.info(f"Saved performance metrics for {metrics.strategy_name} on {metrics.date}")
            
        except Exception as e:
            logger.error(f"Error saving performance metrics: {e}")
    
    async def get_performance_metrics(
        self,
        strategy_name: str,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[PerformanceMetrics]:
        """Get performance metrics for a strategy."""
        if not self.db_pool:
            await self.initialize()
        
        query = """
            SELECT strategy_name, symbol, date, total_trades, winning_trades, losing_trades,
                   win_rate, total_pnl, realized_pnl, unrealized_pnl, max_drawdown,
                   sharpe_ratio, sortino_ratio, avg_trade_pnl, best_trade, worst_trade,
                   profit_factor, recovery_factor, created_at
            FROM strategy_performance
            WHERE strategy_name = $1 AND symbol = $2
        """
        params = [strategy_name, symbol]
        param_count = 2
        
        if start_date:
            param_count += 1
            query += f" AND date >= ${param_count}"
            params.append(start_date)
        
        if end_date:
            param_count += 1
            query += f" AND date <= ${param_count}"
            params.append(end_date)
        
        query += " ORDER BY date ASC"
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            metrics = []
            for row in rows:
                metric = PerformanceMetrics(
                    strategy_name=row['strategy_name'],
                    symbol=row['symbol'],
                    date=row['date'],
                    total_trades=row['total_trades'],
                    winning_trades=row['winning_trades'],
                    losing_trades=row['losing_trades'],
                    win_rate=Decimal(str(row['win_rate'])),
                    total_pnl=Decimal(str(row['total_pnl'])),
                    realized_pnl=Decimal(str(row['realized_pnl'])),
                    unrealized_pnl=Decimal(str(row['unrealized_pnl'])),
                    max_drawdown=Decimal(str(row['max_drawdown'])),
                    sharpe_ratio=Decimal(str(row['sharpe_ratio'])),
                    sortino_ratio=Decimal(str(row['sortino_ratio'])),
                    avg_trade_pnl=Decimal(str(row['avg_trade_pnl'])),
                    best_trade=Decimal(str(row['best_trade'])),
                    worst_trade=Decimal(str(row['worst_trade'])),
                    profit_factor=Decimal(str(row['profit_factor'])),
                    recovery_factor=Decimal(str(row['recovery_factor'])),
                    created_at=row['created_at']
                )
                metrics.append(metric)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return []
    
    async def generate_performance_report(
        self,
        strategy_name: str,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Generate a comprehensive performance report."""
        metrics = await self.get_performance_metrics(strategy_name, symbol, start_date, end_date)
        
        if not metrics:
            return {
                'strategy_name': strategy_name,
                'symbol': symbol,
                'period': f"{start_date} to {end_date}" if start_date and end_date else "All time",
                'message': 'No performance data available'
            }
        
        # Calculate summary statistics
        total_trades = sum(m.total_trades for m in metrics)
        total_pnl = sum(m.total_pnl for m in metrics)
        avg_daily_pnl = total_pnl / len(metrics) if metrics else Decimal('0')
        
        # Best and worst days
        best_day = max(metrics, key=lambda m: m.total_pnl) if metrics else None
        worst_day = min(metrics, key=lambda m: m.total_pnl) if metrics else None
        
        # Win rate over period
        total_winning_trades = sum(m.winning_trades for m in metrics)
        overall_win_rate = total_winning_trades / total_trades if total_trades > 0 else Decimal('0')
        
        # Average metrics
        avg_sharpe = sum(m.sharpe_ratio for m in metrics) / len(metrics) if metrics else Decimal('0')
        avg_sortino = sum(m.sortino_ratio for m in metrics) / len(metrics) if metrics else Decimal('0')
        avg_profit_factor = sum(m.profit_factor for m in metrics) / len(metrics) if metrics else Decimal('0')
        
        # Max drawdown over period
        max_drawdown = max(m.max_drawdown for m in metrics) if metrics else Decimal('0')
        
        return {
            'strategy_name': strategy_name,
            'symbol': symbol,
            'period': f"{start_date} to {end_date}" if start_date and end_date else "All time",
            'summary': {
                'total_trades': total_trades,
                'total_pnl': float(total_pnl),
                'avg_daily_pnl': float(avg_daily_pnl),
                'overall_win_rate': float(overall_win_rate),
                'max_drawdown': float(max_drawdown),
                'avg_sharpe_ratio': float(avg_sharpe),
                'avg_sortino_ratio': float(avg_sortino),
                'avg_profit_factor': float(avg_profit_factor),
            },
            'best_day': {
                'date': best_day.date.isoformat(),
                'pnl': float(best_day.total_pnl),
                'trades': best_day.total_trades
            } if best_day else None,
            'worst_day': {
                'date': worst_day.date.isoformat(),
                'pnl': float(worst_day.total_pnl),
                'trades': worst_day.total_trades
            } if worst_day else None,
            'daily_metrics': [m.to_dict() for m in metrics]
        }
