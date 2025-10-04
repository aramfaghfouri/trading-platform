# Live Trading Platform

A sophisticated live trading system built with QuantConnect Lean integration, supporting multiple strategies with flexible signal aggregation and real-time execution via Interactive Brokers.

## 🚀 Features

- **Multi-Strategy Support**: Run up to 20+ trading strategies simultaneously
- **QuantConnect Lean Integration**: Leverage Lean for strategy development and backtesting
- **Flexible Signal Aggregation**: Multiple aggregation functions (weighted average, majority vote, strength threshold)
- **Real-Time Trading**: Live execution via Interactive Brokers TWS API
- **Advanced Risk Management**: Position limits, drawdown protection, and risk controls
- **TradingView-Style Metrics**: Comprehensive performance tracking and analysis
- **Command-Line Interface**: Full CLI management for all operations
- **Microservices Architecture**: Scalable, fault-tolerant design
- **Docker Support**: Containerized deployment and development

## 🏗️ Architecture

### Core Components

- **Strategy Management**: QuantConnect Lean strategy execution and monitoring
- **Signal Processing**: Flexible signal aggregation and trigger engine
- **Trading Execution**: Interactive Brokers integration for live trading
- **Portfolio Management**: Real-time portfolio tracking and risk management
- **Data Management**: TimescaleDB for time-series data, PostgreSQL for metadata

### Technology Stack

- **Backend**: Python 3.11+ with FastAPI
- **Database**: TimescaleDB (time-series), PostgreSQL (metadata), Redis (caching)
- **Trading**: Interactive Brokers TWS API via ib_insync
- **Strategy Engine**: QuantConnect Lean (Python API)
- **Frontend**: React with Lightweight Charts
- **Deployment**: Docker & Docker Compose

## 📋 Project Status

See [README-Track.md](README-Track.md) for detailed progress tracking and implementation phases.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Interactive Brokers account (paper trading recommended)
- QuantConnect account

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

3. **Configure databases**
   ```bash
   # Start databases with Docker Compose
   docker-compose up -d
   ```

4. **Configure Interactive Brokers**
   - Install Trader Workstation (TWS)
   - Enable API connections
   - Configure paper trading account

5. **Configure strategies**
   ```bash
   # Copy and edit configuration files
   cp config/strategies.yaml.example config/strategies.yaml
   cp config/trigger_rules.yaml.example config/trigger_rules.yaml
   ```

### Running the System

1. **Start all services**
   ```bash
   # Start all services
   python -m services.cli.main start-all
   ```

2. **Manage strategies**
   ```bash
   # List available strategies
   python -m services.cli.main strategy list
   
   # Start a strategy
   python -m services.cli.main strategy start <strategy-id>
   
   # Stop a strategy
   python -m services.cli.main strategy stop <strategy-id>
   ```

3. **Monitor trading**
   ```bash
   # View portfolio status
   python -m services.cli.main portfolio status
   
   # Monitor orders
   python -m services.cli.main order list
   
   # View signals
   python -m services.cli.main signal list
   ```

## 📁 Project Structure

```
trading-platform/
├── services/                 # Microservices
│   ├── strategy-manager/     # Lean strategy execution
│   ├── signal-processor/     # Signal aggregation & triggers
│   ├── order-manager/        # IBKR trading execution
│   ├── risk-manager/         # Risk management
│   ├── portfolio-manager/    # Portfolio tracking
│   ├── data-manager/         # Data ingestion & storage
│   └── cli/                  # Command-line interface
├── shared/                   # Shared utilities
│   ├── models/              # Data models
│   ├── utils/               # Common utilities
│   └── config/              # Configuration management
├── strategies/              # Trading strategies
├── frontend/                # React dashboard
├── config/                  # Configuration files
└── tests/                   # Test suites
```

## 🔧 Configuration

### Strategy Configuration

Define your trading strategies in `config/strategies.yaml`:

```yaml
strategies:
  - id: "momentum_strategy_1"
    name: "Momentum Strategy 1"
    lean_file: "strategies/momentum_strategy.py"
    symbols: ["SPY", "QQQ", "IWM"]
    enabled: true
    risk_limits:
      max_position_size: 5000
      max_daily_loss: 1000
    signal_functions: ["weighted_average", "strength_threshold"]
```

### Trigger Rules

Configure signal triggers in `config/trigger_rules.yaml`:

```yaml
trigger_rules:
  SPY:
    - type: "multiple_signals"
      required_signals: 2
      time_window: "5m"
    - type: "strength_threshold"
      threshold: 0.7
```

## 📊 Signal Aggregation

The system supports multiple signal aggregation methods:

- **Weighted Average**: Average signal strength across strategies
- **Majority Vote**: Democratic decision based on signal count
- **Strength Threshold**: Trade when any signal exceeds threshold
- **Custom Functions**: User-defined aggregation logic

## 🛡️ Risk Management

Comprehensive risk controls:

- **Position Limits**: Per-symbol and portfolio-wide limits
- **Daily Loss Limits**: Stop trading on excessive losses
- **Drawdown Protection**: Automatic trading halt on drawdown
- **Concentration Limits**: Prevent over-concentration in single assets

## 📈 Performance Metrics

TradingView-style performance tracking:

- **Returns**: Daily, weekly, monthly, and annual returns
- **Sharpe Ratio**: Risk-adjusted returns
- **Maximum Drawdown**: Largest peak-to-trough decline
- **Win Rate**: Percentage of profitable trades
- **Average Trade**: Average profit/loss per trade

## 🧪 Testing

### Backtesting

Use QuantConnect Lean for strategy backtesting:

```bash
# Run backtest for a strategy
python -m services.cli.main strategy backtest <strategy-id> --start-date 2023-01-01 --end-date 2023-12-31
```

### Paper Trading

Test live execution with paper trading:

```bash
# Enable paper trading mode
python -m services.cli.main config set paper_trading true
```

## 🚨 Monitoring & Alerts

- **System Health**: Monitor all services and connections
- **Performance Alerts**: Notify on significant P&L changes
- **Error Alerts**: Immediate notification of system errors
- **Risk Alerts**: Warn when approaching risk limits

## 📚 Documentation

- [Architecture Overview](docs/architecture.md)
- [Strategy Development](docs/strategy-development.md)
- [Signal Aggregation](docs/signal-aggregation.md)
- [Risk Management](docs/risk-management.md)
- [API Reference](docs/api-reference.md)
- [Troubleshooting](docs/troubleshooting.md)

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

**Status**: 🚧 In Development | **Version**: 0.1.0 | **Last Updated**: 2024-01-XX
