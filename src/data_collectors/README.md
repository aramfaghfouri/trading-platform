# Data Collectors

This directory contains data collection modules for the trading platform, following the pattern from the ts-timeseries project.

## Structure

```
src/data_collectors/
├── common/                   # Shared, broker-agnostic utilities (e.g. Timescale storage)
├── ibkr/                     # Interactive Brokers collectors
│   ├── client.py             # Async data client over ib_insync
│   ├── collection_manager.py # Historical job orchestration
│   ├── data_storage.py       # IBKR storage wrapper
│   ├── historical.py         # Historical collector facade
│   └── main.py               # CLI entry point for IBKR collection
├── polygon/                  # Polygon.io collectors
│   ├── collection_manager.py # High-level orchestration
│   ├── data_storage.py       # Polygon-specific storage interface
│   ├── enhanced_collector.py # Feature-rich collector
│   ├── main.py               # CLI entry point for polygon collection
│   └── legacy/               # Archived scripts (collect_data.py, utils, etc.)
└── requirements.txt         # Collector-specific dependencies
```

## Quick Start

1. **Install packages:**
   ```bash
   python install_packages.py
   ```

2. **Set up configuration:**
   ```bash
   cp env.example .env
   # Edit .env with your POLYGON_API_KEY
   ```

3. **Configure tickers in project-setup.toml:**
   ```toml
   [data_collection]
   tickers = ["AAPL", "GOOGL", "MSFT", "TSLA"]
   start_date = "2024-12-01"
   end_date = "2024-12-31"
   ```

4. **Run data collection:**
   ```bash
   # Polygon historical (uses configuration-driven manager)
   python -m data_collectors.polygon.main collect

   # IBKR historical (via manage_tp.sh)
   ./manage_tp.sh --collect-hitorical-data --ibkr
   ```

## Features

- **Configuration-driven**: Reads from .env and project-setup.toml
- **Rate limiting**: Respects API limits with configurable delays
- **Data compression**: Uses LZ4 compression for efficient storage
- **Technical analysis**: Includes Heikin Ashi, peak detection, and pattern recognition
- **Multiple formats**: Exports to CSV, JSON, and generates plots
- **Logging**: Comprehensive logging with timestamps
- **Error handling**: Robust error handling and recovery

## Configuration

### Environment Variables (.env)
- `POLYGON_API_KEY`: Your Polygon.io API key
- `DATA_DIRECTORY`: Where to store collected data
- `RATE_LIMIT_DELAY`: Delay between API requests (seconds)

### Project Setup (project-setup.toml)
- `tickers`: List of ticker symbols to collect
- `start_date`/`end_date`: Date range for data collection
- `time_interval`: Data granularity (minute, hour, day)
- Analysis and output settings

## Usage Examples

### Basic Data Collection
```python
from data_collectors.polygon.launch import PolygonDataCollector

collector = PolygonDataCollector()
df = collector.run()
```

### Custom Configuration
```python
from data_collectors.config_reader import ConfigReader

config = ConfigReader()
tickers = config.get_tickers()
api_config = config.get_api_config()
```

## Data Output

The collector generates:
- **Raw data**: Compressed pickle files with OHLCV data
- **Processed data**: CSV/JSON with technical indicators
- **Analysis plots**: Matplotlib charts showing patterns
- **Logs**: Detailed execution logs

## API Rate Limits

The collector respects Polygon.io rate limits:
- Default: 13-second delay between requests
- Configurable via `RATE_LIMIT_DELAY` environment variable
- Automatic retry on rate limit errors

## Troubleshooting

1. **API Key Issues**: Ensure POLYGON_API_KEY is set in .env
2. **No Data**: Check if markets are open for the specified date range
3. **Rate Limits**: Increase RATE_LIMIT_DELAY if getting 429 errors
4. **Memory Issues**: Reduce chunk_size in configuration for large datasets
