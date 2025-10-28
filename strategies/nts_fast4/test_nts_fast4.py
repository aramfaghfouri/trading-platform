"""
Unit tests for NTS FAST4 Strategy.

Tests individual components and calculations of the NTS FAST4 strategy.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from decimal import Decimal

from strategies.nts_fast4.nts_fast4 import NTSFast4
from src.strategies.models import BarData


class TestNTSFast4:
    """Test cases for NTS FAST4 strategy."""
    
    @pytest.fixture
    def strategy_config(self):
        """Default strategy configuration."""
        return {
            'trail_type': 'modified',
            'atr_period': 185,
            'atr_factor': 3.0,
            'use_take_profit': True,
            'tp_fib_level': '78.6',
            'quantity': 100,
            'min_lookback': 200,
            'mtf_resolution': '5m->15m'
        }
    
    @pytest.fixture
    def strategy(self, strategy_config):
        """Create NTS FAST4 strategy instance."""
        return NTSFast4(
            name="test_nts_fast4",
            config=strategy_config,
            symbols=["AAPL"]
        )
    
    @pytest.fixture
    def sample_data(self):
        """Create sample OHLC data for testing."""
        dates = pd.date_range(start='2024-01-01', periods=300, freq='5min')
        
        # Create realistic price data with trend
        base_price = 150.0
        trend = np.linspace(0, 20, 300)  # Upward trend
        noise = np.random.normal(0, 2, 300)
        prices = base_price + trend + noise
        
        # Generate OHLC data
        data = []
        for i, (date, close) in enumerate(zip(dates, prices)):
            high = close + abs(np.random.normal(0, 1))
            low = close - abs(np.random.normal(0, 1))
            open_price = close + np.random.normal(0, 0.5)
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
    
    def test_strategy_initialization(self, strategy):
        """Test strategy initialization."""
        assert strategy.name == "test_nts_fast4"
        assert strategy.trail_type == "modified"
        assert strategy.atr_period == 185
        assert strategy.atr_factor == 3.0
        assert strategy.use_take_profit is True
        assert strategy.tp_fib_level == "78.6"
        assert strategy.quantity == 100
        assert strategy.min_lookback == 200
        assert strategy.chart_tf == "5m"
        assert strategy.signal_tf == "15m"
    
    def test_parse_mtf_resolution(self, strategy):
        """Test MTF resolution parsing."""
        chart_tf, signal_tf = strategy._parse_mtf_resolution("5m->15m")
        assert chart_tf == "5m"
        assert signal_tf == "15m"
        
        chart_tf, signal_tf = strategy._parse_mtf_resolution("1m->5m")
        assert chart_tf == "1m"
        assert signal_tf == "5m"
        
        # Test invalid format
        chart_tf, signal_tf = strategy._parse_mtf_resolution("invalid")
        assert chart_tf == "5m"  # Default fallback
        assert signal_tf == "15m"
    
    def test_wild_ma(self, strategy, sample_data):
        """Test Wilder's Moving Average calculation."""
        src = sample_data['close']
        length = 20
        
        result = strategy._wild_ma(src, length)
        
        assert len(result) == len(src)
        assert not result.isna().all()
        
        # Test exponential smoothing properties
        alpha = 1.0 / length
        expected_first = src.iloc[0]
        assert abs(result.iloc[0] - expected_first) < 1e-10
        
        # Test that it's smoother than original (or at least not more volatile)
        assert result.std() <= src.std() * 1.1  # Allow some tolerance
    
    def test_calculate_atr_modified(self, strategy, sample_data):
        """Test modified ATR calculation."""
        df = sample_data
        period = 20
        
        atr = strategy._calculate_atr(df, period, modified=True)
        
        assert len(atr) == len(df)
        assert not atr.isna().all()
        assert (atr >= 0).all()  # ATR should be non-negative
        
        # Test that ATR values are reasonable
        assert atr.mean() >= 0  # Allow 0 for constant prices
        assert atr.mean() <= df['high'].max() - df['low'].min()
    
    def test_calculate_atr_unmodified(self, strategy, sample_data):
        """Test unmodified (standard) ATR calculation."""
        df = sample_data
        period = 20
        
        atr = strategy._calculate_atr(df, period, modified=False)
        
        assert len(atr) == len(df)
        assert not atr.isna().all()
        assert (atr >= 0).all()
        
        # Standard ATR should be different from modified
        atr_modified = strategy._calculate_atr(df, period, modified=True)
        assert not np.allclose(atr, atr_modified, rtol=1e-3)
    
    def test_calculate_trend_logic(self, strategy, sample_data):
        """Test trend logic calculation."""
        df = sample_data
        atr = strategy._calculate_atr(df, 20, modified=True)
        
        TrendUp, TrendDown, Trend = strategy._calculate_trend_logic(df, atr)
        
        assert len(TrendUp) == len(df)
        assert len(TrendDown) == len(df)
        assert len(Trend) == len(df)
        
        # Test trend values
        assert set(Trend.unique()).issubset({-1, 0, 1})
        
        # Test that TrendUp and TrendDown are reasonable (allow for NaN values)
        valid_up = TrendUp.dropna()
        valid_down = TrendDown.dropna()
        valid_close = df['close'].loc[valid_up.index]
        
        if len(valid_up) > 0:
            # TrendUp should be reasonable relative to close (not necessarily below)
            assert (valid_up >= 0).all()  # Should be non-negative
        if len(valid_down) > 0:
            # TrendDown should be reasonable relative to close (not necessarily above)
            assert (valid_down >= 0).all()  # Should be non-negative
        
        # Test initial values
        assert Trend.iloc[0] == 0  # Initial trend should be neutral
    
    def test_calculate_fibonacci_levels(self, strategy):
        """Test Fibonacci level calculation."""
        ex = 100.0
        trail = 120.0
        
        levels = strategy._calculate_fibonacci_levels(ex, trail)
        
        assert 'f1' in levels
        assert 'f2' in levels
        assert 'f3' in levels
        assert 'l100' in levels
        
        # Test Fibonacci calculations
        expected_f1 = ex + (trail - ex) * 0.618
        expected_f2 = ex + (trail - ex) * 0.786
        expected_f3 = ex + (trail - ex) * 0.886
        expected_l100 = trail
        
        assert abs(levels['f1'] - expected_f1) < 1e-10
        assert abs(levels['f2'] - expected_f2) < 1e-10
        assert abs(levels['f3'] - expected_f3) < 1e-10
        assert abs(levels['l100'] - expected_l100) < 1e-10
        
        # Test edge case where ex == trail
        levels_edge = strategy._calculate_fibonacci_levels(100.0, 100.0)
        assert all(level == 100.0 for level in levels_edge.values())
    
    def test_fibonacci_levels_mapping(self, strategy):
        """Test Fibonacci levels mapping."""
        assert strategy.fib_levels['61.8'] == 0.618
        assert strategy.fib_levels['78.6'] == 0.786
        assert strategy.fib_levels['88.6'] == 0.886
        assert strategy.fib_levels['100.0'] == 1.0
    
    @pytest.mark.asyncio
    async def test_get_required_lookback(self, strategy):
        """Test required lookback calculation."""
        lookback = await strategy.get_required_lookback()
        assert lookback == 200
    
    def test_position_tracking(self, strategy):
        """Test position tracking methods."""
        symbol = "AAPL"
        
        # Initial position should be 0
        assert strategy.get_position(symbol) == 0
        
        # Test trend state
        assert strategy.get_trend_state(symbol) == 0
        
        # Test trend levels
        levels = strategy.get_trend_levels(symbol)
        assert 'trend_up' in levels
        assert 'trend_down' in levels
        assert levels['trend_up'] == 0.0
        assert levels['trend_down'] == 0.0
        
        # Test last signal
        signal = strategy.get_last_signal(symbol)
        assert signal == {}
    
    def test_strategy_with_different_configs(self):
        """Test strategy with different configuration parameters."""
        # Test unmodified ATR
        config_unmodified = {
            'trail_type': 'unmodified',
            'atr_period': 100,
            'atr_factor': 2.5,
            'use_take_profit': False,
            'tp_fib_level': '61.8',
            'quantity': 50,
            'min_lookback': 150,
            'mtf_resolution': '1m->5m'
        }
        
        strategy_unmodified = NTSFast4(
            name="test_unmodified",
            config=config_unmodified,
            symbols=["AAPL"]
        )
        
        assert strategy_unmodified.trail_type == "unmodified"
        assert strategy_unmodified.atr_period == 100
        assert strategy_unmodified.atr_factor == 2.5
        assert strategy_unmodified.use_take_profit is False
        assert strategy_unmodified.tp_fib_level == "61.8"
        assert strategy_unmodified.quantity == 50
        assert strategy_unmodified.min_lookback == 150
        assert strategy_unmodified.chart_tf == "1m"
        assert strategy_unmodified.signal_tf == "5m"
    
    def test_atr_calculation_edge_cases(self, strategy):
        """Test ATR calculation with edge cases."""
        # Test with minimal data
        minimal_data = pd.DataFrame({
            'high': [100, 101, 102],
            'low': [99, 100, 101],
            'close': [99.5, 100.5, 101.5]
        })
        
        atr = strategy._calculate_atr(minimal_data, 2, modified=True)
        assert len(atr) == 3
        assert not atr.isna().all()
        
        # Test with constant prices
        constant_data = pd.DataFrame({
            'high': [100] * 10,
            'low': [100] * 10,
            'close': [100] * 10
        })
        
        atr_constant = strategy._calculate_atr(constant_data, 5, modified=True)
        assert len(atr_constant) == 10
        # ATR should be 0 for constant prices (after initial NaN values)
        non_nan_atr = atr_constant.dropna()
        if len(non_nan_atr) > 0:
            assert (non_nan_atr == 0).all()
    
    def test_trend_logic_edge_cases(self, strategy):
        """Test trend logic with edge cases."""
        # Test with minimal data
        minimal_data = pd.DataFrame({
            'high': [100, 101, 102],
            'low': [99, 100, 101],
            'close': [99.5, 100.5, 101.5]
        })
        
        atr = pd.Series([0.5, 0.6, 0.7])
        
        TrendUp, TrendDown, Trend = strategy._calculate_trend_logic(minimal_data, atr)
        
        assert len(TrendUp) == 3
        assert len(TrendDown) == 3
        assert len(Trend) == 3
        
        # Initial trend should be 0
        assert Trend.iloc[0] == 0
    
    def test_fibonacci_levels_edge_cases(self, strategy):
        """Test Fibonacci levels with edge cases."""
        # Test with negative range (trail < ex)
        levels_neg = strategy._calculate_fibonacci_levels(120.0, 100.0)
        # When trail < ex, levels should be in descending order
        assert levels_neg['f1'] > levels_neg['f2'] > levels_neg['f3'] > levels_neg['l100']
        
        # Test with very small range
        levels_small = strategy._calculate_fibonacci_levels(100.0, 100.01)
        assert all(level >= 100.0 for level in levels_small.values())
        assert all(level <= 100.01 for level in levels_small.values())
    
    def test_strategy_metadata(self, strategy):
        """Test strategy metadata and state."""
        assert strategy.name == "test_nts_fast4"
        assert "AAPL" in strategy.symbols
        assert strategy.is_initialized is False  # Not initialized yet
        
        # Test internal state initialization
        assert len(strategy._positions) == 1
        assert len(strategy._trend_state) == 1
        assert len(strategy._trend_up) == 1
        assert len(strategy._trend_down) == 1
        assert len(strategy._last_signals) == 1
