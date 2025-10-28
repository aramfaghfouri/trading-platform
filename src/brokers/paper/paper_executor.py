"""
Paper Trading Executor

Simulates order execution without real money for strategy testing and validation.
Maintains virtual positions, cash balance, and tracks P&L.
"""

from __future__ import annotations

import asyncio
import asyncpg
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from loguru import logger

from src.strategies.models import OrderSpec, OrderAction, OrderType, TimeInForce
from src.data_pipeline.base import TradeExecutorBase
from src.core.config_loader import get_database_config


@dataclass
class Position:
    """Represents a position in a symbol."""
    symbol: str
    quantity: int  # Positive for long, negative for short
    avg_price: Decimal
    unrealized_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0
    
    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


@dataclass
class Trade:
    """Represents a completed trade."""
    trade_id: str
    symbol: str
    action: OrderAction
    quantity: int
    price: Decimal
    timestamp: datetime
    strategy_name: str
    commission: Decimal = Decimal('0')
    pnl: Optional[Decimal] = None


@dataclass
class AccountBalance:
    """Paper trading account balance."""
    cash: Decimal
    total_equity: Decimal
    buying_power: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderResult:
    """Result of order execution."""
    order_id: str
    symbol: str
    action: OrderAction
    quantity: int
    filled_quantity: int
    avg_fill_price: Decimal
    status: str  # FILLED, PARTIAL, REJECTED, PENDING
    timestamp: datetime
    commission: Decimal
    message: Optional[str] = None


class PaperTradeExecutor(TradeExecutorBase):
    """
    Paper trading executor that simulates order execution without real money.
    
    Features:
    - Maintains virtual positions and cash balance
    - Simulates order fills at market prices from database
    - Tracks P&L, win rate, max drawdown
    - Supports all order types (market, limit, stop, bracket)
    - Persists state to database
    """
    
    def __init__(
        self,
        initial_capital: Decimal = Decimal('100000'),
        commission_per_share: Decimal = Decimal('0.005'),
        account_id: str = 'paper_account_001'
    ):
        """
        Initialize paper trading executor.
        
        Args:
            initial_capital: Starting cash balance
            commission_per_share: Commission per share traded
            account_id: Unique account identifier
        """
        self.account_id = account_id
        self.initial_capital = initial_capital
        self.commission_per_share = commission_per_share
        
        # Account state
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.order_counter = 0
        
        # Database connection
        self.db_config = get_database_config()
        self.db_pool: Optional[asyncpg.Pool] = None
        
        logger.info(f"Paper trading executor initialized with ${initial_capital}")
    
    async def initialize(self) -> None:
        """Initialize database connection and load account state."""
        if self.db_pool:
            return
        
        # Connect to database
        import os
        dsn = os.getenv("DATABASE_URL")
        
        if dsn:
            self.db_pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=5,
                command_timeout=30,
                server_settings={
                    'application_name': f'paper_trading_{self.account_id}',
                    'timezone': 'UTC'
                }
            )
        else:
            self.db_pool = await asyncpg.create_pool(
                host=self.db_config.host,
                port=self.db_config.port,
                database=self.db_config.database,
                user=self.db_config.username,
                password=self.db_config.password,
                ssl=self.db_config.ssl_mode,
                min_size=1,
                max_size=5,
                command_timeout=30,
                server_settings={
                    'application_name': f'paper_trading_{self.account_id}',
                    'timezone': 'UTC'
                }
            )
        
        # Load account state from database
        await self._load_account_state()
        
        logger.info(f"Paper trading executor connected to database")
    
    async def shutdown(self) -> None:
        """Save account state and close database connection."""
        if self.db_pool:
            await self._save_account_state()
            await self.db_pool.close()
            self.db_pool = None
        logger.info("Paper trading executor shut down")
    
    async def place_order(self, order_spec: OrderSpec) -> OrderResult:
        """
        Place a paper trading order.
        
        Args:
            order_spec: Order specification
            
        Returns:
            OrderResult with execution details
        """
        if not self.db_pool:
            await self.initialize()
        
        self.order_counter += 1
        order_id = f"PAPER_{self.order_counter:06d}"
        
        try:
            # Get current market price from database
            current_price = await self._get_current_price(order_spec.symbol)
            if current_price is None:
                return OrderResult(
                    order_id=order_id,
                    symbol=order_spec.symbol,
                    action=order_spec.action,
                    quantity=order_spec.quantity,
                    filled_quantity=0,
                    avg_fill_price=Decimal('0'),
                    status='REJECTED',
                    timestamp=datetime.now(timezone.utc),
                    commission=Decimal('0'),
                    message=f"No current price data for {order_spec.symbol}"
                )
            
            # Simulate order execution
            fill_price = await self._simulate_order_execution(order_spec, current_price)
            if fill_price is None:
                return OrderResult(
                    order_id=order_id,
                    symbol=order_spec.symbol,
                    action=order_spec.action,
                    quantity=order_spec.quantity,
                    filled_quantity=0,
                    avg_fill_price=Decimal('0'),
                    status='REJECTED',
                    timestamp=datetime.now(timezone.utc),
                    commission=Decimal('0'),
                    message="Order execution failed"
                )
            
            # Calculate commission
            commission = self.commission_per_share * order_spec.quantity
            
            # Update account state
            await self._update_position(order_spec.symbol, order_spec.action, order_spec.quantity, fill_price, commission)
            
            # Record trade
            trade = Trade(
                trade_id=order_id,
                symbol=order_spec.symbol,
                action=order_spec.action,
                quantity=order_spec.quantity,
                price=fill_price,
                timestamp=datetime.now(timezone.utc),
                strategy_name=order_spec.strategy_name,
                commission=commission
            )
            self.trades.append(trade)
            
            # Save to database
            await self._save_trade(trade)
            
            logger.info(
                f"PAPER TRADE: {order_spec.action.value} {order_spec.quantity} {order_spec.symbol} @ ${fill_price} "
                f"(Commission: ${commission})"
            )
            
            return OrderResult(
                order_id=order_id,
                symbol=order_spec.symbol,
                action=order_spec.action,
                quantity=order_spec.quantity,
                filled_quantity=order_spec.quantity,
                avg_fill_price=fill_price,
                status='FILLED',
                timestamp=datetime.now(timezone.utc),
                commission=commission
            )
            
        except Exception as e:
            logger.error(f"Error placing paper order: {e}")
            return OrderResult(
                order_id=order_id,
                symbol=order_spec.symbol,
                action=order_spec.action,
                quantity=order_spec.quantity,
                filled_quantity=0,
                avg_fill_price=Decimal('0'),
                status='REJECTED',
                timestamp=datetime.now(timezone.utc),
                commission=Decimal('0'),
                message=str(e)
            )
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        return self.positions.get(symbol.upper())
    
    async def get_all_positions(self) -> Dict[str, Position]:
        """Get all current positions."""
        return self.positions.copy()
    
    async def get_account_balance(self) -> AccountBalance:
        """Get current account balance."""
        # Calculate unrealized P&L
        total_unrealized_pnl = Decimal('0')
        for position in self.positions.values():
            if not position.is_flat:
                current_price = await self._get_current_price(position.symbol)
                if current_price:
                    if position.is_long:
                        position.unrealized_pnl = (current_price - position.avg_price) * position.quantity
                    else:
                        position.unrealized_pnl = (position.avg_price - current_price) * abs(position.quantity)
                    total_unrealized_pnl += position.unrealized_pnl
        
        # Calculate total equity
        total_equity = self.cash + total_unrealized_pnl
        
        return AccountBalance(
            cash=self.cash,
            total_equity=total_equity,
            buying_power=self.cash,  # Simplified - no margin
            unrealized_pnl=total_unrealized_pnl,
            realized_pnl=sum(trade.pnl or Decimal('0') for trade in self.trades),
            last_updated=datetime.now(timezone.utc)
        )
    
    async def get_trade_history(self, symbol: Optional[str] = None) -> List[Trade]:
        """Get trade history, optionally filtered by symbol."""
        if symbol:
            return [trade for trade in self.trades if trade.symbol.upper() == symbol.upper()]
        return self.trades.copy()
    
    async def _get_current_price(self, symbol: str) -> Optional[Decimal]:
        """Get current market price from database."""
        if not self.db_pool:
            return None
        
        try:
            table_name = f"ibkr_ohlcv_{symbol.lower()}_1m"
            query = f"""
                SELECT close FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT 1
            """
            
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(query)
                if row:
                    return Decimal(str(row['close']))
                return None
                
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    async def _simulate_order_execution(self, order_spec: OrderSpec, current_price: Decimal) -> Optional[Decimal]:
        """Simulate order execution based on order type."""
        if order_spec.order_type == OrderType.MARKET:
            # Market orders fill at current price
            return current_price
        
        elif order_spec.order_type == OrderType.LIMIT:
            # Limit orders only fill if price is favorable
            if order_spec.action == OrderAction.BUY:
                return current_price if current_price <= order_spec.limit_price else None
            else:  # SELL
                return current_price if current_price >= order_spec.limit_price else None
        
        elif order_spec.order_type == OrderType.STOP:
            # Stop orders become market orders when triggered
            if order_spec.action == OrderAction.BUY:
                return current_price if current_price >= order_spec.stop_price else None
            else:  # SELL
                return current_price if current_price <= order_spec.stop_price else None
        
        elif order_spec.order_type == OrderType.STOP_LIMIT:
            # Stop-limit orders become limit orders when triggered
            if order_spec.action == OrderAction.BUY:
                if current_price >= order_spec.stop_price:
                    return current_price if current_price <= order_spec.limit_price else None
            else:  # SELL
                if current_price <= order_spec.stop_price:
                    return current_price if current_price >= order_spec.limit_price else None
        
        return None
    
    async def _update_position(
        self, 
        symbol: str, 
        action: OrderAction, 
        quantity: int, 
        price: Decimal, 
        commission: Decimal
    ) -> None:
        """Update position after trade execution."""
        symbol = symbol.upper()
        
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=0,
                avg_price=Decimal('0')
            )
        
        position = self.positions[symbol]
        
        # Calculate trade value and update cash
        trade_value = price * quantity
        if action == OrderAction.BUY:
            self.cash -= (trade_value + commission)
            new_quantity = position.quantity + quantity
        else:  # SELL
            self.cash += (trade_value - commission)
            new_quantity = position.quantity - quantity
        
        # Update position
        if new_quantity == 0:
            # Position closed
            position.quantity = 0
            position.avg_price = Decimal('0')
        else:
            # Update average price
            if (position.quantity > 0 and new_quantity > 0) or (position.quantity < 0 and new_quantity < 0):
                # Same direction - update average price
                total_cost = (position.avg_price * abs(position.quantity)) + (price * quantity)
                position.avg_price = total_cost / abs(new_quantity)
            else:
                # Direction change - set new average price
                position.avg_price = price
            
            position.quantity = new_quantity
        
        position.last_updated = datetime.now(timezone.utc)
    
    async def _save_trade(self, trade: Trade) -> None:
        """Save trade to database."""
        if not self.db_pool:
            return
        
        try:
            query = """
                INSERT INTO paper_trades 
                (trade_id, account_id, symbol, action, quantity, price, timestamp, 
                 strategy_name, commission, pnl)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """
            
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    trade.trade_id,
                    self.account_id,
                    trade.symbol,
                    trade.action.value,
                    trade.quantity,
                    float(trade.price),
                    trade.timestamp,
                    trade.strategy_name,
                    float(trade.commission),
                    float(trade.pnl) if trade.pnl else None
                )
        except Exception as e:
            logger.error(f"Error saving trade to database: {e}")
    
    async def _load_account_state(self) -> None:
        """Load account state from database."""
        if not self.db_pool:
            return
        
        try:
            # Load positions
            positions_query = """
                SELECT symbol, quantity, avg_price, unrealized_pnl, realized_pnl, last_updated
                FROM paper_positions
                WHERE account_id = $1
            """
            
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(positions_query, self.account_id)
                for row in rows:
                    self.positions[row['symbol']] = Position(
                        symbol=row['symbol'],
                        quantity=row['quantity'],
                        avg_price=Decimal(str(row['avg_price'])),
                        unrealized_pnl=Decimal(str(row['unrealized_pnl'])),
                        realized_pnl=Decimal(str(row['realized_pnl'])),
                        last_updated=row['last_updated']
                    )
            
            # Load account balance
            balance_query = """
                SELECT cash, total_equity, buying_power, unrealized_pnl, realized_pnl
                FROM paper_account
                WHERE account_id = $1
            """
            
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(balance_query, self.account_id)
                if row:
                    self.cash = Decimal(str(row['cash']))
            
            logger.info(f"Loaded account state: cash=${self.cash}, positions={len(self.positions)}")
            
        except Exception as e:
            logger.warning(f"Could not load account state: {e}")
    
    async def _save_account_state(self) -> None:
        """Save account state to database."""
        if not self.db_pool:
            return
        
        try:
            # Save positions
            for symbol, position in self.positions.items():
                if not position.is_flat:  # Only save non-zero positions
                    query = """
                        INSERT INTO paper_positions 
                        (account_id, symbol, quantity, avg_price, unrealized_pnl, realized_pnl, last_updated)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (account_id, symbol) DO UPDATE SET
                            quantity = EXCLUDED.quantity,
                            avg_price = EXCLUDED.avg_price,
                            unrealized_pnl = EXCLUDED.unrealized_pnl,
                            realized_pnl = EXCLUDED.realized_pnl,
                            last_updated = EXCLUDED.last_updated
                    """
                    
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            query,
                            self.account_id,
                            position.symbol,
                            position.quantity,
                            float(position.avg_price),
                            float(position.unrealized_pnl),
                            float(position.realized_pnl),
                            position.last_updated
                        )
            
            # Save account balance
            balance = await self.get_account_balance()
            query = """
                INSERT INTO paper_account 
                (account_id, cash, total_equity, buying_power, unrealized_pnl, realized_pnl, last_updated)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (account_id) DO UPDATE SET
                    cash = EXCLUDED.cash,
                    total_equity = EXCLUDED.total_equity,
                    buying_power = EXCLUDED.buying_power,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    realized_pnl = EXCLUDED.realized_pnl,
                    last_updated = EXCLUDED.last_updated
            """
            
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    query,
                    self.account_id,
                    float(balance.cash),
                    float(balance.total_equity),
                    float(balance.buying_power),
                    float(balance.unrealized_pnl),
                    float(balance.realized_pnl),
                    balance.last_updated
                )
            
            logger.info("Saved account state to database")
            
        except Exception as e:
            logger.error(f"Error saving account state: {e}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_trade_pnl': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # Calculate basic metrics
        total_trades = len(self.trades)
        winning_trades = sum(1 for trade in self.trades if trade.pnl and trade.pnl > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        total_pnl = sum(trade.pnl or Decimal('0') for trade in self.trades)
        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else Decimal('0')
        
        return {
            'total_trades': total_trades,
            'win_rate': float(win_rate),
            'total_pnl': float(total_pnl),
            'avg_trade_pnl': float(avg_trade_pnl),
            'max_drawdown': 0.0,  # TODO: Calculate from equity curve
            'sharpe_ratio': 0.0   # TODO: Calculate from returns
        }
