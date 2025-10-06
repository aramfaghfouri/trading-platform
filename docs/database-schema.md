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
- **Consistent prefixes** for related tables:
  - `cagg_*` for continuous aggregates
  - Standard names for core tables

## Core Tables

### 1. ohlcv_data (Main Time-Series Table)
**Purpose**: Stores OHLCV (Open, High, Low, Close, Volume) data for all symbols

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| symbol | VARCHAR(10) | NOT NULL, PK | Stock symbol (e.g., 'AAPL') |
| timestamp | TIMESTAMPTZ | NOT NULL, PK | Data timestamp with timezone |
| open | DECIMAL(10,4) | | Opening price |
| high | DECIMAL(10,4) | | Highest price |
| low | DECIMAL(10,4) | | Lowest price |
| close | DECIMAL(10,4) | | Closing price |
| volume | BIGINT | | Trading volume |
| vwap | DECIMAL(10,4) | | Volume Weighted Average Price |
| transactions | INTEGER | | Number of transactions |

**Indexes**:
- Primary Key: `(symbol, timestamp)`
- `idx_ohlcv_symbol_time`: `(symbol, timestamp DESC)`
- `idx_ohlcv_timestamp`: `(timestamp DESC)`

**TimescaleDB Features**:
- Hypertable with 1-day chunk intervals
- Compression enabled (7-day policy)
- Retention policy: 1 year

### 2. experiments
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

### 3. strategies
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

### 4. orders
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

### 5. positions
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
    port="5432",
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
    port="5432",
    database="trading_platform",
    user="trading_user",
    password="trading_password"
)
```

### Docker Connection
```bash
docker exec -it trading_timescaledb psql -U trading_user -d trading_platform
```
