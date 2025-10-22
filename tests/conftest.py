"""
Pytest configuration and fixtures for the trading platform.
"""

import pytest
import asyncio
from pathlib import Path
from typing import Generator, AsyncGenerator
import tempfile
import shutil

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def test_config_dir(temp_dir: Path) -> Path:
    """Create a test configuration directory."""
    config_dir = temp_dir / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def test_data_dir(temp_dir: Path) -> Path:
    """Create a test data directory."""
    data_dir = temp_dir / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def test_logs_dir(temp_dir: Path) -> Path:
    """Create a test logs directory."""
    logs_dir = temp_dir / "logs"
    logs_dir.mkdir()
    return logs_dir


@pytest.fixture
def mock_database_config():
    """Mock database configuration for tests."""
    return {
        "host": "localhost",
        "port": 6432,
        "database": "test_trading_platform",
        "username": "test_user",
        "password": "test_password",
        "ssl_mode": "prefer",
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 3600
    }


@pytest.fixture
def mock_polygon_config():
    """Mock Polygon.io configuration for tests."""
    return {
        "api_key": "test_api_key",
        "base_url": "https://api.polygon.io",
        "timeout": 30,
        "retry_attempts": 3,
        "retry_delay": 1,
        "rate_limit": 5
    }


@pytest.fixture
def mock_ibkr_config():
    """Mock Interactive Brokers configuration for tests."""
    return {
        "host": "127.0.0.1",
        "port": 7497,
        "client_id": 1,
        "timeout": 30,
        "paper_trading": True,
        "account_id": "test_account"
    }


@pytest.fixture
def mock_strategy_config():
    """Mock strategy configuration for tests."""
    return {
        "name": "test_strategy",
        "enabled": True,
        "parameters": {
            "short_window": 20,
            "long_window": 50,
            "signal_threshold": 0.02
        },
        "risk_management": {
            "position_size": 0.1,
            "stop_loss": 0.05,
            "take_profit": 0.15
        },
        "symbols": ["AAPL", "MSFT", "GOOGL"]
    }


@pytest.fixture
def mock_trading_config():
    """Mock trading configuration for tests."""
    return {
        "environment": "test",
        "timezone": "America/New_York",
        "max_position_size": 0.10,
        "max_daily_loss": 0.05,
        "max_drawdown": 0.15
    }


@pytest.fixture
def mock_logging_config():
    """Mock logging configuration for tests."""
    return {
        "level": "DEBUG",
        "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        "rotation": "100 MB",
        "retention": "7 days",
        "compression": "gz"
    }


# Markers for different test types
pytest_plugins = []


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "requires_api: mark test as requiring external API"
    )
    config.addinivalue_line(
        "markers", "requires_database: mark test as requiring database"
    )
    config.addinivalue_line(
        "markers", "requires_docker: mark test as requiring Docker"
    )
