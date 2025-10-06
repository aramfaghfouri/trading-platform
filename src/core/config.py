"""
Configuration management for the trading platform.

This module provides a centralized configuration system that loads
and manages all configuration files for the trading platform.

The enhanced configuration system includes:
- Comprehensive Pydantic models with validation
- Environment variable support
- YAML configuration files
- Type safety and validation
- Caching and reloading capabilities
"""

# Import the enhanced configuration system
from .config_loader import (
    ConfigLoader, ConfigurationError, get_config_loader,
    get_database_config, get_polygon_config, get_ibkr_config,
    get_strategies_config, get_trading_config, get_logging_config,
    get_main_config
)

from .config_models import (
    MainConfig, DatabaseConfig, PolygonConfig, IBKRConfig,
    StrategiesConfig, TradingConfig, LoggingConfig,
    StrategyConfig, StrategyRiskManagementConfig, StrategyPerformanceConfig
)

# Backward compatibility - keep the old ConfigManager for existing code
from .config_loader import ConfigLoader as ConfigManager

# Global configuration loader instance
config_loader = get_config_loader()

# Backward compatibility aliases
config_manager = config_loader

def get_config_manager() -> ConfigLoader:
    """Get the global configuration manager instance (backward compatibility)."""
    return config_loader
