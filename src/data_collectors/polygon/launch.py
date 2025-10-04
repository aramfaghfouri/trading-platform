"""
Polygon Data Collector Launch Script
Based on the ts-timeseries launch.py pattern
"""

import time
import os
import sys
from pathlib import Path
from tqdm import tqdm
import pandas as pd
import plotly.graph_objects as go
import matplotlib.pyplot as plt

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from data_collectors.config_reader import ConfigReader
from data_collectors.polygon.utils import (
    create_logger,
    segment_same_week_days,
    find_minmax_ohlc,
    get_aggs_for_symbol_and_date,
    read_lz4_files,
    restore_list_from_file,
    agg_to_list,
    get_date_info,
    plot_extrema,
    find_hook,
    calculate_heikin_ashi
)

class PolygonDataCollector:
    """Main data collector class following the ts-timeseries pattern"""
    
    def __init__(self):
        self.config = ConfigReader()
        self.logger = create_logger("polygon-data-collector")
        
        # Validate configuration
        if not self.config.validate_config():
            raise ValueError("Invalid configuration. Please check .env and project-setup.toml files.")
        
        # Get configuration
        self.api_config = self.config.get_api_config()
        self.time_config = self.config.get_time_config()
        self.storage_config = self.config.get_storage_config()
        self.analysis_config = self.config.get_analysis_config()
        self.output_config = self.config.get_output_config()
        
        # Create directories
        self._create_directories()
        
        # Print configuration summary
        self.config.print_config_summary()
    
    def _create_directories(self):
        """Create necessary directories"""
        data_dir = Path(self.storage_config['data_directory'])
        logs_dir = Path(self.storage_config['logs_directory'])
        
        data_dir.mkdir(exist_ok=True)
        logs_dir.mkdir(exist_ok=True)
        
        self.logger.info(f"Created directories: {data_dir}, {logs_dir}")
    
    def collect_data(self):
        """Main data collection method"""
        # Get tickers and time configuration
        symbols = self.config.get_tickers()
        time_interval = self.time_config['time_interval']
        start = self.time_config['start_date']
        end = self.time_config['end_date']
        
        self.logger.info(f"Starting data collection for {len(symbols)} symbols")
        self.logger.info(f"Time range: {start} to {end}")
        self.logger.info(f"Time interval: {time_interval}")
        self.logger.info(f"Symbols: {symbols}")
        
        # Generate weekday segments
        weekday_segments = segment_same_week_days(start, end)
        self.logger.info(f"Generated {len(weekday_segments)} weekday segments")
        
        # Generate symbol-date pairs
        symbol_date_pairs = [(symbol, date) for symbol in symbols for date in weekday_segments]
        self.logger.info(f"Total data collection tasks: {len(symbol_date_pairs)}")
        
        # Collect data with progress bar
        start_time = time.time()
        for symbol_date_pair in tqdm(symbol_date_pairs, desc="Collecting data"):
            try:
                get_aggs_for_symbol_and_date(
                    symbol_date_pair, 
                    time_interval=time_interval,
                    api_key=self.api_config['api_key'],
                    data_directory=self.storage_config['data_directory'],
                    enable_compression=self.storage_config['enable_compression'],
                    compression_format=self.storage_config['compression_format']
                )
                time.sleep(self.api_config['rate_limit_delay'])
            except Exception as e:
                self.logger.error(f"Error collecting data for {symbol_date_pair}: {e}")
                continue
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        self.logger.info(f"Data collection completed in {elapsed_time:.2f} seconds")
        
        return elapsed_time
    
    def process_data(self):
        """Process collected data"""
        self.logger.info("Starting data processing")
        
        # Read collected files
        file_list = read_lz4_files(self.storage_config['data_directory'])
        self.logger.info(f"Found {len(file_list)} data files")
        
        # Process files and create DataFrame
        data_list = []
        for filename in tqdm(file_list, desc="Processing files"):
            try:
                file_path = os.path.join(self.storage_config['data_directory'], filename)
                ticker = filename.split("-")[0]
                aggs = restore_list_from_file(file_path)
                
                for agg in aggs:
                    data_list.append(agg_to_list(agg, ticker, self.analysis_config['timezone']))
            except Exception as e:
                self.logger.error(f"Error processing file {filename}: {e}")
                continue
        
        # Create DataFrame
        columns = ["ticker", "timestamp", "unix_t", "open", "high", "low", "close", "volume", "vwap", "transactions", "otc"]
        df = pd.DataFrame(data=data_list, columns=columns)
        df.drop_duplicates(inplace=True)
        df = df.sort_values(by=["ticker", "unix_t"]).reset_index(drop=True)
        
        self.logger.info(f"Processed data shape: {df.shape}")
        
        # Add date information
        df_with_dates = get_date_info(df.copy(), 'timestamp')
        
        # Apply Heikin Ashi if enabled
        if self.analysis_config['enable_heikin_ashi']:
            df_with_dates = calculate_heikin_ashi(df_with_dates)
            self.logger.info("Applied Heikin Ashi transformation")
        
        return df_with_dates
    
    def analyze_data(self, df):
        """Analyze processed data"""
        if not self.analysis_config['enable_peak_detection']:
            return
        
        self.logger.info("Starting data analysis")
        
        # Get unique tickers
        tickers = df['ticker'].unique()
        
        for ticker in tickers[:5]:  # Analyze first 5 tickers
            self.logger.info(f"Analyzing {ticker}")
            
            # Filter data for ticker
            ticker_df = df[df['ticker'] == ticker].copy()
            
            if len(ticker_df) < 100:
                self.logger.warning(f"Not enough data for {ticker}, skipping analysis")
                continue
            
            # Get recent data for analysis
            n_df = len(ticker_df)
            i_lst = range(max(0, n_df - 5000), n_df)
            recent_data = ticker_df.iloc[i_lst]
            
            # Find peaks and troughs
            try:
                x_pt, i_peaks, i_troughs, peaks, troughs = find_minmax_ohlc(recent_data)
                
                # Plot extrema if matplotlib is enabled
                if self.output_config['enable_matplotlib_plots']:
                    plot_extrema(
                        recent_data, x_pt, i_peaks, peaks, i_troughs, troughs, 
                        self.time_config['time_interval'], index_type="time"
                    )
                
                # Find hook patterns
                if len(x_pt) > 100:
                    n0 = 0
                    search_range = 50
                    input_range = range(n0, min(n0 + 1000, len(x_pt)))
                    x_in = x_pt[input_range, :]
                    
                    res_hk = find_hook(x_in, n0, len(x_pt), search_range)
                    
                    self.logger.info(f"Found hook pattern for {ticker}: {len(res_hk['ind_highs'])} highs, {len(res_hk['ind_lows'])} lows")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {ticker}: {e}")
                continue
    
    def export_data(self, df):
        """Export processed data"""
        self.logger.info("Starting data export")
        
        # Export to CSV if enabled
        if self.output_config['enable_csv_export']:
            csv_filename = f"ticker_data_{self.time_config['start_date']}_{self.time_config['end_date']}.csv"
            csv_path = os.path.join(self.storage_config['data_directory'], csv_filename)
            df.to_csv(csv_path, index=False)
            self.logger.info(f"Exported data to {csv_path}")
        
        # Export to JSON if enabled
        if self.output_config['enable_json_export']:
            json_filename = f"ticker_data_{self.time_config['start_date']}_{self.time_config['end_date']}.json"
            json_path = os.path.join(self.storage_config['data_directory'], json_filename)
            df.to_json(json_path, orient='records', date_format='iso')
            self.logger.info(f"Exported data to {json_path}")
    
    def run(self):
        """Run the complete data collection and analysis pipeline"""
        try:
            # Collect data
            elapsed_time = self.collect_data()
            
            # Process data
            df = self.process_data()
            
            # Analyze data
            self.analyze_data(df)
            
            # Export data
            self.export_data(df)
            
            self.logger.info("Data collection pipeline completed successfully")
            return df
            
        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            raise

def main():
    """Main entry point"""
    try:
        collector = PolygonDataCollector()
        df = collector.run()
        print("Data collection completed successfully!")
        return df
    except Exception as e:
        print(f"Data collection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
