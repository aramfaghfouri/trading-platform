"""
Broker integration modules.

This module contains broker-specific implementations:
- Interactive Brokers (IBKR) for live trading
- Paper trading for testing and development
- Order management and execution
- Position tracking and account management
"""

from .ibkr.adapters import IBBroker

__all__ = [
    "IBBroker",
]
