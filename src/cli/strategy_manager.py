#!/usr/bin/env python3
"""
Strategy Manager CLI

Command-line interface for managing trading strategies:
- Start/stop individual strategies
- Start/stop all enabled strategies
- View strategy status
- View generated signals
- Monitor strategy health
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import asyncpg
from loguru import logger
from tabulate import tabulate

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.config_loader import get_database_config, load_config
from src.strategies.runner.strategy_runner import run_strategy_from_config


class StrategyManager:
    """Manages lifecycle of trading strategies."""
    
    def __init__(self):
        self.db_config = get_database_config()
        self.db_pool: Optional[asyncpg.Pool] = None
        self.processes: Dict[str, subprocess.Popen] = {}
        self.config_path = project_root / 'config' / 'strategies.yaml'
        
    async def __aenter__(self):
        await self.connect_db()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect_db()
    
    async def connect_db(self) -> None:
        """Connect to database."""
        import os
        dsn = os.getenv("DATABASE_URL")
        
        if dsn:
            self.db_pool = await asyncpg.create_pool(dsn=dsn)
        else:
            self.db_pool = await asyncpg.create_pool(
                host=self.db_config.host,
                port=self.db_config.port,
                database=self.db_config.database,
                user=self.db_config.username,
                password=self.db_config.password,
            )
    
    async def disconnect_db(self) -> None:
        """Disconnect from database."""
        if self.db_pool:
            await self.db_pool.close()
    
    def load_config(self) -> Dict:
        """Load strategies configuration."""
        if not self.config_path.exists():
            logger.error(f"Configuration file not found: {self.config_path}")
            return {}
        
        config = load_config(str(self.config_path))
        return config.dict() if hasattr(config, 'dict') else config
    
    async def list_strategies(self) -> None:
        """List all configured strategies."""
        config = self.load_config()
        
        if not config or 'strategies' not in config:
            print("No strategies configured")
            return
        
        strategies_config = config['strategies']
        
        # Get status from database
        query = """
            SELECT strategy_name, is_running, last_heartbeat, error_message
            FROM strategy_state
        """
        
        status_map = {}
        if self.db_pool:
            try:
                rows = await self.db_pool.fetch(query)
                status_map = {row['strategy_name']: row for row in rows}
            except Exception as e:
                logger.warning(f"Could not fetch strategy status: {e}")
        
        # Build table
        table_data = []
        
        for name, config in strategies_config.items():
            if name == 'registry':
                continue
            
            enabled = config.get('enabled', False)
            symbols = ', '.join(config.get('symbols', []))
            class_name = config.get('class', 'N/A').split('.')[-1]
            
            status = status_map.get(name)
            if status:
                running = "🟢 Running" if status['is_running'] else "🔴 Stopped"
                heartbeat = status['last_heartbeat'].strftime('%H:%M:%S') if status['last_heartbeat'] else 'N/A'
                error = status['error_message'][:30] + '...' if status['error_message'] else ''
            else:
                running = "⚪ Not Started"
                heartbeat = 'N/A'
                error = ''
            
            table_data.append([
                name,
                class_name,
                "✓" if enabled else "✗",
                symbols,
                running,
                heartbeat,
                error
            ])
        
        headers = ['Strategy', 'Class', 'Enabled', 'Symbols', 'Status', 'Last Heartbeat', 'Error']
        print("\n" + tabulate(table_data, headers=headers, tablefmt='grid'))
        print()
    
    async def start_strategy(self, strategy_name: str) -> bool:
        """
        Start a strategy in a subprocess.
        
        Args:
            strategy_name: Name of the strategy to start
            
        Returns:
            True if started successfully
        """
        config = self.load_config()
        
        if not config or 'strategies' not in config:
            logger.error("No strategies configuration found")
            return False
        
        strategies_config = config['strategies']
        
        if strategy_name not in strategies_config:
            logger.error(f"Strategy '{strategy_name}' not found in configuration")
            return False
        
        strategy_config = strategies_config[strategy_name]
        
        if not strategy_config.get('enabled', False):
            logger.warning(f"Strategy '{strategy_name}' is not enabled in configuration")
        
        # Check if already running
        if strategy_name in self.processes:
            proc = self.processes[strategy_name]
            if proc.poll() is None:  # Still running
                logger.warning(f"Strategy '{strategy_name}' is already running (PID: {proc.pid})")
                return False
        
        # Start strategy in subprocess
        script_path = project_root / 'scripts' / 'run_strategy.py'
        
        cmd = [
            sys.executable,
            str(script_path),
            strategy_name,
        ]
        
        try:
            logger.info(f"Starting strategy '{strategy_name}'...")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(project_root),
            )
            
            self.processes[strategy_name] = proc
            
            # Wait a moment to check if it started successfully
            time.sleep(1)
            
            if proc.poll() is None:
                logger.info(f"✅ Strategy '{strategy_name}' started successfully (PID: {proc.pid})")
                return True
            else:
                stdout, stderr = proc.communicate()
                logger.error(f"❌ Strategy '{strategy_name}' failed to start:")
                logger.error(f"STDOUT: {stdout.decode()}")
                logger.error(f"STDERR: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Error starting strategy '{strategy_name}': {e}")
            return False
    
    async def stop_strategy(self, strategy_name: str) -> bool:
        """
        Stop a running strategy.
        
        Args:
            strategy_name: Name of the strategy to stop
            
        Returns:
            True if stopped successfully
        """
        # Check if we have a process handle
        if strategy_name in self.processes:
            proc = self.processes[strategy_name]
            if proc.poll() is None:  # Still running
                logger.info(f"Stopping strategy '{strategy_name}' (PID: {proc.pid})...")
                proc.terminate()
                
                # Wait for graceful shutdown
                try:
                    proc.wait(timeout=10)
                    logger.info(f"✅ Strategy '{strategy_name}' stopped")
                except subprocess.TimeoutExpired:
                    logger.warning(f"Strategy '{strategy_name}' did not stop gracefully, killing...")
                    proc.kill()
                    proc.wait()
                    logger.info(f"✅ Strategy '{strategy_name}' killed")
                
                del self.processes[strategy_name]
                return True
        
        # Try to find and kill by querying database
        logger.warning(f"No process handle for '{strategy_name}', cannot stop")
        return False
    
    async def start_all(self) -> None:
        """Start all enabled strategies."""
        config = self.load_config()
        
        if not config or 'strategies' not in config:
            logger.error("No strategies configuration found")
            return
        
        registry = config['strategies'].get('registry', {})
        enabled_strategies = registry.get('enabled_strategies', [])
        
        if not enabled_strategies:
            logger.info("No enabled strategies found in registry")
            return
        
        logger.info(f"Starting {len(enabled_strategies)} strategies...")
        
        for strategy_name in enabled_strategies:
            await self.start_strategy(strategy_name)
            await asyncio.sleep(1)  # Delay between starts
    
    async def stop_all(self) -> None:
        """Stop all running strategies."""
        if not self.processes:
            logger.info("No running strategies to stop")
            return
        
        logger.info(f"Stopping {len(self.processes)} strategies...")
        
        for strategy_name in list(self.processes.keys()):
            await self.stop_strategy(strategy_name)
    
    async def show_status(self, watch: bool = False) -> None:
        """
        Show detailed status of all strategies.
        
        Args:
            watch: If True, continuously update display
        """
        try:
            while True:
                # Clear screen if watching
                if watch:
                    print("\033[2J\033[H", end='')  # Clear screen and move cursor to top
                
                await self.list_strategies()
                
                if not watch:
                    break
                
                print("Refreshing every 5 seconds... (Ctrl+C to stop)")
                await asyncio.sleep(5)
                
        except KeyboardInterrupt:
            print("\nStopped monitoring")
    
    async def run_strategy(self, strategy_name: str, mode: str = 'paper') -> None:
        """
        Run a strategy using the live strategy executor.
        
        Args:
            strategy_name: Name of the strategy to run
            mode: Execution mode ('paper' or 'backtest')
        """
        script_path = project_root / 'scripts' / 'run_live_strategy.py'
        
        cmd = [
            sys.executable,
            str(script_path),
            strategy_name,
            '--mode', mode
        ]
        
        try:
            logger.info(f"Running strategy '{strategy_name}' in {mode} mode...")
            proc = subprocess.run(cmd, cwd=str(project_root))
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Error running strategy '{strategy_name}': {e}")
            return False
    
    async def backtest_strategy(
        self, 
        strategy_name: str, 
        start_date: str, 
        end_date: str,
        initial_capital: float = 100000
    ) -> None:
        """
        Run a backtest for a strategy.
        
        Args:
            strategy_name: Name of the strategy to backtest
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            initial_capital: Starting capital
        """
        from src.strategies.backtesting.backtest_engine import BacktestEngine
        from src.strategies.base import BaseStrategy
        from src.core.config_loader import get_strategies_config
        
        try:
            # Load strategy configuration
            strategies_config = get_strategies_config()
            if strategy_name not in strategies_config.strategies:
                logger.error(f"Strategy '{strategy_name}' not found in configuration")
                return
            
            strategy_config = strategies_config.strategies[strategy_name]
            
            # Import and create strategy instance
            class_path = strategy_config.get('class')
            if not class_path:
                logger.error(f"No 'class' specified for strategy '{strategy_name}'")
                return
            
            module_path, class_name = class_path.rsplit('.', 1)
            import importlib
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, class_name)
            
            strategy = strategy_class(
                name=strategy_name,
                config=strategy_config.get('parameters', {}),
                symbols=strategy_config.get('symbols', []),
            )
            
            # Create backtest engine
            engine = BacktestEngine()
            await engine.initialize()
            
            # Parse dates
            from datetime import datetime
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Run backtest
            logger.info(f"Running backtest for '{strategy_name}' from {start_date} to {end_date}")
            result = await engine.run_backtest(
                strategy=strategy,
                start_date=start_dt,
                end_date=end_dt,
                initial_capital=Decimal(str(initial_capital))
            )
            
            # Display results
            print("\n" + "="*60)
            print(f"BACKTEST RESULTS: {strategy_name}")
            print("="*60)
            print(f"Period: {result.start_date.date()} to {result.end_date.date()}")
            print(f"Initial Capital: ${result.initial_capital:,.2f}")
            print(f"Final Capital: ${result.final_capital:,.2f}")
            print(f"Total Return: {result.total_return:.2f}%")
            print(f"Annualized Return: {result.annualized_return:.2f}%" if result.annualized_return else "N/A")
            print(f"Max Drawdown: {result.max_drawdown:.2f}%" if result.max_drawdown else "N/A")
            print(f"Sharpe Ratio: {result.sharpe_ratio:.4f}" if result.sharpe_ratio else "N/A")
            print(f"Sortino Ratio: {result.sortino_ratio:.4f}" if result.sortino_ratio else "N/A")
            print(f"Win Rate: {result.win_rate:.2%}" if result.win_rate else "N/A")
            print(f"Profit Factor: {result.profit_factor:.2f}" if result.profit_factor else "N/A")
            print(f"Total Trades: {result.total_trades}")
            print("="*60)
            
            await engine.shutdown()
            
        except Exception as e:
            logger.error(f"Error running backtest: {e}", exc_info=True)
    
    async def show_performance(
        self,
        strategy_name: str,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> None:
        """
        Show performance metrics for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            symbol: Filter by symbol (None for all)
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
        """
        from src.strategies.performance.tracker import StrategyPerformanceTracker
        from datetime import date
        
        try:
            tracker = StrategyPerformanceTracker()
            await tracker.initialize()
            
            # Parse dates
            start_dt = date.fromisoformat(start_date) if start_date else None
            end_dt = date.fromisoformat(end_date) if end_date else None
            
            # Get performance report
            report = await tracker.generate_performance_report(
                strategy_name=strategy_name,
                symbol=symbol or "AAPL",  # Default to AAPL
                start_date=start_dt,
                end_date=end_dt
            )
            
            # Display report
            print("\n" + "="*60)
            print(f"PERFORMANCE REPORT: {strategy_name}")
            print("="*60)
            print(f"Symbol: {report['symbol']}")
            print(f"Period: {report['period']}")
            
            if 'message' in report:
                print(f"Status: {report['message']}")
            else:
                summary = report['summary']
                print(f"Total Trades: {summary['total_trades']}")
                print(f"Total P&L: ${summary['total_pnl']:,.2f}")
                print(f"Average Daily P&L: ${summary['avg_daily_pnl']:,.2f}")
                print(f"Overall Win Rate: {summary['overall_win_rate']:.2%}")
                print(f"Max Drawdown: {summary['max_drawdown']:.2f}%")
                print(f"Average Sharpe Ratio: {summary['avg_sharpe_ratio']:.4f}")
                print(f"Average Sortino Ratio: {summary['avg_sortino_ratio']:.4f}")
                print(f"Average Profit Factor: {summary['avg_profit_factor']:.2f}")
                
                if report['best_day']:
                    print(f"\nBest Day: {report['best_day']['date']} (${report['best_day']['pnl']:,.2f})")
                if report['worst_day']:
                    print(f"Worst Day: {report['worst_day']['date']} (${report['worst_day']['pnl']:,.2f})")
            
            print("="*60)
            
            await tracker.shutdown()
            
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}", exc_info=True)
    
    async def show_signals(
        self,
        strategy_name: Optional[str] = None,
        limit: int = 20,
        tail: bool = False,
    ) -> None:
        """
        Show recent signals from strategies.
        
        Args:
            strategy_name: Filter by strategy name (None for all)
            limit: Number of signals to show
            tail: Continuously show new signals
        """
        query = """
            SELECT strategy_name, symbol, signal_time, signal_type, confidence, metadata
            FROM strategy_signals
            WHERE ($1::VARCHAR IS NULL OR strategy_name = $1)
            ORDER BY signal_time DESC
            LIMIT $2
        """
        
        try:
            while True:
                if self.db_pool:
                    rows = await self.db_pool.fetch(query, strategy_name, limit)
                    
                    if tail:
                        print("\033[2J\033[H", end='')  # Clear screen
                    
                    if not rows:
                        print("No signals found")
                    else:
                        table_data = []
                        for row in reversed(rows):  # Show oldest first
                            metadata = json.loads(row['metadata']) if row['metadata'] else {}
                            price = metadata.get('price', metadata.get('bar_close', 'N/A'))
                            
                            table_data.append([
                                row['signal_time'].strftime('%Y-%m-%d %H:%M:%S'),
                                row['strategy_name'],
                                row['symbol'],
                                row['signal_type'],
                                f"{row['confidence']:.2f}",
                                f"{price:.2f}" if isinstance(price, (int, float)) else price,
                            ])
                        
                        headers = ['Time', 'Strategy', 'Symbol', 'Signal', 'Confidence', 'Price']
                        print("\n" + tabulate(table_data, headers=headers, tablefmt='grid'))
                        print()
                
                if not tail:
                    break
                
                print("Refreshing every 5 seconds... (Ctrl+C to stop)")
                await asyncio.sleep(5)
                
        except KeyboardInterrupt:
            print("\nStopped monitoring signals")


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Trading Strategy Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                    # List all strategies
  %(prog)s start sma_crossover     # Start a specific strategy
  %(prog)s start-all               # Start all enabled strategies
  %(prog)s stop sma_crossover      # Stop a strategy
  %(prog)s status --watch          # Monitor strategy status
  %(prog)s signals --tail          # Tail strategy signals
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    subparsers.add_parser('list', help='List all configured strategies')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start a strategy')
    start_parser.add_argument('strategy', help='Strategy name to start')
    
    # Stop command
    stop_parser = subparsers.add_parser('stop', help='Stop a strategy')
    stop_parser.add_argument('strategy', help='Strategy name to stop')
    
    # Start-all command
    subparsers.add_parser('start-all', help='Start all enabled strategies')
    
    # Stop-all command
    subparsers.add_parser('stop-all', help='Stop all running strategies')
    
    # Run command (new)
    run_parser = subparsers.add_parser('run', help='Run a strategy in paper trading mode')
    run_parser.add_argument('strategy', help='Strategy name to run')
    run_parser.add_argument('--mode', choices=['paper', 'backtest'], default='paper', 
                           help='Execution mode (default: paper)')
    
    # Backtest command (new)
    backtest_parser = subparsers.add_parser('backtest', help='Run a backtest for a strategy')
    backtest_parser.add_argument('strategy', help='Strategy name to backtest')
    backtest_parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    backtest_parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    backtest_parser.add_argument('--capital', type=float, default=100000, 
                                help='Initial capital (default: 100000)')
    
    # Performance command (new)
    performance_parser = subparsers.add_parser('performance', help='Show strategy performance metrics')
    performance_parser.add_argument('strategy', help='Strategy name')
    performance_parser.add_argument('--symbol', help='Filter by symbol (default: AAPL)')
    performance_parser.add_argument('--start', help='Start date filter (YYYY-MM-DD)')
    performance_parser.add_argument('--end', help='End date filter (YYYY-MM-DD)')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show strategy status')
    status_parser.add_argument('--watch', action='store_true', help='Continuously update display')
    
    # Signals command
    signals_parser = subparsers.add_parser('signals', help='Show strategy signals')
    signals_parser.add_argument('strategy', nargs='?', help='Filter by strategy name')
    signals_parser.add_argument('--limit', type=int, default=20, help='Number of signals to show')
    signals_parser.add_argument('--tail', action='store_true', help='Continuously show new signals')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    async with StrategyManager() as manager:
        if args.command == 'list':
            await manager.list_strategies()
        
        elif args.command == 'start':
            await manager.start_strategy(args.strategy)
        
        elif args.command == 'stop':
            await manager.stop_strategy(args.strategy)
        
        elif args.command == 'start-all':
            await manager.start_all()
        
        elif args.command == 'stop-all':
            await manager.stop_all()
        
        elif args.command == 'status':
            await manager.show_status(watch=args.watch)
        
        elif args.command == 'run':
            await manager.run_strategy(args.strategy, args.mode)
        
        elif args.command == 'backtest':
            await manager.backtest_strategy(
                strategy_name=args.strategy,
                start_date=args.start,
                end_date=args.end,
                initial_capital=args.capital
            )
        
        elif args.command == 'performance':
            await manager.show_performance(
                strategy_name=args.strategy,
                symbol=args.symbol,
                start_date=args.start,
                end_date=args.end
            )
        
        elif args.command == 'signals':
            await manager.show_signals(
                strategy_name=args.strategy,
                limit=args.limit,
                tail=args.tail,
            )


if __name__ == '__main__':
    asyncio.run(main())

