#!/usr/bin/env python3
"""
Live Strategy Executor

Unified script for running trading strategies with real-time data.
Integrates data collection and strategy execution in a single process.
"""

import asyncio
import sys
import os
import signal
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, BarData
from src.brokers.paper.paper_executor import PaperTradeExecutor
from src.core.config_loader import get_strategies_config


class LiveStrategyExecutor:
    """
    Unified strategy executor that integrates data collection and strategy execution.
    
    Features:
    - Monitors 1-minute candle updates from database
    - Executes orders through paper trading simulator
    - Logs all signals and trades
    - Provides real-time performance metrics
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        mode: str = 'paper',
        poll_interval: float = 10.0
    ):
        """
        Initialize live strategy executor.
        
        Args:
            strategy: Strategy instance to run
            mode: Execution mode ('paper' or 'backtest')
            poll_interval: How often to check for new data (seconds)
        """
        self.strategy = strategy
        self.mode = mode
        self.poll_interval = poll_interval
        
        # Execution components
        self.paper_executor: Optional[PaperTradeExecutor] = None
        self.running = False
        self.start_time: Optional[datetime] = None
        
        # Statistics
        self.bars_processed = 0
        self.orders_generated = 0
        self.orders_executed = 0
        self.errors = 0
        
        logger.info(f"Live strategy executor created for '{strategy.name}' in {mode} mode")
    
    async def start(self) -> None:
        """Start the live strategy executor."""
        if self.running:
            logger.warning(f"Strategy executor for '{self.strategy.name}' is already running")
            return
        
        logger.info(f"Starting live strategy executor for '{self.strategy.name}'...")
        
        # Initialize strategy
        await self.strategy.initialize()
        
        # Initialize paper trading executor if in paper mode
        if self.mode == 'paper':
            self.paper_executor = PaperTradeExecutor(
                initial_capital=Decimal('100000'),
                commission_per_share=Decimal('0.005'),
                account_id=f"paper_{self.strategy.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            await self.paper_executor.initialize()
            logger.info("Paper trading executor initialized")
        
        # Mark as running
        self.running = True
        self.start_time = datetime.now(timezone.utc)
        self.strategy.state.is_running = True
        
        logger.info(f"Live strategy executor started for '{self.strategy.name}'")
        logger.info(f"Monitoring symbols: {', '.join(self.strategy.symbols)}")
        logger.info(f"Poll interval: {self.poll_interval} seconds")
    
    async def stop(self) -> None:
        """Stop the live strategy executor."""
        if not self.running:
            return
        
        logger.info(f"Stopping live strategy executor for '{self.strategy.name}'...")
        self.running = False
        
        # Shutdown strategy
        self.strategy.state.is_running = False
        await self.strategy.shutdown()
        
        # Shutdown paper executor
        if self.paper_executor:
            await self.paper_executor.shutdown()
        
        # Print statistics
        self._print_statistics()
        
        logger.info(f"Live strategy executor stopped for '{self.strategy.name}'")
    
    async def run_forever(self) -> None:
        """Run the strategy until interrupted."""
        await self.start()
        
        # Setup signal handlers
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, stopping...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Main execution loop
        try:
            while self.running:
                try:
                    # Update strategy heartbeat
                    await self.strategy.update_heartbeat()
                    
                    # Check for new bars for each symbol
                    for symbol in self.strategy.symbols:
                        await self._process_symbol(symbol)
                    
                    # Sleep until next poll
                    await asyncio.sleep(self.poll_interval)
                    
                except asyncio.CancelledError:
                    logger.info(f"Strategy executor for '{self.strategy.name}' cancelled")
                    break
                except Exception as e:
                    self.errors += 1
                    self.strategy.state.error_message = str(e)
                    logger.error(f"Error in strategy executor for '{self.strategy.name}': {e}", exc_info=True)
                    await asyncio.sleep(self.poll_interval)  # Avoid tight error loop
        
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.stop()
    
    async def _process_symbol(self, symbol: str) -> None:
        """
        Check for new bars and process them through the strategy.
        
        Args:
            symbol: Symbol to process
        """
        try:
            # Get last processed timestamp for this symbol
            last_timestamp = self.strategy.state.last_processed_timestamp
            
            # Query for new bars
            if last_timestamp:
                new_bars = await self.strategy.get_bars_since(symbol, last_timestamp)
            else:
                # First run - get just the latest bar
                new_bars = await self.strategy.get_recent_bars(symbol, 1)
            
            # Process each new bar
            for bar in new_bars:
                # Update cache
                self.strategy.update_cache(symbol, bar)
                
                # Call strategy logic
                order_spec = await self.strategy.on_bar_update(symbol, bar)
                
                # Track statistics
                self.bars_processed += 1
                self.strategy.state.last_processed_timestamp = bar.timestamp
                
                # Handle generated order
                if order_spec:
                    await self._handle_order(order_spec, bar)
                
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}", exc_info=True)
            self.errors += 1
    
    async def _handle_order(self, order_spec: OrderSpec, bar: BarData) -> None:
        """
        Handle a generated order specification.
        
        Args:
            order_spec: The order to handle
            bar: The bar that triggered the order
        """
        self.orders_generated += 1
        
        # Log the order
        logger.info(
            f"[{self.strategy.name}] ORDER: {order_spec.action.value} "
            f"{order_spec.quantity} {order_spec.symbol} @ {bar.close} "
            f"(type: {order_spec.order_type.value})"
        )
        
        # Execute order if in paper mode
        if self.mode == 'paper' and self.paper_executor:
            try:
                result = await self.paper_executor.place_order(order_spec)
                if result.status == 'FILLED':
                    self.orders_executed += 1
                    logger.info(
                        f"[{self.strategy.name}] ORDER FILLED: {result.action.value} "
                        f"{result.filled_quantity} {result.symbol} @ ${result.avg_fill_price} "
                        f"(Commission: ${result.commission})"
                    )
                else:
                    logger.warning(
                        f"[{self.strategy.name}] ORDER REJECTED: {result.message}"
                    )
            except Exception as e:
                logger.error(f"Error executing paper order: {e}")
                self.errors += 1
        
        # Log signal to database
        from src.strategies.models import SignalSpec, SignalType
        signal = SignalSpec(
            strategy_name=self.strategy.name,
            symbol=order_spec.symbol,
            signal_type=SignalType.BUY if order_spec.action.value == 'BUY' else SignalType.SELL,
            signal_time=bar.timestamp,
            confidence=1.0,
            metadata={
                'price': float(bar.close),
                'quantity': order_spec.quantity,
                'order_type': order_spec.order_type.value,
            }
        )
        
        await self.strategy.log_signal(signal)
    
    def _print_statistics(self) -> None:
        """Print executor statistics."""
        if not self.start_time:
            return
        
        runtime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        logger.info("=" * 60)
        logger.info(f"LIVE STRATEGY EXECUTOR STATISTICS: {self.strategy.name}")
        logger.info("=" * 60)
        logger.info(f"Mode: {self.mode}")
        logger.info(f"Runtime: {runtime:.1f} seconds")
        logger.info(f"Bars Processed: {self.bars_processed}")
        logger.info(f"Orders Generated: {self.orders_generated}")
        logger.info(f"Orders Executed: {self.orders_executed}")
        logger.info(f"Errors: {self.errors}")
        
        if self.bars_processed > 0:
            logger.info(f"Bars/Second: {self.bars_processed / runtime:.2f}")
        
        if self.mode == 'paper' and self.paper_executor:
            balance = await self.paper_executor.get_account_balance()
            logger.info(f"Paper Account Balance: ${balance.cash:.2f}")
            logger.info(f"Total Equity: ${balance.total_equity:.2f}")
            logger.info(f"Unrealized P&L: ${balance.unrealized_pnl:.2f}")
            logger.info(f"Realized P&L: ${balance.realized_pnl:.2f}")
            
            metrics = self.paper_executor.get_performance_metrics()
            logger.info(f"Total Trades: {metrics['total_trades']}")
            logger.info(f"Win Rate: {metrics['win_rate']:.2%}")
            logger.info(f"Total P&L: ${metrics['total_pnl']:.2f}")
        
        logger.info("=" * 60)


async def load_strategy_from_config(strategy_name: str) -> BaseStrategy:
    """
    Load a strategy from configuration.
    
    Args:
        strategy_name: Name of the strategy to load
        
    Returns:
        Initialized strategy instance
    """
    # Load strategies configuration
    strategies_config = get_strategies_config()
    
    if strategy_name not in strategies_config.strategies:
        raise ValueError(f"Strategy '{strategy_name}' not found in configuration")
    
    strategy_config = strategies_config.strategies[strategy_name]
    
    # Import strategy class dynamically
    class_path = strategy_config.get('class')
    if not class_path:
        raise ValueError(f"No 'class' specified for strategy '{strategy_name}'")
    
    # Parse class path
    module_path, class_name = class_path.rsplit('.', 1)
    
    # Import the module
    import importlib
    module = importlib.import_module(module_path)
    strategy_class = getattr(module, class_name)
    
    # Create strategy instance
    strategy = strategy_class(
        name=strategy_name,
        config=strategy_config.get('parameters', {}),
        symbols=strategy_config.get('symbols', []),
    )
    
    return strategy


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Live Strategy Executor")
    parser.add_argument("strategy_name", help="Name of the strategy to run")
    parser.add_argument("--mode", choices=['paper', 'backtest'], default='paper',
                       help="Execution mode (default: paper)")
    parser.add_argument("--poll-interval", type=float, default=10.0,
                       help="Polling interval in seconds (default: 10.0)")
    parser.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Log level (default: INFO)")
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=args.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    try:
        # Load strategy
        logger.info(f"Loading strategy '{args.strategy_name}'...")
        strategy = await load_strategy_from_config(args.strategy_name)
        
        # Create executor
        executor = LiveStrategyExecutor(
            strategy=strategy,
            mode=args.mode,
            poll_interval=args.poll_interval
        )
        
        # Run strategy
        await executor.run_forever()
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error running strategy: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
