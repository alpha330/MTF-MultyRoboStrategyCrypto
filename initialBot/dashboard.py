import dash
from dash import dcc, html, dash_table
import plotly.graph_objs as go
import pandas as pd
import json
from datetime import datetime
import os

# Branding
BRAND = "MAXIMUS"
AUTHOR = "Ali Mahmoodi"

# Initialize Dash app
app = dash.Dash(__name__)

def load_data():
    try:
        with open('dashboard_data.json', 'r') as f:
            data = json.load(f)
        return data
    except:
        return {}

def create_balance_plot(data):
    balance = data.get('balance', 0)
    hodl_value = data.get('hodl_value', 0)
    timestamp = data.get('timestamp', datetime.now().isoformat())
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[timestamp],
        y=[balance],
        mode='lines+markers',
        name='Portfolio Balance (USDT)',
        line=dict(color='blue')
    ))
    fig.add_trace(go.Scatter(
        x=[timestamp],
        y=[hodl_value],
        mode='lines+markers',
        name='HODL Value (USDT)',
        line=dict(color='orange')
    ))
    fig.update_layout(
        title='Portfolio Balance vs HODL Value',
        xaxis_title='Time',
        yaxis_title='Value (USDT)',
        template='plotly_dark'
    )
    return fig

def create_indicators_plot(data):
    rsi = data.get('rsi', 0)
    atr = data.get('atr', 0)
    timestamp = data.get('timestamp', datetime.now().isoformat())
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[timestamp],
        y=[rsi],
        mode='lines+markers',
        name='RSI',
        line=dict(color='green')
    ))
    fig.add_trace(go.Scatter(
        x=[timestamp],
        y=[atr],
        mode='lines+markers',
        name='ATR',
        line=dict(color='red'),
        yaxis='y2'
    ))
    fig.update_layout(
        title='RSI and ATR',
        xaxis_title='Time',
        yaxis_title='RSI',
        yaxis2=dict(title='ATR', overlaying='y', side='right'),
        template='plotly_dark'
    )
    return fig

def create_positions_table(data):
    positions = data.get('positions', {'long': {}, 'short': {}})
    table_data = [
        {
            'Side': 'Long',
            'Active': 'Yes' if positions['long']['active'] else 'No',
            'Quantity': positions['long']['quantity'],
            'Entry Price': positions['long']['entry_price'],
            'Unrealized PnL': positions['long']['unrealized_pnl']
        },
        {
            'Side': 'Short',
            'Active': 'Yes' if positions['short']['active'] else 'No',
            'Quantity': positions['short']['quantity'],
            'Entry Price': positions['short']['entry_price'],
            'Unrealized PnL': positions['short']['unrealized_pnl']
        }
    ]
    return table_data

# Layout
app.layout = html.Div([
    html.H1(f"{BRAND} Trading Dashboard", style={'textAlign': 'center', 'color': '#FFFFFF'}),
    html.H3(f"Developed by {AUTHOR}", style={'textAlign': 'center', 'color': '#BBBBBB'}),
    dcc.Graph(id='balance-plot'),
    dcc.Graph(id='indicators-plot'),
    dash_table.DataTable(
        id='positions-table',
        columns=[
            {'name': 'Side', 'id': 'Side'},
            {'name': 'Active', 'id': 'Active'},
            {'name': 'Quantity', 'id': 'Quantity'},
            {'name': 'Entry Price', 'id': 'Entry Price'},
            {'name': 'Unrealized PnL', 'id': 'Unrealized PnL'}
        ],
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'center', 'backgroundColor': '#1a1a1a', 'color': '#FFFFFF'},
        style_header={'backgroundColor': '#333333', 'fontWeight': 'bold'}
    ),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)  # Update every 60 seconds
], style={'backgroundColor': '#1a1a1a', 'padding': '20px'})

# Callback to update plots and table
@app.callback(
    [
        dash.dependencies.Output('balance-plot', 'figure'),
        dash.dependencies.Output('indicators-plot', 'figure'),
        dash.dependencies.Output('positions-table', 'data')
    ],
    [dash.dependencies.Input('interval-component', 'n_intervals')]
)
def update_dashboard(n_intervals):
    data = load_data()
    balance_plot = create_balance_plot(data)
    indicators_plot = create_indicators_plot(data)
    positions_table = create_positions_table(data)
    return balance_plot, indicators_plot, positions_table

if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=8050)