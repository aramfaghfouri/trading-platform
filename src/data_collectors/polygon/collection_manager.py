"""
Polygon.io Data Collection Manager

This module provides a comprehensive data collection manager that orchestrates
the entire data collection process from Polygon.io, including scheduling,
error handling, and data storage.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
from loguru import logger

from src.core.config_loader import get_polygon_config, get_database_config
from src.core.config_models import PolygonConfig, DatabaseConfig
from .enhanced_collector import (
    PolygonDataCollector, DataCollectionResult, Timeframe,
    collect_symbol_data, collect_multiple_symbols
)
from .data_storage import (
    PolygonDataStorage, StorageResult,
    store_symbol_data, get_symbol_data
)


class CollectionStatus(str, Enum):
    """Collection status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CollectionTask:
    """Data collection task definition."""
    symbol: str
    start_date: datetime
    end_date: datetime
    timeframe: Timeframe = Timeframe.DAY_1
    priority: int = 1  # Higher number = higher priority
    retry_count: int = 0
    max_retries: int = 3
    status: CollectionStatus = CollectionStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[DataCollectionResult] = None
    storage_result: Optional[StorageResult] = None


@dataclass
class CollectionBatch:
    """Batch of collection tasks."""
    tasks: List[CollectionTask]
    batch_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: CollectionStatus = CollectionStatus.PENDING


class PolygonCollectionManager:
    """Comprehensive data collection manager for Polygon.io."""
    
    def __init__(
        self,
        polygon_config: Optional[PolygonConfig] = None,
        db_config: Optional[DatabaseConfig] = None,
        max_concurrent_tasks: int = 10,
        batch_size: int = 50
    ):
        """
        Initialize the collection manager.
        
        Args:
            polygon_config: Polygon.io configuration
            db_config: Database configuration
            max_concurrent_tasks: Maximum concurrent collection tasks
            batch_size: Batch size for processing
        """
        self.polygon_config = polygon_config or get_polygon_config()
        self.db_config = db_config or get_database_config()
        self.max_concurrent_tasks = max_concurrent_tasks
        self.batch_size = batch_size
        
        self.tasks: Dict[str, CollectionTask] = {}
        self.batches: Dict[str, CollectionBatch] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        
        # Statistics
        self.stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'total_records_collected': 0,
            'total_records_stored': 0,
            'start_time': None,
            'end_time': None
        }
        
        # Callbacks
        self.on_task_completed: Optional[Callable[[CollectionTask], None]] = None
        self.on_task_failed: Optional[Callable[[CollectionTask], None]] = None
        self.on_batch_completed: Optional[Callable[[CollectionBatch], None]] = None
        
        logger.info(f"Initialized Polygon collection manager with {max_concurrent_tasks} max concurrent tasks")
        
    def add_collection_task(
        self,
        symbol: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        timeframe: Timeframe = Timeframe.DAY_1,
        priority: int = 1,
        max_retries: int = 3
    ) -> str:
        """
        Add a collection task to the queue.
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Data timeframe
            priority: Task priority
            max_retries: Maximum retry attempts
            
        Returns:
            Task ID
        """
        # Convert string dates to datetime
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date)
            
        task_id = f"{symbol}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{timeframe.value}"
        
        task = CollectionTask(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            priority=priority,
            max_retries=max_retries
        )
        
        self.tasks[task_id] = task
        self.stats['total_tasks'] += 1
        
        logger.info(f"Added collection task: {task_id}")
        return task_id
    
    def add_batch_tasks(
        self,
        symbols: List[str],
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        timeframe: Timeframe = Timeframe.DAY_1,
        priority: int = 1,
        max_retries: int = 3
    ) -> List[str]:
        """
        Add multiple collection tasks for a batch of symbols.
        
        Args:
            symbols: List of stock symbols
            start_date: Start date
            end_date: End date
            timeframe: Data timeframe
            priority: Task priority
            max_retries: Maximum retry attempts
            
        Returns:
            List of task IDs
        """
        task_ids = []
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        batch_tasks = []
        for symbol in symbols:
            task_id = self.add_collection_task(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                priority=priority,
                max_retries=max_retries
            )
            task_ids.append(task_id)
            batch_tasks.append(self.tasks[task_id])
            
        # Create batch
        batch = CollectionBatch(
            tasks=batch_tasks,
            batch_id=batch_id
        )
        self.batches[batch_id] = batch
        
        logger.info(f"Added batch {batch_id} with {len(symbols)} tasks")
        return task_ids
    
    async def execute_task(self, task_id: str) -> CollectionTask:
        """
        Execute a single collection task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Updated CollectionTask
        """
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
            
        task = self.tasks[task_id]
        task.status = CollectionStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        
        try:
            logger.info(f"Executing task: {task_id}")
            
            # Collect data
            async with PolygonDataCollector(self.polygon_config) as collector:
                result = await collector.get_aggregates(
                    symbol=task.symbol,
                    multiplier=1,
                    timespan=task.timeframe,
                    from_date=task.start_date,
                    to_date=task.end_date
                )
                
            task.result = result
            
            if result.success and result.data:
                # Store data
                async with PolygonDataStorage(self.db_config) as storage:
                    storage_result = await storage.store_collection_result(
                        symbol=task.symbol,
                        result=result,
                        timeframe=task.timeframe
                    )
                    
                task.storage_result = storage_result
                
                if storage_result.success:
                    task.status = CollectionStatus.COMPLETED
                    task.completed_at = datetime.now(timezone.utc)
                    
                    # Update statistics
                    self.stats['completed_tasks'] += 1
                    self.stats['total_records_collected'] += len(result.data.get('results', []))
                    self.stats['total_records_stored'] += storage_result.records_inserted
                    
                    logger.info(f"Task completed successfully: {task_id}")
                    
                    # Call callback
                    if self.on_task_completed:
                        self.on_task_completed(task)
                else:
                    raise Exception(f"Storage failed: {storage_result.error}")
            else:
                raise Exception(f"Collection failed: {result.error}")
                
        except Exception as e:
            task.status = CollectionStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now(timezone.utc)
            
            # Update statistics
            self.stats['failed_tasks'] += 1
            
            logger.error(f"Task failed: {task_id} - {e}")
            
            # Retry logic
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = CollectionStatus.PENDING
                task.started_at = None
                task.completed_at = None
                task.error = None
                
                logger.info(f"Retrying task {task_id} (attempt {task.retry_count}/{task.max_retries})")
            else:
                # Call callback
                if self.on_task_failed:
                    self.on_task_failed(task)
                    
        return task
    
    async def execute_batch(self, batch_id: str) -> CollectionBatch:
        """
        Execute a batch of collection tasks.
        
        Args:
            batch_id: Batch ID
            
        Returns:
            Updated CollectionBatch
        """
        if batch_id not in self.batches:
            raise ValueError(f"Batch {batch_id} not found")
            
        batch = self.batches[batch_id]
        batch.status = CollectionStatus.RUNNING
        batch.started_at = datetime.now(timezone.utc)
        
        logger.info(f"Executing batch: {batch_id} with {len(batch.tasks)} tasks")
        
        # Create semaphore to limit concurrent tasks
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        
        async def execute_with_semaphore(task_id: str):
            async with semaphore:
                return await self.execute_task(task_id)
        
        # Execute tasks concurrently
        task_ids = [task.symbol for task in batch.tasks]
        tasks = [execute_with_semaphore(task_id) for task_id in task_ids]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update batch status
            completed_tasks = sum(1 for task in batch.tasks if task.status == CollectionStatus.COMPLETED)
            failed_tasks = sum(1 for task in batch.tasks if task.status == CollectionStatus.FAILED)
            
            if failed_tasks == 0:
                batch.status = CollectionStatus.COMPLETED
            elif completed_tasks == 0:
                batch.status = CollectionStatus.FAILED
            else:
                batch.status = CollectionStatus.COMPLETED  # Partial success
                
            batch.completed_at = datetime.now(timezone.utc)
            
            logger.info(f"Batch completed: {batch_id} - {completed_tasks} completed, {failed_tasks} failed")
            
            # Call callback
            if self.on_batch_completed:
                self.on_batch_completed(batch)
                
        except Exception as e:
            batch.status = CollectionStatus.FAILED
            batch.completed_at = datetime.now(timezone.utc)
            logger.error(f"Batch failed: {batch_id} - {e}")
            
        return batch
    
    async def execute_all_tasks(self) -> Dict[str, Any]:
        """
        Execute all pending tasks.
        
        Returns:
            Execution summary
        """
        self.stats['start_time'] = datetime.now(timezone.utc)
        
        # Get pending tasks
        pending_tasks = [task_id for task_id, task in self.tasks.items() 
                        if task.status == CollectionStatus.PENDING]
        
        if not pending_tasks:
            logger.info("No pending tasks to execute")
            return self.get_stats()
            
        logger.info(f"Executing {len(pending_tasks)} pending tasks")
        
        # Create semaphore to limit concurrent tasks
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        
        async def execute_with_semaphore(task_id: str):
            async with semaphore:
                return await self.execute_task(task_id)
        
        # Execute all tasks concurrently
        tasks = [execute_with_semaphore(task_id) for task_id in pending_tasks]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
            
            self.stats['end_time'] = datetime.now(timezone.utc)
            
            logger.info("All tasks execution completed")
            
        except Exception as e:
            logger.error(f"Error during task execution: {e}")
            
        return self.get_stats()
    
    def get_task_status(self, task_id: str) -> Optional[CollectionTask]:
        """Get task status by ID."""
        return self.tasks.get(task_id)
    
    def get_batch_status(self, batch_id: str) -> Optional[CollectionBatch]:
        """Get batch status by ID."""
        return self.batches.get(batch_id)
    
    def get_pending_tasks(self) -> List[CollectionTask]:
        """Get all pending tasks."""
        return [task for task in self.tasks.values() 
                if task.status == CollectionStatus.PENDING]
    
    def get_running_tasks(self) -> List[CollectionTask]:
        """Get all running tasks."""
        return [task for task in self.tasks.values() 
                if task.status == CollectionStatus.RUNNING]
    
    def get_completed_tasks(self) -> List[CollectionTask]:
        """Get all completed tasks."""
        return [task for task in self.tasks.values() 
                if task.status == CollectionStatus.COMPLETED]
    
    def get_failed_tasks(self) -> List[CollectionTask]:
        """Get all failed tasks."""
        return [task for task in self.tasks.values() 
                if task.status == CollectionStatus.FAILED]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        stats = self.stats.copy()
        
        # Add current counts
        stats['pending_tasks'] = len(self.get_pending_tasks())
        stats['running_tasks'] = len(self.get_running_tasks())
        stats['completed_tasks'] = len(self.get_completed_tasks())
        stats['failed_tasks'] = len(self.get_failed_tasks())
        
        # Calculate duration
        if stats['start_time'] and stats['end_time']:
            stats['duration'] = (stats['end_time'] - stats['start_time']).total_seconds()
        elif stats['start_time']:
            stats['duration'] = (datetime.now(timezone.utc) - stats['start_time']).total_seconds()
        else:
            stats['duration'] = 0
            
        # Calculate success rate
        total_processed = stats['completed_tasks'] + stats['failed_tasks']
        if total_processed > 0:
            stats['success_rate'] = stats['completed_tasks'] / total_processed
        else:
            stats['success_rate'] = 0
            
        return stats
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task.status in [CollectionStatus.PENDING, CollectionStatus.RUNNING]:
                task.status = CollectionStatus.CANCELLED
                task.completed_at = datetime.now(timezone.utc)
                logger.info(f"Cancelled task: {task_id}")
                return True
        return False
    
    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel all tasks in a batch."""
        if batch_id in self.batches:
            batch = self.batches[batch_id]
            cancelled_count = 0
            
            for task in batch.tasks:
                if self.cancel_task(f"{task.symbol}_{task.start_date.strftime('%Y%m%d')}_{task.end_date.strftime('%Y%m%d')}_{task.timeframe.value}"):
                    cancelled_count += 1
                    
            logger.info(f"Cancelled {cancelled_count} tasks in batch: {batch_id}")
            return cancelled_count > 0
        return False
    
    def clear_completed_tasks(self) -> int:
        """Clear completed and failed tasks."""
        cleared_count = 0
        
        for task_id in list(self.tasks.keys()):
            task = self.tasks[task_id]
            if task.status in [CollectionStatus.COMPLETED, CollectionStatus.FAILED, CollectionStatus.CANCELLED]:
                del self.tasks[task_id]
                cleared_count += 1
                
        logger.info(f"Cleared {cleared_count} completed/failed tasks")
        return cleared_count


# Convenience functions
async def collect_and_store_data(
    symbols: List[str],
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    timeframe: Timeframe = Timeframe.DAY_1,
    max_concurrent: int = 10,
    polygon_config: Optional[PolygonConfig] = None,
    db_config: Optional[DatabaseConfig] = None
) -> Dict[str, Any]:
    """
    Convenience function to collect and store data for multiple symbols.
    
    Args:
        symbols: List of stock symbols
        start_date: Start date
        end_date: End date
        timeframe: Data timeframe
        max_concurrent: Maximum concurrent tasks
        polygon_config: Optional Polygon configuration
        db_config: Optional database configuration
        
    Returns:
        Collection statistics
    """
    manager = PolygonCollectionManager(
        polygon_config=polygon_config,
        db_config=db_config,
        max_concurrent_tasks=max_concurrent
    )
    
    # Add tasks
    manager.add_batch_tasks(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe
    )
    
    # Execute all tasks
    return await manager.execute_all_tasks()


async def collect_symbol_range(
    symbol: str,
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    timeframe: Timeframe = Timeframe.DAY_1,
    polygon_config: Optional[PolygonConfig] = None,
    db_config: Optional[DatabaseConfig] = None
) -> bool:
    """
    Convenience function to collect and store data for a single symbol.
    
    Args:
        symbol: Stock symbol
        start_date: Start date
        end_date: End date
        timeframe: Data timeframe
        polygon_config: Optional Polygon configuration
        db_config: Optional database configuration
        
    Returns:
        True if successful, False otherwise
    """
    manager = PolygonCollectionManager(
        polygon_config=polygon_config,
        db_config=db_config,
        max_concurrent_tasks=1
    )
    
    # Add task
    task_id = manager.add_collection_task(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe
    )
    
    # Execute task
    task = await manager.execute_task(task_id)
    
    return task.status == CollectionStatus.COMPLETED
