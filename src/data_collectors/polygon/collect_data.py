#!/usr/bin/env python3
"""
Working data collection approach based on the successful ts-timeseries code
"""

import sys
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from tqdm import tqdm
import pandas as pd
import toml

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from polygon import StocksClient
from core.config_loader import get_polygon_config
from data_collectors.polygon.data_storage import PolygonDataStorage
from loguru import logger


def segment_same_week_days(start_date, end_date):
    """Segment dates by weekdays (avoid weekends) - from working code"""
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


def get_aggs_for_symbol_and_date(symbol_date_pair, time_interval="minute", api_key=None):
    """Retrieve aggs for a given symbol and date - based on working code"""
    symbol, date = symbol_date_pair
    aggs = []
    
    # Use StocksClient (updated for current polygon package)
    client = StocksClient(api_key=api_key)
    
    try:
        # Use get_aggregate_bars with explicit params (works with current client)
        # timespan expects values like "minute", "hour", "day", etc.
        response = client.get_aggregate_bars(
            symbol=symbol,
            from_date=date[0],
            to_date=date[1],
            adjusted=True,
            sort="asc",
            limit=50000,
            multiplier=1,
            timespan=time_interval,
        )

        # Extract results from response dict
        if isinstance(response, dict):
            aggs.extend(response.get("results", []) )
        else:
            # Fallback for client objects with attributes
            if hasattr(response, "results") and response.results:
                aggs.extend(response.results)
            
        logger.info(f"Collected {len(aggs)} bars for {symbol} from {date[0]} to {date[1]}")
        return aggs
        
    except Exception as e:
        logger.error(f"Failed to collect data for {symbol} on {date}: {e}")
        return []


def agg_to_list(agg, ticker):
    """Convert agg object to list format - from working code"""
    if isinstance(agg, dict):
        # Polygon REST returns dict keys: t, o, h, l, c, v, vw, n
        ts_ms = int(agg.get('t'))
        return [
            ticker,
            datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%dT%H:%M:%S'),
            ts_ms,
            agg.get('o'),
            agg.get('h'),
            agg.get('l'),
            agg.get('c'),
            agg.get('v'),
            agg.get('vw'),
            agg.get('n'),
            agg.get('otc', False),
        ]
    else:
        return [
            ticker,
            datetime.fromtimestamp(agg.timestamp / 1000).strftime('%Y-%m-%dT%H:%M:%S'),
            agg.timestamp,
            agg.open,
            agg.high,
            agg.low,
            agg.close,
            agg.volume,
            getattr(agg, 'vwap', None),
            getattr(agg, 'transactions', None),
            getattr(agg, 'otc', False)  # Some aggs might not have otc field
        ]


def load_project_config():
    """Load configuration from project-setup.toml"""
    config_path = Path(__file__).parent.parent.parent.parent / "project-setup.toml"
    with open(config_path, 'r') as f:
        return toml.load(f)

async def collect_and_store_data_working_approach():
    """Collect data using the working approach and store in TimescaleDB"""
    print("🚀 Collecting Data Using Working Approach")
    print("=" * 50)
    
    # Load configuration from project-setup.toml
    project_config = load_project_config()
    data_config = project_config['data_collection']
    
    # Configuration
    polygon_config = get_polygon_config()
    api_key = polygon_config.api.api_key
    
    # Parameters from project-setup.toml
    time_interval = data_config['time_interval']
    start = data_config['start_date']
    end = data_config['end_date']
    symbols = data_config['tickers']
    rate_limit_delay = data_config.get('rate_limit_delay', 13)
    
    print(f"📅 Date range: {start} to {end}")
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"⏱️  Time interval: {time_interval}")
    
    # Generate weekday segments (avoid weekends)
    weekday_segments = segment_same_week_days(start, end)
    print(f"📊 Weekday segments: {len(weekday_segments)}")
    
    # Generate symbol-date pairs
    symbol_date_pairs = [(symbol, date) for symbol in symbols for date in weekday_segments]
    print(f"📋 Total symbol-date pairs: {len(symbol_date_pairs)}")
    
    # Collect data
    all_data = []
    successful_collections = 0
    
    print(f"\n🔄 Starting data collection...")
    ts = time.time()
    
    for symbol_date_pair in tqdm(symbol_date_pairs, desc="Collecting data"):
        symbol, date = symbol_date_pair
        
        # Collect data using working approach
        aggs = get_aggs_for_symbol_and_date(symbol_date_pair, time_interval, api_key)
        
        if aggs:
            # Convert to list format
            for agg in aggs:
                data_row = agg_to_list(agg, symbol)
                all_data.append(data_row)
            successful_collections += 1
        
        # Rate limiting from project-setup.toml
        time.sleep(rate_limit_delay)
    
    te = time.time()
    elapsed_time = te - ts
    
    print(f"\n📊 Collection Results:")
    print(f"   Total pairs processed: {len(symbol_date_pairs)}")
    print(f"   Successful collections: {successful_collections}")
    print(f"   Total data points: {len(all_data)}")
    print(f"   Elapsed time: {elapsed_time:.2f} seconds")
    
    if all_data:
        # Convert to DataFrame
        cols = ["ticker", "timestamp", "unix_t", "open", "high", "low", "close", "volume", "vwap", "transactions", "otc"]
        df = pd.DataFrame(data=all_data, columns=cols)
        df.drop_duplicates(inplace=True)
        df = df.sort_values(by=["ticker", "unix_t"]).reset_index(drop=True)
        
        print(f"   DataFrame shape: {df.shape}")
        print(f"   Unique tickers: {df['ticker'].nunique()}")
        print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        # Store in TimescaleDB
        print(f"\n💾 Storing data in TimescaleDB...")
        await store_dataframe_in_timescaledb(df)
        
        return True
    else:
        print("❌ No data collected")
        return False


async def store_dataframe_in_timescaledb(df):
    """Store DataFrame in TimescaleDB"""
    try:
        async with PolygonDataStorage() as storage:
            # Convert DataFrame to the format expected by storage
            for ticker in df['ticker'].unique():
                ticker_data = df[df['ticker'] == ticker]
                
                # Convert to the format expected by storage
                bars = []
                for _, row in ticker_data.iterrows():
                    bar = {
                        't': int(row['unix_t']),  # timestamp in milliseconds
                        'o': float(row['open']),
                        'h': float(row['high']),
                        'l': float(row['low']),
                        'c': float(row['close']),
                        'v': int(row['volume']),
                        'vw': float(row['vwap']) if pd.notna(row['vwap']) else None,
                        'n': int(row['transactions']) if pd.notna(row['transactions']) else None
                    }
                    bars.append(bar)
                
                # Store the data
                result = await storage.store_ohlcv_data(ticker, bars)
                if result.success:
                    print(f"   ✅ Stored {result.records_inserted} records for {ticker}")
                else:
                    print(f"   ❌ Failed to store data for {ticker}: {result.error}")
                    
    except Exception as e:
        print(f"❌ Failed to store data in TimescaleDB: {e}")


async def main():
    """Main function"""
    success = await collect_and_store_data_working_approach()
    
    if success:
        print(f"\n🎉 Data collection completed successfully!")
        print(f"   Check TimescaleDB for the collected data")
    else:
        print(f"\n❌ Data collection failed!")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
