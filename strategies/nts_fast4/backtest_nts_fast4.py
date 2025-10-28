#!/usr/bin/env python3
"""
Backtest runner for NTS FAST4 Strategy.

This script runs backtests for the NTS FAST4 strategy using historical data.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import pandas as pd
import numpy as np
from loguru import logger
import tomli

from strategies.nts_fast4.nts_fast4 import NTSFast4
from src.strategies.models import BarData, OrderSpec, OrderAction
from src.core.config_loader import get_database_config
import asyncpg
from decimal import Decimal


class NTSFast4BacktestRunner:
    """Backtest runner for NTS FAST4 strategy."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.strategy = None
        self.db_pool = None
        
        # Backtest results
        self.trades = []
        self.equity_curve = []
        self.initial_capital = config.get('initial_capital', 100000)
        self.current_capital = self.initial_capital
        self.commission_per_share = config.get('commission_per_share', 0.005)
    
    @classmethod
    def load_config(cls, config_file: str = None) -> Dict[str, Any]:
        """Load configuration from TOML file."""
        if config_file is None:
            config_file = Path(__file__).parent / "config.toml"
        
        if not Path(config_file).exists():
            logger.warning(f"Config file {config_file} not found, using defaults")
            return cls.get_default_config()
        
        try:
            with open(config_file, 'rb') as f:
                config = tomli.load(f)
            
            # Merge with defaults
            default_config = cls.get_default_config()
            default_config.update(config)
            return default_config
            
        except Exception as e:
            logger.error(f"Error loading config file {config_file}: {e}")
            return cls.get_default_config()
    
    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'parameters': {
                'trail_type': 'modified',
                'atr_period': 185,
                'atr_factor': 3.0,
                'use_take_profit': True,
                'tp_fib_level': '78.6',
                'quantity': 100,
                'min_lookback': 200,
                'mtf_resolution': '5m->15m'
            },
            'backtest': {
                'start_date': '2025-09-01',
                'end_date': '2025-10-27',
                'initial_capital': 100000,
                'commission_per_share': 0.005,
                'symbols': ['AAPL']
            },
            'paper_trading': {
                'enabled': True,
                'initial_capital': 10000,
                'commission_per_share': 0.005
            },
            'live_trading': {
                'enabled': False,
                'max_position_size': 1000,
                'risk_per_trade': 0.02
            }
        }
        
    async def initialize(self):
        """Initialize the backtest runner."""
        # Create strategy
        strategy_config = self.config.get('strategy', {})
        symbols = self.config.get('symbols', ['AAPL'])
        
        self.strategy = NTSFast4(
            name="nts_fast4_backtest",
            config=strategy_config,
            symbols=symbols
        )
        
        # Connect to database
        db_config = get_database_config()
        import os
        dsn = os.getenv("DATABASE_URL")
        
        if dsn:
            self.db_pool = await asyncpg.create_pool(dsn=dsn)
        else:
            self.db_pool = await asyncpg.create_pool(
                host=db_config.host,
                port=db_config.port,
                database=db_config.database,
                user=db_config.username,
                password=db_config.password,
                ssl=db_config.ssl_mode
            )
        
        logger.info("Backtest runner initialized")

    def _ensure_minute_continuity(self, df_1m: pd.DataFrame, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Validate that every RTH minute exists between start and end.

        RTH: 09:30-16:00 America/New_York, Mon-Fri. DB timestamps assumed UTC.
        Returns a DataFrame reindexed to expected minutes or None if gaps exist.
        """
        try:
            if df_1m.empty:
                logger.error("Empty DataFrame for continuity check")
                return None

            import pytz
            ny_tz = pytz.timezone('America/New_York')

            # Normalize timezone awareness
            if df_1m.index.tz is None:
                actual_index = pd.DatetimeIndex(df_1m.index).tz_localize('UTC')
            else:
                actual_index = pd.DatetimeIndex(df_1m.index).tz_convert('UTC')

            # Build expected UTC minute index for trading days and RTH minutes
            start_ny = pd.Timestamp(start_date, tz='UTC').tz_convert(ny_tz)
            end_ny = pd.Timestamp(end_date, tz='UTC').tz_convert(ny_tz)

            expected_utc_minutes = []
            day = start_ny.normalize().date()
            last_day = end_ny.normalize().date()
            while day <= last_day:
                if pd.Timestamp(day).weekday() < 5:
                    rth_start_ny = ny_tz.localize(pd.Timestamp(day).replace(hour=9, minute=30, second=0, microsecond=0).to_pydatetime())
                    rth_end_ny = ny_tz.localize(pd.Timestamp(day).replace(hour=16, minute=0, second=0, microsecond=0).to_pydatetime())
                    rng = pd.date_range(start=rth_start_ny, end=rth_end_ny, freq='1min', inclusive='left')
                    expected_utc_minutes.extend(rng.tz_convert('UTC').to_pydatetime().tolist())
                day = (pd.Timestamp(day) + pd.Timedelta(days=1)).date()

            expected_index = pd.DatetimeIndex(pd.to_datetime(expected_utc_minutes, utc=True))
            # Clamp to requested window [start_date, end_date)
            expected_index = expected_index[(expected_index >= pd.Timestamp(start_date, tz='UTC')) & (expected_index < pd.Timestamp(end_date, tz='UTC'))]

            missing = expected_index.difference(actual_index)
            if len(missing) > 0:
                logger.error(f"Continuity check failed: missing {len(missing)} RTH minutes (first 5) {list(missing[:5])}")
                return None

            # Reindex to expected to ensure alignment ordering
            df_continuous = df_1m.copy()
            df_continuous.index = actual_index
            df_continuous = df_continuous.reindex(expected_index)

            return df_continuous
        except Exception as exc:
            logger.error(f"Continuity check error: {exc}")
            return None
    
    async def load_historical_data(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime,
        timeframe: str = '1m'
    ) -> List[BarData]:
        """Load historical data for backtesting."""
        # Use exact 1m data; do not resample
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
            
            bars = []
            for row in rows:
                bar = BarData(
                    timestamp=row['timestamp'],
                    open=Decimal(str(row['open'])),
                    high=Decimal(str(row['high'])),
                    low=Decimal(str(row['low'])),
                    close=Decimal(str(row['close'])),
                    volume=int(row['volume']),
                    symbol=symbol
                )
                bars.append(bar)
            
            logger.info(f"Loaded {len(bars)} 1m bars for {symbol} from {start_date} to {end_date}")
            return bars
            
        except asyncpg.UndefinedTableError:
            logger.error(f"Table {table_name} does not exist")
            return []
        except Exception as e:
            logger.error(f"Error loading historical data: {e}")
            return []
    
    def _resample_bars(self, bars: List[BarData], timeframe: str) -> List[BarData]:
        """Resample bars to a different timeframe."""
        if not bars:
            return bars
            
        # Convert to DataFrame for resampling
        data = []
        for bar in bars:
            data.append({
                'timestamp': bar.timestamp,
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': bar.volume
            })
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        
        # Resample based on timeframe
        if timeframe == '5m':
            freq = '5T'
        elif timeframe == '15m':
            freq = '15T'
        elif timeframe == '30m':
            freq = '30T'
        elif timeframe == '1h':
            freq = '1H'
        else:
            logger.warning(f"Unknown timeframe {timeframe}, using original bars")
            return bars
        
        # Resample OHLCV data
        resampled = df.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        # Convert back to BarData objects
        resampled_bars = []
        for timestamp, row in resampled.iterrows():
            bar = BarData(
                timestamp=timestamp,
                open=Decimal(str(row['open'])),
                high=Decimal(str(row['high'])),
                low=Decimal(str(row['low'])),
                close=Decimal(str(row['close'])),
                volume=int(row['volume']),
                symbol=bars[0].symbol
            )
            resampled_bars.append(bar)
        
        logger.info(f"Resampled {len(bars)} 1m bars to {len(resampled_bars)} {timeframe} bars")
        return resampled_bars
    
    async def run_backtest(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> Dict[str, Any]:
        """Run the backtest."""
        logger.info(f"Starting backtest for {symbol} from {start_date} to {end_date}")
        
        # Load historical data (exact 1m bars)
        bars = await self.load_historical_data(symbol, start_date, end_date, '1m')
        
        if not bars:
            logger.error("No historical data available for backtesting")
            return {}
        
        # Initialize strategy with historical data
        await self._initialize_strategy_with_data(symbol, bars, start_date, end_date)
        
        # Run backtest
        position = 0
        entry_price = 0.0
        entry_time = None
        
        for i, bar in enumerate(bars):
            # Update strategy cache
            self.strategy.update_cache(symbol, bar)
            
            # Get strategy signal
            order = await self.strategy.on_bar_update(symbol, bar)
            
            if order:
                await self._process_order(order, bar, position, entry_price, entry_time)
                
                # Update position
                if order.action == OrderAction.BUY:
                    position += order.quantity
                    entry_price = float(bar.close)
                    entry_time = bar.timestamp
                elif order.action == OrderAction.SELL:
                    position -= order.quantity
                    if position == 0:
                        entry_price = 0.0
                        entry_time = None
            
            # Update equity curve
            current_equity = self.current_capital + (position * float(bar.close))
            self.equity_curve.append({
                'timestamp': bar.timestamp,
                'equity': current_equity,
                'position': position,
                'price': float(bar.close)
            })
        
        # Close any remaining position
        if position != 0:
            final_bar = bars[-1]
            await self._close_position(symbol, position, final_bar)
        
        # Calculate performance metrics
        metrics = self._calculate_performance_metrics()
        
        logger.info(f"Backtest completed. Total trades: {len(self.trades)}")
        return metrics
    
    async def _initialize_strategy_with_data(self, symbol: str, bars: List[BarData], start_date: datetime, end_date: datetime):
        """Initialize strategy with historical data."""
        # Convert bars to DataFrame for strategy cache
        data = []
        for bar in bars:
            data.append({
                'timestamp': bar.timestamp,
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': bar.volume
            })
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)

        # Ensure continuity for all market minutes in RTH
        df_valid = self._ensure_minute_continuity(df, start_date, end_date)
        if df_valid is None:
            raise RuntimeError("Historical data failed continuity checks. Aborting backtest.")
        df = df_valid

        self.strategy._bar_cache[symbol] = df
        
        # Do not pre-populate higher TF cache; strategy must use exact data
        
        # Initialize strategy
        await self.strategy.initialize()
    
    # MTF prepopulation removed: strict 1m workflow only
    
    async def _process_order(
        self, 
        order: OrderSpec, 
        bar: BarData, 
        current_position: int,
        entry_price: float,
        entry_time: datetime
    ):
        """Process a trading order."""
        if order.action == OrderAction.BUY:
            # Opening long position
            if current_position == 0:
                logger.info(f"OPEN LONG: {bar.timestamp} Price=${float(bar.close):.2f}")
            else:
                logger.info(f"ADD TO LONG: {bar.timestamp} Price=${float(bar.close):.2f}")
                
        elif order.action == OrderAction.SELL:
            if current_position > 0:
                # Closing long position
                pnl = (float(bar.close) - entry_price) * current_position
                commission = abs(current_position) * self.commission_per_share
                net_pnl = pnl - commission
                
                self.current_capital += net_pnl
                
                trade = {
                    'entry_time': entry_time,
                    'exit_time': bar.timestamp,
                    'entry_price': entry_price,
                    'exit_price': float(bar.close),
                    'quantity': current_position,
                    'pnl': pnl,
                    'commission': commission,
                    'net_pnl': net_pnl,
                    'side': 'long'
                }
                
                self.trades.append(trade)
                
                logger.info(
                    f"CLOSE LONG: {bar.timestamp} "
                    f"Entry=${entry_price:.2f} Exit=${float(bar.close):.2f} "
                    f"PnL=${net_pnl:.2f}"
                )
            else:
                # Opening short position
                logger.info(f"OPEN SHORT: {bar.timestamp} Price=${float(bar.close):.2f}")
    
    async def _close_position(self, symbol: str, position: int, bar: BarData):
        """Close any remaining position at the end of backtest."""
        if position != 0:
            # Calculate P&L for remaining position
            # This is a simplified calculation - in reality, we'd need entry price
            logger.info(f"Closing remaining position of {position} shares at ${float(bar.close):.2f}")
    
    def _calculate_performance_metrics(self) -> Dict[str, Any]:
        """Calculate backtest performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # Basic metrics
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t['net_pnl'] > 0])
        losing_trades = len([t for t in self.trades if t['net_pnl'] < 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # P&L metrics
        total_pnl = sum(t['net_pnl'] for t in self.trades)
        gross_profit = sum(t['net_pnl'] for t in self.trades if t['net_pnl'] > 0)
        gross_loss = abs(sum(t['net_pnl'] for t in self.trades if t['net_pnl'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Drawdown calculation
        equity_values = [point['equity'] for point in self.equity_curve]
        peak = equity_values[0]
        max_drawdown = 0
        
        for equity in equity_values:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            max_drawdown = max(max_drawdown, drawdown)
        
        # Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                ret = (self.equity_curve[i]['equity'] - self.equity_curve[i-1]['equity']) / self.equity_curve[i-1]['equity']
                returns.append(ret)
            
            if returns:
                sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'final_capital': self.current_capital,
            'total_return': (self.current_capital - self.initial_capital) / self.initial_capital
        }
    
    async def shutdown(self):
        """Shutdown the backtest runner."""
        if self.db_pool:
            await self.db_pool.close()
        logger.info("Backtest runner shut down")


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Run NTS FAST4 strategy backtest')
    parser.add_argument('--config', help='Path to config file (default: strategies/nts_fast4/config.toml)')
    parser.add_argument('--symbol', help='Symbol to backtest (overrides config)')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD) (overrides config)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD) (overrides config)')
    parser.add_argument('--initial-capital', type=float, help='Initial capital (overrides config)')
    parser.add_argument('--commission', type=float, help='Commission per share (overrides config)')
    
    args = parser.parse_args()
    
    # Load configuration
    config = NTSFast4BacktestRunner.load_config(args.config)
    
    # Override with command line arguments if provided
    if args.symbol:
        config['backtest']['symbols'] = [args.symbol]
    if args.start_date:
        config['backtest']['start_date'] = args.start_date
    if args.end_date:
        config['backtest']['end_date'] = args.end_date
    if args.initial_capital:
        config['backtest']['initial_capital'] = args.initial_capital
    if args.commission:
        config['backtest']['commission_per_share'] = args.commission
    
    # Parse dates
    start_date = datetime.strptime(config['backtest']['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(config['backtest']['end_date'], '%Y-%m-%d')
    
    # Prepare strategy configuration
    strategy_config = config['parameters'].copy()
    
    # Prepare backtest configuration
    backtest_config = {
        'symbols': config['backtest']['symbols'],
        'initial_capital': config['backtest']['initial_capital'],
        'commission_per_share': config['backtest']['commission_per_share'],
        'strategy': strategy_config
    }
    
    # Run backtest
    runner = NTSFast4BacktestRunner(backtest_config)
    
    try:
        await runner.initialize()
        symbol = config['backtest']['symbols'][0]  # Use first symbol from config
        metrics = await runner.run_backtest(symbol, start_date, end_date)
        
        # Print results
        print("\n" + "="*50)
        print("NTS FAST4 STRATEGY BACKTEST RESULTS")
        print("="*50)
        print(f"Symbol: {symbol}")
        print(f"Period: {start_date.date()} to {end_date.date()}")
        print(f"Initial Capital: ${config['backtest']['initial_capital']:,.2f}")
        print(f"Final Capital: ${metrics.get('final_capital', 0):,.2f}")
        print(f"Total Return: {metrics.get('total_return', 0):.2%}")
        print(f"Total Trades: {metrics.get('total_trades', 0)}")
        print(f"Win Rate: {metrics.get('win_rate', 0):.2%}")
        print(f"Total P&L: ${metrics.get('total_pnl', 0):,.2f}")
        print(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        print(f"Max Drawdown: {metrics.get('max_drawdown', 0):.2%}")
        print(f"Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print("="*50)
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
    finally:
        await runner.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
