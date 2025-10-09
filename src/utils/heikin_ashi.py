"""
Heiken-Ashi candle calculation utilities.

Heiken-Ashi (HA) candles are a type of candlestick chart that uses modified
open, high, low, and close values to filter out market noise and provide
clearer trend signals.

Formulas:
- HA_Close = (O + H + L + C) / 4
- HA_Open = (prev_HA_Open + prev_HA_Close) / 2
- HA_High = max(H, HA_Open, HA_Close)
- HA_Low = min(L, HA_Open, HA_Close)
"""

import pandas as pd
import numpy as np
from typing import Optional


def calculate_heikin_ashi(df: pd.DataFrame, 
                         open_col: str = 'open',
                         high_col: str = 'high', 
                         low_col: str = 'low',
                         close_col: str = 'close') -> pd.DataFrame:
    """
    Calculate Heiken-Ashi OHLC from regular OHLC data.
    
    Args:
        df: DataFrame with OHLC data
        open_col: Column name for open prices
        high_col: Column name for high prices
        low_col: Column name for low prices
        close_col: Column name for close prices
        
    Returns:
        DataFrame with original data plus HA columns:
        - ha_open, ha_high, ha_low, ha_close
        
    Raises:
        ValueError: If required columns are missing
    """
    required_cols = [open_col, high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create a copy to avoid modifying original
    result = df.copy()
    
    # Initialize HA arrays
    ha_open = np.zeros(len(df))
    ha_high = np.zeros(len(df))
    ha_low = np.zeros(len(df))
    ha_close = np.zeros(len(df))
    
    # First HA candle
    ha_close[0] = (df[open_col].iloc[0] + df[high_col].iloc[0] + 
                   df[low_col].iloc[0] + df[close_col].iloc[0]) / 4
    ha_open[0] = (df[open_col].iloc[0] + df[close_col].iloc[0]) / 2
    ha_high[0] = max(df[high_col].iloc[0], ha_open[0], ha_close[0])
    ha_low[0] = min(df[low_col].iloc[0], ha_open[0], ha_close[0])
    
    # Calculate remaining HA candles
    for i in range(1, len(df)):
        # HA Close = (O + H + L + C) / 4
        ha_close[i] = (df[open_col].iloc[i] + df[high_col].iloc[i] + 
                       df[low_col].iloc[i] + df[close_col].iloc[i]) / 4
        
        # HA Open = (prev_HA_Open + prev_HA_Close) / 2
        ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2
        
        # HA High = max(H, HA_Open, HA_Close)
        ha_high[i] = max(df[high_col].iloc[i], ha_open[i], ha_close[i])
        
        # HA Low = min(L, HA_Open, HA_Close)
        ha_low[i] = min(df[low_col].iloc[i], ha_open[i], ha_close[i])
    
    # Add HA columns to result
    result['ha_open'] = ha_open
    result['ha_high'] = ha_high
    result['ha_low'] = ha_low
    result['ha_close'] = ha_close
    
    return result


def is_heikin_ashi_bullish(df: pd.DataFrame, index: int = -1) -> bool:
    """
    Determine if a Heiken-Ashi candle is bullish.
    
    A HA candle is bullish if:
    - HA_Close > HA_Open (green candle)
    - OR HA_Close == HA_Open and previous candle was bullish
    
    Args:
        df: DataFrame with HA columns
        index: Index of candle to check (default: last candle)
        
    Returns:
        True if bullish, False if bearish
    """
    if 'ha_open' not in df.columns or 'ha_close' not in df.columns:
        raise ValueError("DataFrame must contain 'ha_open' and 'ha_close' columns")
    
    if index < 0:
        index = len(df) + index
    
    if index >= len(df):
        raise IndexError("Index out of range")
    
    ha_open = df['ha_open'].iloc[index]
    ha_close = df['ha_close'].iloc[index]
    
    # If close > open, it's bullish
    if ha_close > ha_close:
        return True
    
    # If close == open, check previous candle
    if ha_close == ha_open and index > 0:
        return is_heikin_ashi_bullish(df, index - 1)
    
    return False


def get_heikin_ashi_trend(df: pd.DataFrame, lookback: int = 5) -> str:
    """
    Determine the overall trend based on recent Heiken-Ashi candles.
    
    Args:
        df: DataFrame with HA columns
        lookback: Number of recent candles to analyze
        
    Returns:
        'bullish', 'bearish', or 'neutral'
    """
    if len(df) < lookback:
        lookback = len(df)
    
    recent_candles = df.tail(lookback)
    bullish_count = 0
    
    for i in range(len(recent_candles)):
        if is_heikin_ashi_bullish(recent_candles, i):
            bullish_count += 1
    
    if bullish_count > lookback * 0.6:
        return 'bullish'
    elif bullish_count < lookback * 0.4:
        return 'bearish'
    else:
        return 'neutral'


def calculate_heikin_ashi_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate additional indicators based on Heiken-Ashi data.
    
    Args:
        df: DataFrame with HA columns
        
    Returns:
        DataFrame with additional indicator columns:
        - ha_trend: 'bullish', 'bearish', 'neutral'
        - ha_body_size: Size of HA candle body
        - ha_wick_ratio: Ratio of upper wick to lower wick
    """
    if 'ha_open' not in df.columns or 'ha_close' not in df.columns:
        raise ValueError("DataFrame must contain HA columns")
    
    result = df.copy()
    
    # HA trend
    result['ha_trend'] = result.apply(
        lambda row: 'bullish' if row['ha_close'] > row['ha_open'] else 'bearish', 
        axis=1
    )
    
    # HA body size
    result['ha_body_size'] = abs(result['ha_close'] - result['ha_open'])
    
    # HA wick ratios
    result['ha_upper_wick'] = result['ha_high'] - result[['ha_open', 'ha_close']].max(axis=1)
    result['ha_lower_wick'] = result[['ha_open', 'ha_close']].min(axis=1) - result['ha_low']
    
    # Avoid division by zero
    result['ha_wick_ratio'] = np.where(
        result['ha_lower_wick'] > 0,
        result['ha_upper_wick'] / result['ha_lower_wick'],
        np.inf
    )
    
    return result


# ========================= REAL-TIME CALCULATION ========================= #

class HeikinAshiCalculator:
    """
    Incremental Heiken-Ashi calculator for real-time streams.

    Usage:
        ha = HeikinAshiCalculator()
        ha_bar = ha.update_from_bar(timestamp, o, h, l, c)

    Maintains internal state of previous HA open/close to compute the next
    HA values in O(1) time without recalculating the whole series.
    """

    def __init__(self) -> None:
        self._prev_ha_open: float | None = None
        self._prev_ha_close: float | None = None

    def reset(self) -> None:
        self._prev_ha_open = None
        self._prev_ha_close = None

    def update_from_bar(
        self,
        timestamp,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
    ) -> dict:
        """Return next HA bar given a standard OHLC bar.

        Returns a dict with keys: timestamp, ha_open, ha_high, ha_low, ha_close.
        """
        ha_close = (open_price + high_price + low_price + close_price) / 4.0

        if self._prev_ha_open is None or self._prev_ha_close is None:
            # Seed using the first classic approximation
            ha_open = (open_price + close_price) / 2.0
        else:
            ha_open = (self._prev_ha_open + self._prev_ha_close) / 2.0

        ha_high = max(high_price, ha_open, ha_close)
        ha_low = min(low_price, ha_open, ha_close)

        # Persist for next update
        self._prev_ha_open = ha_open
        self._prev_ha_close = ha_close

        return {
            'timestamp': timestamp,
            'ha_open': ha_open,
            'ha_high': ha_high,
            'ha_low': ha_low,
            'ha_close': ha_close,
        }
