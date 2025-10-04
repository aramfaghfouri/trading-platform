"""
Polygon.io API Client
Handles authentication and API requests to Polygon.io
"""

import requests
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class PolygonClient:
    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.rate_limit_delay = 0.1  # 100ms between requests
        
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make authenticated request to Polygon API"""
        if params is None:
            params = {}
            
        params['apikey'] = self.api_key
        url = f"{self.base_url}{endpoint}"
        
        try:
            time.sleep(self.rate_limit_delay)  # Rate limiting
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise
    
    def get_ticker_details(self, ticker: str) -> Dict[str, Any]:
        """Get detailed information about a ticker"""
        endpoint = f"/v3/reference/tickers/{ticker}"
        return self._make_request(endpoint)
    
    def get_ticker_news(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get news for a specific ticker"""
        endpoint = f"/v2/reference/news"
        params = {
            'ticker': ticker,
            'limit': limit
        }
        response = self._make_request(endpoint, params)
        return response.get('results', [])
    
    def get_aggregates(self, ticker: str, multiplier: int, timespan: str, 
                      from_date: str, to_date: str, adjusted: bool = True) -> Dict[str, Any]:
        """Get aggregate bars for a ticker"""
        endpoint = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        params = {'adjusted': adjusted}
        return self._make_request(endpoint, params)
    
    def get_grouped_daily(self, date: str, adjusted: bool = True) -> Dict[str, Any]:
        """Get grouped daily bars for all tickers on a specific date"""
        endpoint = f"/v2/aggs/grouped/locale/us/market/stocks/{date}"
        params = {'adjusted': adjusted}
        return self._make_request(endpoint, params)
    
    def get_ticker_types(self) -> Dict[str, Any]:
        """Get all ticker types"""
        endpoint = "/v3/reference/tickers/types"
        return self._make_request(endpoint)
    
    def get_market_status(self) -> Dict[str, Any]:
        """Get current market status"""
        endpoint = "/v1/marketstatus/now"
        return self._make_request(endpoint)
    
    def search_tickers(self, search: str, market: str = "stocks", 
                      active: bool = True, limit: int = 1000) -> List[Dict[str, Any]]:
        """Search for tickers"""
        endpoint = "/v3/reference/tickers"
        params = {
            'search': search,
            'market': market,
            'active': active,
            'limit': limit
        }
        response = self._make_request(endpoint, params)
        return response.get('results', [])
