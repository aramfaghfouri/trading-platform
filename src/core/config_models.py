"""
Enhanced configuration models with comprehensive validation.

This module defines all configuration models for the trading platform
with proper validation, defaults, and type checking.
"""

from typing import Dict, Any, List, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum


class Environment(str, Enum):
    """Environment types."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"
    TRAILING_STOP = "TRAIL"


class TimeInForce(str, Enum):
    """Time in force options."""
    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

class TimescaleDBConfig(BaseModel):
    """TimescaleDB specific configuration."""
    chunk_time_interval: str = "1 day"
    compression_policy: str = "7 days"
    retention_policy: str = "1 year"
    continuous_aggregates: List[Dict[str, Any]] = Field(default_factory=list)
    
    @field_validator('chunk_time_interval')
    @classmethod
    def validate_chunk_interval(cls, v):
        """Validate chunk time interval format."""
        valid_intervals = ['1 minute', '5 minutes', '15 minutes', '1 hour', '1 day', '1 week']
        if v not in valid_intervals:
            raise ValueError(f"Invalid chunk interval: {v}. Must be one of {valid_intervals}")
        return v


class DatabasePoolConfig(BaseModel):
    """Database connection pool configuration."""
    min_connections: int = Field(5, ge=1, le=100)
    max_connections: int = Field(20, ge=1, le=1000)
    connection_timeout: int = Field(30, ge=1, le=300)
    command_timeout: int = Field(60, ge=1, le=600)
    
    @field_validator('max_connections')
    @classmethod
    def validate_max_connections(cls, v, info):
        """Ensure max_connections >= min_connections."""
        if info.data and 'min_connections' in info.data and v < info.data['min_connections']:
            raise ValueError("max_connections must be >= min_connections")
        return v


class DatabaseStorageConfig(BaseModel):
    """Database storage configuration."""
    enable_compression: bool = True
    enable_retention: bool = True
    backup_enabled: bool = True
    backup_interval: str = "daily"
    backup_retention: str = "30 days"


class DatabaseConfig(BaseModel):
    """Complete database configuration."""
    # PostgreSQL/TimescaleDB settings
    host: str = "localhost"
    port: int = Field(6432, ge=1, le=65535)
    database: str = "trading_platform"
    username: str = "trading_user"
    password: str = "trading_password"
    ssl_mode: str = Field("prefer", pattern="^(disable|allow|prefer|require|verify-ca|verify-full)$")
    
    # Connection pool settings
    pool_size: int = Field(10, ge=1, le=100)
    max_overflow: int = Field(20, ge=0, le=100)
    pool_timeout: int = Field(30, ge=1, le=300)
    pool_recycle: int = Field(3600, ge=60, le=86400)
    
    # TimescaleDB specific
    timescaledb: TimescaleDBConfig = Field(default_factory=TimescaleDBConfig)
    
    # Pool configuration
    pool: DatabasePoolConfig = Field(default_factory=DatabasePoolConfig)
    
    # Storage configuration
    storage: DatabaseStorageConfig = Field(default_factory=DatabaseStorageConfig)


# =============================================================================
# POLYGON.IO CONFIGURATION
# =============================================================================

class PolygonAPIConfig(BaseModel):
    """Polygon.io API configuration."""
    api_key: str = Field(..., min_length=1, description="Polygon.io API key")
    base_url: str = "https://api.polygon.io"
    timeout: int = Field(30, ge=1, le=300)
    retry_attempts: int = Field(3, ge=0, le=10)
    retry_delay: int = Field(1, ge=0, le=60)
    rate_limit: int = Field(5, ge=1, le=100)  # requests per second


class PolygonDataCollectionConfig(BaseModel):
    """Polygon.io data collection configuration."""
    # Historical data
    historical_enabled: bool = True
    max_requests_per_minute: int = Field(5, ge=1, le=100)
    batch_size: int = Field(1000, ge=100, le=10000)
    lookback_days: int = Field(365, ge=1, le=3650)
    
    # Real-time data
    realtime_enabled: bool = False
    websocket_url: str = "wss://socket.polygon.io/stocks"
    reconnect_attempts: int = Field(5, ge=0, le=20)
    reconnect_delay: int = Field(5, ge=1, le=60)


class PolygonMarketDataConfig(BaseModel):
    """Polygon.io market data configuration."""
    exchanges: List[str] = Field(default_factory=lambda: ["NASDAQ", "NYSE", "AMEX"])
    data_types: List[str] = Field(default_factory=lambda: ["trades", "quotes", "bars", "trades_nbbo"])
    timeframes: List[str] = Field(default_factory=lambda: ["1min", "5min", "15min", "1hour", "1day"])
    
    @field_validator('data_types')
    @classmethod
    def validate_data_types(cls, v):
        """Validate data types."""
        valid_types = ["trades", "quotes", "bars", "trades_nbbo", "last_quote", "last_trade"]
        for data_type in v:
            if data_type not in valid_types:
                raise ValueError(f"Invalid data type: {data_type}. Must be one of {valid_types}")
        return v
    
    @field_validator('timeframes')
    @classmethod
    def validate_timeframes(cls, v):
        """Validate timeframes."""
        valid_timeframes = ["1min", "5min", "15min", "30min", "1hour", "2hour", "4hour", "1day"]
        for timeframe in v:
            if timeframe not in valid_timeframes:
                raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {valid_timeframes}")
        return v


class PolygonSymbolsConfig(BaseModel):
    """Polygon.io symbols configuration."""
    default: List[str] = Field(default_factory=lambda: [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", "AMD", "INTC"
    ])
    categories: Dict[str, List[str]] = Field(default_factory=lambda: {
        "tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "INTC"],
        "finance": ["JPM", "BAC", "WFC", "GS", "MS"],
        "healthcare": ["JNJ", "PFE", "UNH", "ABBV", "MRK"],
        "energy": ["XOM", "CVX", "COP", "EOG", "SLB"]
    })


class PolygonDataQualityConfig(BaseModel):
    """Polygon.io data quality configuration."""
    validate_data: bool = True
    min_volume_threshold: int = Field(1000, ge=0)
    max_price_deviation: float = Field(0.1, ge=0.0, le=1.0)  # 10% from previous close
    outlier_detection: bool = True
    missing_data_handling: str = Field("interpolate", pattern="^(interpolate|forward_fill|backward_fill|drop)$")


class PolygonConfig(BaseModel):
    """Complete Polygon.io configuration."""
    api: PolygonAPIConfig
    data_collection: PolygonDataCollectionConfig = Field(default_factory=PolygonDataCollectionConfig)
    market_data: PolygonMarketDataConfig = Field(default_factory=PolygonMarketDataConfig)
    symbols: PolygonSymbolsConfig = Field(default_factory=PolygonSymbolsConfig)
    quality: PolygonDataQualityConfig = Field(default_factory=PolygonDataQualityConfig)


# =============================================================================
# INTERACTIVE BROKERS CONFIGURATION
# =============================================================================

class IBKRConnectionConfig(BaseModel):
    """Interactive Brokers connection configuration."""
    host: str = "127.0.0.1"
    port: int = Field(7497, ge=1, le=65535)
    client_id: int = Field(1, ge=1, le=100)
    timeout: int = Field(30, ge=1, le=300)
    reconnect_attempts: int = Field(5, ge=0, le=20)
    reconnect_delay: int = Field(5, ge=1, le=60)


class IBKRTradingConfig(BaseModel):
    """Interactive Brokers trading configuration."""
    paper_trading: bool = True
    paper_port: int = Field(7497, ge=1, le=65535)
    live_trading: bool = False
    live_port: int = Field(7496, ge=1, le=65535)
    
    # Order settings
    default_order_type: OrderType = OrderType.MARKET
    default_time_in_force: TimeInForce = TimeInForce.DAY
    max_order_size: int = Field(10000, ge=1, le=1000000)
    min_order_size: int = Field(1, ge=1, le=1000)
    
    @field_validator('min_order_size')
    @classmethod
    def validate_min_order_size(cls, v, info):
        """Ensure min_order_size <= max_order_size."""
        if info.data and 'max_order_size' in info.data and v > info.data['max_order_size']:
            raise ValueError("min_order_size must be <= max_order_size")
        return v


class IBKRAccountConfig(BaseModel):
    """Interactive Brokers account configuration."""
    account_id: str = Field(..., min_length=1, description="IBKR account ID")
    
    # Risk management
    max_position_size: float = Field(0.1, ge=0.01, le=1.0)  # 10% of portfolio per position
    max_daily_loss: float = Field(0.05, ge=0.01, le=1.0)    # 5% daily loss limit
    max_drawdown: float = Field(0.15, ge=0.01, le=1.0)      # 15% maximum drawdown
    position_sizing: str = Field("fixed", pattern="^(fixed|kelly|volatility)$")


class IBKRMarketDataConfig(BaseModel):
    """Interactive Brokers market data configuration."""
    data_types: List[str] = Field(default_factory=lambda: ["trades", "quotes", "bars", "trades_nbbo"])
    timeframes: List[str] = Field(default_factory=lambda: ["1 min", "5 mins", "15 mins", "1 hour", "1 day"])
    
    # Real-time data
    realtime_enabled: bool = True
    snapshot: bool = True
    streaming: bool = True


class IBKROrderManagementConfig(BaseModel):
    """Interactive Brokers order management configuration."""
    supported_order_types: List[OrderType] = Field(default_factory=lambda: [
        OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP
    ])
    
    # Order validation
    check_margin: bool = True
    check_balance: bool = True
    validate_symbol: bool = True
    check_market_hours: bool = True


class IBKRPortfolioConfig(BaseModel):
    """Interactive Brokers portfolio configuration."""
    # Position tracking
    position_tracking_enabled: bool = True
    position_update_interval: int = Field(1, ge=1, le=60)  # seconds
    sync_with_database: bool = True
    
    # P&L tracking
    pnl_tracking_enabled: bool = True
    pnl_update_interval: int = Field(5, ge=1, le=300)  # seconds
    track_unrealized: bool = True
    track_realized: bool = True


class IBKRLoggingConfig(BaseModel):
    """Interactive Brokers logging configuration."""
    log_level: LogLevel = LogLevel.INFO
    log_orders: bool = True
    log_positions: bool = True
    log_pnl: bool = True
    log_errors: bool = True


class IBKRConfig(BaseModel):
    """Complete Interactive Brokers configuration."""
    connection: IBKRConnectionConfig = Field(default_factory=IBKRConnectionConfig)
    trading: IBKRTradingConfig = Field(default_factory=IBKRTradingConfig)
    account: IBKRAccountConfig
    market_data: IBKRMarketDataConfig = Field(default_factory=IBKRMarketDataConfig)
    order_management: IBKROrderManagementConfig = Field(default_factory=IBKROrderManagementConfig)
    portfolio: IBKRPortfolioConfig = Field(default_factory=IBKRPortfolioConfig)
    logging: IBKRLoggingConfig = Field(default_factory=IBKRLoggingConfig)


# =============================================================================
# STRATEGY CONFIGURATION
# =============================================================================

class StrategyRiskManagementConfig(BaseModel):
    """Strategy risk management configuration."""
    position_size: float = Field(0.1, ge=0.01, le=1.0)  # 10% of portfolio
    stop_loss: float = Field(0.05, ge=0.01, le=1.0)     # 5% stop loss
    take_profit: float = Field(0.15, ge=0.01, le=1.0)   # 15% take profit
    
    @field_validator('take_profit')
    @classmethod
    def validate_take_profit(cls, v, info):
        """Ensure take_profit > stop_loss."""
        if info.data and 'stop_loss' in info.data and v <= info.data['stop_loss']:
            raise ValueError("take_profit must be > stop_loss")
        return v


class StrategyPerformanceConfig(BaseModel):
    """Strategy performance configuration."""
    # Backtesting settings
    start_date: str = "2023-01-01"
    end_date: str = "2024-01-01"
    initial_capital: float = Field(100000, ge=1000, le=10000000)
    commission: float = Field(0.001, ge=0.0, le=0.01)  # 0.1% commission
    slippage: float = Field(0.0005, ge=0.0, le=0.01)   # 0.05% slippage
    
    # Performance metrics
    calculate_sharpe: bool = True
    calculate_sortino: bool = True
    calculate_max_drawdown: bool = True
    calculate_win_rate: bool = True
    calculate_profit_factor: bool = True
    
    # Risk metrics
    calculate_var: bool = True
    var_confidence: float = Field(0.95, ge=0.5, le=0.99)
    calculate_cvar: bool = True
    calculate_volatility: bool = True
    volatility_window: int = Field(252, ge=30, le=1000)  # 1 year


class StrategyConfig(BaseModel):
    """Complete strategy configuration."""
    name: str = Field(..., min_length=1)
    enabled: bool = True
    parameters: Dict[str, Any] = Field(default_factory=dict)
    risk_management: StrategyRiskManagementConfig = Field(default_factory=StrategyRiskManagementConfig)
    symbols: List[str] = Field(default_factory=list)
    performance: StrategyPerformanceConfig = Field(default_factory=StrategyPerformanceConfig)


class StrategyRegistryConfig(BaseModel):
    """Strategy registry configuration."""
    enabled_strategies: List[str] = Field(default_factory=lambda: [
        "sma_crossover", "rsi_mean_reversion", "bollinger_bands", "momentum", "mean_reversion"
    ])
    max_concurrent_strategies: int = Field(10, ge=1, le=50)
    strategy_timeout: int = Field(300, ge=60, le=3600)  # seconds
    enable_parallel_execution: bool = True


class StrategiesConfig(BaseModel):
    """Complete strategies configuration."""
    registry: StrategyRegistryConfig = Field(default_factory=StrategyRegistryConfig)
    strategies: Dict[str, StrategyConfig] = Field(default_factory=dict)


# =============================================================================
# TRADING CONFIGURATION
# =============================================================================

class TradingHoursConfig(BaseModel):
    """Trading hours configuration."""
    # Market Hours (EST/EDT)
    market_open: str = "09:30"
    market_close: str = "16:00"
    
    # Pre-market Hours
    premarket_open: str = "04:00"
    premarket_close: str = "09:30"
    
    # After-hours
    afterhours_open: str = "16:00"
    afterhours_close: str = "20:00"
    
    # Trading Days
    trading_days: List[str] = Field(default_factory=lambda: [
        "monday", "tuesday", "wednesday", "thursday", "friday"
    ])


class RiskManagementConfig(BaseModel):
    """Risk management configuration."""
    # Portfolio Risk
    max_portfolio_risk: float = Field(0.20, ge=0.01, le=1.0)      # 20% maximum portfolio risk
    max_correlation: float = Field(0.70, ge=0.0, le=1.0)         # 70% maximum correlation between positions
    max_sector_exposure: float = Field(0.30, ge=0.01, le=1.0)     # 30% maximum sector exposure
    
    # Position Risk
    max_position_size: float = Field(0.10, ge=0.01, le=1.0)       # 10% maximum position size
    max_daily_trades: int = Field(50, ge=1, le=1000)              # 50 maximum trades per day
    max_daily_loss: float = Field(0.05, ge=0.01, le=1.0)          # 5% maximum daily loss
    
    # Market Risk
    max_drawdown: float = Field(0.15, ge=0.01, le=1.0)            # 15% maximum drawdown
    volatility_threshold: float = Field(0.30, ge=0.01, le=1.0)    # 30% volatility threshold
    market_cap_minimum: int = Field(1000000000, ge=1000000)       # $1B minimum market cap


class OrderManagementConfig(BaseModel):
    """Order management configuration."""
    # Order Settings
    default_order_type: OrderType = OrderType.MARKET
    default_time_in_force: TimeInForce = TimeInForce.DAY
    max_order_size: int = Field(10000, ge=1, le=1000000)
    min_order_size: int = Field(1, ge=1, le=1000)
    
    # Order Validation
    check_margin: bool = True
    check_balance: bool = True
    validate_symbol: bool = True
    check_market_hours: bool = True
    check_position_limits: bool = True
    
    # Order Execution
    max_retry_attempts: int = Field(3, ge=0, le=10)
    retry_delay: int = Field(1, ge=0, le=60)  # seconds
    execution_timeout: int = Field(30, ge=5, le=300)  # seconds


class DataManagementConfig(BaseModel):
    """Data management configuration."""
    # Data Storage
    enable_compression: bool = True
    enable_retention: bool = True
    retention_period: str = "1 year"
    backup_enabled: bool = True
    backup_interval: str = "daily"
    
    # Data Quality
    validate_data: bool = True
    min_volume_threshold: int = Field(1000, ge=0)
    max_price_deviation: float = Field(0.1, ge=0.0, le=1.0)
    outlier_detection: bool = True
    missing_data_handling: str = Field("interpolate", pattern="^(interpolate|forward_fill|backward_fill|drop)$")


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""
    # System Monitoring
    monitor_cpu: bool = True
    monitor_memory: bool = True
    monitor_disk: bool = True
    monitor_network: bool = True
    
    # Alert Thresholds
    cpu_usage_threshold: int = Field(80, ge=50, le=100)
    memory_usage_threshold: int = Field(80, ge=50, le=100)
    disk_usage_threshold: int = Field(90, ge=70, le=100)
    
    # Trading Monitoring
    monitor_positions: bool = True
    monitor_orders: bool = True
    monitor_pnl: bool = True
    monitor_risk: bool = True
    
    # Trading Alert Thresholds
    daily_loss_alert: float = Field(0.03, ge=0.01, le=1.0)    # 3% daily loss alert
    drawdown_alert: float = Field(0.10, ge=0.01, le=1.0)      # 10% drawdown alert
    position_size_alert: float = Field(0.08, ge=0.01, le=1.0)  # 8% position size alert
    
    # Data Monitoring
    monitor_data_quality: bool = True
    monitor_data_latency: bool = True
    monitor_api_limits: bool = True
    
    # Data Alert Thresholds
    data_latency_threshold: int = Field(5, ge=1, le=60)      # 5 seconds
    api_limit_usage_threshold: int = Field(80, ge=50, le=100)  # 80% of API limit


class LoggingConfig(BaseModel):
    """Logging configuration."""
    # Log Level
    level: LogLevel = LogLevel.INFO
    
    # Log Format
    format: str = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
    
    # Log Rotation
    rotation: str = "100 MB"
    retention: str = "30 days"
    compression: str = "gz"
    
    # Log Files
    main_log_file: str = "logs/trading_platform.log"
    error_log_file: str = "logs/errors.log"
    trading_log_file: str = "logs/trading.log"
    data_log_file: str = "logs/data.log"
    performance_log_file: str = "logs/performance.log"
    
    # Console Logging
    console_enabled: bool = True
    console_level: LogLevel = LogLevel.INFO
    
    # Structured Logging
    structured_enabled: bool = True
    structured_format: str = "json"
    include_extra: bool = True


class PerformanceConfig(BaseModel):
    """Performance configuration."""
    # Optimization
    enable_caching: bool = True
    cache_ttl: int = Field(300, ge=60, le=3600)  # 5 minutes
    enable_parallel_processing: bool = True
    max_workers: int = Field(4, ge=1, le=16)
    
    # Memory Management
    max_memory_usage: float = Field(0.80, ge=0.5, le=1.0)  # 80% of available memory
    garbage_collection_interval: int = Field(3600, ge=300, le=86400)  # 1 hour


class SecurityConfig(BaseModel):
    """Security configuration."""
    # API Security
    enable_authentication: bool = False  # Will be enabled in production
    enable_rate_limiting: bool = True
    max_requests_per_minute: int = Field(100, ge=1, le=10000)
    
    # Data Security
    encrypt_sensitive_data: bool = False  # Will be enabled in production
    enable_audit_logging: bool = True
    data_retention_policy: str = "1 year"


class TradingConfig(BaseModel):
    """Complete trading configuration."""
    # General Settings
    platform_name: str = "VectorBT Trading Platform"
    version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    timezone: str = "America/New_York"
    
    # Trading Hours
    trading_hours: TradingHoursConfig = Field(default_factory=TradingHoursConfig)
    
    # Risk Management
    risk_management: RiskManagementConfig = Field(default_factory=RiskManagementConfig)
    
    # Order Management
    order_management: OrderManagementConfig = Field(default_factory=OrderManagementConfig)
    
    # Data Management
    data_management: DataManagementConfig = Field(default_factory=DataManagementConfig)
    
    # Monitoring and Alerts
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    
    # Logging
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    
    # Performance
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    
    # Security
    security: SecurityConfig = Field(default_factory=SecurityConfig)


# =============================================================================
# MAIN CONFIGURATION
# =============================================================================

class ApplicationConfig(BaseModel):
    """Application configuration."""
    name: str = "Trading Platform"
    version: str = "0.1.0"
    description: str = "VectorBT + Polygon.io + Interactive Brokers Trading Platform"
    author: str = "Trading Platform Team"


class EnvironmentConfig(BaseModel):
    """Environment-specific configuration."""
    current: Environment = Environment.DEVELOPMENT
    
    # Environment-specific settings
    development: Dict[str, Any] = Field(default_factory=lambda: {
        "debug": True,
        "log_level": "DEBUG",
        "enable_hot_reload": True
    })
    
    staging: Dict[str, Any] = Field(default_factory=lambda: {
        "debug": False,
        "log_level": "INFO",
        "enable_hot_reload": False
    })
    
    production: Dict[str, Any] = Field(default_factory=lambda: {
        "debug": False,
        "log_level": "WARNING",
        "enable_hot_reload": False
    })


class FeatureFlagsConfig(BaseModel):
    """Feature flags configuration."""
    # Core features
    core: Dict[str, bool] = Field(default_factory=lambda: {
        "database": True,
        "data_collection": True,
        "strategy_framework": True,
        "backtesting": True
    })
    
    # Advanced features
    advanced: Dict[str, bool] = Field(default_factory=lambda: {
        "live_trading": False,  # Will be enabled in Phase 3
        "real_time_data": False,  # Will be enabled in Phase 3
        "risk_management": True,
        "portfolio_management": True
    })
    
    # Experimental features
    experimental: Dict[str, bool] = Field(default_factory=lambda: {
        "ml_integration": False,
        "advanced_analytics": False,
        "web_dashboard": False
    })


class SystemConfig(BaseModel):
    """System configuration."""
    # Timezone
    timezone: str = "America/New_York"
    
    # Working Directory
    working_directory: str = "."
    
    # Data Directory
    data_directory: str = "data"
    
    # Logs Directory
    logs_directory: str = "logs"
    
    # Config Directory
    config_directory: str = "config"
    
    # Scripts Directory
    scripts_directory: str = "scripts"


class MainConfig(BaseModel):
    """Main configuration that combines all other configurations."""
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    features: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
    
    # Core configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    polygon: PolygonConfig
    ibkr: IBKRConfig
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    
    @model_validator(mode='after')
    def validate_configuration(self):
        """Validate the entire configuration."""
        # Add any cross-configuration validation here
        return self
