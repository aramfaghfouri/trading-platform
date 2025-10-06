-- Initialize TimescaleDB for Trading Platform
-- This script runs when the container starts for the first time

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create ticker registry table (central registry for all tickers and their table names)
CREATE TABLE IF NOT EXISTS ticker_registry (
    symbol VARCHAR(10) PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    data_type VARCHAR(20) NOT NULL DEFAULT 'ohlcv', -- 'ohlcv', 'trades', 'quotes'
    timeframe VARCHAR(10) NOT NULL DEFAULT '1m', -- '1m', '5m', '1d'
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ticker-specific metadata
    company_name VARCHAR(255),
    sector VARCHAR(100),
    market_cap BIGINT,
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Data collection settings
    collection_enabled BOOLEAN DEFAULT TRUE,
    retention_days INTEGER DEFAULT 365,
    compression_enabled BOOLEAN DEFAULT TRUE
);

-- Create index for quick lookups
CREATE INDEX IF NOT EXISTS idx_ticker_registry_active 
    ON ticker_registry (is_active, data_type, timeframe);

-- Create function to get table name for a ticker
CREATE OR REPLACE FUNCTION get_ticker_table_name(
    p_symbol VARCHAR(10),
    p_data_type VARCHAR(20) DEFAULT 'ohlcv',
    p_timeframe VARCHAR(10) DEFAULT '1m'
) RETURNS VARCHAR(50) AS $$
BEGIN
    RETURN (SELECT table_name 
            FROM ticker_registry 
            WHERE symbol = p_symbol 
            AND data_type = p_data_type 
            AND timeframe = p_timeframe);
END;
$$ LANGUAGE plpgsql;

-- Create function to create tables for new tickers
CREATE OR REPLACE FUNCTION create_ticker_table(
    p_symbol VARCHAR(10),
    p_data_type VARCHAR(20) DEFAULT 'ohlcv',
    p_timeframe VARCHAR(10) DEFAULT '1m'
) RETURNS BOOLEAN AS $$
DECLARE
    v_table_name VARCHAR(50);
    sql_statement TEXT;
BEGIN
    -- Generate table name
    v_table_name := p_data_type || '_' || LOWER(p_symbol) || '_' || p_timeframe;
    
    -- Check if table already exists
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_name = v_table_name) THEN
        RETURN FALSE;
    END IF;
    
    -- Create the table
    sql_statement := format('
        CREATE TABLE %I (
            timestamp TIMESTAMPTZ NOT NULL PRIMARY KEY,
            open DECIMAL(10,4) NOT NULL,
            high DECIMAL(10,4) NOT NULL,
            low DECIMAL(10,4) NOT NULL,
            close DECIMAL(10,4) NOT NULL,
            volume BIGINT NOT NULL DEFAULT 0,
            vwap DECIMAL(10,4),
            transactions INTEGER,
            trade_count INTEGER,
            is_complete BOOLEAN DEFAULT TRUE,
            data_source VARCHAR(20) DEFAULT ''polygon'',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )', v_table_name);
    
    EXECUTE sql_statement;
    
    -- Convert to hypertable
    EXECUTE format('
        SELECT create_hypertable(''%I'', ''timestamp'',
            chunk_time_interval => INTERVAL ''1 day'',
            if_not_exists => TRUE)', v_table_name);
    
    -- Add compression policy
    EXECUTE format('
        ALTER TABLE %I SET (timescaledb.compress, 
            timescaledb.compress_segmentby = ''timestamp'')', v_table_name);
    
    -- Add compression policy
    EXECUTE format('
        SELECT add_compression_policy(''%I'', INTERVAL ''7 days'', 
            if_not_exists => TRUE)', v_table_name);
    
    -- Add retention policy
    EXECUTE format('
        SELECT add_retention_policy(''%I'', INTERVAL ''1 year'', 
            if_not_exists => TRUE)', v_table_name);
    
    -- Register in ticker registry
    INSERT INTO ticker_registry (symbol, table_name, data_type, timeframe)
    VALUES (p_symbol, v_table_name, p_data_type, p_timeframe);
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Create function to create continuous aggregates for each ticker
CREATE OR REPLACE FUNCTION create_ticker_continuous_aggregates(
    p_symbol VARCHAR(10),
    p_timeframe VARCHAR(10) DEFAULT '1m'
) RETURNS VOID AS $$
DECLARE
    source_table VARCHAR(50);
    agg_5m_table VARCHAR(50);
    agg_1h_table VARCHAR(50);
BEGIN
    source_table := 'ohlcv_' || LOWER(p_symbol) || '_' || p_timeframe;
    agg_5m_table := 'cagg_' || LOWER(p_symbol) || '_5m';
    agg_1h_table := 'cagg_' || LOWER(p_symbol) || '_1h';
    
    -- 5-minute aggregate
    EXECUTE format('
        CREATE MATERIALIZED VIEW %I
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''5 minutes'', timestamp) AS bucket,
            first(open, timestamp) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, timestamp) AS close,
            sum(volume) AS volume,
            (sum(close * volume) / NULLIF(sum(volume), 0)) AS vwap,
            sum(transactions) AS transactions
        FROM %I
        GROUP BY bucket', agg_5m_table, source_table);
    
    -- 1-hour aggregate
    EXECUTE format('
        CREATE MATERIALIZED VIEW %I
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(''1 hour'', timestamp) AS bucket,
            first(open, timestamp) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, timestamp) AS close,
            sum(volume) AS volume,
            (sum(close * volume) / NULLIF(sum(volume), 0)) AS vwap,
            sum(transactions) AS transactions
        FROM %I
        GROUP BY bucket', agg_1h_table, source_table);
END;
$$ LANGUAGE plpgsql;

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

-- Create unified view for cross-symbol analytics (optional)
CREATE OR REPLACE VIEW unified_ohlcv AS
SELECT 
    tr.symbol,
    o.timestamp,
    o.open,
    o.high,
    o.low,
    o.close,
    o.volume,
    o.vwap,
    o.transactions,
    o.trade_count,
    o.is_complete,
    o.data_source,
    o.created_at,
    o.updated_at
FROM ticker_registry tr
LEFT JOIN LATERAL (
    -- This will be populated dynamically as ticker tables are created
    SELECT NULL::TIMESTAMPTZ as timestamp, 
           NULL::DECIMAL(10,4) as open,
           NULL::DECIMAL(10,4) as high,
           NULL::DECIMAL(10,4) as low,
           NULL::DECIMAL(10,4) as close,
           NULL::BIGINT as volume,
           NULL::DECIMAL(10,4) as vwap,
           NULL::INTEGER as transactions,
           NULL::INTEGER as trade_count,
           NULL::BOOLEAN as is_complete,
           NULL::VARCHAR(20) as data_source,
           NULL::TIMESTAMPTZ as created_at,
           NULL::TIMESTAMPTZ as updated_at
    WHERE FALSE
) o ON true
WHERE tr.is_active = TRUE;

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
DECLARE
    table_name VARCHAR(50);
    sql_query TEXT;
BEGIN
    -- Get the table name for this symbol
    table_name := get_ticker_table_name(symbol_name, 'ohlcv', '1m');
    
    IF table_name IS NULL THEN
        RETURN;
    END IF;
    
    -- Build dynamic query
    sql_query := format('
        SELECT 
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            vwap
        FROM %I
        WHERE timestamp >= NOW() - INTERVAL ''1 hour'' * %s
        ORDER BY timestamp DESC', table_name, lookback_hours);
    
    RETURN QUERY EXECUTE sql_query;
END;
$$ LANGUAGE plpgsql;

-- Create a function to get symbol list
CREATE OR REPLACE FUNCTION get_symbols()
RETURNS TABLE (symbol VARCHAR(10)) AS $$
BEGIN
    RETURN QUERY
    SELECT tr.symbol
    FROM ticker_registry tr
    WHERE tr.is_active = TRUE
    ORDER BY tr.symbol;
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
