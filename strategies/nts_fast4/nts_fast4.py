"""
NTS FAST4 Strategy Implementation

A Python implementation of the TradingView Pine Script "NTS FAST4 Strategy (v6)".
This strategy uses:
- Multi-timeframe (MTF) analysis with higher timeframe for signals
- Modified/Unmodified ATR trailing stops with custom ATR calculation
- Fibonacci retracement levels for entry/exit targets
- Trend detection with trailing stops
- Dynamic stop-loss updates based on ATR trail

Original Pine Script by TradingView user.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, OrderAction, OrderType, BarData, StopLossSpec, TakeProfitSpec


class NTSFast4(BaseStrategy):
    """
    NTS FAST4 Trading Strategy.
    
    Configuration parameters:
        - trail_type: 'modified' or 'unmodified' ATR calculation (default: 'modified')
        - atr_period: ATR calculation period (default: 185)
        - atr_factor: ATR multiplier for stops (default: 3.0)
        - use_take_profit: Enable take-profit orders (default: True)
        - tp_fib_level: Fibonacci level for take-profit ('61.8', '78.6', '88.6', '100.0') (default: '78.6')
        - quantity: Number of shares to trade (default: 100)
        - min_lookback: Minimum bars needed before trading (default: 200)
        - mtf_resolution: Multi-timeframe resolution mapping (default: '5m->15m')
    """
    
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        symbols: List[str],
    ):
        super().__init__(name, config, symbols)
        
        # Strategy parameters
        self.trail_type = config.get('trail_type', 'modified')
        self.atr_period = config.get('atr_period', 185)
        self.atr_factor = config.get('atr_factor', 3.0)
        self.use_take_profit = config.get('use_take_profit', True)
        self.tp_fib_level = config.get('tp_fib_level', '78.6')
        self.quantity = config.get('quantity', 100)
        self.min_lookback = config.get('min_lookback', 200)
        self.mtf_resolution = config.get('mtf_resolution', '5m->15m')
        
        # Parse MTF resolution
        self.chart_tf, self.signal_tf = self._parse_mtf_resolution(self.mtf_resolution)
        
        # State tracking
        self._positions: Dict[str, int] = {symbol: 0 for symbol in symbols}
        self._trend_state: Dict[str, int] = {symbol: 0 for symbol in symbols}  # 1=up, -1=down, 0=neutral
        self._trend_up: Dict[str, float] = {symbol: 0.0 for symbol in symbols}
        self._trend_down: Dict[str, float] = {symbol: 0.0 for symbol in symbols}
        self._extreme: Dict[str, float] = {symbol: 0.0 for symbol in symbols}
        self._trail: Dict[str, float] = {symbol: 0.0 for symbol in symbols}
        self._last_signals: Dict[str, Dict[str, Any]] = {symbol: {} for symbol in symbols}
        
        # Fibonacci levels mapping
        self.fib_levels = {
            '61.8': 0.618,
            '78.6': 0.786,
            '88.6': 0.886,
            '100.0': 1.0
        }
        
        logger.info(
            f"NTS FAST4 strategy '{name}' initialized: "
            f"trail_type={self.trail_type}, atr_period={self.atr_period}, "
            f"atr_factor={self.atr_factor}, tp_level={self.tp_fib_level}, "
            f"mtf={self.mtf_resolution}, qty={self.quantity}"
        )
    
    def _parse_mtf_resolution(self, resolution: str) -> Tuple[str, str]:
        """Parse multi-timeframe resolution string."""
        try:
            chart_tf, signal_tf = resolution.split('->')
            return chart_tf.strip(), signal_tf.strip()
        except ValueError:
            logger.warning(f"Invalid MTF resolution format: {resolution}, using default 5m->15m")
            return '5m', '15m'
    
    async def get_required_lookback(self) -> int:
        """Return required number of historical bars."""
        return self.min_lookback
    
    def _wild_ma(self, src: pd.Series, length: int) -> pd.Series:
        """
        Wilder's Moving Average (exponential smoothing).
        
        Args:
            src: Source series
            length: Period length
            
        Returns:
            Wilder's MA series
        """
        alpha = 1.0 / length
        return src.ewm(alpha=alpha, adjust=False).mean()
    
    def _calculate_atr(self, df: pd.DataFrame, period: int, modified: bool = True) -> pd.Series:
        """
        Calculate ATR (Average True Range) with optional modification.
        
        Args:
            df: DataFrame with OHLC data
            period: ATR period
            modified: Use modified ATR calculation
            
        Returns:
            ATR series
        """
        H = df['high']
        L = df['low']
        C = df['close']
        
        if modified:
            # Modified ATR calculation from Pine Script
            HiLo = np.minimum(H - L, 1.5 * pd.Series(H - L).rolling(window=period).mean())
            HRef = np.where(
                L <= H.shift(1),
                H - C.shift(1),
                H - C.shift(1) - 0.5 * (L - H.shift(1))
            )
            LRef = np.where(
                H >= L.shift(1),
                C.shift(1) - L,
                C.shift(1) - L - 0.5 * (L.shift(1) - H)
            )
            true_range = np.maximum.reduce([HiLo, HRef, LRef])
        else:
            # Standard ATR calculation
            high_low = H - L
            high_close = np.abs(H - C.shift(1))
            low_close = np.abs(L - C.shift(1))
            true_range = np.maximum.reduce([high_low, high_close, low_close])
        
        # Calculate ATR using Wilder's MA
        atr = self._wild_ma(pd.Series(true_range), period)
        
        # Fill NaN values with 0 for the first few periods
        atr = atr.fillna(0)
        
        return atr
    
    def _calculate_trend_logic(self, df: pd.DataFrame, atr: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate trend logic with trailing stops.
        
        Args:
            df: DataFrame with OHLC data
            atr: ATR series
            
        Returns:
            Tuple of (TrendUp, TrendDown, Trend) series
        """
        C = df['close']
        atr_factor = self.atr_factor
        
        # Calculate Up and Down levels
        Up = C - atr * atr_factor
        Dn = C + atr * atr_factor
        
        # Initialize arrays
        TrendUp = pd.Series(index=df.index, dtype=float)
        TrendDown = pd.Series(index=df.index, dtype=float)
        Trend = pd.Series(index=df.index, dtype=int)
        
        # Set initial values
        TrendUp.iloc[0] = Up.iloc[0]
        TrendDown.iloc[0] = Dn.iloc[0]
        Trend.iloc[0] = 0
        
        # Calculate trend logic
        for i in range(1, len(df)):
            # Skip if ATR is NaN or 0
            if pd.isna(atr.iloc[i]) or atr.iloc[i] == 0:
                TrendUp.iloc[i] = TrendUp.iloc[i-1]
                TrendDown.iloc[i] = TrendDown.iloc[i-1]
                Trend.iloc[i] = Trend.iloc[i-1]
                continue
            
            # Update trailing stops
            if C.iloc[i-1] > TrendUp.iloc[i-1]:
                TrendUp.iloc[i] = max(Up.iloc[i], TrendUp.iloc[i-1])
            else:
                TrendUp.iloc[i] = Up.iloc[i]
            
            if C.iloc[i-1] < TrendDown.iloc[i-1]:
                TrendDown.iloc[i] = min(Dn.iloc[i], TrendDown.iloc[i-1])
            else:
                TrendDown.iloc[i] = Dn.iloc[i]
            
            # Determine trend
            if C.iloc[i] > TrendDown.iloc[i-1]:
                Trend.iloc[i] = 1
            elif C.iloc[i] < TrendUp.iloc[i-1]:
                Trend.iloc[i] = -1
            else:
                Trend.iloc[i] = Trend.iloc[i-1]
        
        return TrendUp, TrendDown, Trend
    
    def _calculate_fibonacci_levels(self, ex: float, trail: float) -> Dict[str, float]:
        """
        Calculate Fibonacci retracement levels.
        
        Args:
            ex: Extreme price (high/low)
            trail: Trail price (opposite extreme)
            
        Returns:
            Dictionary with Fibonacci levels
        """
        if ex == trail:
            return {
                'f1': ex,
                'f2': ex,
                'f3': ex,
                'l100': ex
            }
        
        # Calculate Fibonacci levels
        f1 = ex + (trail - ex) * 0.618  # 61.8%
        f2 = ex + (trail - ex) * 0.786  # 78.6%
        f3 = ex + (trail - ex) * 0.886  # 88.6%
        l100 = trail  # 100%
        
        return {
            'f1': f1,
            'f2': f2,
            'f3': f3,
            'l100': l100
        }
    
    async def _get_mtf_data(self, symbol: str, num_bars: int) -> pd.DataFrame:
        """
        Return exact 1m cached bars for signal calculation (no resampling).
        """
        try:
            df = self.get_cached_bars(symbol)
            if df.empty:
                logger.debug(f"[{symbol}] No cached bars available for MTF data")
                return pd.DataFrame()
            return df.tail(num_bars).reset_index()
        except Exception as e:
            logger.error(f"Error getting MTF data for {symbol}: {e}")
            return pd.DataFrame()
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        """
        Check NTS FAST4 strategy and generate order if conditions met.
        
        Args:
            symbol: Symbol being updated
            bar: Latest bar data
            
        Returns:
            OrderSpec if strategy signal is detected, None otherwise
        """
        try:
            # Get cached bars
            df = self.get_cached_bars(symbol)
            
            if df.empty or len(df) < self.min_lookback:
                logger.debug(f"[{symbol}] Insufficient data: {len(df)} bars (need {self.min_lookback})")
                return None
            
            # Get MTF data for signal calculation
            mtf_df = await self._get_mtf_data(symbol, self.min_lookback)
            
            if mtf_df.empty or len(mtf_df) < 50:  # Need enough MTF data
                logger.debug(f"[{symbol}] Insufficient MTF data: {len(mtf_df)} bars")
                return None
            
            # Calculate ATR
            atr = self._calculate_atr(mtf_df, self.atr_period, self.trail_type == 'modified')
            
            if len(atr) < 2 or pd.isna(atr.iloc[-1]):
                return None
            
            # Calculate trend logic
            TrendUp, TrendDown, Trend = self._calculate_trend_logic(mtf_df, atr)
            
            if len(Trend) < 2:
                return None
            
            # Get current values
            current_trend = Trend.iloc[-1]
            previous_trend = Trend.iloc[-2]
            current_price = float(bar.close)
            
            # Update internal state
            self._trend_state[symbol] = current_trend
            self._trend_up[symbol] = TrendUp.iloc[-1]
            self._trend_down[symbol] = TrendDown.iloc[-1]
            
            # Check for trend changes
            if current_trend != previous_trend:
                if current_trend == 1 and previous_trend != 1:  # Trend changed to up
                    return await self._handle_long_signal(symbol, bar, mtf_df, atr)
                elif current_trend == -1 and previous_trend != -1:  # Trend changed to down
                    return await self._handle_short_signal(symbol, bar, mtf_df, atr)
            
            # Check for position management (stop-loss updates)
            if self._positions[symbol] != 0:
                return await self._handle_position_management(symbol, bar, mtf_df, atr)
            
            return None
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in NTS FAST4 logic: {e}", exc_info=True)
            return None
    
    async def _handle_long_signal(
        self, 
        symbol: str, 
        bar: BarData, 
        mtf_df: pd.DataFrame, 
        atr: pd.Series
    ) -> Optional[OrderSpec]:
        """Handle long signal generation."""
        if self._positions[symbol] > 0:  # Already long
            return None
        
        current_price = float(bar.close)
        atr_value = atr.iloc[-1]
        
        # Calculate Fibonacci levels for take-profit
        ex = mtf_df['low'].min()  # Extreme low
        trail = self._trend_up[symbol]  # Current trail
        
        fib_levels = self._calculate_fibonacci_levels(ex, trail)
        tp_level = self.fib_levels[self.tp_fib_level]
        
        # Calculate take-profit price
        if self.tp_fib_level == '100.0':
            take_profit_price = trail
        else:
            take_profit_price = ex + (trail - ex) * tp_level
        
        logger.info(
            f"[{symbol}] 🟢 NTS FAST4 LONG signal! Price=${current_price:.2f}, "
            f"TrendUp=${trail:.2f}, TP=${take_profit_price:.2f}"
        )
        
        # Update position
        self._positions[symbol] = self.quantity
        
        # Store signal metadata
        self._last_signals[symbol] = {
            'signal_type': 'long',
            'entry_price': current_price,
            'trend_up': trail,
            'trend_down': self._trend_down[symbol],
            'atr_value': atr_value,
            'fib_levels': fib_levels,
            'take_profit_price': take_profit_price
        }
        
        # Create order with stop-loss and take-profit
        order = OrderSpec(
            symbol=symbol,
            action=OrderAction.BUY,
            quantity=self.quantity,
            order_type=OrderType.MARKET,
            strategy_name=self.name,
            metadata={
                'signal_type': 'nts_fast4_long',
                'entry_price': current_price,
                'trend_up': trail,
                'trend_down': self._trend_down[symbol],
                'atr_value': atr_value,
                'fib_levels': fib_levels,
                'bar_close': float(bar.close),
            }
        )
        
        # Add stop-loss
        stop_loss_price = trail  # Use trend line as stop
        order.stop_loss = StopLossSpec(
            stop_price=Decimal(str(stop_loss_price)),
            quantity=self.quantity
        )
        
        # Add take-profit if enabled
        if self.use_take_profit:
            order.take_profit = TakeProfitSpec(
                limit_price=Decimal(str(take_profit_price)),
                quantity=self.quantity
            )
        
        return order
    
    async def _handle_short_signal(
        self, 
        symbol: str, 
        bar: BarData, 
        mtf_df: pd.DataFrame, 
        atr: pd.Series
    ) -> Optional[OrderSpec]:
        """Handle short signal generation."""
        if self._positions[symbol] < 0:  # Already short
            return None
        
        current_price = float(bar.close)
        atr_value = atr.iloc[-1]
        
        # Calculate Fibonacci levels for take-profit
        ex = mtf_df['high'].max()  # Extreme high
        trail = self._trend_down[symbol]  # Current trail
        
        fib_levels = self._calculate_fibonacci_levels(ex, trail)
        tp_level = self.fib_levels[self.tp_fib_level]
        
        # Calculate take-profit price
        if self.tp_fib_level == '100.0':
            take_profit_price = trail
        else:
            take_profit_price = ex + (trail - ex) * tp_level
        
        logger.info(
            f"[{symbol}] 🔴 NTS FAST4 SHORT signal! Price=${current_price:.2f}, "
            f"TrendDown=${trail:.2f}, TP=${take_profit_price:.2f}"
        )
        
        # Update position
        self._positions[symbol] = -self.quantity
        
        # Store signal metadata
        self._last_signals[symbol] = {
            'signal_type': 'short',
            'entry_price': current_price,
            'trend_up': self._trend_up[symbol],
            'trend_down': trail,
            'atr_value': atr_value,
            'fib_levels': fib_levels,
            'take_profit_price': take_profit_price
        }
        
        # Create order with stop-loss and take-profit
        order = OrderSpec(
            symbol=symbol,
            action=OrderAction.SELL,
            quantity=self.quantity,
            order_type=OrderType.MARKET,
            strategy_name=self.name,
            metadata={
                'signal_type': 'nts_fast4_short',
                'entry_price': current_price,
                'trend_up': self._trend_up[symbol],
                'trend_down': trail,
                'atr_value': atr_value,
                'fib_levels': fib_levels,
                'bar_close': float(bar.close),
            }
        )
        
        # Add stop-loss
        stop_loss_price = trail  # Use trend line as stop
        order.stop_loss = StopLossSpec(
            stop_price=Decimal(str(stop_loss_price)),
            quantity=self.quantity
        )
        
        # Add take-profit if enabled
        if self.use_take_profit:
            order.take_profit = TakeProfitSpec(
                limit_price=Decimal(str(take_profit_price)),
                quantity=self.quantity
            )
        
        return order
    
    async def _handle_position_management(
        self, 
        symbol: str, 
        bar: BarData, 
        mtf_df: pd.DataFrame, 
        atr: pd.Series
    ) -> Optional[OrderSpec]:
        """Handle position management (stop-loss updates)."""
        current_price = float(bar.close)
        position = self._positions[symbol]
        
        if position > 0:  # Long position
            # Check if price crossed below trend line (exit long)
            if current_price < self._trend_up[symbol]:
                logger.info(
                    f"[{symbol}] 🔴 NTS FAST4 EXIT LONG! Price=${current_price:.2f} < "
                    f"TrendUp=${self._trend_up[symbol]:.2f}"
                )
                
                self._positions[symbol] = 0
                
                return OrderSpec(
                    symbol=symbol,
                    action=OrderAction.SELL,
                    quantity=position,
                    order_type=OrderType.MARKET,
                    strategy_name=self.name,
                    metadata={
                        'signal_type': 'nts_fast4_exit_long',
                        'exit_price': current_price,
                        'trend_up': self._trend_up[symbol],
                        'bar_close': float(bar.close),
                    }
                )
        
        elif position < 0:  # Short position
            # Check if price crossed above trend line (exit short)
            if current_price > self._trend_down[symbol]:
                logger.info(
                    f"[{symbol}] 🟢 NTS FAST4 EXIT SHORT! Price=${current_price:.2f} > "
                    f"TrendDown=${self._trend_down[symbol]:.2f}"
                )
                
                self._positions[symbol] = 0
                
                return OrderSpec(
                    symbol=symbol,
                    action=OrderAction.BUY,
                    quantity=abs(position),
                    order_type=OrderType.MARKET,
                    strategy_name=self.name,
                    metadata={
                        'signal_type': 'nts_fast4_exit_short',
                        'exit_price': current_price,
                        'trend_down': self._trend_down[symbol],
                        'bar_close': float(bar.close),
                    }
                )
        
        return None
    
    def get_position(self, symbol: str) -> int:
        """Get current position for a symbol."""
        return self._positions.get(symbol, 0)
    
    def get_trend_state(self, symbol: str) -> int:
        """Get current trend state for a symbol."""
        return self._trend_state.get(symbol, 0)
    
    def get_trend_levels(self, symbol: str) -> Dict[str, float]:
        """Get current trend levels for a symbol."""
        return {
            'trend_up': self._trend_up.get(symbol, 0.0),
            'trend_down': self._trend_down.get(symbol, 0.0)
        }
    
    def get_last_signal(self, symbol: str) -> Dict[str, Any]:
        """Get last signal metadata for a symbol."""
        return self._last_signals.get(symbol, {})
