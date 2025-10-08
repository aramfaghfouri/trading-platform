# Trading Platform

A comprehensive trading platform built with VectorBT, Polygon.io, and Interactive Brokers integration, designed for algorithmic trading, backtesting, and live execution.

## 🚀 Features

- **VectorBT Integration**: Advanced backtesting, portfolio optimization, and strategy development
- **Polygon.io Data Collection**: Historical and real-time market data with minute-level precision
- **Interactive Brokers Integration**: Live trading execution and portfolio management
- **TimescaleDB Storage**: High-performance time-series database for market data
- **Flexible Configuration**: YAML-based configuration with environment variable overrides
- **Data Quality Validation**: Built-in data validation and outlier detection
- **Rate Limiting**: Intelligent API rate limiting and error handling
- **Docker Support**: Containerized deployment and development
- **Modular Architecture**: Clean separation of concerns with organized code structure

## 🏗️ Architecture

### Core Components

- **Data Collection**: Polygon.io integration for historical and real-time market data
- **Data Storage**: TimescaleDB for high-performance time-series data storage
- **Strategy Framework**: VectorBT-based strategy development and backtesting
- **Trading Execution**: Interactive Brokers integration for live trading
- **Configuration Management**: YAML-based configuration with Pydantic validation
- **Data Quality**: Built-in validation, outlier detection, and quality checks

### Technology Stack

- **Backend**: Python 3.11+ with asyncio
- **Database**: TimescaleDB (time-series data with compression and continuous aggregates)
- **Data Source**: Polygon.io API for market data
- **Trading**: Interactive Brokers TWS API via ib_insync
- **Strategy Engine**: VectorBT for backtesting and portfolio optimization
- **Configuration**: Pydantic models with YAML configuration files
- **Deployment**: Docker & Docker Compose

## 📋 Project Status

See [README-Track.md](README-Track.md) for detailed progress tracking and implementation phases.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Polygon.io API key
- Interactive Brokers account (paper trading recommended)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd trading-platform
   ```

2. **Set up environment**
   ```bash
   # Create virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   # Copy environment template
   cp env.example .env
   
   # Edit .env with your API keys
   nano .env
   ```

4. **Start TimescaleDB (uses dynamic port from .env)**
   ```bash
   # Copy env template and set Timescale vars
   cp env.example .env
   # In .env, ensure:
   # TIMESCALEDB_HOST=localhost
   # TIMESCALEDB_PORT=6432
   # DATABASE_URL=postgresql://trading_user:trading_password@${TIMESCALEDB_HOST}:${TIMESCALEDB_PORT}/trading_platform

   # Start DB via management script (recommended)
   ./manage_tp.sh --start-database
   ```

5. **Configure data collection**
   ```bash
   # Edit project configuration
   nano project-setup.toml
   ```

### Running the System

#### Quick Start with Management Script

The easiest way to get started is using the management script:

```bash
# 1. Delete all databases and start fresh
./manage_tp.sh --delete-databases

# 2. Start TimescaleDB
./manage_tp.sh --start-database

# 3. Collect data for all configured tickers
./manage_tp.sh --collect-data
```

#### Manual Commands

1. **Collect market data**
   ```bash
   # Collect historical data for configured symbols
   python scripts/collect_market_data.py
   ```

2. **Validate configuration**
   ```bash
   # Test configuration and database connection
   python scripts/validate_config.py
   ```

3. **Access database**
   ```bash
   # Connect to TimescaleDB container
   docker exec -it trading_timescaledb psql -U trading_user -d trading_platform
   ```

4. **View collected data**
   ```sql
   -- Check data summary
   SELECT symbol, COUNT(*) as records, 
          MIN(timestamp) as earliest, 
          MAX(timestamp) as latest 
   FROM ohlcv_data 
   GROUP BY symbol 
   ORDER BY records DESC;
   ```

#### Management Script Commands

The `manage_tp.sh` script provides convenient commands:

- `--delete-databases` - Delete all databases and containers
- `--start-database` - Start TimescaleDB
- `--collect-data` - Collect data for all configured tickers
- `--validate-config` - Validate configuration files
- `--status` - Show system status
- `--help` - Show help message

#### IB Paper Trading Quick Checks

```bash
# 0) Ensure TWS/IB Gateway (paper) is running, API enabled (7497)

# 1) Env safety: refuse orders unless explicitly confirmed
export LIVE_TRADING_CONFIRM=false

# 2) Connectivity test
python -m src.cli.ib connect

# 3) Account summary / positions
python -m src.cli.ib summary
python -m src.cli.ib positions

# 4) Real-time ticks for 60s
python -m src.cli.ib subscribe --symbol AAPL --seconds 60

# 5) Paper order (requires LIVE_TRADING_CONFIRM=true)
export LIVE_TRADING_CONFIRM=true
python -m src.cli.ib place-order --symbol AAPL --action BUY --qty 1 --limit 1.00
```

### IBKR Gap-Aware Collection Enhancements

- RTH-aware trading sessions; minute data now limited to regular trading hours when `useRTH=true`
- Gap detection trims existing intervals to avoid duplicates and focus on missing bars only
- `--heartbeat` flag prints progress messages during long database/API tasks (default 15s)
- Heartbeat also applies to chunk collection (`IBKR chunk N/M for <symbol>`)
- `--gaps-limit` continues to control how many gaps are printed per symbol
- Automatic skip of symbols with no gaps in the trading session window
- `manage_tp.sh --collect-data --ibkr` now runs Python unbuffered to stream live updates
- Conda activation in `manage_tp.sh` avoids re-activating `env-trading` if already active

## 📚 Data Model and Table Naming

- Source-prefixed table convention: `<source>_<data_type>_<symbol>_<timeframe>`
  - Examples: `polygon_ohlcv_aapl_1m`, `ibkr_ohlcv_msft_1m`
- Registry: `ticker_registry.table_name` stores the full source-prefixed name.
- New tables are created via helper functions in the DB init:
  - `create_source_ticker_table(source, symbol, data_type, timeframe)`
  - `get_source_ticker_table_name(source, symbol, data_type, timeframe)`

### Rename Existing Tables

We provide a migration script to rename existing non-prefixed OHLCV tables to `polygon_...` without deleting data:

```bash
# DB must be running
./manage_tp.sh --start-database

# Run rename script (in-place, idempotent)
docker cp scripts/rename_tables_to_source_prefix.sql trading_timescaledb:/rename_tables_to_source_prefix.sql
docker exec -i trading_timescaledb psql -U trading_user -d trading_platform -f /rename_tables_to_source_prefix.sql
```

## 🔌 Providers and Brokers Architecture

- Historical providers (e.g., Polygon) implement `HistoricalProviderBase`.
- Realtime providers (e.g., IBKR) implement `RealtimeProviderBase`.
- Trade executors (e.g., IBKR) implement `TradeExecutorBase`.

Key modules:
- `src/data_pipeline/base.py`: interfaces
- `src/data_collectors/polygon/provider.py`: wraps existing Polygon collector for historical pulls
- `src/brokers/ibkr/realtime.py`: realtime subscribe/unsubscribe
- `src/brokers/ibkr/trade_executor.py`: order placement/status

## 📁 Project Structure

```
trading-platform/
├── manage_tp.sh                # Main management script
├── project-setup.toml          # Project configuration
├── src/                        # Source code
│   ├── core/                  # Core functionality
│   │   ├── config_loader.py   # Configuration management
│   │   └── config_models.py   # Pydantic models
│   ├── data_collectors/       # Data collection modules
│   │   └── polygon/           # Polygon.io integration
│   │       ├── collect_data.py     # Main collection script
│   │       ├── enhanced_collector.py # Data collector class
│   │       ├── data_storage.py     # Database storage
│   │       ├── collection_manager.py # Collection orchestration
│   │       └── utils.py           # Utility functions
│   ├── brokers/               # Broker integrations
│   │   └── ibkr/              # Interactive Brokers
│   └── strategies/            # Trading strategies
├── config/                    # Configuration files
│   ├── database.yaml          # Database configuration
│   ├── polygon.yaml           # Polygon.io configuration
│   ├── ibkr.yaml             # Interactive Brokers config
│   └── main.yaml             # Main configuration
├── scripts/                   # Utility scripts
│   ├── collect_market_data.py # Main data collection CLI
│   └── validate_config.py     # Configuration validation
├── docker/                    # Docker configuration
│   └── timescaledb/           # TimescaleDB setup
├── docs/                      # Documentation
└── tests/                     # Test suites
```

## 🔧 Configuration

### Environment Variables

Set connectivity in `.env` (dynamic DB port) and API keys:

```bash
# TimescaleDB (dynamic)
TIMESCALEDB_HOST=localhost
TIMESCALEDB_PORT=6432
DATABASE_URL=postgresql://trading_user:trading_password@${TIMESCALEDB_HOST}:${TIMESCALEDB_PORT}/trading_platform

# Polygon.io API
POLYGON_API_KEY=your_polygon_api_key_here

# Interactive Brokers
IBKR_ACCOUNT_ID=your_account_id
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_PAPER_TRADING=true
```

### Project Configuration

Configure data collection in `project-setup.toml`:

```toml
[data_collection]
time_interval = "minute"
start_date = "2024-10-05"
end_date = "2025-10-04"
tickers = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
rate_limit_delay = 13
```

### YAML Configuration

Main configuration files in `config/`:

- `database.yaml` - TimescaleDB settings
- `polygon.yaml` - Polygon.io API configuration
- `ibkr.yaml` - Interactive Brokers settings
- `strategies.yaml` - Strategy definitions
- `trading.yaml` - Trading parameters

## 📊 Data Collection Features

The system provides comprehensive data collection capabilities:

- **Minute-Level Data**: High-frequency market data collection
- **Data Quality Validation**: Built-in validation and outlier detection
- **Rate Limiting**: Intelligent API rate limiting to respect Polygon.io limits
- **Error Handling**: Robust error handling and retry mechanisms
- **Data Storage**: Efficient storage in TimescaleDB with compression
- **Duplicate Prevention**: Automatic duplicate detection and prevention

## 🛡️ Data Quality & Validation

Comprehensive data quality controls:

- **Price Validation**: OHLC price relationship validation
- **Volume Thresholds**: Minimum volume requirements
- **Outlier Detection**: Statistical outlier detection using IQR method
- **Price Deviation**: Maximum price change validation
- **Data Completeness**: Required field validation

## 📈 Database Features

TimescaleDB-powered data storage:

- **Hypertables**: Automatic time-series partitioning
- **Compression**: Data compression for storage efficiency
- **Continuous Aggregates**: Pre-computed aggregations (1m, 5m bars)
- **Retention Policies**: Automatic data retention management
- **Indexes**: Optimized indexes for fast queries

## 🧪 Testing

### Data Collection Testing

Test data collection and storage:

```bash
# Validate configuration
python scripts/validate_config.py

# Test data collection for a single symbol
python -c "
import asyncio
from src.data_collectors.polygon import collect_symbol_data
asyncio.run(collect_symbol_data('AAPL', '2024-10-01', '2024-10-02'))
"
```

### Database Testing

Test database connectivity and data:

```bash
# Connect to TimescaleDB
docker exec -it trading-platform-timescaledb-1 psql -U trading_user -d trading_platform

# Check data quality
SELECT symbol, COUNT(*) as records, 
       MIN(timestamp) as earliest, 
       MAX(timestamp) as latest,
       AVG(volume) as avg_volume
FROM ohlcv_data 
GROUP BY symbol;
```

## 🚨 Monitoring & Alerts

- **Data Quality Monitoring**: Track data validation failures and outliers
- **API Rate Limiting**: Monitor API usage and rate limit compliance
- **Database Performance**: Track query performance and storage usage
- **Collection Status**: Monitor data collection progress and errors

## 📚 Documentation

- [Quick Start Guide](docs/quick-start.md) - Get up and running in minutes
- [Data Collection Guide](docs/data-collection.md) - Data collection workflows
- [Database Schema](docs/database-schema.md) - Complete database schema documentation
- [Configuration Guide](docs/configuration.md) - Detailed configuration setup
- [API Reference](docs/api-reference.md) - API documentation
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. Always test thoroughly with paper trading before using real money.

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-repo/discussions)
- **Documentation**: [Project Wiki](https://github.com/your-repo/wiki)

---

**Status**: 🚧 Phase 1 - Foundation Complete | **Version**: 0.1.0 | **Last Updated**: 2024-10-05

### Current Status
- ✅ **Phase 1 Complete**: TimescaleDB setup, Polygon.io integration, data collection
- 🚧 **Phase 2 In Progress**: VectorBT strategy framework development
- 📋 **Phase 3 Planned**: Interactive Brokers integration
- 📋 **Phase 4 Planned**: Live trading and monitoring
