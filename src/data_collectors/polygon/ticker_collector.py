"""
Ticker Data Collector
Collects and processes ticker data from Polygon.io
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from .client import PolygonClient

logger = logging.getLogger(__name__)

class TickerCollector:
    def __init__(self, api_key: str):
        self.client = PolygonClient(api_key)
        self.collected_data = []
        
    async def collect_ticker_data(self, ticker: str, days_back: int = 30) -> Dict[str, Any]:
        """Collect comprehensive data for a ticker"""
        try:
            # Get ticker details
            details = self.client.get_ticker_details(ticker)
            
            # Get historical data
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
            
            aggregates = self.client.get_aggregates(
                ticker=ticker,
                multiplier=1,
                timespan='day',
                from_date=from_date,
                to_date=to_date
            )
            
            # Get recent news
            news = self.client.get_ticker_news(ticker, limit=10)
            
            # Combine all data
            ticker_data = {
                'ticker': ticker,
                'details': details,
                'historical_data': aggregates,
                'news': news,
                'collected_at': datetime.now().isoformat()
            }
            
            self.collected_data.append(ticker_data)
            logger.info(f"Successfully collected data for {ticker}")
            
            return ticker_data
            
        except Exception as e:
            logger.error(f"Failed to collect data for {ticker}: {e}")
            raise
    
    async def collect_multiple_tickers(self, tickers: List[str], days_back: int = 30) -> List[Dict[str, Any]]:
        """Collect data for multiple tickers concurrently"""
        tasks = [self.collect_ticker_data(ticker, days_back) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        successful_results = [r for r in results if not isinstance(r, Exception)]
        failed_count = len(results) - len(successful_results)
        
        if failed_count > 0:
            logger.warning(f"Failed to collect data for {failed_count} tickers")
        
        return successful_results
    
    def get_top_tickers(self, limit: int = 100) -> List[str]:
        """Get top tickers by market cap or volume"""
        try:
            # Get grouped daily data for today
            today = datetime.now().strftime('%Y-%m-%d')
            grouped_data = self.client.get_grouped_daily(today)
            
            if 'results' in grouped_data:
                # Sort by volume and get top tickers
                results = grouped_data['results']
                sorted_results = sorted(results, key=lambda x: x.get('v', 0), reverse=True)
                return [result['T'] for result in sorted_results[:limit]]
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to get top tickers: {e}")
            return []
    
    def search_tickers(self, search_term: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Search for tickers by name or symbol"""
        try:
            return self.client.search_tickers(search_term, limit=limit)
        except Exception as e:
            logger.error(f"Failed to search tickers: {e}")
            return []
    
    def get_market_status(self) -> Dict[str, Any]:
        """Get current market status"""
        try:
            return self.client.get_market_status()
        except Exception as e:
            logger.error(f"Failed to get market status: {e}")
            return {}
    
    def export_to_csv(self, filename: str = None) -> str:
        """Export collected data to CSV"""
        if not self.collected_data:
            logger.warning("No data to export")
            return ""
        
        if filename is None:
            filename = f"ticker_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Flatten data for CSV export
        flattened_data = []
        for data in self.collected_data:
            flattened_data.append({
                'ticker': data['ticker'],
                'name': data['details'].get('results', {}).get('name', ''),
                'market': data['details'].get('results', {}).get('market', ''),
                'locale': data['details'].get('results', {}).get('locale', ''),
                'primary_exchange': data['details'].get('results', {}).get('primary_exchange', ''),
                'type': data['details'].get('results', {}).get('type', ''),
                'active': data['details'].get('results', {}).get('active', False),
                'collected_at': data['collected_at']
            })
        
        df = pd.DataFrame(flattened_data)
        df.to_csv(filename, index=False)
        logger.info(f"Data exported to {filename}")
        
        return filename
    
    def get_collected_data(self) -> List[Dict[str, Any]]:
        """Get all collected data"""
        return self.collected_data
    
    def clear_data(self):
        """Clear collected data"""
        self.collected_data = []
        logger.info("Collected data cleared")
