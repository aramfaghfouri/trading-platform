"""
Utility functions for Polygon data collection
Based on the ts-timeseries utils.py pattern
"""

import pandas as pd
import numpy as np
import os
import logging
import pickle
import lz4.frame
import sys
from scipy.signal import find_peaks
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pytz
from polygon import BaseClient as RESTClient

def create_logger(name):
    """
    Creates a logger with a file handler saving to a log file based on current time.
    Based on the ts-timeseries pattern.
    """
    # Create logs folder if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Get current time in ISO format
    now = datetime.now().isoformat()

    # Create log file name with timestamp
    log_filename = os.path.join(log_dir, f"log_{now}.log")

    # Configure logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Create file handler and set formatter
    file_handler = logging.FileHandler(log_filename)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)

    # Add file handler to logger
    logger.addHandler(file_handler)

    return logger

def days_until_closed(row):
    """Calculate days until next closed business day"""
    closed_days = [5, 6]  # Saturday and Sunday are closed (indices 5 and 6)
    weekday = row['weekday']
    # If it's friday (4) and after working hours, consider following monday (0) as closed
    if weekday == 4 and row['datetime'].hour >= 17:
        return (closed_days[0] - weekday) % 7
    # If current day is closed, return 0 days until closed
    if weekday in closed_days:
        return 0
    # Otherwise, calculate days until next closed day 
    return (closed_days[0] - weekday) % 7

def days_since_closed(row):
    """Calculate days since last closed business day"""
    closed_days = [5, 6]  # Saturday and Sunday are closed (indices 5 and 6)
    weekday = row['weekday']
    # If it's monday (0) and before working hours, consider previous friday (3) as closed
    if weekday == 0 and row['datetime'].hour < 9:
        return (weekday - 3) % 7
    # If current day is closed, return 0 days since closed
    if weekday in closed_days:
        return 0
    # Otherwise, calculate days since last closed day 
    return (weekday - closed_days[0]) % 7

def get_date_info(df, date_col):
    """
    Add date information columns to DataFrame.
    Based on the ts-timeseries pattern.
    """
    # Parse dates and create new datetime objects
    df['datetime'] = pd.to_datetime(df[date_col])
    
    # Extract year, month, week, day, weekday
    df['year'] = df['datetime'].dt.year
    df['month'] = df['datetime'].dt.month
    df['week'] = df['datetime'].dt.isocalendar().week
    df['day'] = df['datetime'].dt.day
    df['weekday'] = df['datetime'].dt.weekday
    df['hour'] = df['datetime'].dt.hour
    
    # Define closed business days (weekend)
    closed_days = [5, 6]  # Saturday and Sunday are closed (indices 5 and 6)
    df['days_since_closed'] = df.apply(days_since_closed, axis=1)

    # Calculate days until next closed business day
    df['days_until_closed'] = df.apply(days_until_closed, axis=1)
    df["date_"] = df[date_col].apply(lambda row: row[:10])
    return df

def segment_same_week_days(start_date, end_date):
    """Generate weekday segments between start and end dates"""
    # Convert string dates to datetime objects
    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date = datetime.strptime(end_date, "%Y-%m-%d")

    # Function to find the next Friday from a given date
    def next_friday(date):
        days_ahead = 4 - date.weekday()  # Friday is 4
        if days_ahead < 0:  # Target day already passed this week
            days_ahead += 7
        return date + timedelta(days=days_ahead)

    # Initialize variables
    segments = []
    current_date = start_date

    # Generate segments within the same week
    while current_date <= end_date:
        if current_date.weekday() > 4:  # If the current date is Saturday or Sunday
            current_date += timedelta(days=(7 - current_date.weekday()))  # Skip to next Monday
        if current_date > end_date:
            break
        segment_start = current_date
        segment_end = min(next_friday(current_date), end_date)
        segments.append((segment_start.strftime("%Y-%m-%d"), segment_end.strftime("%Y-%m-%d")))
        current_date = segment_end + timedelta(days=1)  # Move to the next day after segment end

    return segments

def get_aggs_for_symbol_and_date(symbol_date_pair, time_interval="minute", api_key=None, 
                                data_directory="data_results", enable_compression=True, 
                                compression_format="lz4"):
    """Retrieve aggregates for a given symbol and date"""
    symbol, date = symbol_date_pair
    aggs = []
    
    if not api_key:
        raise ValueError("API key is required")
    
    client = RESTClient(api_key=api_key, trace=False)

    try:
        for a in client.list_aggs(
            symbol,
            1,
            time_interval,
            date[0],
            date[1],
            limit=50000,
        ):
            aggs.append(a)
    except Exception as e:
        print(f"Error fetching data for {symbol} on {date}: {e}")
        return

    # Create data directory if it doesn't exist
    os.makedirs(data_directory, exist_ok=True)

    # Save data
    if enable_compression and compression_format == "lz4":
        filename = f"{data_directory}/{symbol}-aggs-{date[0]}_{date[1]}.pickle.lz4"
        with open(filename, "wb") as file:
            try:
                compressed_data = lz4.frame.compress(pickle.dumps(aggs))
                file.write(compressed_data)
            except TypeError as e:
                print(f"Serialization Error: {e}")
    else:
        filename = f"{data_directory}/{symbol}-aggs-{date[0]}_{date[1]}.pickle"
        with open(filename, "wb") as file:
            pickle.dump(aggs, file)

def restore_list_from_file(file_path):
    """Restore list from compressed file"""
    with open(file_path, 'rb') as file:
        if file_path.endswith('.lz4'):
            compressed_data = file.read()
            decompressed_data = lz4.frame.decompress(compressed_data)
            aggs = pickle.loads(decompressed_data)
        else:
            aggs = pickle.load(file)
    
    return aggs

def unix_to_timezone_no_offset(unix_time_ms, timezone_str):
    """Convert Unix timestamp to timezone without offset"""
    unix_time_s = unix_time_ms / 1000
    utc_datetime = datetime.fromtimestamp(unix_time_s)

    # Define timezone
    x_timezone = pytz.timezone(timezone_str)
    
    # Convert UTC datetime to target timezone
    x_datetime = utc_datetime.astimezone(x_timezone)
    
    # Format the datetime string
    formatted_x_time = x_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    return formatted_x_time

def read_lz4_files(directory):
    """Read all lz4 files from directory"""
    files = os.listdir(directory)
    lz4_files = [file for file in files if file.endswith('.lz4')]
    return lz4_files

def agg_to_list(agg, ticker, timezone_str='America/New_York'):
    """Convert aggregate to list format"""
    x_tmp = [ticker, 
             unix_to_timezone_no_offset(agg.timestamp, timezone_str=timezone_str), 
             agg.timestamp, 
             agg.open, 
             agg.high, 
             agg.low, 
             agg.close, 
             agg.volume,
             agg.vwap, 
             agg.transactions, 
             agg.otc]
    return x_tmp

def find_minmax_ohlc(x):
    """Find peaks and troughs in OHLC data"""
    # Find peaks in the inverted time series, which correspond to troughs (local minima) in the original
    i_peaks, _ = find_peaks(x["high"])
    i_troughs, _ = find_peaks(-x["low"])
    
    # Extract the local minima values
    peaks = x["high"].iloc[i_peaks]
    troughs = x["low"].iloc[i_troughs]

    n_i_peaks = len(i_peaks)
    n_i_troughs = len(i_troughs)
    combined = np.concatenate((
        np.column_stack((i_peaks, peaks, np.ones(n_i_peaks))),
        np.column_stack((i_troughs, troughs, -np.ones(n_i_troughs)))
    ))
    
    # Sort the combined array by the first column (indices)
    x_pt = combined[combined[:, 0].argsort()]
    return x_pt, i_peaks, i_troughs, peaks, troughs

def plot_extrema(df, x_pt, i_peaks, peaks, i_troughs, troughs, interval, index_type="index"):
    """Plot extrema on time series"""
    plt.figure(figsize=(10, 6))
    if index_type == "index":
        ind_x = x_pt[:,0]
        ind_peaks = i_peaks
        ind_troughs = i_troughs
        rotation = 0
    elif index_type == "time":
        ind_x = df["timestamp"].iloc[x_pt[:,0]]
        ind_peaks = df["timestamp"].iloc[i_peaks]
        ind_troughs = df["timestamp"].iloc[i_troughs]
        rotation = 90
    else:
        print(f"The index_type is {index_type}, which is not acceptable.")
        return

    plt.plot(ind_x, x_pt[:,1], label='Time Series', linewidth=1, color='blue', linestyle='--')
    plt.xticks(rotation=rotation) 
    plt.scatter(ind_peaks, peaks, color='r', marker='o', label='Local Maxima', s=10)
    plt.scatter(ind_troughs, troughs, color='g', marker='o', label='Local Minima', s=10)
    
    plt.title(f"Local Maxima and Minima in Time Series [{interval}]")
    plt.xlabel('Time')
    plt.ylabel('Value')
    plt.legend()
    plt.grid(True, linewidth=0.5)
    plt.show()
    plt.close()

def find_h(x_in, ptr, low_thr, n_df, search_range=50):
    """Find high point in data"""
    h1 = [None, None]
    ptr_old = ptr
    while ptr < n_df and ptr < (ptr_old + search_range):
        if x_in[ptr,2] and x_in[ptr,1] > low_thr:
            h1 = [ptr, x_in[ptr,1]]
            break
        else:
            ptr = ptr + 1
    return h1

def find_l(x_in, ptr, high_thr, n_df, search_range=50):
    """Find low point in data"""
    l1 = [None, None]
    ptr_old = ptr
    while ptr < n_df and ptr < (ptr_old + search_range):
        if -x_in[ptr,2] and x_in[ptr,1] < high_thr:
            l1 = [ptr, x_in[ptr,1]]
            break
        else:
            ptr = ptr + 1
    return l1

def find_hook(x_in, n0, n_df, search_range):
    """Find hook pattern in data"""
    ptr = n0 + 1
    low_thr = x_in[n0,1]
    h1 = find_h(x_in, ptr, low_thr, n_df, search_range=search_range)

    ptr = h1[0]
    high_thr = h1[1]
    l1 = find_l(x_in, ptr, high_thr, n_df, search_range=search_range)

    ptr = l1[0] + 1
    low_thr = h1[1]
    h2 = find_h(x_in, ptr, low_thr, n_df, search_range=search_range)

    ptr = h2[0]
    high_thr = l1[1]
    l2 = find_l(x_in, ptr, high_thr, n_df, search_range=search_range)

    ptr = l2[0] + 1
    low_thr = h2[1]
    h3 = find_h(x_in, ptr, low_thr, n_df, search_range=search_range)

    ptr = h3[0]
    high_thr = l2[1]
    l3 = find_l(x_in, ptr, high_thr, n_df, search_range=search_range)

    ind_lows = [l1[0], l2[0], l3[0]]
    lows = [l1[1], l2[1], l3[1]]

    ind_highs = [h1[0], h2[0], h3[0]]
    highs = [h1[1], h2[1], h3[1]]

    ind_range = range(n0, l3[0]+1)

    out = {
        "ind_lows": ind_lows,
        "ind_highs": ind_highs,
        "lows": lows,
        "highs": highs,
        "ind_range": ind_range
    }
    return out

def calculate_heikin_ashi(df):
    """Calculate Heikin Ashi values"""
    # Pre-calculate the Heikin Ashi close values
    ha_close = (df['open'] + df['close'] + df['high'] + df['low']) / 4

    # Initialize the Heikin Ashi open values
    ha_open = ha_close.copy()
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2

    # Vectorized calculation for the rest of the Heikin Ashi open values
    ha_open[1:] = (ha_open.shift(1) + ha_close.shift(1))[1:] / 2

    # Calculate Heikin Ashi high and low values
    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

    # Replace original columns with Heikin Ashi values
    df['open'] = ha_open
    df['high'] = ha_high
    df['low'] = ha_low
    df['close'] = ha_close

    return df
