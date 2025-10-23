# Trading Platform

A comprehensive trading platform built with VectorBT, Polygon.io, and Interactive Brokers integration, designed for algorithmic trading, backtesting, and live execution.

## 🚀 Features

- **Hybrid IBKR Data Collection**: Real-time streaming + historical backfill with automatic gap detection
- **VectorBT Integration**: Advanced backtesting, portfolio optimization, and strategy development
- **Interactive Brokers Integration**: Live trading execution and portfolio management
- **TimescaleDB Storage**: High-performance time-series database for market data
- **Flexible Configuration**: YAML-based configuration with environment variable overrides
- **Data Quality Validation**: Built-in data validation and outlier detection
- **Rate Limiting**: Intelligent API rate limiting and error handling
- **Docker Support**: Containerized deployment and development
- **Modular Architecture**: Clean separation of concerns with organized code structure
- **Async/Non-blocking**: All operations use asyncio for optimal performance

## 🏗️ Architecture

### Core Components

- **Hybrid Data Collection**: IBKR real-time streaming + historical backfill with automatic gap detection
- **Data Storage**: TimescaleDB for high-performance time-series data storage
- **Strategy Framework**: VectorBT-based strategy development and backtesting
- **Trading Execution**: Interactive Brokers integration for live trading
- **Configuration Management**: YAML-based configuration with Pydantic validation
- **Data Quality**: Built-in validation, outlier detection, and quality checks

### Technology Stack

- **Backend**: Python 3.11+ with asyncio
- **Database**: TimescaleDB (time-series data with compression and continuous aggregates)
- **Data Source**: Interactive Brokers (IBKR) for real-time and historical market data
- **Trading**: Interactive Brokers TWS API via ib_insync
- **Strategy Engine**: VectorBT for backtesting and portfolio optimization
- **Configuration**: Pydantic models with YAML configuration files
- **Deployment**: Docker & Docker Compose

## 🔄 Hybrid IBKR Data Collection System

### Overview

The platform features a sophisticated hybrid data collection system that automatically combines real-time streaming with historical backfill to ensure complete, gap-free market data:

```
┌─────────────────────────────────────────────────────────────┐
│                Hybrid IBKR Data Collector                  │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │  Real-time      │    │        Historical               │ │
│  │  Streaming      │    │        Backfill                 │ │
│  │                 │    │                                 │ │
│  │  • 5s bars      │    │  • Gap detection               │ │
│  │  • 1m agg       │    │  • Historical API              │ │
│  │  • Live data    │    │  • Off-hours data              │ │
│  └─────────┬───────┘    └─────────────┬───────────────────┘ │
│            │                          │                     │
│            └──────────┬───────────────┘                     │
│                       ▼                                     │
│            ┌─────────────────────────┐                      │
│            │    Gap Detection &      │                      │
│            │    Automatic Backfill   │                      │
│            └─────────┬───────────────┘                      │
│                      │                                      │
└──────────────────────┼──────────────────────────────────────┘
                       ▼
            ┌─────────────────────────┐
            │      TimescaleDB        │
            │                         │
            │  ibkr_ohlcv_*_1m       │◄──── Complete data
            │  strategy_state         │
            │  strategy_signals       │
            └─────────┬───────────────┘
                      │
                      ├──────────────┬──────────────┬──────────────┐
                      ▼              ▼              ▼              ▼
               ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
               │ Strategy │   │ Strategy │   │ Strategy │   │ Strategy │
               │   SMA    │   │   RSI    │   │  Custom  │   │  Custom  │
               │          │   │          │   │          │   │          │
               └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

### Collection Modes

The system supports three collection modes:

#### 1. **Hybrid Mode** (Default - Recommended)
- **Automatic gap detection**: Detects missing data and backfills automatically
- **Real-time streaming**: 5-second bars aggregated to 1-minute during market hours
- **Historical backfill**: Fills gaps using IBKR historical API
- **Smart switching**: Automatically switches between real-time and historical based on data availability
- **Off-hours collection**: Continues collecting data even when markets are closed

#### 2. **Historical Mode**
- **Polling-based**: Checks for new data every 30 seconds
- **Historical API only**: Uses IBKR historical API for all data
- **Gap-aware**: Automatically detects and fills data gaps
- **Off-hours friendly**: Ideal for backfilling old data or collecting during off-hours

#### 3. **Real-time Mode**
- **Streaming only**: 5-second bars aggregated to 1-minute
- **Low latency**: Data available within 5-10 seconds
- **Market hours**: Best for active trading during market hours
- **Continuous connection**: Maintains persistent connection to IBKR

### Key Features

- **🔄 Automatic Gap Detection**: Continuously monitors for missing data and backfills automatically
- **⚡ Real-time Streaming**: 5-second bars aggregated to 1-minute for optimal performance
- **📊 Historical Backfill**: Seamlessly fills gaps using IBKR historical API
- **🕐 Off-hours Collection**: Collects data even when markets are closed
- **🔧 Async/Non-blocking**: All operations use asyncio for optimal performance
- **🛡️ Error Recovery**: Automatic reconnection and error handling
- **📈 Multiple Symbols**: Supports collecting data for multiple symbols simultaneously

## 🎯 Multi-Strategy Real-time Trading System

### Architecture Overview

The platform supports running multiple strategies in parallel, all reading from a centralized TimescaleDB:

### Key Features

1. **Write-Once, Read-Many**: Single data collector writes to TimescaleDB, all strategies read independently
2. **Parallel Execution**: Multiple strategies run simultaneously without conflicts
3. **Database-Driven**: Strategies poll TimescaleDB for new bars (5-10ms latency)
4. **State Management**: Track strategy state, heartbeats, and errors in database
5. **Signal Logging**: All trading signals logged to database with metadata

### Quick Start: Running Strategies

#### 1. Start Hybrid Data Collection

```bash
# Start hybrid IBKR collector (default - recommended)
./manage_tp.sh --start-ibkr-collector AAPL

# Start with specific mode
./manage_tp.sh --start-ibkr-collector AAPL hybrid    # Hybrid mode (default)
./manage_tp.sh --start-ibkr-collector AAPL historical # Historical only
./manage_tp.sh --start-ibkr-collector AAPL realtime   # Real-time only

# Start for multiple symbols
./manage_tp.sh --start-ibkr-collector AAPL,MSFT,GOOGL

# Start with live chart
./manage_tp.sh --chart-live AAPL
```

#### 2. Manage Strategies

```bash
# List all configured strategies
python -m src.cli.strategy_manager list

# Start a specific strategy
python -m src.cli.strategy_manager start sma_crossover

# Start all enabled strategies
python -m src.cli.strategy_manager start-all

# View strategy status (live monitoring)
python -m src.cli.strategy_manager status --watch

# View generated signals
python -m src.cli.strategy_manager signals --tail

# Stop a strategy
python -m src.cli.strategy_manager stop sma_crossover
```

#### 3. Configure Strategies

Edit `config/strategies.yaml`:

```yaml
strategies:
  registry:
    enabled_strategies:
      - "sma_crossover"
      - "rsi_mean_reversion"
    poll_interval_seconds: 5

  sma_crossover:
    enabled: true
    class: "src.strategies.implementations.sma_crossover.SMACrossover"
    parameters:
      short_window: 20
      long_window: 50
      quantity: 100
    symbols:
      - "AAPL"
```

### Implementing Custom Strategies

Create a new strategy by extending `BaseStrategy`:

```python
from src.strategies.base import BaseStrategy
from src.strategies.models import OrderSpec, OrderAction, OrderType, BarData

class MyStrategy(BaseStrategy):
    async def get_required_lookback(self) -> int:
        return 50  # Number of bars needed
    
    async def on_bar_update(self, symbol: str, bar: BarData) -> Optional[OrderSpec]:
        # Your strategy logic here
        df = self.get_cached_bars(symbol)
        
        # Calculate indicators
        # ...
        
        # Generate order if conditions met
        if buy_signal:
            return OrderSpec(
                symbol=symbol,
                action=OrderAction.BUY,
                quantity=100,
                order_type=OrderType.MARKET,
                strategy_name=self.name,
            )
        
        return None
```

Add to `config/strategies.yaml`:

```yaml
  my_strategy:
    enabled: true
    class: "src.strategies.implementations.my_strategy.MyStrategy"
    parameters:
      param1: value1
    symbols:
      - "AAPL"
```

### Database Schema

#### Strategy State Table

```sql
CREATE TABLE strategy_state (
    strategy_name VARCHAR(100) PRIMARY KEY,
    last_processed_timestamp TIMESTAMPTZ,
    is_running BOOLEAN DEFAULT FALSE,
    last_heartbeat TIMESTAMPTZ,
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### Strategy Signals Table

```sql
CREATE TABLE strategy_signals (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    signal_type VARCHAR(20) NOT NULL,
    confidence DECIMAL(5,4) DEFAULT 1.0,
    metadata JSONB,
    order_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Performance Considerations

- **Database Query Latency**: ~10-30ms for fetching recent bars
- **Polling Interval**: 5 seconds default (configurable)
- **Batch Writes**: Data collector batches writes every 12 bars (1 minute)
- **Parallel Strategies**: No limit, but 5-10 strategies recommended per CPU core

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

**Database Management:**
- `--delete-databases` - Delete all databases and containers
- `--start-database` - Start TimescaleDB
- `--status` - Show system status

**Data Collection:**
- `--start-ibkr-collector <symbol> [mode]` - Start hybrid IBKR data collector
- `--chart-live <symbol>` - Start live chart for symbol
- `--monitor-data <symbol>` - Monitor data collection in real-time
- `--collect-data` - Collect data for all configured tickers (legacy)

**Configuration:**
- `--validate-config` - Validate configuration files
- `--help` - Show help message

**Examples:**
```bash
# Start hybrid collector for AAPL
./manage_tp.sh --start-ibkr-collector AAPL

# Start historical-only collector for multiple symbols
./manage_tp.sh --start-ibkr-collector AAPL,MSFT historical

# Start live chart
./manage_tp.sh --chart-live AAPL

# Monitor data collection
./manage_tp.sh --monitor-data AAPL
```

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

**Status**: 🚀 Phase 2 - Hybrid Data Collection Complete | **Version**: 0.2.0 | **Last Updated**: 2025-10-22

### Current Status
- ✅ **Phase 1 Complete**: TimescaleDB setup, data collection infrastructure
- ✅ **Phase 2 Complete**: Hybrid IBKR data collection system with real-time streaming + historical backfill
- 🚧 **Phase 3 In Progress**: VectorBT strategy framework development
- 📋 **Phase 4 Planned**: Live trading and monitoring
