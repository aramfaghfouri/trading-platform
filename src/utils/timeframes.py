"""
Timeframe configuration and aggregation utilities.

Defines supported timeframes and provides utilities for bar aggregation
from 5-second IBKR real-time bars into various timeframes.
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
from datetime import datetime, timedelta


# Timeframe mappings in seconds
TIMEFRAME_MAP = {
    '1m': 60,
    '3m': 180, 
    '5m': 300,
    '9m': 540,
    '10m': 600,
    '15m': 900,
    '30m': 1800,
    '1h': 3600,
    '2h': 7200,
    '4h': 14400,
    '8h': 28800,
    '9h': 32400,
    'D': 86400,
    '3D': 259200,
    'W': 604800
}

# Pandas resample frequency mapping
PANDAS_FREQ_MAP = {
    '1m': '1T',    # 1 minute
    '3m': '3T',    # 3 minutes
    '5m': '5T',    # 5 minutes
    '9m': '9T',    # 9 minutes
    '10m': '10T',  # 10 minutes
    '15m': '15T',  # 15 minutes
    '30m': '30T',  # 30 minutes
    '1h': '1H',    # 1 hour
    '2h': '2H',    # 2 hours
    '4h': '4H',    # 4 hours
    '8h': '8H',    # 8 hours
    '9h': '9H',    # 9 hours
    'D': '1D',     # 1 day
    '3D': '3D',    # 3 days
    'W': '1W'      # 1 week
}

# Timeframe display names
TIMEFRAME_DISPLAY = {
    '1m': '1 Minute',
    '3m': '3 Minutes',
    '5m': '5 Minutes',
    '9m': '9 Minutes',
    '10m': '10 Minutes',
    '15m': '15 Minutes',
    '30m': '30 Minutes',
    '1h': '1 Hour',
    '2h': '2 Hours',
    '4h': '4 Hours',
    '8h': '8 Hours',
    '9h': '9 Hours',
    'D': 'Daily',
    '3D': '3 Days',
    'W': 'Weekly'
}

# Timeframe groups for UI organization
TIMEFRAME_GROUPS = {
    'minutes': ['1m', '3m', '5m', '9m', '10m', '15m', '30m'],
    'hours': ['1h', '2h', '4h', '8h', '9h'],
    'days': ['D', '3D', 'W']
}


def get_timeframe_seconds(timeframe: str) -> int:
    """
    Get the number of seconds for a given timeframe.
    
    Args:
        timeframe: Timeframe string (e.g., '1m', '5m', '1h', 'D')
        
    Returns:
        Number of seconds
        
    Raises:
        ValueError: If timeframe is not supported
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}. "
                        f"Supported: {list(TIMEFRAME_MAP.keys())}")
    return TIMEFRAME_MAP[timeframe]


def get_pandas_freq(timeframe: str) -> str:
    """
    Get pandas resample frequency for a given timeframe.
    
    Args:
        timeframe: Timeframe string
        
    Returns:
        Pandas frequency string
        
    Raises:
        ValueError: If timeframe is not supported
    """
    if timeframe not in PANDAS_FREQ_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}. "
                        f"Supported: {list(PANDAS_FREQ_MAP.keys())}")
    return PANDAS_FREQ_MAP[timeframe]


def get_timeframe_display_name(timeframe: str) -> str:
    """
    Get human-readable display name for timeframe.
    
    Args:
        timeframe: Timeframe string
        
    Returns:
        Display name
    """
    return TIMEFRAME_DISPLAY.get(timeframe, timeframe)


def get_supported_timeframes() -> List[str]:
    """
    Get list of all supported timeframes.
    
    Returns:
        List of timeframe strings
    """
    return list(TIMEFRAME_MAP.keys())


def get_timeframes_by_group(group: str) -> List[str]:
    """
    Get timeframes for a specific group.
    
    Args:
        group: Group name ('minutes', 'hours', 'days')
        
    Returns:
        List of timeframes in the group
        
    Raises:
        ValueError: If group is not supported
    """
    if group not in TIMEFRAME_GROUPS:
        raise ValueError(f"Unsupported group: {group}. "
                        f"Supported: {list(TIMEFRAME_GROUPS.keys())}")
    return TIMEFRAME_GROUPS[group]


def aggregate_bars(df: pd.DataFrame, 
                   timeframe: str,
                   timestamp_col: str = 'timestamp',
                   open_col: str = 'open',
                   high_col: str = 'high',
                   low_col: str = 'low',
                   close_col: str = 'close',
                   volume_col: Optional[str] = None) -> pd.DataFrame:
    """
    Aggregate 5-second bars into the specified timeframe.
    
    Args:
        df: DataFrame with OHLC data
        timeframe: Target timeframe (e.g., '1m', '5m', '1h')
        timestamp_col: Column name for timestamps
        open_col: Column name for open prices
        high_col: Column name for high prices
        low_col: Column name for low prices
        close_col: Column name for close prices
        volume_col: Column name for volume (optional)
        
    Returns:
        Aggregated DataFrame with OHLC data
        
    Raises:
        ValueError: If timeframe is not supported
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    
    if df.empty:
        return df
    
    # Ensure timestamp is datetime and set as index
    df_work = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_work[timestamp_col]):
        df_work[timestamp_col] = pd.to_datetime(df_work[timestamp_col])
    
    df_work = df_work.set_index(timestamp_col)
    
    # Get pandas frequency
    freq = get_pandas_freq(timeframe)
    
    # Define aggregation rules
    agg_rules = {
        open_col: 'first',
        high_col: 'max',
        low_col: 'min',
        close_col: 'last'
    }
    
    if volume_col and volume_col in df_work.columns:
        agg_rules[volume_col] = 'sum'
    
    # Resample and aggregate
    aggregated = df_work.resample(freq).agg(agg_rules)
    
    # Remove any NaN rows (incomplete periods)
    aggregated = aggregated.dropna()
    
    # Reset index to get timestamp back as column
    aggregated = aggregated.reset_index()
    
    return aggregated


def get_aggregation_interval(timeframe: str) -> int:
    """
    Get the number of 5-second bars needed for one period of the timeframe.
    
    Args:
        timeframe: Timeframe string
        
    Returns:
        Number of 5-second bars
        
    Raises:
        ValueError: If timeframe is not supported
    """
    timeframe_seconds = get_timeframe_seconds(timeframe)
    return timeframe_seconds // 5  # 5-second bars


def is_timeframe_complete(current_time: datetime, 
                         timeframe: str,
                         market_open: bool = True) -> bool:
    """
    Check if the current timeframe period is complete.
    
    Args:
        current_time: Current timestamp
        timeframe: Timeframe to check
        market_open: Whether market is currently open
        
    Returns:
        True if timeframe period is complete
    """
    if not market_open:
        return False
    
    timeframe_seconds = get_timeframe_seconds(timeframe)
    
    # For intraday timeframes, check if we're at the boundary
    if timeframe in ['1m', '3m', '5m', '9m', '10m', '15m', '30m']:
        # Check if current minute is divisible by timeframe
        minute = current_time.minute
        if timeframe == '1m':
            return True  # Always complete for 1-minute
        elif timeframe == '3m':
            return minute % 3 == 0
        elif timeframe == '5m':
            return minute % 5 == 0
        elif timeframe == '9m':
            return minute % 9 == 0
        elif timeframe == '10m':
            return minute % 10 == 0
        elif timeframe == '15m':
            return minute % 15 == 0
        elif timeframe == '30m':
            return minute % 30 == 0
    
    elif timeframe in ['1h', '2h', '4h', '8h', '9h']:
        # For hourly timeframes, check hour boundaries
        hour = current_time.hour
        if timeframe == '1h':
            return current_time.minute == 0
        elif timeframe == '2h':
            return hour % 2 == 0 and current_time.minute == 0
        elif timeframe == '4h':
            return hour % 4 == 0 and current_time.minute == 0
        elif timeframe == '8h':
            return hour % 8 == 0 and current_time.minute == 0
        elif timeframe == '9h':
            return hour % 9 == 0 and current_time.minute == 0
    
    elif timeframe in ['D', '3D', 'W']:
        # For daily/weekly, check day boundaries
        if timeframe == 'D':
            return current_time.hour == 16 and current_time.minute == 0  # Market close
        elif timeframe == '3D':
            return (current_time.weekday() == 4 and  # Friday
                    current_time.hour == 16 and current_time.minute == 0)
        elif timeframe == 'W':
            return (current_time.weekday() == 4 and  # Friday
                    current_time.hour == 16 and current_time.minute == 0)
    
    return False


def get_next_timeframe_boundary(current_time: datetime, timeframe: str) -> datetime:
    """
    Get the next timeframe boundary timestamp.
    
    Args:
        current_time: Current timestamp
        timeframe: Timeframe string
        
    Returns:
        Next boundary timestamp
    """
    timeframe_seconds = get_timeframe_seconds(timeframe)
    
    # Calculate next boundary
    if timeframe in ['1m', '3m', '5m', '9m', '10m', '15m', '30m']:
        # Round up to next minute boundary
        if timeframe == '1m':
            return current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        elif timeframe == '3m':
            next_minute = ((current_time.minute // 3) + 1) * 3
            if next_minute >= 60:
                return (current_time.replace(minute=0, second=0, microsecond=0) + 
                        timedelta(hours=1))
            return current_time.replace(minute=next_minute, second=0, microsecond=0)
        # Similar logic for other minute timeframes...
    
    # Default fallback
    return current_time + timedelta(seconds=timeframe_seconds)
