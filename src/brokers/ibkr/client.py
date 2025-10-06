import os
from typing import List
from ib_insync import IB, Stock, MarketOrder, LimitOrder


class IBClient:
    def __init__(self,
                 host: str | None = None,
                 port: int | None = None,
                 client_id: int | None = None):
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("IBKR_PORT", "7497"))
        self.client_id = int(client_id or os.getenv("IBKR_CLIENT_ID", "101"))
        self.ib = IB()

    def connect(self):
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        return self

    def disconnect(self):
        self.ib.disconnect()

    def account_summary(self):
        return self.ib.accountSummary()

    def positions(self):
        return self.ib.positions()

    def subscribe_ticks(self, symbol: str):
        contract = Stock(symbol, 'SMART', 'USD')
        return self.ib.reqMktData(contract, '', False, False)

    def cancel_ticks(self, symbol: str):
        contract = Stock(symbol, 'SMART', 'USD')
        self.ib.cancelMktData(contract)

    def place_order(self, symbol: str, action: str, qty: int, limit: float | None = None):
        contract = Stock(symbol, 'SMART', 'USD')
        order = MarketOrder(action, qty) if limit is None else LimitOrder(action, qty, limit)
        return self.ib.placeOrder(contract, order)


