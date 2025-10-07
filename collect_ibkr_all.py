#!/usr/bin/env python3
"""Collect IBKR historical data for all symbols from project-setup.toml"""

import asyncio
import tomllib
from tqdm import tqdm
from src.data_collectors.ibkr.historical import IBKRHistoricalCollector
from src.data_collectors.ibkr.client import IBKRDataClient
from src.data_collectors.ibkr.client import segment_date_range # Import segment_date_range

with open('project-setup.toml', 'rb') as f:
    cfg = tomllib.load(f)

hist = cfg.get('ibkr', {}).get('historical', cfg.get('ibkr_historical', {}))
conn = cfg.get('ibkr', {}).get('connection', {})

tf = hist.get('timeframe', '1m')
start_date_str = hist.get('start_date', '2024-10-01')
end_date_str = hist.get('end_date', '2024-10-06')
useRTH = bool(hist.get('useRTH', True))
whatToShow = hist.get('what_to_show', 'TRADES')
symbols = hist.get('symbols', ['AAPL'])

host = conn.get('host', '127.0.0.1')
port = int(conn.get('port_paper', 7497))
client_id = int(conn.get('client_id', 102))

print(f"📊 Configuration:")
print(f"   Timeframe: {tf}")
print(f"   Period: {start_date_str} to {end_date_str}")
print(f"   Symbols: {len(symbols)} total")
print(f"   IBKR: {host}:{port} (client_id={client_id})")
print()

async def main():
    client = IBKRDataClient()
    client.broker.client.host = host
    client.broker.client.port = port
    client.broker.client.client_id = client_id
    collector = IBKRHistoricalCollector(client=client)
    
    # Perform initial connection outside the symbol loop
    try:
        await asyncio.wait_for(client.broker.connect_async(), timeout=10.0)
        client._connected = True # Manually set _connected flag
        print("✅ Successfully connected to IBKR!")
    except asyncio.TimeoutError:
        print("❌ Initial connection timeout - IBKR TWS/Gateway not responding")
        print(f"Please ensure IBKR TWS/Gateway is running on port {port}")
        return # Exit if initial connection fails
    except Exception as e:
        print(f"❌ Initial connection failed: {e}")
        print(f"Please ensure IBKR TWS/Gateway is running on port {port}")
        return # Exit if initial connection fails

    results = []
    with tqdm(total=len(symbols), desc="Collecting IBKR data", unit="symbol") as pbar:
        for symbol in symbols:
            pbar.set_description(f"Collecting {symbol}")
            
            # Generate monthly segments for the symbol's date range
            segments = segment_date_range(start_date_str, end_date_str)
            symbol_bars_collected = 0
            symbol_errors = []

            for seg_start, seg_end in segments:
                try:
                    res = await collector.collect_and_store(symbol, seg_start, seg_end, tf)
                    if res.get('success'):
                        symbol_bars_collected += res.get('inserted', 0)
                    else:
                        symbol_errors.append(res.get('error', 'Unknown error'))
                except Exception as e:
                    symbol_errors.append(str(e))
            
            final_res = {
                'success': True if not symbol_errors else False,
                'inserted': symbol_bars_collected,
                'error': ', '.join(symbol_errors) if symbol_errors else None
            }
            results.append((symbol, final_res))
            
            pbar.set_postfix({
                'success': '✓' if final_res['success'] else '✗',
                'bars': final_res['inserted']
            })
            pbar.update(1)
    
    print("\n" + "="*80)
    print("📊 COLLECTION SUMMARY")
    print("="*80)
    total_bars = sum(r[1].get('inserted', 0) for r in results)
    success_count = sum(1 for r in results if r[1].get('success'))
    print(f"✅ Successful: {success_count}/{len(symbols)}")
    print(f"📊 Total bars collected: {total_bars:,}")
    print()
    
    for symbol, res in results:
        if res.get('success'):
            print(f"  ✅ {symbol:6s}: {res.get('inserted', 0):,} bars")
        else:
            print(f"  ❌ {symbol:6s}: {res.get('error', 'Unknown error')}")

if __name__ == "__main__":
    asyncio.run(main())

