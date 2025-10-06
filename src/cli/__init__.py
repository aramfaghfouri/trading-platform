from .ib import ib as ib_cli

__all__ = ["ib_cli"]
"""
Command-line interface for the trading platform.

This module contains CLI commands for:
- Data collection and management
- Strategy backtesting and execution
- Portfolio monitoring and management
- System administration and maintenance
"""

from .main import cli
from .data_commands import data_cli
from .strategy_commands import strategy_cli
from .trading_commands import trading_cli

__all__ = [
    "cli",
    "data_cli",
    "strategy_cli",
    "trading_cli",
]
