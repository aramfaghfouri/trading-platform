"""
MACD Momentum Strategy

Trend following strategy based on MACD (Moving Average Convergence Divergence):
- BUY when MACD line crosses above signal line (bullish crossover)
- SELL when MACD line crosses below signal line (bearish crossover)
- Can also use MACD histogram for additional confirmation
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np
from loguru import logger

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, OrderAction, OrderType, BarData


class MACDMomentum(BaseStrategy):
    """
    MACD (Moving Average Convergence Divergence) Momentum Strategy.
    
    Configuration parameters:
        - fast_period: Fast EMA period (default: 12)
        - slow_period: Slow EMA period (default: 26)
        - signal_period: Signal line EMA period (default: 9)
        - quantity: Number of shares to trade (default: 100)
        - min_lookback: Minimum bars needed before trading (default: slow_period + signal_period + 10)
        - use_histogram: Use MACD histogram for confirmation (default: False)
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        super().__init__(name, config, symbols)
        
        # Strategy parameters
        self.fast_period = config.get('fast_period', 12)
        self.slow_period = config.get('slow_period', 26)
        self.signal_period = config.get('signal_period', 9)
        self.quantity = config.get('quantity', 100)
        self.min_lookback = config.get('min_lookback', self.slow_period + self.signal_period + 10)
        self.use_histogram = config.get('use_histogram', False)
        
        # State tracking
        self._positions: Dict[str, int] = {symbol: 0 for symbol in symbols}
        self._last_macd: Dict[str, Optional[Dict[str, float]]] = {symbol: None for symbol in symbols}
        self._last_crossover: Dict[str, Optional[str]] = {symbol: None for symbol in symbols}
        
        logger.info(
            f"MACD Momentum strategy '{name}' initialized: "
            f"fast={self.fast_period}, slow={self.slow_period}, signal={self.signal_period}, "
            f"histogram={self.use_histogram}, qty={self.quantity}"
        )
    
    async def get_required_lookback(self) -> int:
        """Return required number of historical bars."""
        return self.min_lookback
    
    def _calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            prices: Series of closing prices
            fast: Fast EMA period
            slow: Slow EMA period
            signal: Signal line EMA period
            
        Returns:
            Dictionary with 'macd', 'signal', 'histogram' lines
        """
        # Calculate EMAs
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        
        # Calculate MACD line
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        
        # Calculate histogram
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Check MACD crossovers and generate order if conditions met.
        
        Args:
            symbol: Symbol being updated
            bar: Latest bar data
            
        Returns:
            OrderSpec if MACD signal is detected, None otherwise
        """
        try:
            # Get cached bars
            df = self.get_cached_bars(symbol)
            
            if df.empty or len(df) < self.min_lookback:
                logger.debug(f"[{symbol}] Insufficient data: {len(df)} bars (need {self.min_lookback})")
                return None
            
            # Calculate MACD
            macd_data = self._calculate_macd(df['close'], self.fast_period, self.slow_period, self.signal_period)
            
            # Check for valid MACD values
            if len(df) < 2 or pd.isna(macd_data['macd'].iloc[-1]) or pd.isna(macd_data['signal'].iloc[-1]):
                return None
            
            # Get current and previous values
            macd_curr = macd_data['macd'].iloc[-1]
            signal_curr = macd_data['signal'].iloc[-1]
            histogram_curr = macd_data['histogram'].iloc[-1]
            
            macd_prev = macd_data['macd'].iloc[-2]
            signal_prev = macd_data['signal'].iloc[-2]
            histogram_prev = macd_data['histogram'].iloc[-2]
            
            # Store current MACD values
            self._last_macd[symbol] = {
                'macd': macd_curr,
                'signal': signal_curr,
                'histogram': histogram_curr
            }
            
            # Log MACD values for debugging
            logger.debug(
                f"[{symbol}] MACD={macd_curr:.4f}, Signal={signal_curr:.4f}, "
                f"Histogram={histogram_curr:.4f}, Position={self._positions[symbol]}"
            )
            
            # Detect crossovers
            bullish_crossover = (macd_prev <= signal_prev) and (macd_curr > signal_curr)
            bearish_crossover = (macd_prev >= signal_prev) and (macd_curr < signal_curr)
            
            # Additional histogram confirmation
            histogram_bullish = histogram_curr > 0 if self.use_histogram else True
            histogram_bearish = histogram_curr < 0 if self.use_histogram else True
            
            # Generate orders based on crossovers
            if bullish_crossover and histogram_bullish:
                logger.info(
                    f"[{symbol}] 🟢 MACD BULLISH CROSSOVER! "
                    f"MACD={macd_curr:.4f} > Signal={signal_curr:.4f}"
                )
                
                # Only buy if we don't already have a position
                if self._positions[symbol] <= 0:
                    self._last_crossover[symbol] = 'bullish'
                    self._positions[symbol] = self.quantity
                    
                    return OrderSpec(
                        symbol=symbol,
                        action=OrderAction.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=self.name,
                        metadata={
                            'macd': float(macd_curr),
                            'signal': float(signal_curr),
                            'histogram': float(histogram_curr),
                            'crossover_type': 'bullish',
                            'bar_close': float(bar.close),
                        }
                    )
                else:
                    logger.debug(f"[{symbol}] Already have long position, skipping buy signal")
            
            elif bearish_crossover and histogram_bearish:
                logger.info(
                    f"[{symbol}] 🔴 MACD BEARISH CROSSOVER! "
                    f"MACD={macd_curr:.4f} < Signal={signal_curr:.4f}"
                )
                
                # Only sell if we have a position
                if self._positions[symbol] > 0:
                    quantity = self._positions[symbol]
                    self._last_crossover[symbol] = 'bearish'
                    self._positions[symbol] = 0
                    
                    return OrderSpec(
                        symbol=symbol,
                        action=OrderAction.SELL,
                        quantity=quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=self.name,
                        metadata={
                            'macd': float(macd_curr),
                            'signal': float(signal_curr),
                            'histogram': float(histogram_curr),
                            'crossover_type': 'bearish',
                            'bar_close': float(bar.close),
                        }
                    )
                else:
                    logger.debug(f"[{symbol}] No position to sell, skipping sell signal")
            
            return None
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in MACD momentum logic: {e}", exc_info=True)
            return None
    
    def get_position(self, symbol: str) -> int:
        """Get current position for a symbol."""
        return self._positions.get(symbol, 0)
    
    def get_macd_values(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Get current MACD values for a symbol.
        
        Returns:
            Dict with 'macd', 'signal', 'histogram' values, or None if unavailable
        """
        return self._last_macd.get(symbol)
    
    def get_macd_series(self, symbol: str) -> Optional[Dict[str, pd.Series]]:
        """
        Get full MACD series for a symbol.
        
        Returns:
            Dict with 'macd', 'signal', 'histogram' series, or None if unavailable
        """
        df = self.get_cached_bars(symbol)
        
        if df.empty or len(df) < self.min_lookback:
            return None
        
        macd_data = self._calculate_macd(df['close'], self.fast_period, self.slow_period, self.signal_period)
        
        return macd_data
    
    def get_last_crossover(self, symbol: str) -> Optional[str]:
        """
        Get the last crossover type for a symbol.
        
        Returns:
            'bullish', 'bearish', or None
        """
        return self._last_crossover.get(symbol)
