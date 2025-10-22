"""
Unit tests for configuration management.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch, mock_open

from src.core.config import ConfigManager, DatabaseConfig, PolygonConfig, IBKRConfig


class TestConfigManager:
    """Test cases for ConfigManager."""
    
    def test_init_with_default_config_dir(self):
        """Test ConfigManager initialization with default config directory."""
        manager = ConfigManager()
        assert manager.config_dir == Path("config")
        assert manager._config_cache == {}
    
    def test_init_with_custom_config_dir(self, temp_dir):
        """Test ConfigManager initialization with custom config directory."""
        config_dir = temp_dir / "custom_config"
        config_dir.mkdir()
        
        manager = ConfigManager(config_dir)
        assert manager.config_dir == config_dir
    
    def test_load_config_success(self, temp_dir):
        """Test successful configuration loading."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_data = {"test": "value", "nested": {"key": "value"}}
        config_file = config_dir / "test.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        result = manager.load_config("test.yaml")
        
        assert result == config_data
        assert "test.yaml" in manager._config_cache
    
    def test_load_config_file_not_found(self, temp_dir):
        """Test configuration loading with non-existent file."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        manager = ConfigManager(config_dir)
        
        with pytest.raises(FileNotFoundError):
            manager.load_config("nonexistent.yaml")
    
    def test_load_config_invalid_yaml(self, temp_dir):
        """Test configuration loading with invalid YAML."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_file = config_dir / "invalid.yaml"
        with open(config_file, 'w') as f:
            f.write("invalid: yaml: content: [")
        
        manager = ConfigManager(config_dir)
        
        with pytest.raises(yaml.YAMLError):
            manager.load_config("invalid.yaml")
    
    def test_get_database_config(self, temp_dir, mock_database_config):
        """Test database configuration retrieval."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_data = {"database": {"postgresql": mock_database_config}}
        config_file = config_dir / "database.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        result = manager.get_database_config()
        
        assert isinstance(result, DatabaseConfig)
        assert result.host == mock_database_config["host"]
        assert result.port == mock_database_config["port"]
        assert result.database == mock_database_config["database"]
    
    def test_get_polygon_config(self, temp_dir, mock_polygon_config):
        """Test Polygon.io configuration retrieval."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_data = {"polygon": {"api": mock_polygon_config}}
        config_file = config_dir / "polygon.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        result = manager.get_polygon_config()
        
        assert isinstance(result, PolygonConfig)
        assert result.api_key == mock_polygon_config["api_key"]
        assert result.base_url == mock_polygon_config["base_url"]
    
    def test_get_ibkr_config(self, temp_dir, mock_ibkr_config):
        """Test Interactive Brokers configuration retrieval."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_data = {"ibkr": {"connection": mock_ibkr_config}}
        config_file = config_dir / "ibkr.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        result = manager.get_ibkr_config()
        
        assert isinstance(result, IBKRConfig)
        assert result.host == mock_ibkr_config["host"]
        assert result.port == mock_ibkr_config["port"]
        assert result.paper_trading == mock_ibkr_config["paper_trading"]
    
    def test_get_config_value_with_dot_notation(self, temp_dir):
        """Test configuration value retrieval with dot notation."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        config_data = {
            "database": {
                "postgresql": {
                    "host": "localhost",
                    "port": 6432
                }
            },
            "api": {
                "timeout": 30
            }
        }
        config_file = config_dir / "test.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        
        # Test valid paths
        assert manager.get_config_value("test.yaml", "database.postgresql.host") == "localhost"
        assert manager.get_config_value("test.yaml", "database.postgresql.port") == 6432
        assert manager.get_config_value("test.yaml", "api.timeout") == 30
        
        # Test invalid paths
        assert manager.get_config_value("test.yaml", "nonexistent.key") is None
        assert manager.get_config_value("test.yaml", "database.nonexistent") is None
        
        # Test with default value
        assert manager.get_config_value("test.yaml", "nonexistent.key", "default") == "default"
    
    def test_reload_config(self, temp_dir):
        """Test configuration reloading."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        # Initial config
        config_data = {"test": "initial"}
        config_file = config_dir / "test.yaml"
        
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        manager = ConfigManager(config_dir)
        result1 = manager.load_config("test.yaml")
        assert result1["test"] == "initial"
        
        # Update config
        config_data = {"test": "updated"}
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        
        result2 = manager.reload_config("test.yaml")
        assert result2["test"] == "updated"
    
    def test_validate_config(self, temp_dir):
        """Test configuration validation."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        
        # Valid config
        valid_config = {"test": "valid"}
        valid_file = config_dir / "valid.yaml"
        
        with open(valid_file, 'w') as f:
            yaml.dump(valid_config, f)
        
        # Invalid config
        invalid_file = config_dir / "invalid.yaml"
        with open(invalid_file, 'w') as f:
            f.write("invalid: yaml: content: [")
        
        manager = ConfigManager(config_dir)
        
        assert manager.validate_config("valid.yaml") is True
        assert manager.validate_config("invalid.yaml") is False
        assert manager.validate_config("nonexistent.yaml") is False


class TestDatabaseConfig:
    """Test cases for DatabaseConfig model."""
    
    def test_database_config_defaults(self):
        """Test DatabaseConfig with default values."""
        config = DatabaseConfig()
        
        assert config.host == "localhost"
        assert config.port == 6432
        assert config.database == "trading_platform"
        assert config.username == "trading_user"
        assert config.password == "trading_password"
        assert config.ssl_mode == "prefer"
        assert config.pool_size == 10
    
    def test_database_config_custom_values(self):
        """Test DatabaseConfig with custom values."""
        config = DatabaseConfig(
            host="custom_host",
            port=5433,
            database="custom_db",
            username="custom_user",
            password="custom_pass"
        )
        
        assert config.host == "custom_host"
        assert config.port == 5433
        assert config.database == "custom_db"
        assert config.username == "custom_user"
        assert config.password == "custom_pass"


class TestPolygonConfig:
    """Test cases for PolygonConfig model."""
    
    def test_polygon_config_required_fields(self):
        """Test PolygonConfig with required fields."""
        config = PolygonConfig(api_key="test_key")
        
        assert config.api_key == "test_key"
        assert config.base_url == "https://api.polygon.io"
        assert config.timeout == 30
    
    def test_polygon_config_custom_values(self):
        """Test PolygonConfig with custom values."""
        config = PolygonConfig(
            api_key="custom_key",
            base_url="https://custom.api.com",
            timeout=60,
            rate_limit=10
        )
        
        assert config.api_key == "custom_key"
        assert config.base_url == "https://custom.api.com"
        assert config.timeout == 60
        assert config.rate_limit == 10


class TestIBKRConfig:
    """Test cases for IBKRConfig model."""
    
    def test_ibkr_config_required_fields(self):
        """Test IBKRConfig with required fields."""
        config = IBKRConfig(account_id="test_account")
        
        assert config.account_id == "test_account"
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.paper_trading is True
    
    def test_ibkr_config_custom_values(self):
        """Test IBKRConfig with custom values."""
        config = IBKRConfig(
            account_id="custom_account",
            host="192.168.1.100",
            port=7496,
            paper_trading=False,
            timeout=60
        )
        
        assert config.account_id == "custom_account"
        assert config.host == "192.168.1.100"
        assert config.port == 7496
        assert config.paper_trading is False
        assert config.timeout == 60
