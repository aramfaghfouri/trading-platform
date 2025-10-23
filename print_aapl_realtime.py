#!/usr/bin/env python3
"""
Simple real-time AAPL data printer using ib_async.
Connects to IBKR and prints real-time market data for AAPL.
"""
import sys
import os
from datetime import datetime, timezone
from loguru import logger

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from ib_async import IB, Stock

def print_aapl_realtime():
    """Print real-time AAPL data from IBKR."""
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    ib = IB()
    
    try:
        logger.info("🔌 Connecting to IBKR...")
        
        # Connect with a unique client ID
        import random
        client_id = random.randint(10000, 99999)
        logger.info(f"Using client ID: {client_id}")
        ib.connect('127.0.0.1', 7497, clientId=client_id)
        
        if ib.isConnected():
            logger.info("✅ Connected to IBKR!")
            
            # Create AAPL contract
            contract = Stock('AAPL', 'SMART', 'USD')
            logger.info(f"📈 Contract: {contract}")
            
            # Qualify the contract to get conId
            logger.info("🔍 Qualifying contract...")
            qualified_contracts = ib.qualifyContracts(contract)
            if qualified_contracts:
                contract = qualified_contracts[0]
                logger.info(f"✅ Qualified contract: {contract}")
            else:
                logger.error("❌ Failed to qualify contract")
                return
            
            # Request market data
            ticker = ib.reqMktData(contract, '', False, False)
            logger.info("📊 Market data requested...")
            
            # Set up callback to print real-time data
            def on_ticker_update(ticker):
                if ticker.last and ticker.last > 0:
                    timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
                    print(f"📈 {timestamp} | AAPL | Last: ${ticker.last:.2f} | Bid: ${ticker.bid:.2f} | Ask: ${ticker.ask:.2f} | Volume: {ticker.volume}")
            
            ticker.updateEvent += on_ticker_update
            
            logger.info("✅ Real-time data streaming started!")
            logger.info("Press Ctrl+C to stop...")
            
            # Keep running to receive data
            try:
                while True:
                    ib.sleep(1)
            except KeyboardInterrupt:
                logger.info("🛑 Stopped by user")
            
        else:
            logger.error("❌ Failed to connect to IBKR")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            logger.info("🔌 Disconnecting from IBKR...")
            ib.disconnect()
            logger.info("✅ Disconnected")

if __name__ == "__main__":
    print_aapl_realtime()
