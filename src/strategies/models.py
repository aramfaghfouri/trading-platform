"""
Data models for trading strategies.

Defines standard interfaces for orders, signals, and strategy state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class OrderAction(str, Enum):
    """Order action types."""
    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'


class OrderType(str, Enum):
    """Order types."""
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP = 'STOP'
    STOP_LIMIT = 'STOP_LIMIT'


class TimeInForce(str, Enum):
    """Time in force for orders."""
    DAY = 'DAY'  # Valid for the day
    GTC = 'GTC'  # Good Till Cancelled
    IOC = 'IOC'  # Immediate or Cancel
    FOK = 'FOK'  # Fill or Kill


class SignalType(str, Enum):
    """Trading signal types."""
    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'
    CLOSE_LONG = 'CLOSE_LONG'
    CLOSE_SHORT = 'CLOSE_SHORT'


@dataclass
class StopLossSpec:
    """Stop-loss order specification."""
    stop_price: Decimal
    quantity: Optional[int] = None  # If None, uses parent order quantity
    time_in_force: TimeInForce = TimeInForce.GTC
    
    def __post_init__(self):
        """Validate stop-loss specification."""
        if self.stop_price <= 0:
            raise ValueError(f"Stop price must be positive, got {self.stop_price}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'stop_price': float(self.stop_price),
            'quantity': self.quantity,
            'time_in_force': self.time_in_force.value,
        }


@dataclass
class TakeProfitSpec:
    """Take-profit order specification."""
    limit_price: Decimal
    quantity: Optional[int] = None  # If None, uses parent order quantity
    time_in_force: TimeInForce = TimeInForce.GTC
    
    def __post_init__(self):
        """Validate take-profit specification."""
        if self.limit_price <= 0:
            raise ValueError(f"Limit price must be positive, got {self.limit_price}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'limit_price': float(self.limit_price),
            'quantity': self.quantity,
            'time_in_force': self.time_in_force.value,
        }


@dataclass
class TrailingStopSpec:
    """Trailing stop order specification."""
    trail_amount: Decimal  # Fixed dollar amount to trail
    trail_percent: Optional[Decimal] = None  # Percentage to trail (alternative to trail_amount)
    quantity: Optional[int] = None  # If None, uses parent order quantity
    time_in_force: TimeInForce = TimeInForce.GTC
    
    def __post_init__(self):
        """Validate trailing stop specification."""
        if self.trail_amount <= 0:
            raise ValueError(f"Trail amount must be positive, got {self.trail_amount}")
        if self.trail_percent is not None and not (0 < self.trail_percent < 1):
            raise ValueError(f"Trail percent must be between 0 and 1, got {self.trail_percent}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'trail_amount': float(self.trail_amount),
            'trail_percent': float(self.trail_percent) if self.trail_percent else None,
            'quantity': self.quantity,
            'time_in_force': self.time_in_force.value,
        }


@dataclass
class BracketOrderSpec:
    """Bracket order specification (entry + stop-loss + take-profit)."""
    entry_order: OrderSpec
    stop_loss: Optional[StopLossSpec] = None
    take_profit: Optional[TakeProfitSpec] = None
    
    def __post_init__(self):
        """Validate bracket order specification."""
        if not self.stop_loss and not self.take_profit:
            raise ValueError("Bracket order must have at least stop-loss or take-profit")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'entry_order': self.entry_order.to_dict(),
            'stop_loss': self.stop_loss.to_dict() if self.stop_loss else None,
            'take_profit': self.take_profit.to_dict() if self.take_profit else None,
        }


@dataclass
class OrderSpec:
    """
    Specification for a trading order to be executed.
    
    This is the output of a strategy that gets sent to the Order Manager.
    """
    symbol: str
    action: OrderAction
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None  # For LIMIT orders
    stop_price: Optional[Decimal] = None  # For STOP orders
    time_in_force: TimeInForce = TimeInForce.DAY
    strategy_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Advanced order types
    stop_loss: Optional[StopLossSpec] = None
    take_profit: Optional[TakeProfitSpec] = None
    trailing_stop: Optional[TrailingStopSpec] = None
    
    def __post_init__(self):
        """Validate order specification."""
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive, got {self.quantity}")
        
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT orders require a limit_price")
        
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError("STOP orders require a stop_price")
        
        if self.order_type == OrderType.STOP_LIMIT and self.limit_price is None:
            raise ValueError("STOP_LIMIT orders require both limit_price and stop_price")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'symbol': self.symbol,
            'action': self.action.value,
            'quantity': self.quantity,
            'order_type': self.order_type.value,
            'limit_price': float(self.limit_price) if self.limit_price else None,
            'stop_price': float(self.stop_price) if self.stop_price else None,
            'time_in_force': self.time_in_force.value,
            'strategy_name': self.strategy_name,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'stop_loss': self.stop_loss.to_dict() if self.stop_loss else None,
            'take_profit': self.take_profit.to_dict() if self.take_profit else None,
            'trailing_stop': self.trailing_stop.to_dict() if self.trailing_stop else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OrderSpec:
        """Create from dictionary."""
        # Helper function to create StopLossSpec from dict
        def create_stop_loss(data_dict):
            if not data_dict:
                return None
            return StopLossSpec(
                stop_price=Decimal(str(data_dict['stop_price'])),
                quantity=data_dict.get('quantity'),
                time_in_force=TimeInForce(data_dict.get('time_in_force', 'GTC'))
            )
        
        # Helper function to create TakeProfitSpec from dict
        def create_take_profit(data_dict):
            if not data_dict:
                return None
            return TakeProfitSpec(
                limit_price=Decimal(str(data_dict['limit_price'])),
                quantity=data_dict.get('quantity'),
                time_in_force=TimeInForce(data_dict.get('time_in_force', 'GTC'))
            )
        
        # Helper function to create TrailingStopSpec from dict
        def create_trailing_stop(data_dict):
            if not data_dict:
                return None
            return TrailingStopSpec(
                trail_amount=Decimal(str(data_dict['trail_amount'])),
                trail_percent=Decimal(str(data_dict['trail_percent'])) if data_dict.get('trail_percent') else None,
                quantity=data_dict.get('quantity'),
                time_in_force=TimeInForce(data_dict.get('time_in_force', 'GTC'))
            )
        
        return cls(
            symbol=data['symbol'],
            action=OrderAction(data['action']),
            quantity=data['quantity'],
            order_type=OrderType(data['order_type']),
            limit_price=Decimal(str(data['limit_price'])) if data.get('limit_price') else None,
            stop_price=Decimal(str(data['stop_price'])) if data.get('stop_price') else None,
            time_in_force=TimeInForce(data.get('time_in_force', 'DAY')),
            strategy_name=data.get('strategy_name', ''),
            metadata=data.get('metadata', {}),
            timestamp=datetime.fromisoformat(data['timestamp']) if 'timestamp' in data else datetime.utcnow(),
            stop_loss=create_stop_loss(data.get('stop_loss')),
            take_profit=create_take_profit(data.get('take_profit')),
            trailing_stop=create_trailing_stop(data.get('trailing_stop')),
        )


@dataclass
class SignalSpec:
    """
    Trading signal generated by a strategy.
    
    Signals are logged to the database and can be converted to OrderSpec
    for execution.
    """
    strategy_name: str
    symbol: str
    signal_type: SignalType
    signal_time: datetime
    confidence: float = 1.0  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    order_id: Optional[str] = None  # Linked order ID if executed
    
    def __post_init__(self):
        """Validate signal specification."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'signal_type': self.signal_type.value,
            'signal_time': self.signal_time.isoformat(),
            'confidence': self.confidence,
            'metadata': self.metadata,
            'order_id': self.order_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SignalSpec:
        """Create from dictionary."""
        return cls(
            strategy_name=data['strategy_name'],
            symbol=data['symbol'],
            signal_type=SignalType(data['signal_type']),
            signal_time=datetime.fromisoformat(data['signal_time']),
            confidence=data.get('confidence', 1.0),
            metadata=data.get('metadata', {}),
            order_id=data.get('order_id'),
        )


@dataclass
class BarData:
    """
    OHLCV bar data as returned from database queries.
    """
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    symbol: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'open': float(self.open),
            'high': float(self.high),
            'low': float(self.low),
            'close': float(self.close),
            'volume': self.volume,
            'symbol': self.symbol,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BarData:
        """Create from dictionary."""
        return cls(
            timestamp=data['timestamp'] if isinstance(data['timestamp'], datetime) else datetime.fromisoformat(data['timestamp']),
            open=Decimal(str(data['open'])),
            high=Decimal(str(data['high'])),
            low=Decimal(str(data['low'])),
            close=Decimal(str(data['close'])),
            volume=int(data['volume']),
            symbol=data.get('symbol', ''),
        )


@dataclass
class StrategyState:
    """
    State information for a running strategy.
    """
    strategy_name: str
    last_processed_timestamp: Optional[datetime] = None
    is_running: bool = False
    last_heartbeat: Optional[datetime] = None
    error_message: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'strategy_name': self.strategy_name,
            'last_processed_timestamp': self.last_processed_timestamp.isoformat() if self.last_processed_timestamp else None,
            'is_running': self.is_running,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'error_message': self.error_message,
            'updated_at': self.updated_at.isoformat(),
            'metadata': self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StrategyState:
        """Create from dictionary."""
        return cls(
            strategy_name=data['strategy_name'],
            last_processed_timestamp=datetime.fromisoformat(data['last_processed_timestamp']) if data.get('last_processed_timestamp') else None,
            is_running=data.get('is_running', False),
            last_heartbeat=datetime.fromisoformat(data['last_heartbeat']) if data.get('last_heartbeat') else None,
            error_message=data.get('error_message'),
            updated_at=datetime.fromisoformat(data['updated_at']) if 'updated_at' in data else datetime.utcnow(),
            metadata=data.get('metadata', {}),
        )

