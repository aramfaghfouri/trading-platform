#!/usr/bin/env python3
"""
Run a single trading strategy.

This script is called by the strategy_manager CLI to execute individual strategies.
It loads the strategy configuration and runs it in a polling loop.

Usage:
    python scripts/run_strategy.py <strategy_name>
    python scripts/run_strategy.py sma_crossover
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.strategies.runner.strategy_runner import run_strategy_from_config
from src.core.config_loader import load_config


async def main():
    """Main entry point for strategy execution."""
    if len(sys.argv) < 2:
        logger.error("Usage: python run_strategy.py <strategy_name>")
        sys.exit(1)
    
    strategy_name = sys.argv[1]
    
    # Load strategies configuration
    config_path = project_root / 'config' / 'strategies.yaml'
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    
    logger.info(f"Loading configuration from {config_path}")
    config = load_config(str(config_path))
    
    # Convert to dict if needed
    config_dict = config.dict() if hasattr(config, 'dict') else config
    
    if 'strategies' not in config_dict:
        logger.error("No 'strategies' section in configuration")
        sys.exit(1)
    
    strategies_config = config_dict['strategies']
    
    if strategy_name not in strategies_config:
        logger.error(f"Strategy '{strategy_name}' not found in configuration")
        logger.info(f"Available strategies: {', '.join(k for k in strategies_config.keys() if k != 'registry')}")
        sys.exit(1)
    
    strategy_config = strategies_config[strategy_name]
    
    # Check if enabled
    if not strategy_config.get('enabled', False):
        logger.warning(f"Strategy '{strategy_name}' is not enabled in configuration, but starting anyway")
    
    # Get polling interval from registry
    registry = strategies_config.get('registry', {})
    poll_interval = registry.get('poll_interval_seconds', 5.0)
    
    logger.info("=" * 60)
    logger.info(f"Starting Strategy: {strategy_name}")
    logger.info("=" * 60)
    logger.info(f"Class: {strategy_config.get('class', 'N/A')}")
    logger.info(f"Symbols: {', '.join(strategy_config.get('symbols', []))}")
    logger.info(f"Parameters: {strategy_config.get('parameters', {})}")
    logger.info(f"Poll Interval: {poll_interval}s")
    logger.info("=" * 60)
    
    # Run the strategy
    try:
        await run_strategy_from_config(
            strategy_name=strategy_name,
            config=strategy_config,
            poll_interval=poll_interval,
        )
    except KeyboardInterrupt:
        logger.info(f"Strategy '{strategy_name}' interrupted by user")
    except Exception as e:
        logger.error(f"Strategy '{strategy_name}' failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    # Configure logger
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
    )
    
    # Also log to file
    log_file = project_root / 'logs' / f'strategy_{sys.argv[1] if len(sys.argv) > 1 else "unknown"}_{asyncio.get_event_loop().time():.0f}.log'
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        rotation="100 MB",
        retention="7 days",
        level="DEBUG",
    )
    
    asyncio.run(main())

