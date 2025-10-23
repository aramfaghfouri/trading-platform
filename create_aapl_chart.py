#!/usr/bin/env python3
"""
Create AAPL chart from database data using lightweight-charts
"""

import asyncio
import asyncpg
import pandas as pd
from lightweight_charts import Chart

async def create_aapl_chart():
    print('🚀 Creating AAPL chart from database data...')
    
    try:
        # Connect to database
        conn = await asyncpg.connect('postgresql://trading_user:trading_password@127.0.0.1:6432/trading_platform')
        
        # Get recent AAPL data
        print('📊 Fetching AAPL data from database...')
        rows = await conn.fetch('''
            SELECT timestamp, open, high, low, close, volume 
            FROM polygon_ohlcv_aapl_1m 
            ORDER BY timestamp DESC 
            LIMIT 100
        ''')
        
        if not rows:
            print('❌ No AAPL data found')
            return
            
        print(f'✅ Found {len(rows)} AAPL bars')
        print(f'📅 Date range: {rows[-1][0]} to {rows[0][0]}')
        
        # Convert to DataFrame with proper column names
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        print(f'📊 DataFrame columns: {list(df.columns)}')
        
        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Prepare data for chart (convert to DataFrame format)
        df['time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(int)
        
        # Select only the columns needed for the chart
        chart_df = df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        print(f'📈 Creating chart with {len(chart_df)} data points...')
        low_price = chart_df['low'].min()
        high_price = chart_df['high'].max()
        print(f'💰 Price range: ${low_price:.2f} - ${high_price:.2f}')
        
        # Create chart
        chart = Chart()
        chart.set(chart_df)
        print('📊 Chart created! Window should appear...')
        chart.show(block=True)
        
        await conn.close()
        
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(create_aapl_chart())
