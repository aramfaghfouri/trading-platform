#!/usr/bin/env python3
"""
Convenience script to start real-time IBKR data streaming with TimescaleDB writes.

Usage:
    python scripts/start_realtime_stream.py AAPL MSFT GOOGL
    python scripts/start_realtime_stream.py --symbols AAPL,MSFT,GOOGL
    python scripts/start_realtime_stream.py --config config/trading.yaml
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.data_collectors.ibkr.realtime_stream import main as stream_main
from src.core.config_loader import load_config


def parse_args():
    parser = argparse.ArgumentParser(
        description='Stream real-time IBKR data to TimescaleDB'
    )
    
    parser.add_argument(
        'symbols',
        nargs='*',
        help='Space-separated list of symbols to stream (e.g., AAPL MSFT)'
    )
    
    parser.add_argument(
        '--symbols',
        dest='symbols_arg',
        help='Comma-separated list of symbols (e.g., AAPL,MSFT,GOOGL)'
    )
    
    parser.add_argument(
        '--config',
        help='Load symbols from config file'
    )
    
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='IBKR TWS/Gateway host (default: 127.0.0.1)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=7497,
        help='IBKR TWS/Gateway port (default: 7497 for paper trading)'
    )
    
    parser.add_argument(
        '--client-id',
        type=int,
        default=100,
        help='IBKR client ID (default: 100)'
    )
    
    parser.add_argument(
        '--chart',
        action='store_true',
        help='Enable chart display for first symbol'
    )
    
    parser.add_argument(
        '--chart-symbol',
        help='Symbol to display on chart (defaults to first symbol)'
    )
    
    return parser.parse_args()


def get_symbols(args) -> list:
    """Extract symbols from various argument formats."""
    symbols = []
    
    # From positional arguments
    if args.symbols:
        symbols.extend(args.symbols)
    
    # From --symbols flag
    if args.symbols_arg:
        symbols.extend([s.strip() for s in args.symbols_arg.split(',')])
    
    # From config file
    if args.config:
        try:
            config = load_config(args.config)
            # Try to extract symbols from various config structures
            if hasattr(config, 'symbols'):
                symbols.extend(config.symbols)
            elif hasattr(config, 'trading') and hasattr(config.trading, 'symbols'):
                symbols.extend(config.trading.symbols)
        except Exception as e:
            logger.warning(f"Could not load symbols from config: {e}")
    
    # Default to AAPL if no symbols provided
    if not symbols:
        logger.info("No symbols specified, defaulting to AAPL")
        symbols = ['AAPL']
    
    # Remove duplicates and convert to uppercase
    symbols = list(set(s.upper() for s in symbols))
    
    return symbols


def main():
    args = parse_args()
    
    # Get symbols
    symbols = get_symbols(args)
    
    logger.info("=" * 60)
    logger.info("IBKR Real-time Data Streamer")
    logger.info("=" * 60)
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"IBKR Host: {args.host}:{args.port}")
    logger.info(f"Client ID: {args.client_id}")
    logger.info(f"Chart: {'Enabled' if args.chart else 'Disabled'}")
    if args.chart and args.chart_symbol:
        logger.info(f"Chart Symbol: {args.chart_symbol}")
    logger.info("=" * 60)
    
    # Run the streamer
    asyncio.run(
        stream_main(
            symbols=symbols,
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            enable_chart=args.chart,
            chart_symbol=args.chart_symbol,
        )
    )


if __name__ == '__main__':
    main()

