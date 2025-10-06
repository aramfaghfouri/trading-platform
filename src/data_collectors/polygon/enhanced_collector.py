"""
Enhanced Polygon.io Data Collector

This module provides a comprehensive data collection system for Polygon.io
with advanced features including rate limiting, error handling, data validation,
and integration with the configuration system.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np
from loguru import logger
from polygon import StocksClient, ReferenceClient
from ratelimit import limits, sleep_and_retry
import httpx
from pydantic import BaseModel, Field

from core.config_loader import get_polygon_config, PolygonConfig
from core.config_models import PolygonDataQualityConfig


class DataType(str, Enum):
    """Supported data types."""
    TRADES = "trades"
    QUOTES = "quotes"
    BARS = "bars"
    TRADES_NBBO = "trades_nbbo"
    LAST_QUOTE = "last_quote"
    LAST_TRADE = "last_trade"


class Timeframe(str, Enum):
    """Supported timeframes."""
    MINUTE_1 = "1min"
    MINUTE_5 = "5min"
    MINUTE_15 = "15min"
    MINUTE_30 = "30min"
    HOUR_1 = "1hour"
    HOUR_2 = "2hour"
    HOUR_4 = "4hour"
    DAY_1 = "1day"


@dataclass
class DataCollectionResult:
    """Result of data collection operation."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RateLimitInfo:
    """Rate limit information."""
    requests_per_minute: int
    requests_per_second: float
    last_request_time: float = 0.0
    request_count: int = 0
    window_start: float = 0.0


class PolygonDataValidator:
    """Data validation and quality checks for Polygon.io data."""
    
    def __init__(self, quality_config: PolygonDataQualityConfig):
        self.config = quality_config
        
    def validate_bar_data(self, data: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Validate bar data quality.
        
        Args:
            data: List of bar data dictionaries
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        if not data:
            return True, errors
            
        for i, bar in enumerate(data):
            # Check required fields
            required_fields = ['t', 'o', 'h', 'l', 'c', 'v']
            for field in required_fields:
                if field not in bar:
                    errors.append(f"Bar {i}: Missing required field '{field}'")
                    
            # Check data types and ranges
            if 'o' in bar and not isinstance(bar['o'], (int, float)):
                errors.append(f"Bar {i}: Open price must be numeric")
            if 'h' in bar and not isinstance(bar['h'], (int, float)):
                errors.append(f"Bar {i}: High price must be numeric")
            if 'l' in bar and not isinstance(bar['l'], (int, float)):
                errors.append(f"Bar {i}: Low price must be numeric")
            if 'c' in bar and not isinstance(bar['c'], (int, float)):
                errors.append(f"Bar {i}: Close price must be numeric")
            if 'v' in bar and not isinstance(bar['v'], (int, float)):
                errors.append(f"Bar {i}: Volume must be numeric")
                
            # Check price relationships
            if all(field in bar for field in ['o', 'h', 'l', 'c']):
                if bar['h'] < max(bar['o'], bar['c']):
                    errors.append(f"Bar {i}: High price is less than open/close")
                if bar['l'] > min(bar['o'], bar['c']):
                    errors.append(f"Bar {i}: Low price is greater than open/close")
                    
            # Check volume threshold
            if 'v' in bar and bar['v'] < self.config.min_volume_threshold:
                errors.append(f"Bar {i}: Volume below threshold ({bar['v']} < {self.config.min_volume_threshold})")
                
        return len(errors) == 0, errors
    
    def detect_outliers(self, data: List[Dict[str, Any]], field: str = 'c') -> List[int]:
        """
        Detect outliers in price data using IQR method.
        
        Args:
            data: List of bar data
            field: Field to check for outliers
            
        Returns:
            List of indices with outliers
        """
        if not data or len(data) < 4:
            return []
            
        values = [bar.get(field, 0) for bar in data if field in bar]
        if len(values) < 4:
            return []
            
        q1 = np.percentile(values, 25)
        q3 = np.percentile(values, 75)
        iqr = q3 - q1
        
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        outliers = []
        for i, value in enumerate(values):
            if value < lower_bound or value > upper_bound:
                outliers.append(i)
                
        return outliers
    
    def validate_price_deviation(self, data: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Validate price deviations from previous close.
        
        Args:
            data: List of bar data
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        if not data or len(data) < 2:
            return True, errors
            
        for i in range(1, len(data)):
            current_bar = data[i]
            previous_bar = data[i-1]
            
            if 'c' in current_bar and 'c' in previous_bar:
                current_price = current_bar['c']
                previous_price = previous_bar['c']
                
                if previous_price > 0:
                    deviation = abs(current_price - previous_price) / previous_price
                    if deviation > self.config.max_price_deviation:
                        errors.append(
                            f"Bar {i}: Price deviation too high "
                            f"({deviation:.2%} > {self.config.max_price_deviation:.2%})"
                        )
                        
        return len(errors) == 0, errors


class PolygonRateLimiter:
    """Rate limiter for Polygon.io API requests."""
    
    def __init__(self, config: PolygonConfig):
        self.config = config
        self.rate_limit_info = RateLimitInfo(
            requests_per_minute=config.data_collection.max_requests_per_minute,
            requests_per_second=config.data_collection.max_requests_per_minute / 60.0
        )
        
    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded."""
        current_time = time.time()
        
        # Reset window if needed
        if current_time - self.rate_limit_info.window_start >= 60:
            self.rate_limit_info.window_start = current_time
            self.rate_limit_info.request_count = 0
            
        # Check if we need to wait
        if self.rate_limit_info.request_count >= self.rate_limit_info.requests_per_minute:
            wait_time = 60 - (current_time - self.rate_limit_info.window_start)
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
                self.rate_limit_info.window_start = time.time()
                self.rate_limit_info.request_count = 0
                
        # Per-second rate limiting
        time_since_last = current_time - self.rate_limit_info.last_request_time
        min_interval = 1.0 / self.rate_limit_info.requests_per_second
        
        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last
            await asyncio.sleep(wait_time)
            
        self.rate_limit_info.last_request_time = time.time()
        self.rate_limit_info.request_count += 1


class PolygonDataCollector:
    """Enhanced Polygon.io data collector with comprehensive features."""
    
    def __init__(self, config: Optional[PolygonConfig] = None):
        """
        Initialize the data collector.
        
        Args:
            config: Polygon.io configuration (if None, loads from config system)
        """
        self.config = config or get_polygon_config()
        self.stocks_client = StocksClient(api_key=self.config.api.api_key)
        self.reference_client = ReferenceClient(api_key=self.config.api.api_key)
        self.rate_limiter = PolygonRateLimiter(self.config)
        self.validator = PolygonDataValidator(self.config.quality)
        self.session = httpx.AsyncClient(
            timeout=self.config.api.timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
        
        logger.info(f"Initialized Polygon data collector for {self.config.api.base_url}")
        
    async def __aenter__(self):
        """Async context manager entry."""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.session.aclose()
        
    async def get_aggregates(
        self,
        symbol: str,
        multiplier: int,
        timespan: Timeframe,
        from_date: Union[str, datetime],
        to_date: Union[str, datetime],
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000
    ) -> DataCollectionResult:
        """
        Get aggregate bars for a symbol.
        
        Args:
            symbol: Stock symbol
            multiplier: Size of the timespan multiplier
            timespan: Size of the time window
            from_date: Start date (YYYY-MM-DD or datetime)
            to_date: End date (YYYY-MM-DD or datetime)
            adjusted: Whether results are adjusted for splits
            sort: Sort order (asc/desc)
            limit: Maximum number of results
            
        Returns:
            DataCollectionResult with bars data
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            # Convert dates to string format
            if isinstance(from_date, datetime):
                from_date = from_date.strftime('%Y-%m-%d')
            if isinstance(to_date, datetime):
                to_date = to_date.strftime('%Y-%m-%d')
                
            # Make API request
            response = self.stocks_client.get_aggregate_bars(
                symbol=symbol,
                multiplier=multiplier,
                timespan=timespan.value.replace('1', ''),  # Convert "1day" to "day"
                from_date=from_date,
                to_date=to_date,
                adjusted=adjusted,
                sort=sort,
                limit=limit
            )
            
            
            if not response:
                return DataCollectionResult(
                    success=False,
                    error="No data returned from API"
                )
                
            # Extract results
            if isinstance(response, dict):
                results = response.get('results', [])
            else:
                results = response.results if hasattr(response, 'results') else []
            
            # Validate data quality
            if self.config.quality.validate_data and results:
                is_valid, errors = self.validator.validate_bar_data(results)
                if not is_valid:
                    logger.warning(f"Data validation failed for {symbol}: {errors}")
                    if self.config.quality.outlier_detection:
                        outliers = self.validator.detect_outliers(results)
                        if outliers:
                            logger.warning(f"Outliers detected in {symbol} at indices: {outliers}")
                            
            # Check price deviation
            if self.config.quality.validate_data and results:
                is_valid, errors = self.validator.validate_price_deviation(results)
                if not is_valid:
                    logger.warning(f"Price deviation validation failed for {symbol}: {errors}")
                    
            # Prepare response data
            if isinstance(response, dict):
                data = {
                    'symbol': symbol,
                    'results': results,
                    'count': len(results),
                    'next_url': response.get('next_url'),
                    'request_id': response.get('request_id')
                }
            else:
                data = {
                    'symbol': symbol,
                    'results': results,
                    'count': len(results),
                    'next_url': getattr(response, 'next_url', None),
                    'request_id': getattr(response, 'request_id', None)
                }
            
            metadata = {
                'multiplier': multiplier,
                'timespan': timespan.value,
                'from_date': from_date,
                'to_date': to_date,
                'adjusted': adjusted,
                'sort': sort,
                'limit': limit
            }
            
            logger.info(f"Successfully collected {len(results)} bars for {symbol}")
            
            return DataCollectionResult(
                success=True,
                data=data,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to get aggregates for {symbol}: {e}")
            return DataCollectionResult(
                success=False,
                error=str(e)
            )
    
    async def get_ticker_details(self, symbol: str) -> DataCollectionResult:
        """
        Get detailed information about a ticker.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            DataCollectionResult with ticker details
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            response = self.reference_client.get_ticker_details(symbol=symbol)
            
            if not response:
                return DataCollectionResult(
                    success=False,
                    error="No ticker details returned"
                )
                
            data = {
                'symbol': symbol,
                'details': response.results if hasattr(response, 'results') else response
            }
            
            logger.info(f"Successfully collected ticker details for {symbol}")
            
            return DataCollectionResult(
                success=True,
                data=data
            )
            
        except Exception as e:
            logger.error(f"Failed to get ticker details for {symbol}: {e}")
            return DataCollectionResult(
                success=False,
                error=str(e)
            )
    
    async def get_ticker_news(
        self,
        symbol: str,
        limit: int = 100,
        order: str = "desc"
    ) -> DataCollectionResult:
        """
        Get news for a specific ticker.
        
        Args:
            symbol: Stock symbol
            limit: Maximum number of news articles
            order: Sort order (asc/desc)
            
        Returns:
            DataCollectionResult with news data
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            response = self.reference_client.get_ticker_news(
                symbol=symbol,
                limit=limit,
                order=order
            )
            
            if not response:
                return DataCollectionResult(
                    success=False,
                    error="No news returned"
                )
                
            results = response.results if hasattr(response, 'results') else []
            
            data = {
                'symbol': symbol,
                'news': results,
                'count': len(results)
            }
            
            metadata = {
                'limit': limit,
                'order': order
            }
            
            logger.info(f"Successfully collected {len(results)} news articles for {symbol}")
            
            return DataCollectionResult(
                success=True,
                data=data,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to get news for {symbol}: {e}")
            return DataCollectionResult(
                success=False,
                error=str(e)
            )
    
    async def get_grouped_daily(
        self,
        date: Union[str, datetime],
        adjusted: bool = True
    ) -> DataCollectionResult:
        """
        Get grouped daily bars for all tickers on a specific date.
        
        Args:
            date: Date (YYYY-MM-DD or datetime)
            adjusted: Whether results are adjusted for splits
            
        Returns:
            DataCollectionResult with grouped daily data
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            if isinstance(date, datetime):
                date = date.strftime('%Y-%m-%d')
                
            response = self.stocks_client.get_grouped_daily_bars(
                date=date,
                adjusted=adjusted
            )
            
            if not response:
                return DataCollectionResult(
                    success=False,
                    error="No grouped daily data returned"
                )
                
            results = response.results if hasattr(response, 'results') else []
            
            data = {
                'date': date,
                'results': results,
                'count': len(results)
            }
            
            metadata = {
                'adjusted': adjusted
            }
            
            logger.info(f"Successfully collected grouped daily data for {date}: {len(results)} tickers")
            
            return DataCollectionResult(
                success=True,
                data=data,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to get grouped daily data for {date}: {e}")
            return DataCollectionResult(
                success=False,
                error=str(e)
            )
    
    async def get_market_status(self) -> DataCollectionResult:
        """
        Get current market status.
        
        Returns:
            DataCollectionResult with market status
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            response = self.reference_client.get_market_status()
            
            if not response:
                return DataCollectionResult(
                    success=False,
                    error="No market status returned"
                )
                
            data = {
                'market': response.market if hasattr(response, 'market') else response,
                'serverTime': response.serverTime if hasattr(response, 'serverTime') else None
            }
            
            logger.info("Successfully collected market status")
            
            return DataCollectionResult(
                success=True,
                data=data
            )
            
        except Exception as e:
            logger.error(f"Failed to get market status: {e}")
            return DataCollectionResult(
                success=False,
                error=str(e)
            )
    
    async def collect_historical_data(
        self,
        symbols: List[str],
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        timeframe: Timeframe = Timeframe.DAY_1,
        batch_size: int = 10
    ) -> Dict[str, DataCollectionResult]:
        """
        Collect historical data for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            start_date: Start date
            end_date: End date
            timeframe: Data timeframe
            batch_size: Number of symbols to process concurrently
            
        Returns:
            Dictionary mapping symbols to DataCollectionResult
        """
        results = {}
        
        # Process symbols in batches
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Create tasks for concurrent processing
            tasks = []
            for symbol in batch:
                task = self.get_aggregates(
                    symbol=symbol,
                    multiplier=1,
                    timespan=timeframe,
                    from_date=start_date,
                    to_date=end_date
                )
                tasks.append((symbol, task))
            
            # Execute batch concurrently
            batch_results = await asyncio.gather(
                *[task for _, task in tasks],
                return_exceptions=True
            )
            
            # Process results
            for (symbol, _), result in zip(tasks, batch_results):
                if isinstance(result, Exception):
                    results[symbol] = DataCollectionResult(
                        success=False,
                        error=str(result)
                    )
                else:
                    results[symbol] = result
                    
            # Log batch progress
            successful = sum(1 for r in results.values() if r.success)
            logger.info(f"Batch {i//batch_size + 1}: {successful}/{len(batch)} symbols successful")
            
        return results
    
    def to_dataframe(self, result: DataCollectionResult) -> Optional[pd.DataFrame]:
        """
        Convert DataCollectionResult to pandas DataFrame.
        
        Args:
            result: DataCollectionResult with bars data
            
        Returns:
            DataFrame with OHLCV data or None if conversion fails
        """
        if not result.success or not result.data or 'results' not in result.data:
            return None
            
        bars = result.data['results']
        if not bars:
            return pd.DataFrame()
            
        # Convert to DataFrame
        df = pd.DataFrame(bars)
        
        # Rename columns to standard format
        column_mapping = {
            't': 'timestamp',
            'o': 'open',
            'h': 'high',
            'l': 'low',
            'c': 'close',
            'v': 'volume',
            'vw': 'vwap',
            'n': 'transactions'
        }
        
        df = df.rename(columns=column_mapping)
        
        # Convert timestamp to datetime
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
        return df
    
    async def close(self):
        """Close the HTTP session."""
        await self.session.aclose()
        logger.info("Polygon data collector session closed")


# Convenience functions for easy usage
async def collect_symbol_data(
    symbol: str,
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    timeframe: Timeframe = Timeframe.DAY_1,
    config: Optional[PolygonConfig] = None
) -> DataCollectionResult:
    """
    Convenience function to collect data for a single symbol.
    
    Args:
        symbol: Stock symbol
        start_date: Start date
        end_date: End date
        timeframe: Data timeframe
        config: Optional configuration
        
    Returns:
        DataCollectionResult
    """
    async with PolygonDataCollector(config) as collector:
        return await collector.get_aggregates(
            symbol=symbol,
            multiplier=1,
            timespan=timeframe,
            from_date=start_date,
            to_date=end_date
        )


async def collect_multiple_symbols(
    symbols: List[str],
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    timeframe: Timeframe = Timeframe.DAY_1,
    batch_size: int = 10,
    config: Optional[PolygonConfig] = None
) -> Dict[str, DataCollectionResult]:
    """
    Convenience function to collect data for multiple symbols.
    
    Args:
        symbols: List of stock symbols
        start_date: Start date
        end_date: End date
        timeframe: Data timeframe
        batch_size: Batch size for concurrent processing
        config: Optional configuration
        
    Returns:
        Dictionary mapping symbols to DataCollectionResult
    """
    async with PolygonDataCollector(config) as collector:
        return await collector.collect_historical_data(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            batch_size=batch_size
        )
