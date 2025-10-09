#!/usr/bin/env python3
"""
Simple script to run the real-time Heiken-Ashi chart using lightweight-charts.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.visualization.lightweight_chart import launch_lightweight_chart

if __name__ == "__main__":
    print("🚀 Launching Real-time Heiken-Ashi Chart (TradingView-like)")
    print("=" * 60)
    print("Symbol: EURUSD")
    print("Timeframe: 1m")
    print("Chart: Lightweight Charts (TradingView-like)")
    print("=" * 60)
    print("Features:")
    print("• Real-time Heiken-Ashi candles")
    print("• Multiple timeframes (1m, 3m, 5m, 9m, 10m, 15m, 30m, 1h, 2h, 4h, 8h, 9h, D, 3D, W)")
    print("• Toggle between OHLC and Heiken-Ashi")
    print("• Volume and SMA overlays")
    print("• Drawing tools and indicators")
    print("• Symbol search")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print()
    
    try:
        launch_lightweight_chart(symbol='EURUSD', timeframe='1m')
    except KeyboardInterrupt:
        print("\n👋 Chart stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
