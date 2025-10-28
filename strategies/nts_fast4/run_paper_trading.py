#!/usr/bin/env python3
"""
Paper trading runner for NTS FAST4 strategy.

This script runs the strategy in paper trading mode using the configuration file.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.nts_fast4.backtest_nts_fast4 import NTSFast4BacktestRunner
from strategies.nts_fast4.nts_fast4 import NTSFast4
from src.strategies.models import BarData
from src.core.config_loader import get_database_config
import asyncpg
from datetime import datetime, timedelta
from decimal import Decimal
from loguru import logger


class NTSFast4PaperTrader:
    """Paper trading runner for NTS FAST4 strategy."""
    
    def __init__(self, config):
        self.config = config
        self.strategy = None
        self.db_pool = None
        self.running = True
        
        # Paper trading state
        self.positions = {}
        self.cash = config['paper_trading']['initial_capital']
        self.commission_per_share = config['paper_trading']['commission_per_share']
        
    async def initialize(self):
        """Initialize the paper trader."""
        # Create strategy
        strategy_config = self.config['parameters'].copy()
        symbols = self.config['backtest']['symbols']
        
        self.strategy = NTSFast4(
            name="nts_fast4_paper",
            config=strategy_config,
            symbols=symbols
        )
        
        # Connect to database
        db_config = get_database_config()
        self.db_pool = await asyncpg.create_pool(
            host=db_config.host,
            port=db_config.port,
            database=db_config.database,
            user=db_config.username,
            password=db_config.password,
            ssl=db_config.ssl_mode
        )
        
        await self.strategy.initialize()
        logger.info("Paper trader initialized")
    
    async def run_paper_trading(self):
        """Run paper trading simulation."""
        logger.info("Starting paper trading simulation")
        
        # Get latest data and run simulation
        symbol = self.config['backtest']['symbols'][0]
        
        # Load recent data for simulation
        table_name = f"ibkr_ohlcv_{symbol.lower()}_1m"
        
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            WHERE timestamp >= $1
            ORDER BY timestamp ASC
            LIMIT 1000
        """
        
        # Get data from last 7 days
        start_time = datetime.now() - timedelta(days=7)
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, start_time)
            
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
            
            logger.info(f"Loaded {len(bars)} bars for paper trading simulation")
            
            # Run simulation
            await self._simulate_trading(symbol, bars)
            
        except Exception as e:
            logger.error(f"Error in paper trading: {e}")
    
    async def _simulate_trading(self, symbol: str, bars):
        """Simulate trading with historical data."""
        position = 0
        entry_price = 0.0
        
        for bar in bars:
            # Update strategy cache
            self.strategy.update_cache(symbol, bar)
            
            # Get strategy signal
            order = await self.strategy.on_bar_update(symbol, bar)
            
            if order:
                await self._process_paper_order(order, bar, position, entry_price)
                
                # Update position
                if order.action.value == 'BUY':
                    position += order.quantity
                    entry_price = float(bar.close)
                elif order.action.value == 'SELL':
                    position -= order.quantity
                    if position == 0:
                        entry_price = 0.0
            
            # Log current state
            if position != 0:
                unrealized_pnl = (float(bar.close) - entry_price) * position
                logger.info(f"[{bar.timestamp}] Price: ${float(bar.close):.2f}, Position: {position}, Unrealized P&L: ${unrealized_pnl:.2f}")
    
    async def _process_paper_order(self, order, bar, current_position, entry_price):
        """Process a paper trading order."""
        if order.action.value == 'BUY':
            cost = float(bar.close) * order.quantity
            commission = order.quantity * self.commission_per_share
            total_cost = cost + commission
            
            if total_cost <= self.cash:
                self.cash -= total_cost
                logger.info(f"📈 BUY {order.quantity} shares at ${float(bar.close):.2f} (Cost: ${total_cost:.2f})")
            else:
                logger.warning(f"❌ Insufficient cash for BUY order: ${total_cost:.2f} > ${self.cash:.2f}")
                
        elif order.action.value == 'SELL':
            if current_position >= order.quantity:
                proceeds = float(bar.close) * order.quantity
                commission = order.quantity * self.commission_per_share
                net_proceeds = proceeds - commission
                
                self.cash += net_proceeds
                pnl = (float(bar.close) - entry_price) * order.quantity
                
                logger.info(f"📉 SELL {order.quantity} shares at ${float(bar.close):.2f} (Proceeds: ${net_proceeds:.2f}, P&L: ${pnl:.2f})")
            else:
                logger.warning(f"❌ Insufficient position for SELL order: {order.quantity} > {current_position}")
    
    async def shutdown(self):
        """Shutdown the paper trader."""
        if self.db_pool:
            await self.db_pool.close()
        logger.info("Paper trader shut down")


async def main():
    """Main function."""
    print("📊 Starting NTS FAST4 Paper Trading")
    print("=" * 50)
    
    # Load configuration
    config = NTSFast4BacktestRunner.load_config()
    
    # Check if paper trading is enabled
    if not config.get('paper_trading', {}).get('enabled', False):
        print("❌ Paper trading is disabled in configuration")
        return
    
    # Create paper trader
    trader = NTSFast4PaperTrader(config)
    
    try:
        await trader.initialize()
        await trader.run_paper_trading()
        
        # Print final results
        print("\n" + "="*50)
        print("PAPER TRADING RESULTS")
        print("="*50)
        print(f"Final Cash: ${trader.cash:,.2f}")
        print(f"Initial Capital: ${config['paper_trading']['initial_capital']:,.2f}")
        print(f"Total Return: {(trader.cash - config['paper_trading']['initial_capital']) / config['paper_trading']['initial_capital']:.2%}")
        print("="*50)
        
    except Exception as e:
        print(f"❌ Paper trading failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await trader.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
