"""
RSI Mean Reversion Strategy

Classic RSI-based mean reversion strategy:
- BUY when RSI drops below oversold threshold (e.g., 30)
- SELL when RSI rises above overbought threshold (e.g., 70)
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


class RSIMeanReversion(BaseStrategy):
    """
    RSI (Relative Strength Index) Mean Reversion Strategy.
    
    Configuration parameters:
        - rsi_period: Number of periods for RSI calculation (default: 14)
        - oversold_threshold: RSI level to trigger BUY (default: 30)
        - overbought_threshold: RSI level to trigger SELL (default: 70)
        - quantity: Number of shares to trade (default: 100)
        - min_lookback: Minimum bars needed before trading (default: rsi_period + 10)
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        super().__init__(name, config, symbols)
        
        # Strategy parameters
        self.rsi_period = config.get('rsi_period', 14)
        self.oversold_threshold = config.get('oversold_threshold', 30.0)
        self.overbought_threshold = config.get('overbought_threshold', 70.0)
        self.quantity = config.get('quantity', 100)
        self.min_lookback = config.get('min_lookback', self.rsi_period + 10)
        
        # State tracking
        self._positions: Dict[str, int] = {symbol: 0 for symbol in symbols}
        self._last_rsi: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        
        logger.info(
            f"RSI Mean Reversion strategy '{name}' initialized: "
            f"period={self.rsi_period}, oversold={self.oversold_threshold}, "
            f"overbought={self.overbought_threshold}, qty={self.quantity}"
        )
    
    async def get_required_lookback(self) -> int:
        """Return required number of historical bars."""
        return self.min_lookback
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate RSI (Relative Strength Index).
        
        Args:
            prices: Series of closing prices
            period: RSI period (default: 14)
            
        Returns:
            Series of RSI values
        """
        # Calculate price changes
        delta = prices.diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        
        # Calculate exponential moving averages
        avg_gains = gains.ewm(span=period, adjust=False).mean()
        avg_losses = losses.ewm(span=period, adjust=False).mean()
        
        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Check RSI levels and generate order if conditions met.
        
        Args:
            symbol: Symbol being updated
            bar: Latest bar data
            
        Returns:
            OrderSpec if RSI signal is detected, None otherwise
        """
        try:
            # Get cached bars
            df = self.get_cached_bars(symbol)
            
            if df.empty or len(df) < self.min_lookback:
                logger.debug(f"[{symbol}] Insufficient data: {len(df)} bars (need {self.min_lookback})")
                return None
            
            # Calculate RSI
            df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)
            
            # Check for valid RSI values
            if len(df) < 2 or pd.isna(df['rsi'].iloc[-1]):
                return None
            
            # Get current RSI
            rsi_curr = df['rsi'].iloc[-1]
            self._last_rsi[symbol] = rsi_curr
            
            # Log RSI values for debugging
            logger.debug(
                f"[{symbol}] RSI={rsi_curr:.2f}, Position={self._positions[symbol]}"
            )
            
            # Generate orders based on RSI levels
            # BUY signal: RSI crosses below oversold threshold
            if rsi_curr < self.oversold_threshold and self._positions[symbol] <= 0:
                logger.info(
                    f"[{symbol}] 🟢 RSI OVERSOLD signal! RSI={rsi_curr:.2f} < {self.oversold_threshold}"
                )
                
                self._positions[symbol] = self.quantity
                
                return OrderSpec(
                    symbol=symbol,
                    action=OrderAction.BUY,
                    quantity=self.quantity,
                    order_type=OrderType.MARKET,
                    strategy_name=self.name,
                    metadata={
                        'rsi': float(rsi_curr),
                        'signal_type': 'oversold',
                        'bar_close': float(bar.close),
                    }
                )
            
            # SELL signal: RSI crosses above overbought threshold
            elif rsi_curr > self.overbought_threshold and self._positions[symbol] > 0:
                logger.info(
                    f"[{symbol}] 🔴 RSI OVERBOUGHT signal! RSI={rsi_curr:.2f} > {self.overbought_threshold}"
                )
                
                quantity = self._positions[symbol]
                self._positions[symbol] = 0
                
                return OrderSpec(
                    symbol=symbol,
                    action=OrderAction.SELL,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    strategy_name=self.name,
                    metadata={
                        'rsi': float(rsi_curr),
                        'signal_type': 'overbought',
                        'bar_close': float(bar.close),
                    }
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in RSI mean reversion logic: {e}", exc_info=True)
            return None
    
    def get_position(self, symbol: str) -> int:
        """Get current position for a symbol."""
        return self._positions.get(symbol, 0)
    
    def get_rsi(self, symbol: str) -> Optional[float]:
        """
        Get current RSI value for a symbol.
        
        Returns:
            Current RSI value, or None if unavailable
        """
        return self._last_rsi.get(symbol)
    
    def get_rsi_series(self, symbol: str) -> Optional[pd.Series]:
        """
        Get full RSI series for a symbol.
        
        Returns:
            Pandas Series of RSI values, or None if unavailable
        """
        df = self.get_cached_bars(symbol)
        
        if df.empty or len(df) < self.min_lookback:
            return None
        
        df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)
        
        return df['rsi']

