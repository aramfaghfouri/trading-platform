-- Database migrations for trading strategy system
-- Run this script to create the necessary tables for paper trading and strategy performance

-- Paper trading tables
CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id VARCHAR(50) PRIMARY KEY,
    account_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL, -- BUY/SELL
    quantity INTEGER NOT NULL,
    price DECIMAL(10,4) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    strategy_name VARCHAR(100),
    commission DECIMAL(10,4) DEFAULT 0,
    pnl DECIMAL(10,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_account_id ON paper_trades(account_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_paper_trades_timestamp ON paper_trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_paper_trades_strategy_name ON paper_trades(strategy_name);

-- Paper trading positions
CREATE TABLE IF NOT EXISTS paper_positions (
    account_id VARCHAR(50),
    symbol VARCHAR(10),
    quantity INTEGER NOT NULL,
    avg_price DECIMAL(10,4) NOT NULL,
    unrealized_pnl DECIMAL(10,4) DEFAULT 0,
    realized_pnl DECIMAL(10,4) DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (account_id, symbol)
);

-- Paper trading account balance
CREATE TABLE IF NOT EXISTS paper_account (
    account_id VARCHAR(50) PRIMARY KEY,
    cash DECIMAL(15,2) NOT NULL,
    total_equity DECIMAL(15,2) NOT NULL,
    buying_power DECIMAL(15,2) NOT NULL,
    unrealized_pnl DECIMAL(15,2) DEFAULT 0,
    realized_pnl DECIMAL(15,2) DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategy performance metrics
CREATE TABLE IF NOT EXISTS strategy_performance (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate DECIMAL(5,4) DEFAULT 0, -- 0.0000 to 1.0000
    total_pnl DECIMAL(15,2) DEFAULT 0,
    realized_pnl DECIMAL(15,2) DEFAULT 0,
    unrealized_pnl DECIMAL(15,2) DEFAULT 0,
    max_drawdown DECIMAL(5,4) DEFAULT 0,
    sharpe_ratio DECIMAL(8,4) DEFAULT 0,
    sortino_ratio DECIMAL(8,4) DEFAULT 0,
    avg_trade_pnl DECIMAL(10,4) DEFAULT 0,
    best_trade DECIMAL(10,4) DEFAULT 0,
    worst_trade DECIMAL(10,4) DEFAULT 0,
    profit_factor DECIMAL(8,4) DEFAULT 0,
    recovery_factor DECIMAL(8,4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_name, symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_strategy ON strategy_performance(strategy_name);
CREATE INDEX IF NOT EXISTS idx_strategy_performance_symbol ON strategy_performance(symbol);
CREATE INDEX IF NOT EXISTS idx_strategy_performance_date ON strategy_performance(date);

-- Backtesting results
CREATE TABLE IF NOT EXISTS backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DECIMAL(15,2) NOT NULL,
    final_capital DECIMAL(15,2) NOT NULL,
    total_return DECIMAL(8,4) NOT NULL, -- Percentage
    annualized_return DECIMAL(8,4),
    max_drawdown DECIMAL(5,4),
    sharpe_ratio DECIMAL(8,4),
    sortino_ratio DECIMAL(8,4),
    win_rate DECIMAL(5,4),
    profit_factor DECIMAL(8,4),
    total_trades INTEGER DEFAULT 0,
    avg_trade_duration INTERVAL,
    volatility DECIMAL(8,4),
    calmar_ratio DECIMAL(8,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_results_strategy ON backtest_results(strategy_name);
CREATE INDEX IF NOT EXISTS idx_backtest_results_symbol ON backtest_results(symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_results_dates ON backtest_results(start_date, end_date);

-- Strategy state (already exists, but ensure it has all needed columns)
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_name VARCHAR(100) PRIMARY KEY,
    last_processed_timestamp TIMESTAMPTZ,
    is_running BOOLEAN DEFAULT FALSE,
    last_heartbeat TIMESTAMPTZ,
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Strategy signals (already exists, but ensure it has all needed columns)
CREATE TABLE IF NOT EXISTS strategy_signals (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    signal_type VARCHAR(20) NOT NULL,
    confidence DECIMAL(3,2) DEFAULT 1.0, -- 0.00 to 1.00
    metadata JSONB,
    order_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy ON strategy_signals(strategy_name);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_symbol ON strategy_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_time ON strategy_signals(signal_time);

-- Comments for documentation
COMMENT ON TABLE paper_trades IS 'Paper trading order history and execution records';
COMMENT ON TABLE paper_positions IS 'Current paper trading positions for each account and symbol';
COMMENT ON TABLE paper_account IS 'Paper trading account balances and equity information';
COMMENT ON TABLE strategy_performance IS 'Daily performance metrics for each strategy and symbol';
COMMENT ON TABLE backtest_results IS 'Historical backtesting results for strategy validation';
COMMENT ON TABLE strategy_state IS 'Runtime state information for active strategies';
COMMENT ON TABLE strategy_signals IS 'Trading signals generated by strategies';

-- Grant permissions (adjust as needed for your setup)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO trading_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trading_user;
