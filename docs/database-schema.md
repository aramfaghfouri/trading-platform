# Trading Platform Database Schema

## Database Information
- **Database Name**: `trading_platform`
- **Database Type**: TimescaleDB (PostgreSQL 15.13)
- **Connection Details**:
  - Host: `localhost`
  - Port: `5432`
  - Username: `trading_user`
  - Password: `trading_password`

## Table Naming Conventions
- **Snake_case** for all table names
- **Descriptive names** that clearly indicate purpose
- **Ticker-specific tables**: `{data_type}_{ticker}_{timeframe}` (e.g., `ohlcv_aapl_1m`)
- **Consistent prefixes** for related tables:
  - `cagg_*` for continuous aggregates
  - Standard names for core tables

## Core Tables

### 1. ticker_registry (Central Registry)
**Purpose**: Central registry for all tickers and their table names

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| symbol | VARCHAR(10) | PRIMARY KEY | Stock symbol (e.g., 'AAPL') |
| table_name | VARCHAR(50) | NOT NULL | Name of the ticker's data table |
| data_type | VARCHAR(20) | NOT NULL | Type of data ('ohlcv', 'trades', 'quotes') |
| timeframe | VARCHAR(10) | NOT NULL | Data timeframe ('1m', '5m', '1d') |
| is_active | BOOLEAN | DEFAULT TRUE | Whether ticker is active |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Registry entry creation time |
| last_updated | TIMESTAMPTZ | DEFAULT NOW() | Last update time |
| company_name | VARCHAR(255) | | Company name |
| sector | VARCHAR(100) | | Market sector |
| market_cap | BIGINT | | Market capitalization |
| currency | VARCHAR(3) | DEFAULT 'USD' | Currency code |
| collection_enabled | BOOLEAN | DEFAULT TRUE | Whether data collection is enabled |
| retention_days | INTEGER | DEFAULT 365 | Data retention period |
| compression_enabled | BOOLEAN | DEFAULT TRUE | Whether compression is enabled |

**Indexes**:
- Primary Key: `symbol`
- `idx_ticker_registry_active`: `(is_active, data_type, timeframe)`

### 2. ohlcv_{ticker}_{timeframe} (Ticker-Specific Tables)
**Purpose**: Stores OHLCV data for individual tickers

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| timestamp | TIMESTAMPTZ | PRIMARY KEY | Data timestamp with timezone |
| open | DECIMAL(10,4) | NOT NULL | Opening price |
| high | DECIMAL(10,4) | NOT NULL | Highest price |
| low | DECIMAL(10,4) | NOT NULL | Lowest price |
| close | DECIMAL(10,4) | NOT NULL | Closing price |
| volume | BIGINT | NOT NULL DEFAULT 0 | Trading volume |
| vwap | DECIMAL(10,4) | | Volume Weighted Average Price |
| transactions | INTEGER | | Number of transactions |
| trade_count | INTEGER | | Number of trades |
| is_complete | BOOLEAN | DEFAULT TRUE | Whether bar is complete |
| data_source | VARCHAR(20) | DEFAULT 'polygon' | Data source |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Record creation time |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | Last update time |

**Indexes**:
- Primary Key: `timestamp`
- Automatic TimescaleDB indexes for time-series optimization

**TimescaleDB Features**:
- Hypertable with 1-day chunk intervals
- Compression enabled (7-day policy)
- Retention policy: 1 year
- Per-ticker continuous aggregates

## Architecture Benefits

### Ticker-Specific Tables
- **Performance**: Smaller tables = faster queries for individual tickers
- **Isolation**: One ticker's data issues don't affect others
- **Flexibility**: Ticker-specific configurations and retention policies
- **Scalability**: Easy to add new tickers without schema changes

### Dynamic Table Management
- **Automatic Creation**: Tables are created on-demand when data is first collected
- **Registry-Based**: Central registry tracks all tickers and their table names
- **Function-Based Access**: Database functions handle table name resolution

## Database Functions

### Table Management
- `create_ticker_table(symbol, data_type, timeframe)`: Creates a new ticker table
- `get_ticker_table_name(symbol, data_type, timeframe)`: Gets table name for a ticker
- `create_ticker_continuous_aggregates(symbol, timeframe)`: Creates continuous aggregates

### Data Access
- `get_latest_data(symbol, lookback_hours)`: Gets latest data for a symbol
- `get_symbols()`: Gets list of all active symbols

## Migration from Single Table

If you have existing data in the old `ohlcv_data` table, use the migration script:

```bash
# Dry run to see what would be migrated
python scripts/migrate_to_ticker_tables.py --dry-run

# Migrate with backup
python scripts/migrate_to_ticker_tables.py --backup

# Migrate without backup
python scripts/migrate_to_ticker_tables.py
```

### 3. experiments
**Purpose**: Tracks strategy experiment results and performance metrics

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Auto-incrementing ID |
| experiment_name | VARCHAR(100) | NOT NULL | Name of the experiment |
| strategy_name | VARCHAR(100) | NOT NULL | Strategy being tested |
| timestamp | TIMESTAMPTZ | DEFAULT NOW() | Experiment timestamp |
| parameters | JSONB | | Strategy parameters as JSON |
| metrics | JSONB | | Performance metrics as JSON |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Record creation time |

### 4. strategies
**Purpose**: Stores strategy definitions and metadata

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Auto-incrementing ID |
| name | VARCHAR(100) | NOT NULL, UNIQUE | Strategy name |
| description | TEXT | | Strategy description |
| class_name | VARCHAR(100) | NOT NULL | Python class name |
| parameters | JSONB | | Default parameters |
| is_active | BOOLEAN | DEFAULT FALSE | Whether strategy is active |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

### 5. orders
**Purpose**: Tracks all trading orders

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Auto-incrementing ID |
| order_id | VARCHAR(50) | NOT NULL, UNIQUE | External order ID |
| symbol | VARCHAR(10) | NOT NULL | Stock symbol |
| side | VARCHAR(10) | NOT NULL | 'BUY' or 'SELL' |
| quantity | INTEGER | NOT NULL | Number of shares |
| price | DECIMAL(10,4) | | Order price (NULL for market orders) |
| order_type | VARCHAR(20) | NOT NULL | 'MARKET', 'LIMIT', etc. |
| status | VARCHAR(20) | NOT NULL | 'PENDING', 'FILLED', 'CANCELLED' |
| strategy_name | VARCHAR(100) | | Associated strategy |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Order creation time |
| filled_at | TIMESTAMPTZ | | When order was filled |
| cancelled_at | TIMESTAMPTZ | | When order was cancelled |

### 6. positions
**Purpose**: Tracks current portfolio positions

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Auto-incrementing ID |
| symbol | VARCHAR(10) | NOT NULL | Stock symbol |
| quantity | INTEGER | NOT NULL | Number of shares held |
| avg_price | DECIMAL(10,4) | NOT NULL | Average purchase price |
| market_value | DECIMAL(15,2) | | Current market value |
| unrealized_pnl | DECIMAL(15,2) | | Unrealized profit/loss |
| strategy_name | VARCHAR(100) | | Associated strategy |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | Last update time |

**Constraints**:
- Unique constraint on `(symbol, strategy_name)`

## Continuous Aggregates (Views)

### 1. cagg_bars_1m
**Purpose**: Pre-aggregated 1-minute bars for faster queries

| Column | Type | Description |
|--------|------|-------------|
| symbol | VARCHAR(10) | Stock symbol |
| bucket | TIMESTAMPTZ | 1-minute time bucket |
| open | NUMERIC | Opening price |
| high | NUMERIC | Highest price |
| low | NUMERIC | Lowest price |
| close | NUMERIC | Closing price |
| volume | NUMERIC | Total volume |
| vwap | NUMERIC | Volume Weighted Average Price |
| transactions | BIGINT | Total transactions |

**Refresh Policy**: Every 30 seconds, 2-hour lookback

### 2. cagg_bars_5m
**Purpose**: Pre-aggregated 5-minute bars for faster queries

| Column | Type | Description |
|--------|------|-------------|
| symbol | VARCHAR(10) | Stock symbol |
| bucket | TIMESTAMPTZ | 5-minute time bucket |
| open | NUMERIC | Opening price |
| high | NUMERIC | Highest price |
| low | NUMERIC | Lowest price |
| close | NUMERIC | Closing price |
| volume | NUMERIC | Total volume |
| vwap | NUMERIC | Volume Weighted Average Price |
| transactions | BIGINT | Total transactions |

**Refresh Policy**: Every 1 minute, 6-hour lookback

## TimescaleDB Features

### Compression
- **Table**: `ohlcv_data`
- **Policy**: Compress data older than 7 days
- **Segment By**: `symbol`

### Retention
- **Table**: `ohlcv_data`
- **Policy**: Retain data for 1 year

### Continuous Aggregates
- Automatic refresh of 1-minute and 5-minute bars
- Real-time and historical data combination
- Optimized for time-series queries

## Sample Queries

### Get Latest Data for a Symbol
```sql
SELECT * FROM ohlcv_data 
WHERE symbol = 'AAPL' 
ORDER BY timestamp DESC 
LIMIT 100;
```

### Get 1-Minute Bars
```sql
SELECT * FROM cagg_bars_1m 
WHERE symbol = 'AAPL' 
AND bucket >= NOW() - INTERVAL '1 day'
ORDER BY bucket DESC;
```

### Get Strategy Performance
```sql
SELECT experiment_name, metrics->>'total_return' as return
FROM experiments 
WHERE strategy_name = 'my_strategy'
ORDER BY created_at DESC;
```

### Get Current Positions
```sql
SELECT symbol, quantity, avg_price, unrealized_pnl
FROM positions 
WHERE strategy_name = 'my_strategy';
```

## Connection Examples

### Python (psycopg2)
```python
import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port="6432",
    database="trading_platform",
    user="trading_user",
    password="trading_password"
)
```

### Python (asyncpg)
```python
import asyncpg

conn = await asyncpg.connect(
    host="localhost",
    port="6432",
    database="trading_platform",
    user="trading_user",
    password="trading_password"
)
```

### Docker Connection
```bash
docker exec -it trading_timescaledb psql -U trading_user -d trading_platform
```
