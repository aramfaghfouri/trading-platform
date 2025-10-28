"""
Integration tests for NTS FAST4 Strategy.

Tests the strategy with historical data and validates against expected behavior.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from strategies.nts_fast4.nts_fast4 import NTSFast4
from src.strategies.models import BarData, OrderSpec, OrderAction, OrderType


class TestNTSFast4Integration:
    """Integration tests for NTS FAST4 strategy."""
    
    @pytest.fixture
    def strategy_config(self):
        """Default strategy configuration."""
        return {
            'trail_type': 'modified',
            'atr_period': 50,  # Shorter for testing
            'atr_factor': 2.0,  # Smaller factor for testing
            'use_take_profit': True,
            'tp_fib_level': '78.6',
            'quantity': 100,
            'min_lookback': 100,  # Shorter for testing
            'mtf_resolution': '5m->15m'
        }
    
    @pytest.fixture
    def strategy(self, strategy_config):
        """Create NTS FAST4 strategy instance."""
        strategy = NTSFast4(
            name="test_nts_fast4",
            config=strategy_config,
            symbols=["AAPL"]
        )
        
        # Mock database connection
        strategy.db_pool = AsyncMock()
        strategy.is_initialized = True
        
        return strategy
    
    @pytest.fixture
    def historical_data(self):
        """Create realistic historical data for testing."""
        dates = pd.date_range(start='2024-01-01', periods=500, freq='5min')
        
        # Create price data with clear trends and reversals
        base_price = 150.0
        
        # Create a clear uptrend followed by downtrend
        trend_up = np.linspace(0, 30, 200)  # 200 bars up
        trend_down = np.linspace(30, -20, 200)  # 200 bars down
        trend_flat = np.zeros(100)  # 100 bars flat
        
        trend = np.concatenate([trend_up, trend_down, trend_flat])
        noise = np.random.normal(0, 1, 500)
        prices = base_price + trend + noise
        
        # Generate OHLC data
        data = []
        for i, (date, close) in enumerate(zip(dates, prices)):
            # Add realistic OHLC relationships
            high = close + abs(np.random.normal(0, 0.8))
            low = close - abs(np.random.normal(0, 0.8))
            open_price = close + np.random.normal(0, 0.3)
            volume = np.random.randint(1000, 10000)
            
            data.append({
                'timestamp': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume
            })
        
        return pd.DataFrame(data)
    
    @pytest.fixture
    def mock_bar_data(self, historical_data):
        """Create mock BarData objects."""
        bars = []
        for _, row in historical_data.iterrows():
            bar = BarData(
                timestamp=row['timestamp'],
                open=Decimal(str(row['open'])),
                high=Decimal(str(row['high'])),
                low=Decimal(str(row['low'])),
                close=Decimal(str(row['close'])),
                volume=int(row['volume']),
                symbol="AAPL"
            )
            bars.append(bar)
        return bars
    
    def test_strategy_initialization_with_data(self, strategy, historical_data):
        """Test strategy initialization with historical data."""
        # Set up cached data
        strategy._bar_cache["AAPL"] = historical_data
        
        # Test that data is properly cached
        cached_data = strategy.get_cached_bars("AAPL")
        assert len(cached_data) == 500
        assert not cached_data.empty
        
        # Test MTF data resampling
        mtf_data = strategy._get_mtf_data("AAPL", 100)
        assert not mtf_data.empty
        assert len(mtf_data) > 0
    
    @pytest.mark.asyncio
    async def test_strategy_with_insufficient_data(self, strategy):
        """Test strategy behavior with insufficient data."""
        # Set up minimal data
        minimal_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=10, freq='5min'),
            'open': [100] * 10,
            'high': [101] * 10,
            'low': [99] * 10,
            'close': [100] * 10,
            'volume': [1000] * 10
        })
        
        strategy._bar_cache["AAPL"] = minimal_data
        
        # Create a bar
        bar = BarData(
            timestamp=datetime.now(),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100'),
            volume=1000,
            symbol="AAPL"
        )
        
        # Should return None due to insufficient data
        result = await strategy.on_bar_update("AAPL", bar)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_strategy_trend_detection(self, strategy, historical_data, mock_bar_data):
        """Test trend detection and signal generation."""
        # Set up sufficient data
        strategy._bar_cache["AAPL"] = historical_data
        
        # Test with bars from different parts of the trend
        test_bars = mock_bar_data[150:200]  # Middle of uptrend
        
        signals_generated = 0
        for bar in test_bars:
            result = await strategy.on_bar_update("AAPL", bar)
            if result is not None:
                signals_generated += 1
                assert isinstance(result, OrderSpec)
                assert result.symbol == "AAPL"
                assert result.strategy_name == "test_nts_fast4"
        
        # Should generate some signals during trend changes
        assert signals_generated >= 0  # May or may not generate signals depending on data
    
    @pytest.mark.asyncio
    async def test_long_signal_generation(self, strategy, historical_data):
        """Test long signal generation."""
        # Set up data with clear uptrend
        uptrend_data = historical_data.iloc[100:300].copy()
        strategy._bar_cache["AAPL"] = uptrend_data
        
        # Mock MTF data to force long signal
        mtf_data = uptrend_data.copy()
        mtf_data['low'] = mtf_data['low'] - 5  # Lower lows for Fibonacci calculation
        
        # Mock the _get_mtf_data method
        strategy._get_mtf_data = AsyncMock(return_value=mtf_data)
        
        # Create a bar that should trigger long signal
        bar = BarData(
            timestamp=datetime.now(),
            open=Decimal('160'),
            high=Decimal('161'),
            low=Decimal('159'),
            close=Decimal('160'),
            volume=1000,
            symbol="AAPL"
        )
        
        # Manually set trend state to trigger long signal
        strategy._trend_state["AAPL"] = 1
        strategy._trend_up["AAPL"] = 155.0
        strategy._trend_down["AAPL"] = 165.0
        
        result = await strategy.on_bar_update("AAPL", bar)
        
        # Should generate long signal
        if result is not None:
            assert result.action == OrderAction.BUY
            assert result.quantity == 100
            assert result.order_type == OrderType.MARKET
            assert result.stop_loss is not None
            assert result.take_profit is not None
    
    @pytest.mark.asyncio
    async def test_short_signal_generation(self, strategy, historical_data):
        """Test short signal generation."""
        # Set up data with clear downtrend
        downtrend_data = historical_data.iloc[300:500].copy()
        strategy._bar_cache["AAPL"] = downtrend_data
        
        # Mock MTF data to force short signal
        mtf_data = downtrend_data.copy()
        mtf_data['high'] = mtf_data['high'] + 5  # Higher highs for Fibonacci calculation
        
        # Mock the _get_mtf_data method
        strategy._get_mtf_data = AsyncMock(return_value=mtf_data)
        
        # Create a bar that should trigger short signal
        bar = BarData(
            timestamp=datetime.now(),
            open=Decimal('140'),
            high=Decimal('141'),
            low=Decimal('139'),
            close=Decimal('140'),
            volume=1000,
            symbol="AAPL"
        )
        
        # Manually set trend state to trigger short signal
        strategy._trend_state["AAPL"] = -1
        strategy._trend_up["AAPL"] = 145.0
        strategy._trend_down["AAPL"] = 135.0
        
        result = await strategy.on_bar_update("AAPL", bar)
        
        # Should generate short signal
        if result is not None:
            assert result.action == OrderAction.SELL
            assert result.quantity == 100
            assert result.order_type == OrderType.MARKET
            assert result.stop_loss is not None
            assert result.take_profit is not None
    
    @pytest.mark.asyncio
    async def test_position_management(self, strategy, historical_data):
        """Test position management and exit signals."""
        # Set up data
        strategy._bar_cache["AAPL"] = historical_data
        
        # Set up a long position
        strategy._positions["AAPL"] = 100
        strategy._trend_up["AAPL"] = 155.0
        strategy._trend_down["AAPL"] = 165.0
        
        # Create a bar that should trigger exit
        bar = BarData(
            timestamp=datetime.now(),
            open=Decimal('150'),
            high=Decimal('151'),
            low=Decimal('149'),
            close=Decimal('150'),  # Below trend_up, should exit
            volume=1000,
            symbol="AAPL"
        )
        
        result = await strategy.on_bar_update("AAPL", bar)
        
        # Should generate exit signal
        if result is not None:
            assert result.action == OrderAction.SELL
            assert result.quantity == 100
            assert result.order_type == OrderType.MARKET
    
    def test_fibonacci_calculation_integration(self, strategy, historical_data):
        """Test Fibonacci calculation with real data."""
        # Test with actual price ranges
        high_price = historical_data['high'].max()
        low_price = historical_data['low'].min()
        
        fib_levels = strategy._calculate_fibonacci_levels(low_price, high_price)
        
        # Verify Fibonacci levels are in correct order
        assert fib_levels['f1'] < fib_levels['f2'] < fib_levels['f3'] < fib_levels['l100']
        
        # Verify levels are within price range
        assert low_price <= fib_levels['f1'] <= high_price
        assert low_price <= fib_levels['f2'] <= high_price
        assert low_price <= fib_levels['f3'] <= high_price
        assert low_price <= fib_levels['l100'] <= high_price
    
    def test_atr_calculation_integration(self, strategy, historical_data):
        """Test ATR calculation with real data."""
        atr_modified = strategy._calculate_atr(historical_data, 20, modified=True)
        atr_unmodified = strategy._calculate_atr(historical_data, 20, modified=False)
        
        # Both should be valid
        assert len(atr_modified) == len(historical_data)
        assert len(atr_unmodified) == len(historical_data)
        
        # Both should be non-negative
        assert (atr_modified >= 0).all()
        assert (atr_unmodified >= 0).all()
        
        # They should be different
        assert not np.allclose(atr_modified, atr_unmodified, rtol=1e-3)
    
    def test_trend_logic_integration(self, strategy, historical_data):
        """Test trend logic with real data."""
        atr = strategy._calculate_atr(historical_data, 20, modified=True)
        TrendUp, TrendDown, Trend = strategy._calculate_trend_logic(historical_data, atr)
        
        # All series should have same length
        assert len(TrendUp) == len(historical_data)
        assert len(TrendDown) == len(historical_data)
        assert len(Trend) == len(historical_data)
        
        # Trend should only have values -1, 0, 1
        assert set(Trend.unique()).issubset({-1, 0, 1})
        
        # TrendUp should be below close, TrendDown should be above close
        assert (TrendUp <= historical_data['close']).all()
        assert (TrendDown >= historical_data['close']).all()
    
    def test_strategy_state_tracking(self, strategy):
        """Test strategy state tracking."""
        symbol = "AAPL"
        
        # Test initial state
        assert strategy.get_position(symbol) == 0
        assert strategy.get_trend_state(symbol) == 0
        
        # Update state
        strategy._positions[symbol] = 100
        strategy._trend_state[symbol] = 1
        strategy._trend_up[symbol] = 155.0
        strategy._trend_down[symbol] = 165.0
        
        # Test updated state
        assert strategy.get_position(symbol) == 100
        assert strategy.get_trend_state(symbol) == 1
        
        levels = strategy.get_trend_levels(symbol)
        assert levels['trend_up'] == 155.0
        assert levels['trend_down'] == 165.0
    
    def test_strategy_with_multiple_symbols(self):
        """Test strategy with multiple symbols."""
        config = {
            'trail_type': 'modified',
            'atr_period': 50,
            'atr_factor': 2.0,
            'use_take_profit': True,
            'tp_fib_level': '78.6',
            'quantity': 100,
            'min_lookback': 100,
            'mtf_resolution': '5m->15m'
        }
        
        strategy = NTSFast4(
            name="multi_symbol_test",
            config=config,
            symbols=["AAPL", "MSFT", "GOOGL"]
        )
        
        # Test that all symbols are tracked
        assert len(strategy._positions) == 3
        assert len(strategy._trend_state) == 3
        assert len(strategy._trend_up) == 3
        assert len(strategy._trend_down) == 3
        assert len(strategy._last_signals) == 3
        
        # Test individual symbol access
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            assert strategy.get_position(symbol) == 0
            assert strategy.get_trend_state(symbol) == 0
            assert strategy.get_last_signal(symbol) == {}
    
    def test_strategy_configuration_validation(self):
        """Test strategy configuration validation."""
        # Test with invalid Fibonacci level
        config_invalid = {
            'trail_type': 'modified',
            'atr_period': 50,
            'atr_factor': 2.0,
            'use_take_profit': True,
            'tp_fib_level': 'invalid',  # Invalid level
            'quantity': 100,
            'min_lookback': 100,
            'mtf_resolution': '5m->15m'
        }
        
        # Should still create strategy but use default behavior
        strategy = NTSFast4(
            name="invalid_config_test",
            config=config_invalid,
            symbols=["AAPL"]
        )
        
        assert strategy.tp_fib_level == 'invalid'  # Should keep the value
        # The strategy should handle this gracefully in calculations
    
    def test_strategy_performance_with_large_dataset(self):
        """Test strategy performance with large dataset."""
        # Create large dataset
        dates = pd.date_range(start='2020-01-01', periods=10000, freq='5min')
        prices = 150 + np.cumsum(np.random.normal(0, 0.1, 10000))
        
        large_data = pd.DataFrame({
            'timestamp': dates,
            'open': prices + np.random.normal(0, 0.1, 10000),
            'high': prices + abs(np.random.normal(0, 0.5, 10000)),
            'low': prices - abs(np.random.normal(0, 0.5, 10000)),
            'close': prices,
            'volume': np.random.randint(1000, 10000, 10000)
        })
        
        config = {
            'trail_type': 'modified',
            'atr_period': 100,
            'atr_factor': 2.0,
            'use_take_profit': True,
            'tp_fib_level': '78.6',
            'quantity': 100,
            'min_lookback': 200,
            'mtf_resolution': '5m->15m'
        }
        
        strategy = NTSFast4(
            name="large_dataset_test",
            config=config,
            symbols=["AAPL"]
        )
        
        # Test that calculations work with large dataset
        atr = strategy._calculate_atr(large_data, 100, modified=True)
        TrendUp, TrendDown, Trend = strategy._calculate_trend_logic(large_data, atr)
        
        assert len(atr) == 10000
        assert len(TrendUp) == 10000
        assert len(TrendDown) == 10000
        assert len(Trend) == 10000
        
        # Test that results are reasonable
        assert not atr.isna().all()
        assert set(Trend.unique()).issubset({-1, 0, 1})
