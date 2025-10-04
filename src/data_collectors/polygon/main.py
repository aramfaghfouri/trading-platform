"""
Main entry point for Polygon Data Collector
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from .client import PolygonClient
from .ticker_collector import TickerCollector
from .data_processor import TickerDataProcessor
from .config import PolygonConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PolygonDataService:
    """Main service class for Polygon data collection"""
    
    def __init__(self):
        self.config = PolygonConfig()
        self.config.validate()
        
        self.collector = TickerCollector(self.config.api_key)
        self.processor = TickerDataProcessor()
        
        # Create data directory if it doesn't exist
        os.makedirs(self.config.data_storage_path, exist_ok=True)
    
    async def collect_ticker_data(self, tickers: List[str], days_back: int = None) -> List[Dict[str, Any]]:
        """Collect data for specified tickers"""
        if days_back is None:
            days_back = self.config.default_days_back
        
        logger.info(f"Starting data collection for {len(tickers)} tickers")
        
        try:
            # Collect data
            collected_data = await self.collector.collect_multiple_tickers(tickers, days_back)
            
            # Process data
            processed_data = []
            for data in collected_data:
                processed = self.processor.process_historical_data(data)
                if processed:
                    processed_data.append(processed)
            
            # Export data
            if self.config.enable_csv_export:
                csv_filename = os.path.join(
                    self.config.data_storage_path,
                    f"ticker_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                self.collector.export_to_csv(csv_filename)
                logger.info(f"Data exported to {csv_filename}")
            
            logger.info(f"Successfully collected and processed data for {len(processed_data)} tickers")
            return processed_data
            
        except Exception as e:
            logger.error(f"Failed to collect ticker data: {e}")
            raise
    
    async def collect_top_tickers(self, limit: int = 100, days_back: int = None) -> List[Dict[str, Any]]:
        """Collect data for top tickers by volume"""
        logger.info(f"Collecting data for top {limit} tickers")
        
        try:
            # Get top tickers
            top_tickers = self.collector.get_top_tickers(limit)
            
            if not top_tickers:
                logger.warning("No top tickers found")
                return []
            
            # Collect data for top tickers
            return await self.collect_ticker_data(top_tickers, days_back)
            
        except Exception as e:
            logger.error(f"Failed to collect top tickers data: {e}")
            raise
    
    async def search_and_collect(self, search_term: str, limit: int = 50, days_back: int = None) -> List[Dict[str, Any]]:
        """Search for tickers and collect data"""
        logger.info(f"Searching for tickers with term: {search_term}")
        
        try:
            # Search for tickers
            search_results = self.collector.search_tickers(search_term, limit)
            
            if not search_results:
                logger.warning(f"No tickers found for search term: {search_term}")
                return []
            
            # Extract ticker symbols
            tickers = [result['ticker'] for result in search_results]
            
            # Collect data
            return await self.collect_ticker_data(tickers, days_back)
            
        except Exception as e:
            logger.error(f"Failed to search and collect data: {e}")
            raise
    
    def get_market_status(self) -> Dict[str, Any]:
        """Get current market status"""
        return self.collector.get_market_status()
    
    def generate_report(self, processed_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate analysis report"""
        return self.processor.generate_summary_report(processed_data)

async def main():
    """Main function for command line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Polygon Data Collector')
    parser.add_argument('--tickers', nargs='+', help='Ticker symbols to collect data for')
    parser.add_argument('--search', type=str, help='Search term for tickers')
    parser.add_argument('--top', type=int, help='Number of top tickers to collect')
    parser.add_argument('--days', type=int, default=30, help='Number of days back to collect data')
    parser.add_argument('--limit', type=int, default=100, help='Limit for search results')
    
    args = parser.parse_args()
    
    # Initialize service
    service = PolygonDataService()
    
    try:
        if args.tickers:
            # Collect data for specific tickers
            data = await service.collect_ticker_data(args.tickers, args.days)
        elif args.search:
            # Search and collect data
            data = await service.search_and_collect(args.search, args.limit, args.days)
        elif args.top:
            # Collect top tickers
            data = await service.collect_top_tickers(args.top, args.days)
        else:
            # Default: collect top 50 tickers
            data = await service.collect_top_tickers(50, args.days)
        
        # Generate report
        report = service.generate_report(data)
        logger.info(f"Analysis report: {report}")
        
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
