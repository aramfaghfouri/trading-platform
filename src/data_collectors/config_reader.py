"""
Configuration reader for data collectors
Reads from .env and project-setup.toml files
"""

import os
import toml
from typing import Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

class ConfigReader:
    """Reads configuration from .env and project-setup.toml files"""
    
    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent.parent
        
        self.project_root = Path(project_root)
        self.env_file = self.project_root / ".env"
        self.toml_file = self.project_root / "project-setup.toml"
        
        # Load environment variables
        self._load_env()
        
        # Load TOML configuration
        self._load_toml()
    
    def _load_env(self):
        """Load environment variables from .env file"""
        if self.env_file.exists():
            load_dotenv(self.env_file)
        else:
            print(f"Warning: .env file not found at {self.env_file}")
    
    def _load_toml(self):
        """Load configuration from project-setup.toml"""
        if self.toml_file.exists():
            with open(self.toml_file, 'r') as f:
                self.toml_config = toml.load(f)
        else:
            print(f"Warning: project-setup.toml not found at {self.toml_file}")
            self.toml_config = {}
    
    def get_env_var(self, key: str, default: str = None) -> str:
        """Get environment variable with optional default"""
        return os.getenv(key, default)
    
    def get_toml_value(self, key_path: str, default: Any = None) -> Any:
        """Get value from TOML config using dot notation (e.g., 'data_collection.tickers')"""
        keys = key_path.split('.')
        value = self.toml_config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_tickers(self) -> List[str]:
        """Get list of tickers from configuration"""
        return self.get_toml_value('data_collection.tickers', [])
    
    def get_time_config(self) -> Dict[str, str]:
        """Get time configuration"""
        return {
            'time_interval': self.get_toml_value('data_collection.time_interval', 'minute'),
            'start_date': self.get_toml_value('data_collection.start_date', '2024-12-01'),
            'end_date': self.get_toml_value('data_collection.end_date', '2024-12-31')
        }
    
    def get_api_config(self) -> Dict[str, Any]:
        """Get API configuration"""
        return {
            'api_key': self.get_env_var('POLYGON_API_KEY'),
            'base_url': self.get_env_var('POLYGON_BASE_URL', 'https://api.polygon.io'),
            'rate_limit_delay': int(self.get_env_var('RATE_LIMIT_DELAY', '13')),
            'max_retries': int(self.get_env_var('MAX_RETRIES', '3')),
            'timeout': int(self.get_env_var('TIMEOUT', '30'))
        }
    
    def get_storage_config(self) -> Dict[str, Any]:
        """Get storage configuration"""
        return {
            'data_directory': self.get_env_var('DATA_DIRECTORY', './data_results'),
            'logs_directory': self.get_env_var('LOGS_DIRECTORY', './logs'),
            'enable_compression': self.get_env_var('ENABLE_COMPRESSION', 'true').lower() == 'true',
            'compression_format': self.get_env_var('COMPRESSION_FORMAT', 'lz4')
        }
    
    def get_processing_config(self) -> Dict[str, Any]:
        """Get processing configuration"""
        return {
            'chunk_size': int(self.get_env_var('CHUNK_SIZE', '50000')),
            'enable_parallel_processing': self.get_env_var('ENABLE_PARALLEL_PROCESSING', 'false').lower() == 'true',
            'max_workers': int(self.get_env_var('MAX_WORKERS', '4'))
        }
    
    def get_analysis_config(self) -> Dict[str, Any]:
        """Get analysis configuration"""
        return {
            'enable_technical_analysis': self.get_env_var('ENABLE_TECHNICAL_ANALYSIS', 'true').lower() == 'true',
            'enable_heikin_ashi': self.get_env_var('ENABLE_HEIKIN_ASHI', 'true').lower() == 'true',
            'enable_peak_detection': self.get_env_var('ENABLE_PEAK_DETECTION', 'true').lower() == 'true',
            'timezone': self.get_env_var('TIMEZONE', 'America/New_York')
        }
    
    def get_output_config(self) -> Dict[str, Any]:
        """Get output configuration"""
        return {
            'enable_csv_export': self.get_env_var('ENABLE_CSV_EXPORT', 'true').lower() == 'true',
            'enable_json_export': self.get_env_var('ENABLE_JSON_EXPORT', 'true').lower() == 'true',
            'enable_plotly_charts': self.get_env_var('ENABLE_PLOTLY_CHARTS', 'true').lower() == 'true',
            'enable_matplotlib_plots': self.get_env_var('ENABLE_MATPLOTLIB_PLOTS', 'true').lower() == 'true'
        }
    
    def validate_config(self) -> bool:
        """Validate that required configuration is present"""
        api_key = self.get_api_config()['api_key']
        if not api_key or api_key == 'your_polygon_api_key_here':
            print("Error: POLYGON_API_KEY not set in .env file")
            return False
        
        tickers = self.get_tickers()
        if not tickers:
            print("Error: No tickers configured in project-setup.toml")
            return False
        
        return True
    
    def print_config_summary(self):
        """Print a summary of the current configuration"""
        print("=== Configuration Summary ===")
        print(f"Tickers: {len(self.get_tickers())} configured")
        print(f"Time range: {self.get_time_config()['start_date']} to {self.get_time_config()['end_date']}")
        print(f"Time interval: {self.get_time_config()['time_interval']}")
        print(f"Data directory: {self.get_storage_config()['data_directory']}")
        print(f"API key configured: {'Yes' if self.get_api_config()['api_key'] else 'No'}")
        print("=============================")
