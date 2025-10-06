"""
Enhanced configuration loader with comprehensive validation and environment support.

This module provides a robust configuration loading system that supports
YAML files, environment variables, and validation using Pydantic models.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union, Type, TypeVar
from pydantic import ValidationError
from loguru import logger
from dotenv import load_dotenv

from .config_models import (
    MainConfig, DatabaseConfig, PolygonConfig, IBKRConfig, 
    StrategiesConfig, TradingConfig, LoggingConfig
)

T = TypeVar('T')


class ConfigurationError(Exception):
    """Configuration-related errors."""
    pass


class ConfigLoader:
    """Enhanced configuration loader with validation and environment support."""
    
    def __init__(self, config_dir: Optional[Union[str, Path]] = None, env_file: Optional[str] = None):
        """
        Initialize the configuration loader.
        
        Args:
            config_dir: Directory containing configuration files
            env_file: Path to .env file (optional)
        """
        self.config_dir = Path(config_dir) if config_dir else Path("config")
        self._config_cache: Dict[str, Any] = {}
        self._validated_configs: Dict[str, Any] = {}
        
        # Load environment variables
        if env_file and Path(env_file).exists():
            load_dotenv(env_file)
        elif Path(".env").exists():
            load_dotenv(".env")
            
        self._load_environment_variables()
        
    def _load_environment_variables(self) -> None:
        """Load configuration from environment variables."""
        env_mappings = {
            # Database
            "DATABASE_URL": "database_url",
            "DB_HOST": "db_host",
            "DB_PORT": "db_port",
            "DB_NAME": "db_name",
            "DB_USER": "db_user",
            "DB_PASSWORD": "db_password",
            
            # Polygon.io
            "POLYGON_API_KEY": "polygon_api_key",
            "POLYGON_BASE_URL": "polygon_base_url",
            "POLYGON_TIMEOUT": "polygon_timeout",
            
            # Interactive Brokers
            "IBKR_ACCOUNT_ID": "ibkr_account_id",
            "IBKR_HOST": "ibkr_host",
            "IBKR_PORT": "ibkr_port",
            "IBKR_CLIENT_ID": "ibkr_client_id",
            "IBKR_PAPER_TRADING": "ibkr_paper_trading",
            
            # Trading
            "TRADING_ENVIRONMENT": "trading_environment",
            "TRADING_TIMEZONE": "trading_timezone",
            "MAX_POSITION_SIZE": "max_position_size",
            "MAX_DAILY_LOSS": "max_daily_loss",
            
            # Logging
            "LOG_LEVEL": "log_level",
            "LOG_FILE": "log_file",
            
            # Security
            "SECRET_KEY": "secret_key",
            "JWT_SECRET_KEY": "jwt_secret_key",
        }
        
        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert string values to appropriate types
                if env_var in ["DB_PORT", "IBKR_PORT", "IBKR_CLIENT_ID", "POLYGON_TIMEOUT"]:
                    try:
                        value = int(value)
                    except ValueError:
                        logger.warning(f"Invalid integer value for {env_var}: {value}")
                        continue
                elif env_var in ["IBKR_PAPER_TRADING"]:
                    value = value.lower() in ("true", "1", "yes", "on")
                elif env_var in ["MAX_POSITION_SIZE", "MAX_DAILY_LOSS"]:
                    try:
                        value = float(value)
                    except ValueError:
                        logger.warning(f"Invalid float value for {env_var}: {value}")
                        continue
                        
                self._config_cache[config_key] = value
                logger.debug(f"Loaded environment variable {env_var} -> {config_key}")
    
    def load_yaml_config(self, config_file: str) -> Dict[str, Any]:
        """
        Load configuration from a YAML file.
        
        Args:
            config_file: Name of the configuration file
            
        Returns:
            Configuration dictionary
        """
        if config_file in self._config_cache:
            return self._config_cache[config_file]
            
        config_path = self.config_dir / config_file
        
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            if config is None:
                config = {}
                
            self._config_cache[config_file] = config
            logger.info(f"Loaded configuration from {config_path}")
            return config
            
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Error parsing YAML file {config_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Error loading configuration file {config_path}: {e}")
    
    def load_and_validate_config(self, config_type: Type[T], config_file: str, 
                                config_path: Optional[str] = None) -> T:
        """
        Load and validate configuration using Pydantic models.
        
        Args:
            config_type: Pydantic model class
            config_file: Name of the configuration file
            config_path: Optional path within the config (e.g., "database.postgresql")
            
        Returns:
            Validated configuration object
        """
        cache_key = f"{config_file}:{config_path or 'root'}:{config_type.__name__}"
        
        if cache_key in self._validated_configs:
            return self._validated_configs[cache_key]
        
        try:
            # Load raw configuration
            config_data = self.load_yaml_config(config_file)
            
            # Navigate to the specific path if provided
            if config_path:
                for key in config_path.split('.'):
                    config_data = config_data.get(key, {})
            
            # Apply environment variable overrides
            config_data = self._apply_env_overrides(config_data, config_type.__name__)
            
            # Validate with Pydantic model
            validated_config = config_type(**config_data)
            
            self._validated_configs[cache_key] = validated_config
            logger.info(f"Validated configuration for {config_type.__name__}")
            return validated_config
            
        except ValidationError as e:
            raise ConfigurationError(f"Configuration validation failed for {config_type.__name__}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Error loading configuration for {config_type.__name__}: {e}")
    
    def _apply_env_overrides(self, config_data: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration data."""
        overrides = {
            "DatabaseConfig": {
                "host": "db_host",
                "port": "db_port", 
                "database": "db_name",
                "username": "db_user",
                "password": "db_password",
            },
            "PolygonConfig": {
                "api": {
                    "api_key": "polygon_api_key",
                    "base_url": "polygon_base_url",
                    "timeout": "polygon_timeout",
                }
            },
            "IBKRConfig": {
                "account_id": "ibkr_account_id",
                "host": "ibkr_host",
                "port": "ibkr_port",
                "client_id": "ibkr_client_id",
                "paper_trading": "ibkr_paper_trading",
            },
            "TradingConfig": {
                "environment": "trading_environment",
                "timezone": "trading_timezone",
            },
        }
        
        if config_type in overrides:
            for config_key, env_mapping in overrides[config_type].items():
                if isinstance(env_mapping, dict):
                    # Handle nested configuration (e.g., api.api_key)
                    for nested_key, env_key in env_mapping.items():
                        if env_key in self._config_cache:
                            if config_key not in config_data:
                                config_data[config_key] = {}
                            config_data[config_key][nested_key] = self._config_cache[env_key]
                else:
                    # Handle flat configuration
                    env_key = env_mapping
                    if env_key in self._config_cache:
                        config_data[config_key] = self._config_cache[env_key]
        
        return config_data
    
    def get_database_config(self) -> DatabaseConfig:
        """Get validated database configuration."""
        return self.load_and_validate_config(
            DatabaseConfig, 
            "database.yaml", 
            "database"
        )
    
    def get_polygon_config(self) -> PolygonConfig:
        """Get validated Polygon.io configuration."""
        return self.load_and_validate_config(
            PolygonConfig,
            "polygon.yaml",
            "polygon"
        )
    
    def get_ibkr_config(self) -> IBKRConfig:
        """Get validated Interactive Brokers configuration."""
        return self.load_and_validate_config(
            IBKRConfig,
            "ibkr.yaml", 
            "ibkr"
        )
    
    def get_strategies_config(self) -> StrategiesConfig:
        """Get validated strategies configuration."""
        return self.load_and_validate_config(
            StrategiesConfig,
            "strategies.yaml",
            "strategies"
        )
    
    def get_trading_config(self) -> TradingConfig:
        """Get validated trading configuration."""
        return self.load_and_validate_config(
            TradingConfig,
            "trading.yaml",
            "trading"
        )
    
    def get_logging_config(self) -> LoggingConfig:
        """Get validated logging configuration."""
        return self.load_and_validate_config(
            LoggingConfig,
            "logging.yaml",
            "logging"
        )
    
    def get_main_config(self) -> MainConfig:
        """Get complete validated configuration."""
        try:
            # Load all individual configurations
            database_config = self.get_database_config()
            polygon_config = self.get_polygon_config()
            ibkr_config = self.get_ibkr_config()
            strategies_config = self.get_strategies_config()
            trading_config = self.get_trading_config()
            
            # Create main configuration
            main_config = MainConfig(
                database=database_config,
                polygon=polygon_config,
                ibkr=ibkr_config,
                strategies=strategies_config,
                trading=trading_config
            )
            
            logger.info("Successfully loaded and validated main configuration")
            return main_config
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load main configuration: {e}")
    
    def get_config_value(self, config_file: str, key_path: str, default: Any = None) -> Any:
        """
        Get a specific configuration value using dot notation.
        
        Args:
            config_file: Name of the configuration file
            key_path: Dot-separated path to the configuration value
            default: Default value if key is not found
            
        Returns:
            Configuration value or default
        """
        try:
            config = self.load_yaml_config(config_file)
            
            keys = key_path.split('.')
            value = config
            
            for key in keys:
                value = value[key]
            return value
            
        except (KeyError, TypeError):
            return default
    
    def reload_config(self, config_file: str) -> Dict[str, Any]:
        """
        Reload a specific configuration file.
        
        Args:
            config_file: Name of the configuration file to reload
            
        Returns:
            Reloaded configuration dictionary
        """
        # Clear cache for this file
        if config_file in self._config_cache:
            del self._config_cache[config_file]
        
        # Clear validated configs that depend on this file
        keys_to_remove = [key for key in self._validated_configs.keys() if key.startswith(config_file)]
        for key in keys_to_remove:
            del self._validated_configs[key]
        
        return self.load_yaml_config(config_file)
    
    def reload_all_configs(self) -> None:
        """Reload all configuration files."""
        self._config_cache.clear()
        self._validated_configs.clear()
        logger.info("Reloaded all configurations")
    
    def validate_all_configs(self) -> Dict[str, bool]:
        """
        Validate all configuration files.
        
        Returns:
            Dictionary mapping config file names to validation results
        """
        results = {}
        
        config_files = [
            "database.yaml",
            "polygon.yaml", 
            "ibkr.yaml",
            "strategies.yaml",
            "trading.yaml",
            "logging.yaml"
        ]
        
        for config_file in config_files:
            try:
                self.load_yaml_config(config_file)
                results[config_file] = True
                logger.info(f"✅ {config_file} is valid")
            except Exception as e:
                results[config_file] = False
                logger.error(f"❌ {config_file} validation failed: {e}")
        
        return results
    
    def export_config(self, config_file: str, output_path: Optional[str] = None) -> None:
        """
        Export configuration to a file.
        
        Args:
            config_file: Name of the configuration file to export
            output_path: Optional output path (defaults to config_file)
        """
        config_data = self.load_yaml_config(config_file)
        
        if output_path is None:
            output_path = config_file
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Exported configuration to {output_path}")
    
    def get_config_summary(self) -> Dict[str, Any]:
        """Get a summary of all loaded configurations."""
        summary = {
            "config_directory": str(self.config_dir),
            "cached_files": list(self._config_cache.keys()),
            "validated_configs": list(self._validated_configs.keys()),
            "environment_variables": len(self._config_cache),
            "validation_status": self.validate_all_configs()
        }
        
        return summary


# Global configuration loader instance
config_loader = ConfigLoader()


def get_config_loader() -> ConfigLoader:
    """Get the global configuration loader instance."""
    return config_loader


def get_database_config() -> DatabaseConfig:
    """Get database configuration."""
    return config_loader.get_database_config()


def get_polygon_config() -> PolygonConfig:
    """Get Polygon.io configuration."""
    return config_loader.get_polygon_config()


def get_ibkr_config() -> IBKRConfig:
    """Get Interactive Brokers configuration."""
    return config_loader.get_ibkr_config()


def get_strategies_config() -> StrategiesConfig:
    """Get strategies configuration."""
    return config_loader.get_strategies_config()


def get_trading_config() -> TradingConfig:
    """Get trading configuration."""
    return config_loader.get_trading_config()


def get_logging_config() -> LoggingConfig:
    """Get logging configuration."""
    return config_loader.get_logging_config()


def get_main_config() -> MainConfig:
    """Get complete configuration."""
    return config_loader.get_main_config()
