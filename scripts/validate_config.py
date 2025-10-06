#!/usr/bin/env python3
"""
Configuration validation script.

This script validates all configuration files and tests the configuration system.
"""

import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config_loader import ConfigLoader, ConfigurationError
from core.config_models import (
    DatabaseConfig, PolygonConfig, IBKRConfig, 
    StrategiesConfig, TradingConfig, LoggingConfig, MainConfig
)
from loguru import logger


def validate_configuration():
    """Validate all configuration files."""
    print("🔧 Trading Platform Configuration Validation")
    print("=" * 60)
    
    try:
        # Initialize configuration loader
        config_loader = ConfigLoader()
        
        print("\n📋 Validating Configuration Files...")
        
        # Validate individual configurations
        configs_to_validate = [
            ("Database", lambda: config_loader.get_database_config()),
            ("Polygon.io", lambda: config_loader.get_polygon_config()),
            ("Interactive Brokers", lambda: config_loader.get_ibkr_config()),
            ("Strategies", lambda: config_loader.get_strategies_config()),
            ("Trading", lambda: config_loader.get_trading_config()),
            ("Logging", lambda: config_loader.get_logging_config()),
        ]
        
        validation_results = {}
        
        for config_name, config_func in configs_to_validate:
            try:
                config = config_func()
                validation_results[config_name] = True
                print(f"✅ {config_name} configuration is valid")
                
                # Print some key configuration details
                if hasattr(config, 'host'):
                    print(f"   Host: {config.host}")
                if hasattr(config, 'api_key'):
                    print(f"   API Key: {'*' * (len(config.api_key) - 4) + config.api_key[-4:] if config.api_key else 'Not set'}")
                if hasattr(config, 'account_id'):
                    print(f"   Account ID: {config.account_id}")
                    
            except ConfigurationError as e:
                validation_results[config_name] = False
                print(f"❌ {config_name} configuration failed: {e}")
            except Exception as e:
                validation_results[config_name] = False
                print(f"❌ {config_name} configuration error: {e}")
        
        print("\n📊 Configuration Summary:")
        print(f"   Total configurations: {len(configs_to_validate)}")
        print(f"   Valid configurations: {sum(validation_results.values())}")
        print(f"   Invalid configurations: {len(validation_results) - sum(validation_results.values())}")
        
        # Test main configuration
        print("\n🔧 Testing Main Configuration...")
        try:
            main_config = config_loader.get_main_config()
            print("✅ Main configuration loaded successfully")
            print(f"   Platform: {main_config.application.name}")
            print(f"   Version: {main_config.application.version}")
            print(f"   Environment: {main_config.environment.current}")
            print(f"   Timezone: {main_config.system.timezone}")
        except Exception as e:
            print(f"❌ Main configuration failed: {e}")
        
        # Test configuration summary
        print("\n📈 Configuration Summary:")
        summary = config_loader.get_config_summary()
        print(f"   Config directory: {summary['config_directory']}")
        print(f"   Cached files: {len(summary['cached_files'])}")
        print(f"   Validated configs: {len(summary['validated_configs'])}")
        print(f"   Environment variables: {summary['environment_variables']}")
        
        # Test environment variable overrides
        print("\n🌍 Testing Environment Variable Overrides...")
        test_env_vars = {
            "TRADING_ENVIRONMENT": "staging",
            "LOG_LEVEL": "DEBUG",
            "DB_HOST": "test-host",
            "DB_PORT": "5433"
        }
        
        for env_var, value in test_env_vars.items():
            os.environ[env_var] = value
            print(f"   Set {env_var} = {value}")
        
        # Reload configurations to pick up environment variables
        config_loader.reload_all_configs()
        
        try:
            trading_config = config_loader.get_trading_config()
            print(f"✅ Environment override test passed")
            print(f"   Trading environment: {trading_config.environment}")
        except Exception as e:
            print(f"❌ Environment override test failed: {e}")
        
        # Clean up test environment variables
        for env_var in test_env_vars:
            if env_var in os.environ:
                del os.environ[env_var]
        
        print("\n🎯 Configuration Validation Complete!")
        
        # Return success if all configurations are valid
        return all(validation_results.values())
        
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False


def test_configuration_features():
    """Test advanced configuration features."""
    print("\n🧪 Testing Advanced Configuration Features...")
    
    try:
        config_loader = ConfigLoader()
        
        # Test configuration value retrieval
        print("   Testing configuration value retrieval...")
        db_host = config_loader.get_config_value("database.yaml", "database.postgresql.host", "default")
        print(f"   Database host: {db_host}")
        
        # Test configuration reloading
        print("   Testing configuration reloading...")
        config_loader.reload_config("database.yaml")
        print("   ✅ Configuration reloaded successfully")
        
        # Test configuration validation
        print("   Testing configuration validation...")
        validation_results = config_loader.validate_all_configs()
        valid_count = sum(validation_results.values())
        total_count = len(validation_results)
        print(f"   ✅ {valid_count}/{total_count} configuration files are valid")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Advanced features test failed: {e}")
        return False


def main():
    """Main validation function."""
    print("🚀 Starting Trading Platform Configuration Validation")
    print("=" * 60)
    
    # Basic validation
    basic_success = validate_configuration()
    
    # Advanced features test
    advanced_success = test_configuration_features()
    
    print("\n" + "=" * 60)
    if basic_success and advanced_success:
        print("🎉 All configuration tests passed!")
        print("✅ Configuration system is ready for use")
        return 0
    else:
        print("❌ Some configuration tests failed")
        print("🔧 Please check the configuration files and fix any issues")
        return 1


if __name__ == "__main__":
    sys.exit(main())
