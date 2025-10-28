"""
Bollinger Bands Strategy

Trading strategy based on Bollinger Bands:
- BUY when price touches or breaks below the lower band (oversold)
- SELL when price touches or breaks above the upper band (overbought)
- Can also trade breakouts in the direction of the trend
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


class BollingerBands(BaseStrategy):
    """
    Bollinger Bands Trading Strategy.
    
    Configuration parameters:
        - period: Number of periods for moving average (default: 20)
        - std_dev: Standard deviation multiplier (default: 2.0)
        - quantity: Number of shares to trade (default: 100)
        - min_lookback: Minimum bars needed before trading (default: period + 10)
        - strategy_type: 'mean_reversion' or 'breakout' (default: 'mean_reversion')
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        super().__init__(name, config, symbols)
        
        # Strategy parameters
        self.period = config.get('period', 20)
        self.std_dev = config.get('std_dev', 2.0)
        self.quantity = config.get('quantity', 100)
        self.min_lookback = config.get('min_lookback', self.period + 10)
        self.strategy_type = config.get('strategy_type', 'mean_reversion')
        
        # State tracking
        self._positions: Dict[str, int] = {symbol: 0 for symbol in symbols}
        self._last_bands: Dict[str, Optional[Dict[str, float]]] = {symbol: None for symbol in symbols}
        
        logger.info(
            f"Bollinger Bands strategy '{name}' initialized: "
            f"period={self.period}, std_dev={self.std_dev}, "
            f"type={self.strategy_type}, qty={self.quantity}"
        )
    
    async def get_required_lookback(self) -> int:
        """Return required number of historical bars."""
        return self.min_lookback
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
        """
        Calculate Bollinger Bands.
        
        Args:
            prices: Series of closing prices
            period: Moving average period
            std_dev: Standard deviation multiplier
            
        Returns:
            Dictionary with 'upper', 'middle', 'lower' bands
        """
        # Calculate middle band (SMA)
        middle = prices.rolling(window=period).mean()
        
        # Calculate standard deviation
        std = prices.rolling(window=period).std()
        
        # Calculate upper and lower bands
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Check Bollinger Bands and generate order if conditions met.
        
        Args:
            symbol: Symbol being updated
            bar: Latest bar data
            
        Returns:
            OrderSpec if Bollinger Bands signal is detected, None otherwise
        """
        try:
            # Get cached bars
            df = self.get_cached_bars(symbol)
            
            if df.empty or len(df) < self.min_lookback:
                logger.debug(f"[{symbol}] Insufficient data: {len(df)} bars (need {self.min_lookback})")
                return None
            
            # Calculate Bollinger Bands
            bands = self._calculate_bollinger_bands(df['close'], self.period, self.std_dev)
            
            # Check for valid band values
            if len(df) < 2 or pd.isna(bands['upper'].iloc[-1]) or pd.isna(bands['lower'].iloc[-1]):
                return None
            
            # Get current values
            price_curr = float(bar.close)
            upper_curr = bands['upper'].iloc[-1]
            middle_curr = bands['middle'].iloc[-1]
            lower_curr = bands['lower'].iloc[-1]
            
            # Store current bands
            self._last_bands[symbol] = {
                'upper': upper_curr,
                'middle': middle_curr,
                'lower': lower_curr
            }
            
            # Log band values for debugging
            logger.debug(
                f"[{symbol}] Price=${price_curr:.2f}, Upper=${upper_curr:.2f}, "
                f"Middle=${middle_curr:.2f}, Lower=${lower_curr:.2f}, Position={self._positions[symbol]}"
            )
            
            if self.strategy_type == 'mean_reversion':
                return await self._mean_reversion_logic(symbol, bar, price_curr, upper_curr, lower_curr)
            elif self.strategy_type == 'breakout':
                return await self._breakout_logic(symbol, bar, price_curr, upper_curr, lower_curr, middle_curr)
            else:
                logger.error(f"Unknown strategy type: {self.strategy_type}")
                return None
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in Bollinger Bands logic: {e}", exc_info=True)
            return None
    
    async def _mean_reversion_logic(
        self, 
        symbol: str, 
        bar: BarData, 
        price: float, 
        upper: float, 
        lower: float
    ) -> Optional[OrderSpec]:
        """Mean reversion logic: buy oversold, sell overbought."""
        # BUY signal: Price touches or breaks below lower band
        if price <= lower and self._positions[symbol] <= 0:
            logger.info(
                f"[{symbol}] 🟢 BOLLINGER OVERSOLD signal! Price=${price:.2f} <= Lower=${lower:.2f}"
            )
            
            self._positions[symbol] = self.quantity
            
            return OrderSpec(
                symbol=symbol,
                action=OrderAction.BUY,
                quantity=self.quantity,
                order_type=OrderType.MARKET,
                strategy_name=self.name,
                metadata={
                    'price': price,
                    'upper_band': upper,
                    'lower_band': lower,
                    'signal_type': 'oversold',
                    'bar_close': float(bar.close),
                }
            )
        
        # SELL signal: Price touches or breaks above upper band
        elif price >= upper and self._positions[symbol] > 0:
            logger.info(
                f"[{symbol}] 🔴 BOLLINGER OVERBOUGHT signal! Price=${price:.2f} >= Upper=${upper:.2f}"
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
                    'price': price,
                    'upper_band': upper,
                    'lower_band': lower,
                    'signal_type': 'overbought',
                    'bar_close': float(bar.close),
                }
            )
        
        return None
    
    async def _breakout_logic(
        self, 
        symbol: str, 
        bar: BarData, 
        price: float, 
        upper: float, 
        lower: float, 
        middle: float
    ) -> Optional[OrderSpec]:
        """Breakout logic: buy breakouts above upper band, sell breakouts below lower band."""
        # BUY signal: Price breaks above upper band (bullish breakout)
        if price > upper and self._positions[symbol] <= 0:
            logger.info(
                f"[{symbol}] 🟢 BOLLINGER BREAKOUT UP! Price=${price:.2f} > Upper=${upper:.2f}"
            )
            
            self._positions[symbol] = self.quantity
            
            return OrderSpec(
                symbol=symbol,
                action=OrderAction.BUY,
                quantity=self.quantity,
                order_type=OrderType.MARKET,
                strategy_name=self.name,
                metadata={
                    'price': price,
                    'upper_band': upper,
                    'middle_band': middle,
                    'lower_band': lower,
                    'signal_type': 'breakout_up',
                    'bar_close': float(bar.close),
                }
            )
        
        # SELL signal: Price breaks below lower band (bearish breakout)
        elif price < lower and self._positions[symbol] > 0:
            logger.info(
                f"[{symbol}] 🔴 BOLLINGER BREAKOUT DOWN! Price=${price:.2f} < Lower=${lower:.2f}"
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
                    'price': price,
                    'upper_band': upper,
                    'middle_band': middle,
                    'lower_band': lower,
                    'signal_type': 'breakout_down',
                    'bar_close': float(bar.close),
                }
            )
        
        return None
    
    def get_position(self, symbol: str) -> int:
        """Get current position for a symbol."""
        return self._positions.get(symbol, 0)
    
    def get_bollinger_bands(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Get current Bollinger Bands for a symbol.
        
        Returns:
            Dict with 'upper', 'middle', 'lower' band values, or None if unavailable
        """
        return self._last_bands.get(symbol)
    
    def get_bollinger_bands_series(self, symbol: str) -> Optional[Dict[str, pd.Series]]:
        """
        Get full Bollinger Bands series for a symbol.
        
        Returns:
            Dict with 'upper', 'middle', 'lower' band series, or None if unavailable
        """
        df = self.get_cached_bars(symbol)
        
        if df.empty or len(df) < self.min_lookback:
            return None
        
        bands = self._calculate_bollinger_bands(df['close'], self.period, self.std_dev)
        
        return bands
