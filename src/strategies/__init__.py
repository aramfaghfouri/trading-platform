"""
Trading strategies built with VectorBT.

This module contains:
- Base strategy classes
- Strategy implementations (SMA, RSI, Bollinger Bands, etc.)
- Strategy registry and management
- Performance metrics and analysis
"""

from .base import BaseStrategy
from .implementations import (
    SMACrossover,
    RSIMeanReversion,
    BollingerBands,
    MACDMomentum,
)

# Note: NTSFast4 is now in strategies/nts_fast4/ directory
# Import it directly when needed: from strategies.nts_fast4 import NTSFast4

__all__ = [
    "BaseStrategy",
    "SMACrossover",
    "RSIMeanReversion", 
    "BollingerBands",
    "MACDMomentum",
]
