# Quick Start Guide: Multi-Strategy Trading System

This guide will help you get the multi-strategy trading system up and running in minutes.

## Prerequisites

- ✅ Python 3.11+ installed
- ✅ TimescaleDB running (via `./manage_tp.sh --start-database`)
- ✅ Interactive Brokers TWS or Gateway running (paper trading recommended)
- ✅ Database initialized with strategy tables

## Step 1: Verify Database Setup

Make sure your database has the required tables:

```bash
# Check if strategy tables exist
psql $DATABASE_URL -c "\dt strategy*"

# If tables don't exist, run the init script
psql $DATABASE_URL -f docker/timescaledb/init/01-init-database.sql
```

Expected output:
```
              List of relations
 Schema |       Name       | Type  |    Owner     
--------+------------------+-------+--------------
 public | strategy_signals | table | trading_user
 public | strategy_state   | table | trading_user
```

## Step 2: Start Real-time Data Collection

In Terminal 1:

```bash
# Start data collector for AAPL with chart
python scripts/start_realtime_stream.py AAPL --chart

# OR for multiple symbols without chart
# python scripts/start_realtime_stream.py AAPL MSFT GOOGL
```

You should see:
```
2025-01-11 10:30:00 | INFO     | Connected to TimescaleDB
2025-01-11 10:30:01 | INFO     | Connected to IBKR
2025-01-11 10:30:02 | INFO     | Subscribing to real-time bars for AAPL...
2025-01-11 10:30:03 | INFO     | Subscribed to 1 symbols: AAPL
2025-01-11 10:30:03 | INFO     | Real-time streaming started
```

**Wait 1-2 minutes** for some data to accumulate before starting strategies.

## Step 3: Verify Data is Flowing

In Terminal 2:

```bash
# Check if data is being written
psql $DATABASE_URL -c "SELECT COUNT(*), MAX(timestamp) FROM ibkr_ohlcv_aapl_5s;"
```

Expected output:
```
 count |          max           
-------+------------------------
    24 | 2025-01-11 15:32:00+00
```

If count is 0, wait a bit longer or check IBKR connection.

## Step 4: List Available Strategies

```bash
python -m src.cli.strategy_manager list
```

Expected output:
```
╔══════════════════╦═════════════════╦═════════╦═════════╦══════════════╦════════════════╦═══════╗
║ Strategy         ║ Class           ║ Enabled ║ Symbols ║ Status       ║ Last Heartbeat ║ Error ║
╠══════════════════╬═════════════════╬═════════╬═════════╬══════════════╬════════════════╬═══════╣
║ sma_crossover    ║ SMACrossover    ║ ✓       ║ AAPL    ║ ⚪ Not Started ║ N/A            ║       ║
║ rsi_mean_...     ║ RSIMeanRev...   ║ ✓       ║ AAPL    ║ ⚪ Not Started ║ N/A            ║       ║
╚══════════════════╩═════════════════╩═════════╩═════════╩══════════════╩════════════════╩═══════╝
```

## Step 5: Start a Strategy

In Terminal 2:

```bash
# Start SMA Crossover strategy
python -m src.cli.strategy_manager start sma_crossover
```

Expected output:
```
2025-01-11 10:35:00 | INFO     | Starting strategy 'sma_crossover'...
2025-01-11 10:35:01 | INFO     | ✅ Strategy 'sma_crossover' started successfully (PID: 12345)
```

## Step 6: Monitor Strategy Status

In Terminal 3:

```bash
# Live monitoring (updates every 5 seconds)
python -m src.cli.strategy_manager status --watch
```

Expected output:
```
╔══════════════════╦═════════════════╦═════════╦═════════╦═════════════╦════════════════╦═══════╗
║ Strategy         ║ Class           ║ Enabled ║ Symbols ║ Status      ║ Last Heartbeat ║ Error ║
╠══════════════════╬═════════════════╬═════════╬═════════╬═════════════╬════════════════╬═══════╣
║ sma_crossover    ║ SMACrossover    ║ ✓       ║ AAPL    ║ 🟢 Running   ║ 10:35:15       ║       ║
║ rsi_mean_...     ║ RSIMeanRev...   ║ ✓       ║ AAPL    ║ ⚪ Not Started ║ N/A            ║       ║
╚══════════════════╩═════════════════╩═════════╩═════════╩═════════════╩════════════════╩═══════╝

Refreshing every 5 seconds... (Ctrl+C to stop)
```

## Step 7: Start Another Strategy

Back in Terminal 2:

```bash
# Start RSI Mean Reversion strategy
python -m src.cli.strategy_manager start rsi_mean_reversion
```

Now you have **two strategies running in parallel**!

## Step 8: View Generated Signals

In Terminal 4:

```bash
# Live signal monitoring
python -m src.cli.strategy_manager signals --tail
```

Expected output (when signals are generated):
```
╔═════════════════════╦════════════════╦════════╦════════╦════════════╦════════╗
║ Time                ║ Strategy       ║ Symbol ║ Signal ║ Confidence ║ Price  ║
╠═════════════════════╬════════════════╬════════╬════════╬════════════╬════════╣
║ 2025-01-11 15:40:00 ║ sma_crossover  ║ AAPL   ║ BUY    ║ 1.00       ║ 185.50 ║
║ 2025-01-11 15:42:00 ║ rsi_mean_rev   ║ AAPL   ║ SELL   ║ 1.00       ║ 186.20 ║
╚═════════════════════╩════════════════╩════════╩════════╩════════════╩════════╝

Refreshing every 5 seconds... (Ctrl+C to stop)
```

## Step 9: Check Strategy Logs

Each strategy writes detailed logs:

```bash
# Find strategy log files
ls -lth logs/strategy_*.log

# Tail a specific strategy's log
tail -f logs/strategy_sma_crossover_*.log
```

## Step 10: Stop Strategies

```bash
# Stop a specific strategy
python -m src.cli.strategy_manager stop sma_crossover

# Or stop all
python -m src.cli.strategy_manager stop-all
```

## Common Commands Reference

### Data Collection

```bash
# Single symbol with chart
python scripts/start_realtime_stream.py AAPL --chart

# Multiple symbols
python scripts/start_realtime_stream.py AAPL MSFT GOOGL

# With custom IBKR port
python scripts/start_realtime_stream.py AAPL --port 7496  # Live trading port
```

### Strategy Management

```bash
# List all strategies
python -m src.cli.strategy_manager list

# Start strategies
python -m src.cli.strategy_manager start <strategy_name>
python -m src.cli.strategy_manager start-all

# Stop strategies
python -m src.cli.strategy_manager stop <strategy_name>
python -m src.cli.strategy_manager stop-all

# Monitor status
python -m src.cli.strategy_manager status
python -m src.cli.strategy_manager status --watch

# View signals
python -m src.cli.strategy_manager signals
python -m src.cli.strategy_manager signals <strategy_name>
python -m src.cli.strategy_manager signals --limit 50
python -m src.cli.strategy_manager signals --tail
```

### Database Queries

```bash
# Check data freshness
psql $DATABASE_URL -c "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM ibkr_ohlcv_aapl_5s;"

# Check strategy state
psql $DATABASE_URL -c "SELECT * FROM strategy_state;"

# Check signals
psql $DATABASE_URL -c "SELECT * FROM strategy_signals ORDER BY signal_time DESC LIMIT 10;"

# Count signals by strategy
psql $DATABASE_URL -c "SELECT strategy_name, COUNT(*) FROM strategy_signals GROUP BY strategy_name;"
```

## Troubleshooting

### "No data found" when starting strategy

**Cause**: Not enough historical data yet

**Solution**: Wait 2-3 minutes for data to accumulate, or ensure data collector is running

```bash
# Verify data collector is running
ps aux | grep realtime_stream

# Check data count
psql $DATABASE_URL -c "SELECT COUNT(*) FROM ibkr_ohlcv_aapl_5s;"
```

### "Connection refused" from IBKR

**Cause**: TWS/Gateway not running or wrong port

**Solution**: 
1. Start TWS or IB Gateway
2. Enable API connections (Settings → API → Enable ActiveX and Socket Clients)
3. Check port: 7497 for paper trading, 7496 for live
4. Check client ID is not already in use

### Strategy not generating signals

**Cause**: Conditions not met yet (e.g., no SMA crossover)

**Solution**: Be patient - signals only generate when conditions are met. Check strategy logs:

```bash
tail -f logs/strategy_sma_crossover_*.log
```

You should see SMA values being calculated even if no signals are generated.

### "Table does not exist" error

**Cause**: Database not initialized

**Solution**: Run the initialization script:

```bash
psql $DATABASE_URL -f docker/timescaledb/init/01-init-database.sql
```

### Strategy keeps crashing

**Cause**: Check error in `strategy_state` table

**Solution**:
```bash
psql $DATABASE_URL -c "SELECT strategy_name, error_message FROM strategy_state;"
```

Check the strategy log file for full traceback:
```bash
tail -100 logs/strategy_<name>_*.log
```

## Next Steps

Now that you have the basic system running:

1. **Let it run** for an hour during market hours to see signals
2. **Monitor performance** using the status and signals commands
3. **Review logs** to understand strategy behavior
4. **Customize strategies** by editing `config/strategies.yaml`
5. **Create your own strategy** - see `docs/multi-strategy-system.md`

## Getting Help

- **Full Documentation**: `docs/multi-strategy-system.md`
- **Implementation Details**: `IMPLEMENTATION_SUMMARY.md`
- **Architecture**: `README.md` (Multi-Strategy section)
- **Database Schema**: `docs/database-schema.md`

## Example: Full Workflow

```bash
# Terminal 1: Database
./manage_tp.sh --start-database

# Terminal 2: Data Collector
python scripts/start_realtime_stream.py AAPL MSFT --chart --chart-symbol AAPL

# Wait 2 minutes for data...

# Terminal 3: Start Strategies
python -m src.cli.strategy_manager start-all

# Terminal 4: Monitor
python -m src.cli.strategy_manager status --watch

# Terminal 5: Watch Signals
python -m src.cli.strategy_manager signals --tail

# Let run for 1+ hours during market hours
# Review signals and logs
# Stop when done:
# python -m src.cli.strategy_manager stop-all
```

That's it! You now have a multi-strategy real-time trading system running. 🎉

