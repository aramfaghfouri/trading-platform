"""
Trading strategies built with VectorBT.

This module contains:
- Base strategy classes
- Strategy implementations (SMA, RSI, Bollinger Bands, etc.)
- Strategy registry and management
- Performance metrics and analysis
"""

from .base import BaseStrategy, StrategyRegistry
from .implementations import (
    SMACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerBandsStrategy,
)

__all__ = [
    "BaseStrategy",
    "StrategyRegistry",
    "SMACrossoverStrategy",
    "RSIMeanReversionStrategy", 
    "BollingerBandsStrategy",
]
