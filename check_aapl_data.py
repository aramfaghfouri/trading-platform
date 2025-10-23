#!/usr/bin/env python3
"""
Check AAPL data in the database to verify data exists for all minutes.
"""
import asyncio
import asyncpg
from datetime import datetime, timezone, timedelta

async def check_aapl_data():
    dsn = 'postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform'
    conn = await asyncpg.connect(dsn)
    
    try:
        # Check if the table exists
        table_name = 'ibkr_ohlcv_aapl_1m'
        table_exists = await conn.fetchval(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table_name}')")
        
        if not table_exists:
            print(f'❌ Table {table_name} does not exist')
            return
        
        print(f'✅ Table {table_name} exists')
        
        # Get total count
        total_count = await conn.fetchval(f'SELECT COUNT(*) FROM {table_name}')
        print(f'📊 Total records: {total_count}')
        
        if total_count > 0:
            # Get date range
            min_time = await conn.fetchval(f'SELECT MIN(timestamp) FROM {table_name}')
            max_time = await conn.fetchval(f'SELECT MAX(timestamp) FROM {table_name}')
            print(f'📅 Date range: {min_time} to {max_time}')
            
            # Get latest 5 records
            latest = await conn.fetch(f'SELECT timestamp, open, high, low, close, volume FROM {table_name} ORDER BY timestamp DESC LIMIT 5')
            print(f'📈 Latest 5 records:')
            for row in latest:
                print(f'   {row["timestamp"]}: O:${row["open"]:.2f} H:${row["high"]:.2f} L:${row["low"]:.2f} C:${row["close"]:.2f} V:{row["volume"]}')
            
            # Check for gaps in the last hour
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_data = await conn.fetch(f'SELECT timestamp FROM {table_name} WHERE timestamp >= $1 ORDER BY timestamp', one_hour_ago)
            
            if recent_data:
                print(f'🕐 Recent data (last hour): {len(recent_data)} records')
                # Check for minute gaps
                timestamps = [row['timestamp'] for row in recent_data]
                gaps = []
                for i in range(1, len(timestamps)):
                    diff = timestamps[i] - timestamps[i-1]
                    if diff.total_seconds() > 120:  # More than 2 minutes gap
                        gaps.append((timestamps[i-1], timestamps[i], diff))
                
                if gaps:
                    print(f'⚠️  Found {len(gaps)} gaps:')
                    for gap in gaps[:3]:  # Show first 3 gaps
                        print(f'   Gap: {gap[0]} to {gap[1]} ({gap[2]})')
                else:
                    print('✅ No significant gaps found in recent data')
            else:
                print('⚠️  No recent data found in the last hour')
        else:
            print('⚠️  No data found in table')
    
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_aapl_data())
