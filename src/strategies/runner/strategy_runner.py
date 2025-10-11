"""
Strategy Runner - Manages the lifecycle and execution of a single trading strategy.

The runner polls TimescaleDB for new bar data and calls the strategy's
on_bar_update method when new data is available.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, SignalSpec, BarData, SignalType


class StrategyRunner:
    """
    Runs a single strategy instance with database polling.
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        poll_interval: float = 5.0,
        order_log_path: Optional[Path] = None,
    ):
        """
        Initialize strategy runner.
        
        Args:
            strategy: The strategy instance to run
            poll_interval: How often to poll for new data (seconds)
            order_log_path: Optional path to log generated orders
        """
        self.strategy = strategy
        self.poll_interval = poll_interval
        self.order_log_path = order_log_path or Path(f'logs/orders_{strategy.name}.jsonl')
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Statistics
        self.bars_processed = 0
        self.signals_generated = 0
        self.orders_generated = 0
        self.errors = 0
        self.start_time: Optional[datetime] = None
        
        logger.info(f"StrategyRunner created for '{strategy.name}'")
    
    async def start(self) -> None:
        """Start the strategy runner."""
        if self._running:
            logger.warning(f"Strategy '{self.strategy.name}' is already running")
            return
        
        logger.info(f"Starting strategy '{self.strategy.name}'...")
        
        # Initialize strategy
        await self.strategy.initialize()
        
        # Mark as running
        self._running = True
        self.start_time = datetime.now(tz=timezone.utc)
        self.strategy.state.is_running = True
        
        # Start main loop
        self._task = asyncio.create_task(self._run_loop())
        
        logger.info(f"Strategy '{self.strategy.name}' started")
    
    async def stop(self) -> None:
        """Stop the strategy runner."""
        if not self._running:
            return
        
        logger.info(f"Stopping strategy '{self.strategy.name}'...")
        self._running = False
        
        # Cancel main loop
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Shutdown strategy
        self.strategy.state.is_running = False
        await self.strategy.shutdown()
        
        # Print statistics
        self._print_statistics()
        
        logger.info(f"Strategy '{self.strategy.name}' stopped")
    
    async def _run_loop(self) -> None:
        """Main strategy execution loop."""
        logger.info(f"Strategy '{self.strategy.name}' entering main loop")
        
        while self._running:
            try:
                # Update heartbeat
                await self.strategy.update_heartbeat()
                
                # Check for new bars for each symbol
                for symbol in self.strategy.symbols:
                    await self._process_symbol(symbol)
                
                # Sleep until next poll
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                logger.info(f"Strategy '{self.strategy.name}' loop cancelled")
                break
            except Exception as e:
                self.errors += 1
                self.strategy.state.error_message = str(e)
                logger.error(f"Error in strategy '{self.strategy.name}' main loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)  # Avoid tight error loop
        
        logger.info(f"Strategy '{self.strategy.name}' exited main loop")
    
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
        
        For now, just log it. In production, this would send to Order Manager.
        
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
        
        # Create and log signal
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
        self.signals_generated += 1
        
        # Write to order log file
        await self._write_order_log(order_spec, bar)
    
    async def _write_order_log(self, order_spec: OrderSpec, bar: BarData) -> None:
        """Write order to log file."""
        import json
        import aiofiles
        
        # Ensure directory exists
        self.order_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare log entry
        log_entry = {
            **order_spec.to_dict(),
            'bar_timestamp': bar.timestamp.isoformat(),
            'bar_close': float(bar.close),
            'logged_at': datetime.now(tz=timezone.utc).isoformat(),
        }
        
        # Append to file
        try:
            async with aiofiles.open(self.order_log_path, 'a') as f:
                await f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Error writing order log: {e}")
    
    def _print_statistics(self) -> None:
        """Print runner statistics."""
        if not self.start_time:
            return
        
        runtime = (datetime.now(tz=timezone.utc) - self.start_time).total_seconds()
        
        logger.info("=" * 60)
        logger.info(f"STRATEGY STATISTICS: {self.strategy.name}")
        logger.info("=" * 60)
        logger.info(f"Runtime: {runtime:.1f} seconds")
        logger.info(f"Bars Processed: {self.bars_processed}")
        logger.info(f"Signals Generated: {self.signals_generated}")
        logger.info(f"Orders Generated: {self.orders_generated}")
        logger.info(f"Errors: {self.errors}")
        if self.bars_processed > 0:
            logger.info(f"Bars/Second: {self.bars_processed / runtime:.2f}")
        logger.info("=" * 60)
    
    async def run_forever(self) -> None:
        """
        Run the strategy until interrupted.
        
        Sets up signal handlers and keeps the strategy running.
        """
        # Start strategy
        await self.start()
        
        # Setup signal handlers
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, stopping...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Keep running
        try:
            while self._running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.stop()


async def run_strategy_from_config(
    strategy_name: str,
    config: Dict[str, Any],
    poll_interval: float = 5.0,
) -> None:
    """
    Load and run a strategy from configuration.
    
    Args:
        strategy_name: Name of the strategy to run
        config: Strategy configuration dictionary
        poll_interval: Polling interval in seconds
    """
    # Import strategy class dynamically
    class_path = config.get('class')
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
        config=config.get('parameters', {}),
        symbols=config.get('symbols', []),
    )
    
    # Create and run runner
    runner = StrategyRunner(
        strategy=strategy,
        poll_interval=poll_interval,
    )
    
    await runner.run_forever()


if __name__ == '__main__':
    import sys
    from pathlib import Path
    
    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))
    
    # Simple test with a dummy strategy
    from src.strategies.base import BaseStrategy
    from src.strategies.models import OrderSpec, BarData
    
    class TestStrategy(BaseStrategy):
        async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
            logger.info(f"Test strategy received bar for {symbol}: close={bar.close}")
            return None
        
        async def get_required_lookback(self) -> int:
            return 50
    
    async def main():
        strategy = TestStrategy(
            name='test_strategy',
            config={},
            symbols=['AAPL'],
        )
        
        runner = StrategyRunner(strategy, poll_interval=5.0)
        await runner.run_forever()
    
    asyncio.run(main())

