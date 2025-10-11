"""
SMA Crossover Strategy

Classic moving average crossover strategy:
- BUY when short-term SMA crosses above long-term SMA (golden cross)
- SELL when short-term SMA crosses below long-term SMA (death cross)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, OrderAction, OrderType, BarData


class SMACrossover(BaseStrategy):
    """
    Simple Moving Average Crossover Strategy.
    
    Configuration parameters:
        - short_window: Number of periods for short-term SMA (default: 20)
        - long_window: Number of periods for long-term SMA (default: 50)
        - quantity: Number of shares to trade (default: 100)
        - min_lookback: Minimum bars needed before trading (default: long_window + 10)
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        super().__init__(name, config, symbols)
        
        # Strategy parameters
        self.short_window = config.get('short_window', 20)
        self.long_window = config.get('long_window', 50)
        self.quantity = config.get('quantity', 100)
        self.min_lookback = config.get('min_lookback', self.long_window + 10)
        
        # State tracking
        self._positions: Dict[str, int] = {symbol: 0 for symbol in symbols}  # Current position (shares)
        self._last_crossover: Dict[str, Optional[str]] = {symbol: None for symbol in symbols}  # 'golden' or 'death'
        
        logger.info(
            f"SMA Crossover strategy '{name}' initialized: "
            f"short={self.short_window}, long={self.long_window}, qty={self.quantity}"
        )
    
    async def get_required_lookback(self) -> int:
        """Return required number of historical bars."""
        return self.min_lookback
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Check for SMA crossover and generate order if conditions met.
        
        Args:
            symbol: Symbol being updated
            bar: Latest bar data
            
        Returns:
            OrderSpec if a crossover signal is detected, None otherwise
        """
        try:
            # Get cached bars
            df = self.get_cached_bars(symbol)
            
            if df.empty or len(df) < self.long_window:
                logger.debug(f"[{symbol}] Insufficient data: {len(df)} bars (need {self.long_window})")
                return None
            
            # Calculate SMAs
            df['sma_short'] = df['close'].rolling(window=self.short_window).mean()
            df['sma_long'] = df['close'].rolling(window=self.long_window).mean()
            
            # Check for valid SMA values
            if len(df) < 2 or pd.isna(df['sma_short'].iloc[-1]) or pd.isna(df['sma_long'].iloc[-1]):
                return None
            
            if pd.isna(df['sma_short'].iloc[-2]) or pd.isna(df['sma_long'].iloc[-2]):
                return None
            
            # Get current and previous values
            sma_short_curr = df['sma_short'].iloc[-1]
            sma_long_curr = df['sma_long'].iloc[-1]
            sma_short_prev = df['sma_short'].iloc[-2]
            sma_long_prev = df['sma_long'].iloc[-2]
            
            # Detect crossovers
            golden_cross = (sma_short_prev <= sma_long_prev) and (sma_short_curr > sma_long_curr)
            death_cross = (sma_short_prev >= sma_long_prev) and (sma_short_curr < sma_long_curr)
            
            # Log SMA values for debugging
            logger.debug(
                f"[{symbol}] SMA_short={sma_short_curr:.2f}, SMA_long={sma_long_curr:.2f}, "
                f"Position={self._positions[symbol]}"
            )
            
            # Generate orders based on crossover
            if golden_cross:
                logger.info(
                    f"[{symbol}] 🟢 GOLDEN CROSS detected! "
                    f"SMA({self.short_window})={sma_short_curr:.2f} > SMA({self.long_window})={sma_long_curr:.2f}"
                )
                
                # Only buy if we don't already have a position
                if self._positions[symbol] <= 0:
                    self._last_crossover[symbol] = 'golden'
                    self._positions[symbol] = self.quantity
                    
                    return OrderSpec(
                        symbol=symbol,
                        action=OrderAction.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=self.name,
                        metadata={
                            'sma_short': float(sma_short_curr),
                            'sma_long': float(sma_long_curr),
                            'crossover_type': 'golden',
                            'bar_close': float(bar.close),
                        }
                    )
                else:
                    logger.debug(f"[{symbol}] Already have long position, skipping buy signal")
            
            elif death_cross:
                logger.info(
                    f"[{symbol}] 🔴 DEATH CROSS detected! "
                    f"SMA({self.short_window})={sma_short_curr:.2f} < SMA({self.long_window})={sma_long_curr:.2f}"
                )
                
                # Only sell if we have a position
                if self._positions[symbol] > 0:
                    quantity = self._positions[symbol]
                    self._last_crossover[symbol] = 'death'
                    self._positions[symbol] = 0
                    
                    return OrderSpec(
                        symbol=symbol,
                        action=OrderAction.SELL,
                        quantity=quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=self.name,
                        metadata={
                            'sma_short': float(sma_short_curr),
                            'sma_long': float(sma_long_curr),
                            'crossover_type': 'death',
                            'bar_close': float(bar.close),
                        }
                    )
                else:
                    logger.debug(f"[{symbol}] No position to sell, skipping sell signal")
            
            return None
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in SMA crossover logic: {e}", exc_info=True)
            return None
    
    def get_position(self, symbol: str) -> int:
        """Get current position for a symbol."""
        return self._positions.get(symbol, 0)
    
    def get_sma_values(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Get current SMA values for a symbol.
        
        Returns:
            Dict with 'short' and 'long' SMA values, or None if unavailable
        """
        df = self.get_cached_bars(symbol)
        
        if df.empty or len(df) < self.long_window:
            return None
        
        df['sma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['sma_long'] = df['close'].rolling(window=self.long_window).mean()
        
        if pd.isna(df['sma_short'].iloc[-1]) or pd.isna(df['sma_long'].iloc[-1]):
            return None
        
        return {
            'short': float(df['sma_short'].iloc[-1]),
            'long': float(df['sma_long'].iloc[-1]),
        }

