"""
Real-time IBKR bar streaming with TimescaleDB persistence for multiple symbols.

This module extends the test303.py functionality to support:
- Multiple symbol subscriptions
- Async database writes using SourceDataStorage
- Batch write optimization
- Health monitoring
- Optional chart display for a single symbol
"""

from __future__ import annotations

import asyncio
import signal
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from loguru import logger

from ib_async import IB, util
from ib_async.contract import Stock

from src.data_collectors.common.source_storage import SourceDataStorage

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    ZoneInfo = None

try:
    from src.visualization.lightweight_chart import LightweightRealtimeChart
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False
    logger.warning("Chart functionality not available")


class SymbolStreamer:
    """Manages streaming for a single symbol with buffering for batch writes."""
    
    def __init__(
        self,
        symbol: str,
        aggregation_minutes: int = 1,
        batch_size: int = 12,  # Write every 12 bars (1 minute of 5s bars)
    ):
        self.symbol = symbol.upper()
        self.aggregation_minutes = aggregation_minutes
        self.batch_size = batch_size
        
        # Buffers for 5-second and aggregated bars
        self.raw_buffer: deque = deque(maxlen=1000)  # Keep recent 5s bars in memory
        self.agg_buffer: deque = deque(maxlen=500)   # Keep recent aggregated bars
        self.pending_writes: List[Dict[str, Any]] = []  # Batch write buffer
        
        # Aggregation state
        self._agg_state: Optional[Dict[str, Any]] = None
        self._agg_period_seconds = aggregation_minutes * 60
        
        # Statistics
        self.bars_received = 0
        self.bars_written = 0
        self.last_bar_time: Optional[datetime] = None
        self.last_write_time: Optional[datetime] = None
        
    def process_bar(self, bar: Any, timestamp: datetime) -> Optional[Dict[str, Any]]:
        """
        Process a new 5-second bar, update aggregation state.
        Returns completed aggregated bar if one is finalized.
        """
        self.bars_received += 1
        self.last_bar_time = timestamp
        
        # Store raw bar in memory buffer
        raw_bar = {
            'timestamp': timestamp,
            'open': float(getattr(bar, 'open_', getattr(bar, 'open'))),
            'high': float(getattr(bar, 'high_', getattr(bar, 'high'))),
            'low': float(getattr(bar, 'low_', getattr(bar, 'low'))),
            'close': float(getattr(bar, 'close_', getattr(bar, 'close'))),
            'volume': int(getattr(bar, 'volume', 0) or 0),
        }
        self.raw_buffer.append(raw_bar)
        self.pending_writes.append(raw_bar)
        
        # Update aggregation
        completed_agg = None
        if self._agg_state and timestamp >= self._agg_state['end']:
            # Current aggregation period ended
            completed_agg = self._agg_state.copy()
            self.agg_buffer.append(completed_agg)
            self._agg_state = None
        
        if self._agg_state is None:
            # Start new aggregation period
            period_start_epoch = (int(timestamp.timestamp()) // self._agg_period_seconds) * self._agg_period_seconds
            period_start = datetime.fromtimestamp(period_start_epoch, tz=timezone.utc)
            period_end = period_start + timedelta(seconds=self._agg_period_seconds)
            
            self._agg_state = {
                'timestamp': period_start,
                'start': period_start,
                'end': period_end,
                'open': raw_bar['open'],
                'high': raw_bar['high'],
                'low': raw_bar['low'],
                'close': raw_bar['close'],
                'volume': raw_bar['volume'],
            }
        else:
            # Update current aggregation
            self._agg_state['high'] = max(self._agg_state['high'], raw_bar['high'])
            self._agg_state['low'] = min(self._agg_state['low'], raw_bar['low'])
            self._agg_state['close'] = raw_bar['close']
            self._agg_state['volume'] += raw_bar['volume']
        
        return completed_agg
    
    def get_pending_writes(self) -> List[Dict[str, Any]]:
        """Get and clear pending write buffer."""
        pending = self.pending_writes.copy()
        self.pending_writes.clear()
        return pending
    
    def should_write(self) -> bool:
        """Check if we have enough bars buffered for a batch write."""
        return len(self.pending_writes) >= self.batch_size


class MultiSymbolRealtimeStreamer:
    """
    Stream real-time 5-second bars from IBKR for multiple symbols.
    Writes data to TimescaleDB with batch optimization.
    """
    
    def __init__(
        self,
        symbols: List[str],
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 100,
        aggregation_minutes: int = 1,
        batch_size: int = 12,
        enable_chart: bool = False,
        chart_symbol: Optional[str] = None,
    ):
        self.symbols = [s.upper() for s in symbols]
        self.host = host
        self.port = port
        self.client_id = client_id
        self.aggregation_minutes = aggregation_minutes
        self.batch_size = batch_size
        
        # IBKR connection
        self.ib = IB()
        self.subscriptions: Dict[str, Any] = {}
        
        # Symbol streamers
        self.streamers: Dict[str, SymbolStreamer] = {
            symbol: SymbolStreamer(symbol, aggregation_minutes, batch_size)
            for symbol in self.symbols
        }
        
        # Database storage
        self.storage: Optional[SourceDataStorage] = None
        self.db_task: Optional[asyncio.Task] = None
        self.write_queue: asyncio.Queue = asyncio.Queue()
        
        # Chart (optional, for one symbol only)
        self.enable_chart = enable_chart and CHART_AVAILABLE
        self.chart_symbol = (chart_symbol or symbols[0]).upper() if enable_chart else None
        self.chart: Optional[LightweightRealtimeChart] = None
        self.chart_thread: Optional[threading.Thread] = None
        
        # Control flags
        self._stopping = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Statistics
        self.start_time: Optional[datetime] = None
        
    def _on_bar_update(self, bars: Any, has_new_bar: bool) -> None:
        """Callback when new 5-second bar arrives from IBKR."""
        if not has_new_bar or self._stopping:
            return
        
        try:
            # Determine which symbol this bar is for
            symbol = bars.contract.symbol.upper()
            if symbol not in self.streamers:
                return
            
            # Get latest bar
            bar = bars[-1]
            timestamp = self._as_utc(bar.time)
            
            # Process through symbol streamer
            streamer = self.streamers[symbol]
            completed_agg = streamer.process_bar(bar, timestamp)
            
            # Log bar
            logger.debug(
                f"[{symbol}] 5s bar: {timestamp.isoformat()} "
                f"O:{bar.open_:.2f} H:{bar.high_:.2f} L:{bar.low_:.2f} C:{bar.close_:.2f} V:{bar.volume}"
            )
            
            # If aggregated bar completed, log it and update chart
            if completed_agg:
                logger.info(
                    f"[{symbol}] {self.aggregation_minutes}m bar: {completed_agg['start'].isoformat()} "
                    f"O:{completed_agg['open']:.2f} H:{completed_agg['high']:.2f} "
                    f"L:{completed_agg['low']:.2f} C:{completed_agg['close']:.2f} V:{completed_agg['volume']}"
                )
                
                # Update chart if this is the chart symbol
                if self.enable_chart and symbol == self.chart_symbol and self.chart:
                    self._update_chart(completed_agg)
            
            # Queue batch write if threshold reached
            if streamer.should_write() and self._loop:
                pending = streamer.get_pending_writes()
                self._loop.call_soon_threadsafe(
                    self.write_queue.put_nowait,
                    (symbol, pending)
                )
                
        except Exception as e:
            logger.error(f"Error processing bar: {e}", exc_info=True)
    
    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract: Any) -> None:
        """Handle IBKR errors."""
        if errorCode in (2104, 2106, 2158):  # Informational messages
            logger.debug(f"IBKR info [{errorCode}]: {errorString}")
        else:
            logger.warning(f"IBKR error [{errorCode}]: {errorString}")
    
    @staticmethod
    def _as_utc(ts: Union[int, float, datetime]) -> datetime:
        """Normalize timestamp to timezone-aware UTC datetime."""
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    
    def _update_chart(self, bar_data: Dict[str, Any]) -> None:
        """Update chart with new bar data."""
        if not self.enable_chart or not self.chart:
            return
        
        try:
            chart_bar = {
                'timestamp': bar_data['timestamp'],
                'symbol': self.chart_symbol,
                'open': bar_data['open'],
                'high': bar_data['high'],
                'low': bar_data['low'],
                'close': bar_data['close'],
                'volume': bar_data['volume']
            }
            self.chart._on_timeframe_update(chart_bar, f'{self.aggregation_minutes}m')
        except Exception as e:
            logger.error(f"Error updating chart: {e}")
    
    async def _db_writer_loop(self) -> None:
        """Async task that processes write queue and writes to TimescaleDB."""
        logger.info("Database writer loop started")
        
        while not self._stopping:
            try:
                # Wait for batch or timeout
                symbol, bars = await asyncio.wait_for(self.write_queue.get(), timeout=5.0)
                
                if not bars:
                    continue
                
                # Write to database
                timeframe = '5s'  # Raw bars are 5-second
                result = await self.storage.store_ohlcv(symbol, timeframe, bars)
                
                if result.success:
                    streamer = self.streamers[symbol]
                    streamer.bars_written += result.records_inserted
                    streamer.last_write_time = datetime.now(tz=timezone.utc)
                    logger.info(
                        f"[{symbol}] Wrote {result.records_inserted} bars to DB "
                        f"(total: {streamer.bars_written}/{streamer.bars_received})"
                    )
                else:
                    logger.error(f"[{symbol}] Database write failed: {result.error}")
                    
            except asyncio.TimeoutError:
                # Periodic flush of any pending writes
                for symbol, streamer in self.streamers.items():
                    if streamer.pending_writes:
                        pending = streamer.get_pending_writes()
                        if pending:
                            result = await self.storage.store_ohlcv(symbol, '5s', pending)
                            if result.success:
                                streamer.bars_written += result.records_inserted
                                logger.debug(f"[{symbol}] Flushed {result.records_inserted} bars to DB")
                            
            except Exception as e:
                logger.error(f"Database writer error: {e}", exc_info=True)
                await asyncio.sleep(1)
        
        logger.info("Database writer loop stopped")
    
    def _start_chart(self) -> None:
        """Start chart in a separate thread for the designated symbol."""
        if not self.enable_chart or not CHART_AVAILABLE or not self.chart_symbol:
            return
        
        try:
            self.chart = LightweightRealtimeChart(
                symbol=self.chart_symbol,
                initial_timeframe=f'{self.aggregation_minutes}m'
            )
            self.chart.is_connected = False  # Prevent chart from connecting to IBKR
            
            def run_chart():
                try:
                    self.chart._create_chart()
                    self.chart.chart_type = 'ha'
                    self.chart._add_sample_data()
                    import time
                    time.sleep(1.0)
                    self.chart.chart.show(block=True)
                except Exception as e:
                    logger.error(f"Chart error: {e}", exc_info=True)
            
            self.chart_thread = threading.Thread(target=run_chart, daemon=True)
            self.chart_thread.start()
            logger.info(f"Chart started for {self.chart_symbol}")
            
        except Exception as e:
            logger.error(f"Failed to start chart: {e}")
            self.enable_chart = False
    
    async def start(self) -> None:
        """Connect to IBKR and start streaming for all symbols."""
        self.start_time = datetime.now(tz=timezone.utc)
        self._loop = asyncio.get_event_loop()
        
        # Connect to database
        logger.info("Connecting to TimescaleDB...")
        self.storage = SourceDataStorage(source='ibkr')
        await self.storage.connect()
        
        # Start database writer task
        self.db_task = asyncio.create_task(self._db_writer_loop())
        
        # Connect to IBKR
        logger.info(f"Connecting to IBKR at {self.host}:{self.port} (clientId={self.client_id})...")
        self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)
        
        if not self.ib.isConnected():
            raise RuntimeError("Could not connect to IBKR")
        
        logger.info("Connected to IBKR")
        self.ib.reqMarketDataType(1)  # Real-time data
        self.ib.errorEvent += self._on_error
        
        # Subscribe to each symbol
        for symbol in self.symbols:
            contract = Stock(
                symbol=symbol,
                exchange='SMART',
                currency='USD',
                primaryExchange='NASDAQ'
            )
            
            logger.info(f"Subscribing to real-time bars for {symbol}...")
            subscription = self.ib.reqRealTimeBars(
                contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=False,
                realTimeBarsOptions=[],
            )
            subscription.updateEvent += self._on_bar_update
            self.subscriptions[symbol] = subscription
            
            # Small delay between subscriptions
            await asyncio.sleep(0.5)
        
        logger.info(f"Subscribed to {len(self.symbols)} symbols: {', '.join(self.symbols)}")
        
        # Start chart if enabled
        if self.enable_chart:
            self._start_chart()
        
        logger.info("Real-time streaming started")
    
    async def stop(self) -> None:
        """Stop streaming and disconnect."""
        if self._stopping:
            return
        
        logger.info("Stopping real-time streamer...")
        self._stopping = True
        
        # Flush all pending writes
        for symbol, streamer in self.streamers.items():
            if streamer.pending_writes:
                pending = streamer.get_pending_writes()
                if pending and self.storage:
                    result = await self.storage.store_ohlcv(symbol, '5s', pending)
                    logger.info(f"[{symbol}] Final flush: {result.records_inserted} bars")
        
        # Stop database writer
        if self.db_task:
            self.db_task.cancel()
            try:
                await self.db_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect from IBKR
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IBKR")
        
        # Disconnect from database
        if self.storage:
            await self.storage.disconnect()
        
        # Stop chart
        if self.chart:
            try:
                self.chart.disconnect_from_ibkr()
            except Exception as e:
                logger.debug(f"Chart disconnect error: {e}")
        
        # Print statistics
        self._print_statistics()
        logger.info("Real-time streamer stopped")
    
    def _print_statistics(self) -> None:
        """Print streaming statistics for all symbols."""
        if not self.start_time:
            return
        
        runtime = (datetime.now(tz=timezone.utc) - self.start_time).total_seconds()
        logger.info("=" * 60)
        logger.info("STREAMING STATISTICS")
        logger.info("=" * 60)
        logger.info(f"Runtime: {runtime:.1f} seconds")
        
        for symbol, streamer in self.streamers.items():
            logger.info(
                f"{symbol:6s}: {streamer.bars_received:4d} bars received, "
                f"{streamer.bars_written:4d} written to DB, "
                f"{len(streamer.agg_buffer)} aggregated bars in memory"
            )
        
        logger.info("=" * 60)
    
    async def run_forever(self) -> None:
        """Run the streamer until interrupted."""
        await self.start()
        
        # Setup signal handlers
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, stopping...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Keep running
        try:
            while not self._stopping:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.stop()


async def main(
    symbols: List[str],
    host: str = '127.0.0.1',
    port: int = 7497,
    client_id: int = 100,
    enable_chart: bool = False,
    chart_symbol: Optional[str] = None,
) -> None:
    """Main entry point for real-time streaming."""
    streamer = MultiSymbolRealtimeStreamer(
        symbols=symbols,
        host=host,
        port=port,
        client_id=client_id,
        aggregation_minutes=1,
        batch_size=12,
        enable_chart=enable_chart,
        chart_symbol=chart_symbol,
    )
    
    await streamer.run_forever()


if __name__ == '__main__':
    import sys
    
    # Parse command line arguments
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['AAPL']
    
    logger.info(f"Starting real-time streamer for symbols: {', '.join(symbols)}")
    
    # Run the streamer
    asyncio.run(main(
        symbols=symbols,
        enable_chart=True,  # Enable chart for first symbol
        chart_symbol=symbols[0],
    ))

