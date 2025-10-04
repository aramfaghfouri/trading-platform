"""
Configuration for Polygon Data Collector
"""

import os
from typing import Dict, Any

class PolygonConfig:
    """Configuration class for Polygon data collection"""
    
    def __init__(self):
        self.api_key = os.getenv('POLYGON_API_KEY')
        self.base_url = os.getenv('POLYGON_BASE_URL', 'https://api.polygon.io')
        self.rate_limit_delay = float(os.getenv('POLYGON_RATE_LIMIT_DELAY', '0.1'))
        self.max_retries = int(os.getenv('POLYGON_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('POLYGON_TIMEOUT', '30'))
        
        # Data collection settings
        self.default_days_back = int(os.getenv('POLYGON_DAYS_BACK', '30'))
        self.max_tickers_per_request = int(os.getenv('POLYGON_MAX_TICKERS', '100'))
        
        # Storage settings
        self.data_storage_path = os.getenv('POLYGON_DATA_PATH', './data/polygon')
        self.enable_csv_export = os.getenv('POLYGON_CSV_EXPORT', 'true').lower() == 'true'
        self.enable_json_export = os.getenv('POLYGON_JSON_EXPORT', 'true').lower() == 'true'
        
        # Processing settings
        self.enable_technical_analysis = os.getenv('POLYGON_TECH_ANALYSIS', 'true').lower() == 'true'
        self.enable_sentiment_analysis = os.getenv('POLYGON_SENTIMENT_ANALYSIS', 'true').lower() == 'true'
        
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY environment variable is required")
        
        if self.rate_limit_delay < 0:
            raise ValueError("Rate limit delay must be non-negative")
        
        if self.max_retries < 0:
            raise ValueError("Max retries must be non-negative")
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            'api_key': self.api_key,
            'base_url': self.base_url,
            'rate_limit_delay': self.rate_limit_delay,
            'max_retries': self.max_retries,
            'timeout': self.timeout,
            'default_days_back': self.default_days_back,
            'max_tickers_per_request': self.max_tickers_per_request,
            'data_storage_path': self.data_storage_path,
            'enable_csv_export': self.enable_csv_export,
            'enable_json_export': self.enable_json_export,
            'enable_technical_analysis': self.enable_technical_analysis,
            'enable_sentiment_analysis': self.enable_sentiment_analysis
        }
