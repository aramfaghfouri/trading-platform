"""
Data collection modules for market data.

This module contains data collectors for various sources:
- Polygon.io for historical and real-time data
- Interactive Brokers for live market data
- Data validation and quality checks
"""

from .polygon import PolygonDataCollector

__all__ = [
    "PolygonDataCollector",
]