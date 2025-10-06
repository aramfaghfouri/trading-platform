-- Initialize TimescaleDB for Trading Platform
-- This script runs when the container starts for the first time

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create the main OHLCV data table
CREATE TABLE IF NOT EXISTS ohlcv_data (
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

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('ohlcv_data', 'timestamp', 
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_time 
    ON ohlcv_data (symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ohlcv_timestamp 
    ON ohlcv_data (timestamp DESC);

-- Create experiments table for tracking strategy results
CREATE TABLE IF NOT EXISTS experiments (
    id SERIAL PRIMARY KEY,
    experiment_name VARCHAR(100) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    parameters JSONB,
    metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create strategies table for strategy metadata
CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    class_name VARCHAR(100) NOT NULL,
    parameters JSONB,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create orders table for tracking trades
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) UNIQUE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(10) NOT NULL, -- 'BUY' or 'SELL'
    quantity INTEGER NOT NULL,
    price DECIMAL(10,4),
    order_type VARCHAR(20) NOT NULL, -- 'MARKET', 'LIMIT', etc.
    status VARCHAR(20) NOT NULL, -- 'PENDING', 'FILLED', 'CANCELLED'
    strategy_name VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ
);

-- Create positions table for tracking current positions
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    avg_price DECIMAL(10,4) NOT NULL,
    market_value DECIMAL(15,2),
    unrealized_pnl DECIMAL(15,2),
    strategy_name VARCHAR(100),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, strategy_name)
);

-- Create continuous aggregate for 1-minute bars from raw data
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_1m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 minute', timestamp) AS bucket,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume,
    (sum(close * volume) / NULLIF(sum(volume), 0)) AS vwap,
    sum(transactions) AS transactions
FROM ohlcv_data
GROUP BY symbol, bucket;

-- Enable real-time aggregation (include newest rows not yet materialized)
ALTER MATERIALIZED VIEW cagg_bars_1m SET (timescaledb.materialized_only = false);

-- Create refresh policy for 1-minute bars
SELECT add_continuous_aggregate_policy('cagg_bars_1m',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '30 seconds',
    if_not_exists => TRUE);

-- Create continuous aggregate for 5-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_5m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('5 minutes', timestamp) AS bucket,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume,
    (sum(close * volume) / NULLIF(sum(volume), 0)) AS vwap,
    sum(transactions) AS transactions
FROM ohlcv_data
GROUP BY symbol, bucket;

-- Enable real-time aggregation for 5-minute bars
ALTER MATERIALIZED VIEW cagg_bars_5m SET (timescaledb.materialized_only = false);

-- Create refresh policy for 5-minute bars
SELECT add_continuous_aggregate_policy('cagg_bars_5m',
    start_offset => INTERVAL '6 hours',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

-- Set up compression for historical data (compress data older than 7 days)
ALTER TABLE ohlcv_data SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');

-- Add compression policy
SELECT add_compression_policy('ohlcv_data', INTERVAL '7 days', if_not_exists => TRUE);

-- Set up data retention (keep data for 1 year)
SELECT add_retention_policy('ohlcv_data', INTERVAL '1 year', if_not_exists => TRUE);

-- Create a function to get latest data for a symbol
CREATE OR REPLACE FUNCTION get_latest_data(symbol_name VARCHAR(10), lookback_hours INTEGER DEFAULT 24)
RETURNS TABLE (
    timestamp TIMESTAMPTZ,
    open DECIMAL(10,4),
    high DECIMAL(10,4),
    low DECIMAL(10,4),
    close DECIMAL(10,4),
    volume BIGINT,
    vwap DECIMAL(10,4)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        o.timestamp,
        o.open,
        o.high,
        o.low,
        o.close,
        o.volume,
        o.vwap
    FROM ohlcv_data o
    WHERE o.symbol = symbol_name
    AND o.timestamp >= NOW() - INTERVAL '1 hour' * lookback_hours
    ORDER BY o.timestamp DESC;
END;
$$ LANGUAGE plpgsql;

-- Create a function to get symbol list
CREATE OR REPLACE FUNCTION get_symbols()
RETURNS TABLE (symbol VARCHAR(10)) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT o.symbol
    FROM ohlcv_data o
    ORDER BY o.symbol;
END;
$$ LANGUAGE plpgsql;

-- Insert some sample data for testing
INSERT INTO strategies (name, description, class_name, parameters, is_active) VALUES
('SMA_Crossover', 'Simple Moving Average Crossover Strategy', 'SMACrossoverStrategy', '{"fast_period": 10, "slow_period": 50}', false),
('Mean_Reversion', 'Mean Reversion Strategy', 'MeanReversionStrategy', '{"lookback_period": 20, "threshold": 2.0}', false),
('RSI_Strategy', 'RSI-based Strategy', 'RSIStrategy', '{"period": 14, "oversold": 30, "overbought": 70}', false);

-- Grant permissions to trading_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO trading_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO trading_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO trading_user;
