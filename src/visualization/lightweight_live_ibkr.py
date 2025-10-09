"""
Lightweight live chart using `lightweight-charts` only, with IBKR bars.

- Uses Chart() directly per library examples
  Docs: https://github.com/louisnw01/lightweight-charts-python
  Live example: https://github.com/louisnw01/lightweight-charts-python/blob/main/examples/2_live_data/live_data.py

- Real-time data source: IBKR realtime 5s bars aggregated to selectable timeframes
"""

from collections import deque
from datetime import datetime
from typing import Deque, Dict, Any, List

import pandas as pd

from lightweight_charts import Chart
from src.brokers.ibkr.realtime_bars import IBKRRealtimeBarStream
from src.utils.heikin_ashi import calculate_heikin_ashi
from src.utils.timeframes import get_supported_timeframes, get_timeframe_display_name


def launch(symbol: str = "EURUSD", timeframe: str = "1m") -> None:
    # ---- Chart (direct library API) ----
    chart = Chart(toolbox=True, width=1400, height=800)
    chart.legend(True)
    chart.layout(background_color="#131722", text_color="#d1d4dc", font_size=12)
    chart.candle_style(
        up_color="#26a69a",
        down_color="#ef5350",
        border_up_color="#26a69a",
        border_down_color="#ef5350",
        wick_up_color="#26a69a",
        wick_down_color="#ef5350",
    )
    chart.watermark(f"{symbol} - {get_timeframe_display_name(timeframe)}")
    chart.time_scale(visible=True, time_visible=True, seconds_visible=False)

    # ---- Topbar ----
    chart.topbar.textbox("symbol", symbol)
    chart.topbar.switcher(
        "timeframe",
        tuple(get_supported_timeframes()),
        default=timeframe,
        func=lambda c: _on_timeframe_selection(c),
    )
    chart.topbar.switcher(
        "chart_type",
        ("Candlestick", "Heiken-Ashi"),
        default="Heiken-Ashi",
        func=lambda c: _render_all(),
    )
    chart.topbar.textbox("status", "Connecting…")

    # ---- State ----
    bars_by_tf: Dict[str, Deque[Dict[str, Any]]] = {tf: deque(maxlen=800) for tf in get_supported_timeframes()}
    current_symbol = symbol
    current_tf = timeframe
    chart_type = "ha"  # 'ha' | 'ohlc'

    # ---- IBKR stream ----
    stream = IBKRRealtimeBarStream()
    stream.connect()

    def _apply_chart_type_from_topbar() -> None:
        nonlocal chart_type
        ct = chart.topbar["chart_type"].value
        chart_type = "ha" if ct == "Heiken-Ashi" else "ohlc"

    def _set_watermark() -> None:
        chart.watermark(f"{current_symbol} - {get_timeframe_display_name(current_tf)}")

    def _on_timeframe_selection(c: Chart) -> None:
        nonlocal current_tf
        new_tf = c.topbar["timeframe"].value
        if new_tf == current_tf:
            return
        current_tf = new_tf
        _set_watermark()
        _restart_stream()

    def _restart_stream() -> None:
        stream.stop_streaming()
        # (re)start for the new tf
        stream.start_streaming(current_symbol, [current_tf])
        stream.add_timeframe_callback(current_tf, _on_bar)

        # backfill
        seed = stream.get_bars(current_tf, count=300)
        bars_by_tf[current_tf].clear()
        for b in seed:
            bars_by_tf[current_tf].append(b)
        _render_all()

    def _on_bar(bar: Dict[str, Any], tf: str) -> None:
        if tf != current_tf:
            return
        bars_by_tf[tf].append(bar)
        # Simple: full re-render for correctness; can be optimized to incremental
        _render_all()

    def _render_all() -> None:
        _apply_chart_type_from_topbar()
        bars: List[Dict[str, Any]] = list(bars_by_tf[current_tf])
        if not bars:
            return
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"])  # ensure datetime

        if chart_type == "ha":
            ha = calculate_heikin_ashi(df)
            # include volume for compatibility with expected schema
            data = ha[["timestamp", "ha_open", "ha_high", "ha_low", "ha_close", "volume"]].copy()
            data.columns = ["date", "open", "high", "low", "close", "volume"]
        else:
            data = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
            data.columns = ["date", "open", "high", "low", "close", "volume"]

        chart.set(data)
        try:
            chart.time_scale(fit_content=True)
        except Exception:
            pass

    # initial start
    stream.start_streaming(current_symbol, [current_tf])
    stream.add_timeframe_callback(current_tf, _on_bar)

    # initial backfill
    seed = stream.get_bars(current_tf, count=300)
    for b in seed:
        bars_by_tf[current_tf].append(b)
    chart.topbar["status"].set("Connected")
    _render_all()

    try:
        chart.show(block=True)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            stream.stop_streaming()
            stream.disconnect()
        finally:
            chart.topbar["status"].set("Disconnected")


if __name__ == "__main__":
    launch()


