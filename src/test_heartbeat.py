"""
Quick IBKR API heartbeat: connect, print status and server time, disconnect.

Usage:
  conda activate env-trading
  python -m src.test_heartbeat
"""

from __future__ import annotations

import sys
from datetime import datetime

from src.brokers.ibkr.client import IBClient


def main() -> None:
    client = IBClient()
    try:
        print("🔌 Connecting to IBKR ...")
        client.connect()
        ib = client.ib
        print(f"✅ isConnected: {ib.isConnected()}")

        # Request server time as a lightweight heartbeat call
        server_time = ib.reqCurrentTime()
        if isinstance(server_time, datetime):
            print(f"🕒 Server time: {server_time.isoformat()}")
        else:
            print(f"🕒 Server time: {server_time}")

        # Basic account ping (optional; may require permissions)
        try:
            accts = ib.managedAccounts()
            print(f"👤 Managed accounts: {accts}")
        except Exception as e:
            print(f"(info) Could not fetch accounts: {e}")

    except Exception as e:
        print(f"❌ Heartbeat failed: {e}")
        sys.exit(1)
    finally:
        try:
            client.disconnect()
            print("🔌 Disconnected")
        except Exception:
            pass


if __name__ == "__main__":
    main()


