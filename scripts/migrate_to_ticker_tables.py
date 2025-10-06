#!/usr/bin/env python3
"""
Migration script to move data from single ohlcv_data table to ticker-specific tables.

This script migrates existing data from the old single table structure to the new
ticker-specific table structure. It preserves all data and creates the necessary
ticker registry entries.

Usage:
    python scripts/migrate_to_ticker_tables.py [--dry-run] [--backup]
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncpg
from loguru import logger

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_loader import get_database_config
from core.config_models import DatabaseConfig


class TickerTableMigration:
    """Handles migration from single table to ticker-specific tables."""
    
    def __init__(self, db_config: Optional[DatabaseConfig] = None):
        """Initialize migration handler."""
        self.db_config = db_config or get_database_config()
        self.conn: Optional[asyncpg.Connection] = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        
    async def connect(self) -> None:
        """Establish database connection."""
        try:
            self.conn = await asyncpg.connect(
                host=self.db_config.host,
                port=self.db_config.port,
                database=self.db_config.database,
                user=self.db_config.username,
                password=self.db_config.password,
                ssl=self.db_config.ssl_mode
            )
            logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
            
    async def disconnect(self) -> None:
        """Close database connection."""
        if self.conn:
            await self.conn.close()
            logger.info("Disconnected from database")
    
    async def check_old_table_exists(self) -> bool:
        """Check if the old ohlcv_data table exists."""
        try:
            result = await self.conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ohlcv_data'
                )
            """)
            return result
        except Exception as e:
            logger.error(f"Error checking for old table: {e}")
            return False
    
    async def get_symbols_from_old_table(self) -> List[str]:
        """Get all unique symbols from the old table."""
        try:
            symbols = await self.conn.fetch("""
                SELECT DISTINCT symbol 
                FROM ohlcv_data 
                ORDER BY symbol
            """)
            return [row['symbol'] for row in symbols]
        except Exception as e:
            logger.error(f"Error getting symbols from old table: {e}")
            return []
    
    async def get_data_count_for_symbol(self, symbol: str) -> int:
        """Get data count for a specific symbol."""
        try:
            count = await self.conn.fetchval("""
                SELECT COUNT(*) FROM ohlcv_data WHERE symbol = $1
            """, symbol)
            return count
        except Exception as e:
            logger.error(f"Error getting count for {symbol}: {e}")
            return 0
    
    async def migrate_symbol_data(self, symbol: str, dry_run: bool = False) -> Dict[str, Any]:
        """Migrate data for a specific symbol."""
        try:
            # Get data count
            total_count = await self.get_data_count_for_symbol(symbol)
            if total_count == 0:
                return {'symbol': symbol, 'status': 'skipped', 'reason': 'no_data'}
            
            # Create ticker table if not exists
            if not dry_run:
                created = await self.conn.fetchval(
                    "SELECT create_ticker_table($1, $2, $3)",
                    symbol, 'ohlcv', '1m'
                )
                if not created:
                    return {'symbol': symbol, 'status': 'failed', 'reason': 'table_creation_failed'}
            
            # Get table name
            table_name = await self.conn.fetchval(
                "SELECT get_ticker_table_name($1, $2, $3)",
                symbol, 'ohlcv', '1m'
            )
            
            if not table_name:
                return {'symbol': symbol, 'status': 'failed', 'reason': 'table_not_found'}
            
            if dry_run:
                return {
                    'symbol': symbol, 
                    'status': 'would_migrate', 
                    'records': total_count,
                    'target_table': table_name
                }
            
            # Migrate data in batches
            batch_size = 1000
            migrated_count = 0
            
            # Get all data for this symbol
            offset = 0
            while True:
                rows = await self.conn.fetch("""
                    SELECT timestamp, open, high, low, close, volume, vwap, transactions
                    FROM ohlcv_data 
                    WHERE symbol = $1
                    ORDER BY timestamp
                    LIMIT $2 OFFSET $3
                """, symbol, batch_size, offset)
                
                if not rows:
                    break
                
                # Insert into new table
                insert_query = f"""
                    INSERT INTO {table_name} (
                        timestamp, open, high, low, close, volume, vwap, transactions
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (timestamp) DO NOTHING
                """
                
                for row in rows:
                    await self.conn.execute(
                        insert_query,
                        row['timestamp'],
                        row['open'],
                        row['high'],
                        row['low'],
                        row['close'],
                        row['volume'],
                        row['vwap'],
                        row['transactions']
                    )
                    migrated_count += 1
                
                offset += batch_size
                logger.info(f"Migrated {migrated_count}/{total_count} records for {symbol}")
            
            return {
                'symbol': symbol,
                'status': 'completed',
                'records_migrated': migrated_count,
                'target_table': table_name
            }
            
        except Exception as e:
            logger.error(f"Error migrating data for {symbol}: {e}")
            return {'symbol': symbol, 'status': 'failed', 'reason': str(e)}
    
    async def create_backup(self) -> str:
        """Create a backup of the old table."""
        try:
            backup_table = f"ohlcv_data_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            await self.conn.execute(f"""
                CREATE TABLE {backup_table} AS 
                SELECT * FROM ohlcv_data
            """)
            
            logger.info(f"Created backup table: {backup_table}")
            return backup_table
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            raise
    
    async def migrate_all_data(self, dry_run: bool = False, create_backup: bool = False) -> Dict[str, Any]:
        """Migrate all data from old table to new structure."""
        try:
            # Check if old table exists
            if not await self.check_old_table_exists():
                return {'status': 'skipped', 'reason': 'old_table_not_found'}
            
            # Get all symbols
            symbols = await self.get_symbols_from_old_table()
            if not symbols:
                return {'status': 'skipped', 'reason': 'no_symbols_found'}
            
            logger.info(f"Found {len(symbols)} symbols to migrate: {symbols}")
            
            # Create backup if requested
            backup_table = None
            if create_backup and not dry_run:
                backup_table = await self.create_backup()
            
            # Migrate each symbol
            results = []
            for symbol in symbols:
                logger.info(f"Migrating data for {symbol}...")
                result = await self.migrate_symbol_data(symbol, dry_run)
                results.append(result)
                logger.info(f"Migration result for {symbol}: {result['status']}")
            
            # Summary
            successful = [r for r in results if r['status'] in ['completed', 'would_migrate']]
            failed = [r for r in results if r['status'] == 'failed']
            skipped = [r for r in results if r['status'] == 'skipped']
            
            summary = {
                'status': 'completed',
                'total_symbols': len(symbols),
                'successful': len(successful),
                'failed': len(failed),
                'skipped': len(skipped),
                'backup_table': backup_table,
                'results': results
            }
            
            logger.info(f"Migration summary: {summary}")
            return summary
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return {'status': 'failed', 'error': str(e)}


async def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(description='Migrate from single table to ticker-specific tables')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be migrated without making changes')
    parser.add_argument('--backup', action='store_true',
                       help='Create backup of old table before migration')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("Running in DRY RUN mode - no changes will be made")
    
    try:
        async with TickerTableMigration() as migration:
            result = await migration.migrate_all_data(
                dry_run=args.dry_run,
                create_backup=args.backup
            )
            
            if result['status'] == 'completed':
                logger.info("✅ Migration completed successfully!")
                if args.dry_run:
                    logger.info("This was a dry run - no actual changes were made")
            else:
                logger.error(f"❌ Migration failed: {result}")
                return 1
                
    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
