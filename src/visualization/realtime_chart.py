"""
Real-time Heiken-Ashi charting application using Plotly Dash.

Provides a TradingView-like interface for real-time market data visualization
with Heiken-Ashi candles and multiple timeframes.
"""

import dash
from dash import dcc, html, Input, Output, State, callback_context
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import threading
import time
from collections import deque

from src.brokers.ibkr.realtime_bars import IBKRRealtimeBarStream
from src.utils.heikin_ashi import calculate_heikin_ashi
from src.utils.timeframes import (
    get_supported_timeframes,
    get_timeframes_by_group,
    get_timeframe_display_name,
    TIMEFRAME_GROUPS
)


class RealtimeChartApp:
    """Main application class for the real-time chart."""
    
    def __init__(self, symbol: str = "AAPL", initial_timeframe: str = "1m", port: int = 8050):
        self.symbol = symbol
        self.current_timeframe = initial_timeframe
        self.port = port
        
        # Data storage
        self.bars_data: Dict[str, deque] = {}  # timeframe -> deque of bars
        self.max_bars = 500
        
        # Chart state
        self.chart_type = "ha"  # "ha" or "ohlc"
        self.overlays = []  # List of active overlays
        
        # IBKR connection
        self.bar_stream: Optional[IBKRRealtimeBarStream] = None
        self.is_connected = False
        
        # Initialize data storage
        for tf in get_supported_timeframes():
            self.bars_data[tf] = deque(maxlen=self.max_bars)
        
        # Create Dash app
        self.app = dash.Dash(__name__)
        self._setup_layout()
        self._setup_callbacks()
    
    def _setup_layout(self):
        """Set up the Dash application layout."""
        
        # Timeframe buttons
        timeframe_buttons = []
        for group_name, timeframes in TIMEFRAME_GROUPS.items():
            group_buttons = []
            for tf in timeframes:
                group_buttons.append(
                    html.Button(
                        tf,
                        id=f'btn-{tf}',
                        className='timeframe-btn',
                        style={
                            'margin': '2px',
                            'padding': '5px 10px',
                            'border': '1px solid #ccc',
                            'borderRadius': '4px',
                            'backgroundColor': '#f0f0f0' if tf != self.current_timeframe else '#007bff',
                            'color': '#000' if tf != self.current_timeframe else '#fff',
                            'cursor': 'pointer'
                        }
                    )
                )
            timeframe_buttons.append(
                html.Div(
                    group_buttons,
                    style={'display': 'inline-block', 'margin': '5px'}
                )
            )
        
        self.app.layout = html.Div([
            # Store components for state management
            dcc.Store(id='current-symbol', data=self.symbol),
            dcc.Store(id='current-timeframe', data=self.current_timeframe),
            dcc.Store(id='chart-type', data=self.chart_type),
            dcc.Store(id='overlays', data=self.overlays),
            dcc.Store(id='bars-data', data={}),
            
            # Top toolbar
            html.Div([
                # Symbol input
                html.Div([
                    html.Label("Symbol:", style={'marginRight': '10px'}),
                    dcc.Input(
                        id='symbol-input',
                        value=self.symbol,
                        placeholder='Enter symbol',
                        style={'width': '100px', 'marginRight': '20px'}
                    )
                ], style={'display': 'inline-block'}),
                
                # Timeframe buttons
                html.Div([
                    html.Label("Timeframe:", style={'marginRight': '10px'}),
                    html.Div(timeframe_buttons)
                ], style={'display': 'inline-block', 'marginLeft': '20px'}),
                
                # Chart type toggle
                html.Div([
                    html.Label("Chart Type:", style={'marginRight': '10px'}),
                    dcc.RadioItems(
                        id='chart-type-toggle',
                        options=[
                            {'label': 'Heiken-Ashi', 'value': 'ha'},
                            {'label': 'Candlestick', 'value': 'ohlc'}
                        ],
                        value=self.chart_type,
                        inline=True,
                        style={'marginLeft': '10px'}
                    )
                ], style={'display': 'inline-block', 'marginLeft': '20px'}),
                
                # Overlays
                html.Div([
                    html.Label("Overlays:", style={'marginRight': '10px'}),
                    dcc.Checklist(
                        id='overlays-checklist',
                        options=[
                            {'label': 'Volume', 'value': 'volume'},
                            {'label': 'SMA(20)', 'value': 'sma20'},
                            {'label': 'SMA(50)', 'value': 'sma50'},
                            {'label': 'EMA(12)', 'value': 'ema12'},
                            {'label': 'EMA(26)', 'value': 'ema26'}
                        ],
                        value=self.overlays,
                        inline=True,
                        style={'marginLeft': '10px'}
                    )
                ], style={'display': 'inline-block', 'marginLeft': '20px'}),
                
                # Connection status
                html.Div([
                    html.Span("Status: ", style={'marginRight': '5px'}),
                    html.Span(
                        "Disconnected",
                        id='connection-status',
                        style={'color': 'red', 'fontWeight': 'bold'}
                    )
                ], style={'display': 'inline-block', 'marginLeft': '20px'})
                
            ], style={
                'padding': '10px',
                'borderBottom': '1px solid #ccc',
                'backgroundColor': '#f8f9fa'
            }),
            
            # Main chart
            dcc.Graph(
                id='live-chart',
                style={'height': '80vh', 'width': '100%'}
            ),
            
            # Update interval
            dcc.Interval(
                id='interval-component',
                interval=5000,  # Update every 5 seconds
                n_intervals=0
            )
        ])
    
    def _setup_callbacks(self):
        """Set up Dash callbacks."""
        
        @self.app.callback(
            [Output('live-chart', 'figure'),
             Output('connection-status', 'children'),
             Output('connection-status', 'style')],
            [Input('interval-component', 'n_intervals'),
             Input('current-timeframe', 'data'),
             Input('chart-type', 'data'),
             Input('overlays', 'data')],
            [State('current-symbol', 'data')]
        )
        def update_chart(n_intervals, timeframe, chart_type, overlays, symbol):
            """Update the chart with new data."""
            
            # Get current bars data
            bars = list(self.bars_data.get(timeframe, []))
            
            if not bars:
                # Return empty chart
                fig = go.Figure()
                fig.update_layout(
                    title=f"{symbol} - {get_timeframe_display_name(timeframe)} - No Data",
                    xaxis_title="Time",
                    yaxis_title="Price"
                )
                return fig, "No Data", {'color': 'orange', 'fontWeight': 'bold'}
            
            # Convert to DataFrame
            df = pd.DataFrame(bars)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Create chart
            fig = self._create_chart(df, symbol, timeframe, chart_type, overlays)
            
            # Update connection status
            if self.is_connected:
                status = "Connected"
                status_style = {'color': 'green', 'fontWeight': 'bold'}
            else:
                status = "Disconnected"
                status_style = {'color': 'red', 'fontWeight': 'bold'}
            
            return fig, status, status_style
        
        # Timeframe button callbacks
        for tf in get_supported_timeframes():
            @self.app.callback(
                Output('current-timeframe', 'data'),
                [Input(f'btn-{tf}', 'n_clicks')],
                [State('current-timeframe', 'data')]
            )
            def update_timeframe(n_clicks, current_tf):
                if n_clicks and n_clicks > 0:
                    ctx = callback_context
                    if ctx.triggered:
                        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
                        new_tf = button_id.replace('btn-', '')
                        return new_tf
                return current_tf
        
        # Symbol input callback
        @self.app.callback(
            Output('current-symbol', 'data'),
            [Input('symbol-input', 'value')]
        )
        def update_symbol(symbol):
            if symbol:
                return symbol.upper()
            return self.symbol
        
        # Chart type callback
        @self.app.callback(
            Output('chart-type', 'data'),
            [Input('chart-type-toggle', 'value')]
        )
        def update_chart_type(chart_type):
            return chart_type
        
        # Overlays callback
        @self.app.callback(
            Output('overlays', 'data'),
            [Input('overlays-checklist', 'value')]
        )
        def update_overlays(overlays):
            return overlays or []
    
    def _create_chart(self, df: pd.DataFrame, symbol: str, timeframe: str, 
                     chart_type: str, overlays: List[str]) -> go.Figure:
        """Create the chart figure."""
        
        # Create subplots
        subplot_titles = [f"{symbol} - {get_timeframe_display_name(timeframe)}"]
        if 'volume' in overlays:
            subplot_titles.append("Volume")
        
        fig = make_subplots(
            rows=2 if 'volume' in overlays else 1,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=subplot_titles,
            row_heights=[0.7, 0.3] if 'volume' in overlays else [1.0]
        )
        
        # Prepare data
        if chart_type == "ha":
            # Calculate Heiken-Ashi
            df_ha = calculate_heikin_ashi(df)
            open_col, high_col, low_col, close_col = 'ha_open', 'ha_high', 'ha_low', 'ha_close'
            name = "Heiken-Ashi"
        else:
            open_col, high_col, low_col, close_col = 'open', 'high', 'low', 'close'
            name = "Candlestick"
        
        # Add candlestick trace
        fig.add_trace(
            go.Candlestick(
                x=df['timestamp'],
                open=df[open_col],
                high=df[high_col],
                low=df[low_col],
                close=df[close_col],
                name=name,
                increasing_line_color='#00ff00',
                decreasing_line_color='#ff0000'
            ),
            row=1, col=1
        )
        
        # Add overlays
        if 'sma20' in overlays:
            sma20 = df['close'].rolling(window=20).mean()
            fig.add_trace(
                go.Scatter(
                    x=df['timestamp'],
                    y=sma20,
                    mode='lines',
                    name='SMA(20)',
                    line=dict(color='blue', width=1)
                ),
                row=1, col=1
            )
        
        if 'sma50' in overlays:
            sma50 = df['close'].rolling(window=50).mean()
            fig.add_trace(
                go.Scatter(
                    x=df['timestamp'],
                    y=sma50,
                    mode='lines',
                    name='SMA(50)',
                    line=dict(color='orange', width=1)
                ),
                row=1, col=1
            )
        
        if 'ema12' in overlays:
            ema12 = df['close'].ewm(span=12).mean()
            fig.add_trace(
                go.Scatter(
                    x=df['timestamp'],
                    y=ema12,
                    mode='lines',
                    name='EMA(12)',
                    line=dict(color='purple', width=1)
                ),
                row=1, col=1
            )
        
        if 'ema26' in overlays:
            ema26 = df['close'].ewm(span=26).mean()
            fig.add_trace(
                go.Scatter(
                    x=df['timestamp'],
                    y=ema26,
                    mode='lines',
                    name='EMA(26)',
                    line=dict(color='brown', width=1)
                ),
                row=1, col=1
            )
        
        # Add volume if requested
        if 'volume' in overlays and 'volume' in df.columns:
            fig.add_trace(
                go.Bar(
                    x=df['timestamp'],
                    y=df['volume'],
                    name='Volume',
                    marker_color='lightblue',
                    opacity=0.7
                ),
                row=2, col=1
            )
        
        # Update layout
        fig.update_layout(
            title=f"{symbol} - {get_timeframe_display_name(timeframe)} - {name}",
            xaxis_title="Time",
            yaxis_title="Price",
            template="plotly_white",
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            height=800 if 'volume' in overlays else 600
        )
        
        # Update x-axis
        fig.update_xaxes(
            rangeslider_visible=False,
            type='date'
        )
        
        return fig
    
    def _on_bar_update(self, bar_data: Dict[str, Any]) -> None:
        """Handle new bar data from IBKR."""
        # This will be called by the bar stream when new data arrives
        pass
    
    def _on_timeframe_update(self, bar_data: Dict[str, Any], timeframe: str) -> None:
        """Handle new aggregated bar data."""
        # Add to appropriate timeframe buffer
        if timeframe in self.bars_data:
            self.bars_data[timeframe].append(bar_data)
    
    def connect_to_ibkr(self) -> None:
        """Connect to IBKR and start streaming."""
        try:
            self.bar_stream = IBKRRealtimeBarStream()
            
            # Add callbacks
            self.bar_stream.add_timeframe_callback(
                self.current_timeframe, 
                self._on_timeframe_update
            )
            
            # Start streaming
            self.bar_stream.start_streaming(
                symbol=self.symbol,
                timeframes=[self.current_timeframe]
            )
            
            self.is_connected = True
            print(f"Connected to IBKR and streaming {self.symbol}")
            
        except Exception as e:
            print(f"Failed to connect to IBKR: {e}")
            self.is_connected = False
    
    def disconnect_from_ibkr(self) -> None:
        """Disconnect from IBKR."""
        if self.bar_stream:
            self.bar_stream.stop_streaming()
            self.bar_stream.disconnect()
            self.is_connected = False
            print("Disconnected from IBKR")
    
    def run(self, debug: bool = False) -> None:
        """Run the Dash application."""
        print(f"Starting real-time chart for {self.symbol} on port {self.port}")
        print(f"Initial timeframe: {self.current_timeframe}")
        print(f"Chart type: {'Heiken-Ashi' if self.chart_type == 'ha' else 'Candlestick'}")
        
        # Connect to IBKR in a separate thread
        def connect_thread():
            time.sleep(2)  # Wait for app to start
            self.connect_to_ibkr()
        
        threading.Thread(target=connect_thread, daemon=True).start()
        
        # Run the app
        self.app.run_server(debug=debug, port=self.port, host='0.0.0.0')


def launch_chart(symbol: str = "AAPL", timeframe: str = "1m", port: int = 8050, debug: bool = False):
    """
    Launch the real-time chart application.
    
    Args:
        symbol: Symbol to chart
        timeframe: Initial timeframe
        port: Port to run the app on
        debug: Enable debug mode
    """
    app = RealtimeChartApp(symbol=symbol, initial_timeframe=timeframe, port=port)
    app.run(debug=debug)


if __name__ == "__main__":
    # For direct execution
    launch_chart()
