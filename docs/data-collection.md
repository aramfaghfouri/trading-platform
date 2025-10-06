# Data Collection Guide

This guide explains how to use the data collection system for gathering market data from Polygon.io and storing it in TimescaleDB.

## 🚀 Quick Start

### 1. Prerequisites

- Polygon.io API key
- TimescaleDB running (via Docker)
- Python environment with dependencies installed

### 2. Configuration

Set your API key in `.env`:
```bash
POLYGON_API_KEY=your_polygon_api_key_here
```

Configure data collection in `project-setup.toml`:
```toml
[data_collection]
time_interval = "minute"
start_date = "2024-10-05"
end_date = "2025-10-04"
tickers = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
rate_limit_delay = 13
```

### 3. Run Data Collection

```bash
# Collect data for all configured symbols
python scripts/collect_market_data.py
```

## 📊 Data Collection Features

### Supported Data Types

- **OHLCV Data**: Open, High, Low, Close, Volume
- **VWAP**: Volume Weighted Average Price
- **Transactions**: Number of transactions per bar
- **OTC**: Over-the-counter flag

### Time Intervals

- `minute` - 1-minute bars
- `day` - Daily bars
- `hour` - Hourly bars

### Data Quality Features

- **Price Validation**: Ensures OHLC relationships are correct
- **Volume Thresholds**: Filters out low-volume data
- **Outlier Detection**: Identifies statistical outliers
- **Duplicate Prevention**: Prevents duplicate data storage

## 🔧 Configuration Options

### Environment Variables

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=trading_platform
DB_USER=trading_user
DB_PASSWORD=trading_password

# Polygon.io API
POLYGON_API_KEY=your_api_key_here
POLYGON_BASE_URL=https://api.polygon.io
POLYGON_TIMEOUT=30
```

### YAML Configuration

Main configuration files in `config/`:

- `database.yaml` - TimescaleDB connection settings
- `polygon.yaml` - Polygon.io API configuration
- `ibkr.yaml` - Interactive Brokers settings
- `strategies.yaml` - Strategy definitions
- `trading.yaml` - Trading parameters

## 📈 Data Storage

### TimescaleDB Features

- **Hypertables**: Automatic time-series partitioning
- **Compression**: Data compression for storage efficiency
- **Continuous Aggregates**: Pre-computed 1m and 5m bars
- **Retention Policies**: Automatic data retention management

### Database Schema

```sql
-- Main OHLCV data table
CREATE TABLE ohlcv_data (
    symbol VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(10,4),
    high DECIMAL(10,4),
    low DECIMAL(10,4),
    close DECIMAL(10,4),
    volume BIGINT,
    vwap DECIMAL(10,4),
    transactions INTEGER,
    PRIMARY KEY (symbol, timestamp)
);
```

## 🛠️ Advanced Usage

### Programmatic Data Collection

```python
import asyncio
from src.data_collectors.polygon import collect_and_store_data_working_approach

# Collect data programmatically
await collect_and_store_data_working_approach()
```

### Custom Symbol Lists

```python
# Collect data for specific symbols
from src.data_collectors.polygon import collect_symbol_data

await collect_symbol_data('AAPL', '2024-10-01', '2024-10-02')
```

### Data Validation

```python
from src.data_collectors.polygon import PolygonDataValidator

validator = PolygonDataValidator()
is_valid, errors = validator.validate_bar_data(data)
```

## 📊 Monitoring Data Quality

### Check Data Summary

```sql
-- View data summary by symbol
SELECT 
    symbol, 
    COUNT(*) as records,
    MIN(timestamp) as earliest,
    MAX(timestamp) as latest,
    AVG(volume) as avg_volume
FROM ohlcv_data 
GROUP BY symbol 
ORDER BY records DESC;
```

### Validate Data Quality

```bash
# Run data quality validation
python scripts/validate_config.py
```

## 🚨 Troubleshooting

### Common Issues

1. **API Key Issues**
   - Ensure `POLYGON_API_KEY` is set in `.env`
   - Verify API key is valid and has sufficient credits

2. **Database Connection Issues**
   - Check TimescaleDB is running: `docker ps`
   - Verify connection settings in `config/database.yaml`

3. **Rate Limiting**
   - Adjust `rate_limit_delay` in `project-setup.toml`
   - Monitor API usage in Polygon.io dashboard

4. **Data Quality Issues**
   - Check validation logs for specific errors
   - Review outlier detection results

### Debug Mode

```bash
# Run with debug logging
LOG_LEVEL=DEBUG python scripts/collect_market_data.py
```

## 📚 API Reference

### Main Collection Function

```python
async def collect_and_store_data_working_approach():
    """
    Main data collection function that:
    1. Reads configuration from project-setup.toml
    2. Collects data for all configured symbols
    3. Stores data in TimescaleDB
    4. Provides progress updates
    """
```

### Data Storage Interface

```python
class PolygonDataStorage:
    async def store_ohlcv_data(symbol, data, timeframe)
    async def get_latest_data(symbol, limit)
    async def get_data_range(symbol, start_date, end_date)
```

## 🔄 Data Collection Workflow

1. **Configuration Loading**: Read settings from YAML and TOML files
2. **API Authentication**: Authenticate with Polygon.io API
3. **Data Collection**: Fetch historical data for each symbol
4. **Data Validation**: Validate data quality and detect outliers
5. **Data Storage**: Store validated data in TimescaleDB
6. **Progress Tracking**: Log collection progress and statistics

## 📈 Performance Optimization

### Rate Limiting

- Default: 13 seconds between requests
- Configurable via `rate_limit_delay`
- Respects Polygon.io API limits

### Batch Processing

- Processes symbols in weekday segments
- Avoids weekend data collection
- Optimizes API usage

### Storage Optimization

- Uses TimescaleDB compression
- Implements duplicate prevention
- Creates efficient indexes

---

For more information, see the [Database Schema](database-schema.md) documentation.
