# NTS FAST4 Strategy Documentation

## Overview

The NTS FAST4 Strategy is a Python implementation of the TradingView Pine Script "NTS FAST4 Strategy (v6)". This strategy uses multi-timeframe analysis, modified ATR trailing stops, Fibonacci retracement levels, and trend detection to generate trading signals.

## Strategy Logic

### Core Components

1. **Multi-Timeframe (MTF) Analysis**: Uses a higher timeframe for signal generation while executing on a lower timeframe
2. **Modified ATR Trailing Stops**: Custom ATR calculation with trend-following logic
3. **Fibonacci Retracement Levels**: Dynamic entry/exit targets based on Fibonacci levels
4. **Trend Detection**: Tracks long/short trends with trailing stops
5. **Dynamic Stop-Loss**: Updates stop-loss based on ATR trail

### Key Calculations

#### Wilder's Moving Average (Wild_ma)
```python
def _wild_ma(self, src: pd.Series, length: int) -> pd.Series:
    alpha = 1.0 / length
    return src.ewm(alpha=alpha, adjust=False).mean()
```

#### Modified ATR Calculation
```python
HiLo = np.minimum(H - L, 1.5 * ta.sma(H - L, atr_period))
HRef = np.where(L <= H.shift(1), H - C.shift(1), H - C.shift(1) - 0.5 * (L - H.shift(1)))
LRef = np.where(H >= L.shift(1), C.shift(1) - L, C.shift(1) - L - 0.5 * (L.shift(1) - H))
true_range = np.maximum.reduce([HiLo, HRef, LRef])
```

#### Trend Logic
```python
# Update trailing stops
TrendUp = np.where(C.shift(1) > TrendUp.shift(1), 
                   np.maximum(Up, TrendUp.shift(1)), Up)
TrendDown = np.where(C.shift(1) < TrendDown.shift(1),
                     np.minimum(Dn, TrendDown.shift(1)), Dn)

# Determine trend
Trend = np.where(C > TrendDown.shift(1), 1,
                np.where(C < TrendUp.shift(1), -1, Trend.shift(1)))
```

#### Fibonacci Levels
```python
f1 = ex + (trail - ex) * 0.618  # 61.8%
f2 = ex + (trail - ex) * 0.786  # 78.6%
f3 = ex + (trail - ex) * 0.886  # 88.6%
l100 = trail                     # 100%
```

## Configuration Parameters

### Strategy Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `trail_type` | string | 'modified' | ATR calculation type ('modified' or 'unmodified') |
| `atr_period` | int | 185 | ATR calculation period |
| `atr_factor` | float | 3.0 | ATR multiplier for stops |
| `use_take_profit` | bool | True | Enable take-profit orders |
| `tp_fib_level` | string | '78.6' | Fibonacci level for take-profit |
| `quantity` | int | 100 | Number of shares to trade |
| `min_lookback` | int | 200 | Minimum bars needed before trading |
| `mtf_resolution` | string | '5m->15m' | Multi-timeframe resolution mapping |

### Fibonacci Levels

Available Fibonacci levels for take-profit:
- `61.8%`: 61.8% retracement
- `78.6%`: 78.6% retracement  
- `88.6%`: 88.6% retracement
- `100.0%`: 100% retracement (trend line)

### Multi-Timeframe Resolution

The strategy supports different timeframe combinations:
- `5m->15m`: 5-minute chart, 15-minute signals
- `1m->5m`: 1-minute chart, 5-minute signals
- `15m->1h`: 15-minute chart, 1-hour signals

## Signal Generation

### Long Signals
- Generated when trend changes from non-up to up (Trend = 1)
- Entry: Market buy order
- Stop-loss: Current TrendUp level
- Take-profit: Fibonacci level from extreme low to TrendUp

### Short Signals
- Generated when trend changes from non-down to down (Trend = -1)
- Entry: Market sell order
- Stop-loss: Current TrendDown level
- Take-profit: Fibonacci level from extreme high to TrendDown

### Exit Signals
- Long positions: Exit when price crosses below TrendUp
- Short positions: Exit when price crosses above TrendDown

## Usage Examples

### Basic Configuration

```yaml
nts_fast4_aapl:
  enabled: true
  class: "src.strategies.implementations.nts_fast4.NTSFast4"
  symbols: ["AAPL"]
  timeframe: "5m"
  parameters:
    trail_type: "modified"
    atr_period: 185
    atr_factor: 3.0
    use_take_profit: true
    tp_fib_level: "78.6"
    quantity: 100
    min_lookback: 200
    mtf_resolution: "5m->15m"
  paper_trading:
    enabled: true
    initial_capital: 100000
    commission_per_share: 0.005
```

### Advanced Configuration

```yaml
nts_fast4_advanced:
  enabled: true
  class: "src.strategies.implementations.nts_fast4.NTSFast4"
  symbols: ["AAPL", "MSFT", "GOOGL"]
  timeframe: "1m"
  parameters:
    trail_type: "unmodified"
    atr_period: 100
    atr_factor: 2.5
    use_take_profit: true
    tp_fib_level: "61.8"
    quantity: 50
    min_lookback: 150
    mtf_resolution: "1m->5m"
  paper_trading:
    enabled: true
    initial_capital: 100000
    commission_per_share: 0.005
```

## Backtesting

### Running Backtests

```bash
# Basic backtest
python scripts/backtest_nts_fast4.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-10-27

# Custom parameters
python scripts/backtest_nts_fast4.py \
  --symbol AAPL \
  --start-date 2024-01-01 \
  --end-date 2024-10-27 \
  --initial-capital 100000 \
  --commission 0.005
```

### Backtest Output

The backtest provides comprehensive performance metrics:

```
==================================================
NTS FAST4 STRATEGY BACKTEST RESULTS
==================================================
Symbol: AAPL
Period: 2024-01-01 to 2024-10-27
Initial Capital: $100,000.00
Final Capital: $105,250.00
Total Return: 5.25%
Total Trades: 45
Win Rate: 62.22%
Total P&L: $5,250.00
Profit Factor: 1.85
Max Drawdown: 8.50%
Sharpe Ratio: 1.42
==================================================
```

## Paper Trading

### Starting Paper Trading

```bash
# Start paper trading
python -m src.cli.strategy_manager start nts_fast4_aapl --mode paper

# Check status
python -m src.cli.strategy_manager status nts_fast4_aapl
```

### Paper Trading Features

- Real-time signal generation
- Simulated order execution
- P&L tracking
- Risk management
- Performance monitoring

## Live Trading

### Prerequisites

1. **Paper Trading Validation**: Strategy must perform well in paper trading
2. **Risk Limits**: Configure appropriate risk limits
3. **Manual Approval**: Manual approval required for live trading
4. **IBKR Connection**: Active IBKR TWS/Gateway connection

### Starting Live Trading

```bash
# Start live trading (requires manual approval)
python -m src.cli.strategy_manager start nts_fast4_aapl --mode live
```

### Risk Management

- Position sizing based on account equity
- Maximum position limits per symbol
- Daily loss limits
- Stop-loss orders for all positions
- Take-profit orders for profit protection

## Performance Considerations

### Data Requirements

- Minimum 200 bars of historical data for initialization
- Multi-timeframe data availability
- Real-time data feed for live trading

### Computational Efficiency

- Efficient ATR calculation using vectorized operations
- Cached trend calculations
- Optimized Fibonacci level computation
- Minimal database queries

### Memory Usage

- Strategy state tracking per symbol
- Historical data caching (1000 bars max)
- Signal metadata storage

## Troubleshooting

### Common Issues

1. **Insufficient Data**: Ensure enough historical data is available
2. **MTF Data Issues**: Verify multi-timeframe data availability
3. **Signal Generation**: Check trend detection logic
4. **Order Execution**: Verify broker connection and permissions

### Debugging

Enable debug logging to troubleshoot issues:

```python
import logging
logging.getLogger('src.strategies.implementations.nts_fast4').setLevel(logging.DEBUG)
```

### Performance Optimization

1. **Reduce Lookback**: Lower `min_lookback` for faster initialization
2. **Optimize ATR Period**: Adjust `atr_period` for better performance
3. **MTF Resolution**: Use appropriate timeframe combinations
4. **Position Sizing**: Optimize `quantity` for account size

## Risk Considerations

### Market Risks

- **Trend Reversals**: Strategy may generate false signals during choppy markets
- **Gap Risk**: Overnight gaps may cause significant losses
- **Liquidity Risk**: Ensure sufficient liquidity for order execution

### Strategy Risks

- **Parameter Sensitivity**: ATR period and factor significantly affect performance
- **MTF Dependencies**: Strategy relies on multi-timeframe data accuracy
- **Fibonacci Levels**: Take-profit levels may not always be reached

### Risk Mitigation

- **Diversification**: Trade multiple symbols
- **Position Sizing**: Limit position size per trade
- **Stop-Losses**: Always use stop-loss orders
- **Monitoring**: Continuous performance monitoring
- **Backtesting**: Extensive backtesting before live trading

## Future Enhancements

### Planned Features

1. **Dynamic ATR Period**: Adaptive ATR period based on market volatility
2. **Multiple Fibonacci Levels**: Support for multiple take-profit levels
3. **Risk-Adjusted Position Sizing**: Position sizing based on volatility
4. **Machine Learning Integration**: ML-based signal filtering
5. **Advanced MTF Support**: More sophisticated multi-timeframe analysis

### Customization Options

1. **Custom Fibonacci Levels**: User-defined retracement levels
2. **Alternative ATR Calculations**: Different ATR methodologies
3. **Signal Filtering**: Additional signal validation
4. **Performance Metrics**: Custom performance indicators

## Support and Maintenance

### Documentation Updates

This documentation is updated regularly to reflect strategy improvements and new features.

### Community Support

For questions, issues, or contributions:
- GitHub Issues: Report bugs and request features
- Documentation: Check this documentation for common questions
- Code Review: Submit pull requests for improvements

### Version History

- **v1.0**: Initial implementation of NTS FAST4 strategy
- **v1.1**: Added multi-timeframe support
- **v1.2**: Enhanced Fibonacci level calculations
- **v1.3**: Improved backtesting framework
- **v1.4**: Added paper trading support
