#!/usr/bin/env python3
"""
Simple AAPL chart from database data
"""

import asyncpg
import pandas as pd
from lightweight_charts import Chart
import asyncio

async def get_aapl_data():
    """Get AAPL data from database"""
    conn = await asyncpg.connect('postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform')
    
    rows = await conn.fetch('''
        SELECT timestamp, open, high, low, close, volume 
        FROM polygon_ohlcv_aapl_1m 
        ORDER BY timestamp DESC 
        LIMIT 100
    ''')
    
    await conn.close()
    return rows

def create_chart():
    """Create and show the chart"""
    print('🚀 Creating AAPL chart from database data...')
    
    # Get data
    rows = asyncio.run(get_aapl_data())
    
    if not rows:
        print('❌ No AAPL data found')
        return
        
    print(f'✅ Found {len(rows)} AAPL bars')
    
    # Convert to DataFrame
    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Prepare chart data
    df['time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(int)
    
    chart_df = df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    print(f'📈 Creating chart with {len(chart_df)} data points...')
    print(f'💰 Price range: ${chart_df["low"].min():.2f} - ${chart_df["high"].max():.2f}')
    
    # Create and show chart
    chart = Chart()
    chart.set(chart_df)
    print('📊 Chart created! Window should appear...')
    chart.show(block=True)

if __name__ == "__main__":
    create_chart()
