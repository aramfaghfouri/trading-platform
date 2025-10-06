# Quick Start Guide

Get up and running with the trading platform in minutes!

## 🚀 One-Command Setup

The fastest way to get started:

```bash
# Complete setup: delete, start, collect data
./manage_tp.sh --delete-databases && \
./manage_tp.sh --start-database && \
./manage_tp.sh --collect-data
```

This will:
1. Delete all existing databases and containers
2. Start a fresh TimescaleDB instance
3. Collect data for all 30 tickers configured in `project-setup.toml`

## 📋 Prerequisites

Before running, ensure you have:

1. **Docker installed and running**
   ```bash
   docker --version
   ```

2. **Python 3.11+ installed**
   ```bash
   python --version
   ```

3. **API key configured**
   ```bash
   # Copy environment template
   cp env.example .env
   
   # Edit with your API key
   nano .env
   ```

## ⚙️ Configuration

### 1. Set API Key

Edit `.env` file:
```bash
POLYGON_API_KEY=your_polygon_api_key_here
```

### 2. Configure Data Collection

Edit `project-setup.toml` to customize:
- **Tickers**: Add/remove symbols
- **Date Range**: Change start/end dates
- **Time Interval**: minute, day, hour
- **Rate Limiting**: Adjust delay between requests

## 🔧 Management Commands

### Database Management

```bash
# Delete everything and start fresh
./manage_tp.sh --delete-databases

# Start TimescaleDB
./manage_tp.sh --start-database

# Check database status
./manage_tp.sh --status
```

### Data Collection

```bash
# Collect data for all configured tickers
./manage_tp.sh --collect-data

# Validate configuration first
./manage_tp.sh --validate-config
```

### Help

```bash
# Show all available commands
./manage_tp.sh --help
```

## 📊 Verify Data Collection

After data collection completes, verify the data:

```bash
# Check system status
./manage_tp.sh --status

# Or connect to database directly
docker exec -it trading-platform-timescaledb-1 psql -U trading_user -d trading_platform

# Query data summary
SELECT symbol, COUNT(*) as records, 
       MIN(timestamp) as earliest, 
       MAX(timestamp) as latest 
FROM ohlcv_data 
GROUP BY symbol 
ORDER BY records DESC;
```

## 🎯 Expected Results

After successful data collection, you should see:

- **30 symbols** with data (AAPL, GOOGL, MSFT, etc.)
- **Minute-level data** from 2024-10-05 to 2025-10-04
- **~78,000+ records** per symbol (depending on market hours)
- **Data quality validation** passed
- **Compressed storage** in TimescaleDB

## 🚨 Troubleshooting

### Common Issues

1. **Docker not running**
   ```bash
   # Start Docker Desktop or Docker daemon
   sudo systemctl start docker  # Linux
   ```

2. **API key not set**
   ```bash
   # Check if .env exists and has API key
   cat .env | grep POLYGON_API_KEY
   ```

3. **Permission denied**
   ```bash
   # Make script executable
   chmod +x manage_trading_platform.sh
   ```

4. **Database connection failed**
   ```bash
   # Check if TimescaleDB is running
   docker ps | grep timescaledb
   ```

### Debug Mode

Run with verbose output:
```bash
# Enable debug logging
LOG_LEVEL=DEBUG ./manage_tp.sh --collect-data
```

## 📚 Next Steps

Once data collection is complete:

1. **Explore the data** using SQL queries
2. **Start Phase 2** - VectorBT strategy framework
3. **Develop strategies** using the collected data
4. **Set up Interactive Brokers** for live trading

## 🆘 Need Help?

- Check the [Data Collection Guide](data-collection.md) for detailed information
- Review [Database Schema](database-schema.md) for data structure
- See [Troubleshooting](troubleshooting.md) for common issues

---

**Ready to start?** Run the one-command setup above! 🚀
