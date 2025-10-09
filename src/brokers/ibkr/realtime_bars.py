"""
Real-time bar streaming for IBKR.

Provides real-time bar data subscription and aggregation capabilities
for the charting application.
"""

import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Callable, Optional, Any
from collections import deque
import threading
import time

from ib_insync import IB, Stock, RealTimeBar
from loguru import logger

from src.brokers.ibkr.adapters import IBBroker
from src.utils.timeframes import (
    get_timeframe_seconds, 
    aggregate_bars, 
    is_timeframe_complete,
    get_aggregation_interval
)


class BarBuffer:
    """Ring buffer for storing real-time bars."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
    
    def add_bar(self, bar: Dict[str, Any]) -> None:
        """Add a new bar to the buffer."""
        with self.lock:
            self.buffer.append(bar)
    
    def get_bars(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get bars from the buffer."""
        with self.lock:
            if count is None:
                return list(self.buffer)
            return list(self.buffer)[-count:] if count > 0 else []
    
    def get_latest_bar(self) -> Optional[Dict[str, Any]]:
        """Get the most recent bar."""
        with self.lock:
            return self.buffer[-1] if self.buffer else None
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self.lock:
            self.buffer.clear()


class IBKRRealtimeBarStream:
    """Real-time bar streaming manager for IBKR."""
    
    def __init__(self, broker: Optional[IBBroker] = None):
        self.broker = broker or IBBroker()
        self.ib = self.broker.client.ib
        
        # Bar storage
        self.bar_buffer = BarBuffer(max_size=2000)  # Store 5-second bars
        self.aggregated_bars: Dict[str, BarBuffer] = {}  # By timeframe
        
        # Subscription state
        self.subscribed_symbols: Dict[str, Any] = {}  # symbol -> reqId
        self.is_connected = False
        self.is_streaming = False
        
        # Callbacks
        self.bar_callbacks: List[Callable] = []
        self.timeframe_callbacks: Dict[str, List[Callable]] = {}
        
        # Threading
        self.aggregation_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
    
    def connect(self) -> None:
        """Connect to IBKR."""
        if not self.is_connected:
            self.broker.connect()
            self.is_connected = True
            logger.info("Connected to IBKR for real-time bars")
    
    def disconnect(self) -> None:
        """Disconnect from IBKR."""
        self.stop_streaming()
        if self.is_connected:
            self.broker.disconnect()
            self.is_connected = False
            logger.info("Disconnected from IBKR")
    
    def subscribe_bars(self, symbol: str, bar_size: int = 5) -> None:
        """
        Subscribe to real-time bars for a symbol.
        
        Args:
            symbol: Symbol to subscribe to
            bar_size: Bar size in seconds (default: 5)
        """
        if not self.is_connected:
            self.connect()
        
        if symbol in self.subscribed_symbols:
            logger.warning(f"Already subscribed to {symbol}")
            return
        
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            
            # Subscribe to real-time bars
            req_id = self.ib.reqRealTimeBars(
                contract,
                barSize=bar_size,
                whatToShow='TRADES',
                useRTH=False,  # Include pre/post market
                realTimeBarsOptions=[]
            )
            
            self.subscribed_symbols[symbol] = req_id
            
            # Set up bar update callback
            self.ib.realTimeBarUpdateEvent += self._on_bar_update
            
            logger.info(f"Subscribed to {bar_size}s bars for {symbol} (reqId: {req_id})")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to bars for {symbol}: {e}")
            raise
    
    def unsubscribe_bars(self, symbol: str) -> None:
        """Unsubscribe from real-time bars for a symbol."""
        if symbol not in self.subscribed_symbols:
            return
        
        try:
            req_id = self.subscribed_symbols[symbol]
            self.ib.cancelRealTimeBars(req_id)
            del self.subscribed_symbols[symbol]
            logger.info(f"Unsubscribed from bars for {symbol}")
        except Exception as e:
            logger.error(f"Failed to unsubscribe from bars for {symbol}: {e}")
    
    def _on_bar_update(self, req_id: int, time: int, open_: float, high: float, 
                      low: float, close: float, volume: int, wap: float, count: int) -> None:
        """Handle real-time bar updates from IBKR."""
        try:
            # Find symbol for this req_id
            symbol = None
            for sym, rid in self.subscribed_symbols.items():
                if rid == req_id:
                    symbol = sym
                    break
            
            if not symbol:
                logger.warning(f"Received bar update for unknown reqId: {req_id}")
                return
            
            # Convert timestamp
            timestamp = datetime.fromtimestamp(time)
            
            # Create bar data
            bar_data = {
                'timestamp': timestamp,
                'symbol': symbol,
                'open': open_,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'wap': wap,
                'count': count
            }
            
            # Add to buffer
            self.bar_buffer.add_bar(bar_data)
            
            # Notify callbacks
            for callback in self.bar_callbacks:
                try:
                    callback(bar_data)
                except Exception as e:
                    logger.error(f"Error in bar callback: {e}")
            
            logger.debug(f"Received bar for {symbol}: {timestamp} O:{open_} H:{high} L:{low} C:{close}")
            
        except Exception as e:
            logger.error(f"Error processing bar update: {e}")
    
    def start_aggregation(self, timeframes: List[str]) -> None:
        """
        Start aggregation thread for specified timeframes.
        
        Args:
            timeframes: List of timeframes to aggregate (e.g., ['1m', '5m', '1h'])
        """
        if self.aggregation_thread and self.aggregation_thread.is_alive():
            logger.warning("Aggregation thread already running")
            return
        
        # Initialize aggregated bar buffers
        for tf in timeframes:
            if tf not in self.aggregated_bars:
                self.aggregated_bars[tf] = BarBuffer(max_size=500)
                self.timeframe_callbacks[tf] = []
        
        # Start aggregation thread
        self.stop_event.clear()
        self.aggregation_thread = threading.Thread(
            target=self._aggregation_worker,
            args=(timeframes,),
            daemon=True
        )
        self.aggregation_thread.start()
        self.is_streaming = True
        
        logger.info(f"Started aggregation for timeframes: {timeframes}")
    
    def stop_aggregation(self) -> None:
        """Stop the aggregation thread."""
        if self.aggregation_thread:
            self.stop_event.set()
            self.aggregation_thread.join(timeout=5.0)
            self.is_streaming = False
            logger.info("Stopped aggregation thread")
    
    def _aggregation_worker(self, timeframes: List[str]) -> None:
        """Worker thread for bar aggregation."""
        logger.info("Aggregation worker started")
        
        while not self.stop_event.is_set():
            try:
                # Get recent bars
                recent_bars = self.bar_buffer.get_bars(100)  # Last 100 bars
                
                if not recent_bars:
                    time.sleep(1)
                    continue
                
                # Convert to DataFrame
                df = pd.DataFrame(recent_bars)
                if df.empty:
                    time.sleep(1)
                    continue
                
                # Aggregate for each timeframe
                for timeframe in timeframes:
                    try:
                        # Aggregate bars
                        aggregated = aggregate_bars(
                            df, 
                            timeframe,
                            timestamp_col='timestamp',
                            open_col='open',
                            high_col='high',
                            low_col='low',
                            close_col='close',
                            volume_col='volume'
                        )
                        
                        if not aggregated.empty:
                            # Get latest aggregated bar
                            latest_bar = aggregated.iloc[-1].to_dict()
                            
                            # Check if this is a new bar (not already in buffer)
                            existing_bars = self.aggregated_bars[timeframe].get_bars()
                            if (not existing_bars or 
                                existing_bars[-1]['timestamp'] != latest_bar['timestamp']):
                                
                                # Add to aggregated buffer
                                self.aggregated_bars[timeframe].add_bar(latest_bar)
                                
                                # Notify callbacks
                                for callback in self.timeframe_callbacks[timeframe]:
                                    try:
                                        callback(latest_bar, timeframe)
                                    except Exception as e:
                                        logger.error(f"Error in timeframe callback: {e}")
                                
                                logger.debug(f"Aggregated {timeframe} bar: {latest_bar['timestamp']}")
                    
                    except Exception as e:
                        logger.error(f"Error aggregating {timeframe}: {e}")
                
                # Sleep briefly
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in aggregation worker: {e}")
                time.sleep(1)
        
        logger.info("Aggregation worker stopped")
    
    def get_bars(self, timeframe: str, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get aggregated bars for a timeframe.
        
        Args:
            timeframe: Timeframe (e.g., '1m', '5m', '1h')
            count: Number of bars to return (None for all)
            
        Returns:
            List of bar dictionaries
        """
        if timeframe not in self.aggregated_bars:
            return []
        
        return self.aggregated_bars[timeframe].get_bars(count)
    
    def get_latest_bar(self, timeframe: str) -> Optional[Dict[str, Any]]:
        """Get the latest bar for a timeframe."""
        if timeframe not in self.aggregated_bars:
            return None
        
        return self.aggregated_bars[timeframe].get_latest_bar()
    
    def add_bar_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Add callback for raw 5-second bar updates."""
        self.bar_callbacks.append(callback)
    
    def add_timeframe_callback(self, timeframe: str, 
                              callback: Callable[[Dict[str, Any], str], None]) -> None:
        """Add callback for aggregated bar updates."""
        if timeframe not in self.timeframe_callbacks:
            self.timeframe_callbacks[timeframe] = []
        self.timeframe_callbacks[timeframe].append(callback)
    
    def remove_bar_callback(self, callback: Callable) -> None:
        """Remove bar callback."""
        if callback in self.bar_callbacks:
            self.bar_callbacks.remove(callback)
    
    def remove_timeframe_callback(self, timeframe: str, callback: Callable) -> None:
        """Remove timeframe callback."""
        if timeframe in self.timeframe_callbacks and callback in self.timeframe_callbacks[timeframe]:
            self.timeframe_callbacks[timeframe].remove(callback)
    
    def start_streaming(self, symbol: str, timeframes: List[str]) -> None:
        """
        Start streaming bars for a symbol with aggregation.
        
        Args:
            symbol: Symbol to stream
            timeframes: Timeframes to aggregate
        """
        self.subscribe_bars(symbol)
        self.start_aggregation(timeframes)
        logger.info(f"Started streaming {symbol} with timeframes: {timeframes}")
    
    def stop_streaming(self) -> None:
        """Stop all streaming."""
        # Unsubscribe from all symbols
        for symbol in list(self.subscribed_symbols.keys()):
            self.unsubscribe_bars(symbol)
        
        # Stop aggregation
        self.stop_aggregation()
        
        logger.info("Stopped all streaming")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current streaming status."""
        return {
            'is_connected': self.is_connected,
            'is_streaming': self.is_streaming,
            'subscribed_symbols': list(self.subscribed_symbols.keys()),
            'active_timeframes': list(self.aggregated_bars.keys()),
            'bar_count': len(self.bar_buffer.get_bars()),
            'aggregated_counts': {
                tf: len(buf.get_bars()) 
                for tf, buf in self.aggregated_bars.items()
            }
        }
