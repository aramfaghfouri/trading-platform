import os
import time
import click
from src.brokers.ibkr.adapters import IBBroker


def _get_env(name: str, default: str = "") -> str:
    val = os.getenv(name, default)
    if val is None or val == "":
        return default
    return val


@click.group()
def ib():
    """Interactive Brokers CLI."""
    pass


@ib.command()
@click.option("--host", default=lambda: _get_env("IBKR_HOST", "127.0.0.1"), show_default=True)
@click.option("--port", default=lambda: int(_get_env("IBKR_PORT", "7497")), type=int, show_default=True)
@click.option("--client-id", default=lambda: int(_get_env("IBKR_CLIENT_ID", "101")), type=int, show_default=True)
def connect(host: str, port: int, client_id: int):
    """Test connection to IBKR TWS/Gateway."""
    broker = IBBroker()
    broker.client.host = host
    broker.client.port = port
    broker.client.client_id = client_id
    broker.connect()
    account_values = broker.account_summary()
    click.echo(f"Connected. Account summary items: {len(account_values)}")
    broker.disconnect()


@ib.command()
@click.option("--host", default=lambda: _get_env("IBKR_HOST", "127.0.0.1"), show_default=True)
@click.option("--port", default=lambda: int(_get_env("IBKR_PORT", "7497")), type=int, show_default=True)
@click.option("--client-id", default=lambda: int(_get_env("IBKR_CLIENT_ID", "101")), type=int, show_default=True)
def summary(host: str, port: int, client_id: int):
    """Fetch and print account summary."""
    broker = IBBroker()
    broker.client.host = host
    broker.client.port = port
    broker.client.client_id = client_id
    broker.connect()
    items = broker.account_summary()
    for it in items[:20]:
        click.echo(f"{it.tag}: {it.value} {it.currency}")
    broker.disconnect()


@ib.command()
@click.option("--host", default=lambda: _get_env("IBKR_HOST", "127.0.0.1"), show_default=True)
@click.option("--port", default=lambda: int(_get_env("IBKR_PORT", "7497")), type=int, show_default=True)
@click.option("--client-id", default=lambda: int(_get_env("IBKR_CLIENT_ID", "101")), type=int, show_default=True)
def positions(host: str, port: int, client_id: int):
    """List current positions."""
    broker = IBBroker()
    broker.client.host = host
    broker.client.port = port
    broker.client.client_id = client_id
    broker.connect()
    pos = broker.positions()
    for p in pos:
        click.echo(f"{p.contract.symbol}: qty={p.position} avgCost={p.avgCost}")
    broker.disconnect()


@ib.command()
@click.option("--host", default=lambda: _get_env("IBKR_HOST", "127.0.0.1"), show_default=True)
@click.option("--port", default=lambda: int(_get_env("IBKR_PORT", "7497")), type=int, show_default=True)
@click.option("--client-id", default=lambda: int(_get_env("IBKR_CLIENT_ID", "101")), type=int, show_default=True)
@click.option("--symbol", default="AAPL", show_default=True)
@click.option("--seconds", default=60, show_default=True, type=int)
def subscribe(host: str, port: int, client_id: int, symbol: str, seconds: int):
    """Subscribe to real-time ticks for a symbol for a short period."""
    broker = IBBroker()
    broker.client.host = host
    broker.client.port = port
    broker.client.client_id = client_id
    broker.connect()
    handle = broker.subscribe_ticks([symbol])
    ticker = handle[0][1]
    click.echo(f"Subscribed to {symbol} ticks for {seconds}s...")
    t0 = time.time()
    while time.time() - t0 < seconds:
        broker.client.ib.waitOnUpdate(timeout=1)
        if ticker.last is not None:
            click.echo(f"last={ticker.last} bid={ticker.bid} ask={ticker.ask}")
    broker.unsubscribe(handle)
    broker.disconnect()


@ib.command()
@click.option("--host", default=lambda: _get_env("IBKR_HOST", "127.0.0.1"), show_default=True)
@click.option("--port", default=lambda: int(_get_env("IBKR_PORT", "7497")), type=int, show_default=True)
@click.option("--client-id", default=lambda: int(_get_env("IBKR_CLIENT_ID", "101")), type=int, show_default=True)
@click.option("--symbol", default="AAPL", show_default=True)
@click.option("--action", default="BUY", type=click.Choice(["BUY", "SELL"]))
@click.option("--qty", default=1, type=int, show_default=True)
@click.option("--limit", default=None, type=float)
def place_order(host: str, port: int, client_id: int, symbol: str, action: str, qty: int, limit):
    """Place a tiny paper order (guarded by LIVE_TRADING_CONFIRM)."""
    if os.getenv("LIVE_TRADING_CONFIRM", "false").lower() != "true":
        click.echo("LIVE_TRADING_CONFIRM is not true. Refusing to place orders.")
        return

    broker = IBBroker()
    broker.client.host = host
    broker.client.port = port
    broker.client.client_id = client_id
    broker.connect()
    trade = broker.place_order(symbol, action, qty, 'limit' if limit else 'market', limit=limit)
    click.echo(f"Placed orderId={trade.order.orderId} {action} {qty} {symbol}")
    broker.disconnect()


@ib.command()
@click.option("--symbol", default="EURUSD", help="Symbol to chart")
@click.option("--timeframe", default="1m", help="Initial timeframe")
@click.option("--chart-type", default="lightweight", type=click.Choice(["lightweight", "dash"]), help="Chart type")
def chart(symbol: str, timeframe: str, chart_type: str):
    """Launch real-time Heiken-Ashi chart."""
    
    click.echo(f"🚀 Launching real-time chart for {symbol} on timeframe {timeframe}")
    click.echo(f"📊 Chart type: {chart_type}")
    
    try:
        if chart_type == "lightweight":
            # Use direct lightweight-charts implementation (no custom framework)
            from src.visualization.lightweight_live_ibkr import launch
            click.echo("📈 Using TradingView-like lightweight chart (live IBKR)")
            launch(symbol=symbol, timeframe=timeframe)
        else:
            from src.visualization.realtime_chart import launch_chart
            click.echo("🌐 Using Dash web chart")
            launch_chart(symbol=symbol, timeframe=timeframe, port=8050, debug=False)
    except KeyboardInterrupt:
        click.echo("\n👋 Chart stopped by user")
    except Exception as e:
        click.echo(f"❌ Error launching chart: {e}")
        import traceback
        traceback.print_exc()


def main():
    ib()


