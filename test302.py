#from IPython.display import display, clear_output
#import matplotlib.pyplot as plt
import pandas as pd
from ib_async import *
from lightweight_charts import Chart
import threading
import time
from src.utils.heikin_ashi import HeikinAshiCalculator

util.startLoop()

ib = IB()
ib.disconnect()

ib.connect('127.0.0.1', 7497, clientId=2)

def onBarUpdate(bars, hasNewBar):
    print(bars[-1])

contract = Forex("EURUSD")
contract = Stock("AAPL", "SMART", "USD")
contract = Stock("AAPL", "SMART", "USD", primaryExchange="NASDAQ")

bars = ib.reqHistoricalData(
    contract,
    endDateTime="",
    durationStr="1 D",
    barSizeSetting="10 secs",
    whatToShow="MIDPOINT",
    useRTH=False,
    formatDate=1,
    keepUpToDate=True,
)

bars = ib.reqRealTimeBars(contract=contract, barSize=5, whatToShow="MIDPOINT", useRTH=False)
bars.updateEvent += onBarUpdate

df = util.df(bars)
print(df)
ib.sleep(10)
ib.cancelRealTimeBars(bars)
ib.disconnect()




#==============================================
# Real time
import pandas as pd
from ib_async import *
from lightweight_charts import Chart
import threading
import time
from src.utils.heikin_ashi import HeikinAshiCalculator

def onBarUpdate(bars, hasNewBar):
    print(bars[-1])

util.startLoop()
ib = IB()
ib.disconnect()
ib.connect('127.0.0.1', 7497, clientId=2)

stock = Stock("AAPL", "SMART", "USD")
bars = ib.reqRealTimeBars(contract=stock, barSize=5, whatToShow="MIDPOINT", useRTH=False)
bars.updateEvent += onBarUpdate

ib.run()
ib.sleep(30)

ib.cancelRealTimeBars(bars)
ib.disconnect()

