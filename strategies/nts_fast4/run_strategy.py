#!/usr/bin/env python3
"""
Simple runner script for NTS FAST4 strategy.

This script runs the strategy using the configuration file.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.nts_fast4.backtest_nts_fast4 import NTSFast4BacktestRunner


async def run_strategy():
    """Run the strategy using configuration file."""
    print("🚀 Starting NTS FAST4 Strategy Backtest")
    print("=" * 50)
    
    # Load configuration
    config = NTSFast4BacktestRunner.load_config()
    
    # Parse dates
    from datetime import datetime
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
        symbol = config['backtest']['symbols'][0]
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
        print(f"❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await runner.shutdown()


if __name__ == "__main__":
    asyncio.run(run_strategy())
