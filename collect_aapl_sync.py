#!/usr/bin/env python3
"""Synchronous script to collect IBKR data for a single symbol (AAPL)."""

from datetime import datetime, timedelta
import time
import sys

from ib_async import IB, Stock, util
from loguru import logger

# Configure logger to show all levels
logger.remove()
logger.add(sys.stderr, level="DEBUG")

def collect_single_symbol_sync():
    print("=" * 80)
    print("Starting Synchronous IBKR Data Collection for AAPL")
    print("=" * 80)

    ib = IB()
    host = "127.0.0.1"
    port = 7497
    client_id = 101

    print(f"\n📡 Configuration:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Client ID: {client_id}")
    print()

    try:
        print("⏳ Attempting to connect to IBKR...")
        ib.connect(host, port, client_id, timeout=10)
        print("✅ Successfully connected to IBKR!")

        # Define test parameters for a single month
        symbol = "AAPL"
        end_dt = datetime(2024, 10, 31)  # End of October 2024
        duration_str = "1 M"  # One month duration
        bar_size = "1 min"
        what_to_show = "TRADES"
        use_rth = True

        print(f"📊 Requesting data for {symbol}: up to {end_dt.strftime('%Y-%m-%d')} for {duration_str} in {bar_size} resolution")

        contract = Stock(symbol, "SMART", "USD")
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_dt,
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1
        )

        if bars:
            print(f"✅ Retrieved {len(bars)} bars for {symbol}")
            print("📈 Sample bars (first 5):")
            for bar in bars[:5]:
                print(f"   {bar}")
        else:
            print(f"⚠️  No bars returned for {symbol}")

    except Exception as e:
        print(f"\n❌ Error during collection: {e}")
        logger.exception("Full traceback:")
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("🔌 Disconnected from IBKR")

    print("\n" + "=" * 80)
    print("Synchronous Collection Finished")
    print("=" * 80)

if __name__ == "__main__":
    collect_single_symbol_sync()
