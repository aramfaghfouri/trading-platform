"""
Trading Platform - VectorBT + Polygon.io + Interactive Brokers Integration

A comprehensive trading platform built with VectorBT for backtesting,
Polygon.io for market data, and Interactive Brokers for live trading.
"""

__version__ = "0.1.0"
__author__ = "Trading Platform Team"
__email__ = "team@trading-platform.com"

# Core modules
from . import core
from . import data_collectors
from . import strategies
from . import brokers
from . import utils
from . import cli

__all__ = [
    "core",
    "data_collectors", 
    "strategies",
    "brokers",
    "utils",
    "cli",
]