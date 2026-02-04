"""
HTML Backtest Report Generator

Generates professional HTML reports with:
- Performance metrics summary
- Equity curve chart
- Trade list
- Drawdown analysis
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import base64
from io import BytesIO


def generate_equity_chart_svg(equity_df: pd.DataFrame, width: int = 800, height: int = 300) -> str:
    """Generate SVG equity curve chart."""
    if equity_df.empty:
        return "<p>No equity data</p>"

    equity = equity_df['equity'].values
    timestamps = equity_df.index

    # Normalize to SVG coordinates
    min_eq = equity.min()
    max_eq = equity.max()
    eq_range = max_eq - min_eq if max_eq != min_eq else 1

    padding = 60
    chart_width = width - 2 * padding
    chart_height = height - 2 * padding

    # Create points for polyline
    points = []
    step = max(1, len(equity) // 500)  # Sample if too many points
    for i in range(0, len(equity), step):
        x = padding + (i / len(equity)) * chart_width
        y = padding + chart_height - ((equity[i] - min_eq) / eq_range) * chart_height
        points.append(f"{x:.1f},{y:.1f}")

    points_str = " ".join(points)

    # Generate Y-axis labels
    y_labels = ""
    for i in range(5):
        val = min_eq + (eq_range * i / 4)
        y_pos = padding + chart_height - (i / 4) * chart_height
        y_labels += f'<text x="{padding - 5}" y="{y_pos}" text-anchor="end" font-size="10">${val:,.0f}</text>'

    svg = f'''
    <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#f8f9fa"/>
        <rect x="{padding}" y="{padding}" width="{chart_width}" height="{chart_height}" fill="white" stroke="#ddd"/>
        <polyline points="{points_str}" fill="none" stroke="#2196F3" stroke-width="1.5"/>
        {y_labels}
        <text x="{width/2}" y="{height - 10}" text-anchor="middle" font-size="12">Time</text>
        <text x="15" y="{height/2}" text-anchor="middle" transform="rotate(-90, 15, {height/2})" font-size="12">Equity ($)</text>
    </svg>
    '''
    return svg


def generate_drawdown_chart_svg(equity_df: pd.DataFrame, width: int = 800, height: int = 200) -> str:
    """Generate SVG drawdown chart."""
    if equity_df.empty:
        return "<p>No drawdown data</p>"

    equity = equity_df['equity'].values
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak * 100

    padding = 60
    chart_width = width - 2 * padding
    chart_height = height - 2 * padding

    min_dd = drawdown.min()
    dd_range = abs(min_dd) if min_dd < 0 else 1

    points = []
    step = max(1, len(drawdown) // 500)
    for i in range(0, len(drawdown), step):
        x = padding + (i / len(drawdown)) * chart_width
        y = padding + (abs(drawdown[i]) / dd_range) * chart_height
        points.append(f"{x:.1f},{y:.1f}")

    points_str = " ".join(points)

    svg = f'''
    <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#f8f9fa"/>
        <rect x="{padding}" y="{padding}" width="{chart_width}" height="{chart_height}" fill="white" stroke="#ddd"/>
        <polyline points="{points_str}" fill="none" stroke="#f44336" stroke-width="1.5"/>
        <text x="{width/2}" y="{height - 10}" text-anchor="middle" font-size="12">Time</text>
        <text x="15" y="{height/2}" text-anchor="middle" transform="rotate(-90, 15, {height/2})" font-size="12">Drawdown (%)</text>
    </svg>
    '''
    return svg


def generate_html_report(
    results: dict,
    strategy_name: str,
    ticker: str,
    output_path: Path,
):
    """Generate HTML backtest report."""

    # Extract metrics
    initial_capital = results['initial_capital']
    final_equity = results['final_equity']
    total_pnl = results['total_pnl']
    total_return = results['total_return_pct']
    total_trades = results['total_trades']
    win_rate = results['win_rate']
    avg_win = results['avg_win']
    avg_loss = results['avg_loss']
    profit_factor = results['profit_factor']
    max_drawdown = results['max_drawdown']
    sharpe_ratio = results['sharpe_ratio']
    equity_df = results['equity_curve']
    trades_df = results['trades']

    # Calculate additional metrics
    if len(trades_df) > 0:
        avg_bars_held = trades_df['bars_held'].mean()
        max_bars_held = trades_df['bars_held'].max()
        total_commission = trades_df['commission'].sum()
        best_trade = trades_df['pnl'].max()
        worst_trade = trades_df['pnl'].min()
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        for pnl in trades_df['pnl']:
            if pnl > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            else:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
    else:
        avg_bars_held = 0
        max_bars_held = 0
        total_commission = 0
        best_trade = 0
        worst_trade = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

    # Generate charts
    equity_chart = generate_equity_chart_svg(equity_df)
    drawdown_chart = generate_drawdown_chart_svg(equity_df)

    # Generate trades table HTML
    trades_html = ""
    if len(trades_df) > 0:
        for i, row in trades_df.iterrows():
            pnl_class = "positive" if row['pnl'] > 0 else "negative"
            trades_html += f"""
            <tr>
                <td>{row['entry_time']}</td>
                <td>{row['exit_time']}</td>
                <td>{row['side']}</td>
                <td>{row['quantity']}</td>
                <td>${row['entry_price']:,.2f}</td>
                <td>${row['exit_price']:,.2f}</td>
                <td class="{pnl_class}">${row['pnl']:,.2f}</td>
                <td>{row['bars_held']}</td>
            </tr>
            """

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{strategy_name} - {ticker} Backtest Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            background: linear-gradient(135deg, #1a237e, #3949ab);
            color: white;
            padding: 30px;
            margin-bottom: 20px;
            border-radius: 8px;
        }}
        header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        header p {{
            opacity: 0.9;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metric-card .label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        .metric-card .value {{
            font-size: 24px;
            font-weight: bold;
        }}
        .metric-card .value.positive {{
            color: #4caf50;
        }}
        .metric-card .value.negative {{
            color: #f44336;
        }}
        .chart-section {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .chart-section h2 {{
            font-size: 18px;
            margin-bottom: 15px;
            color: #333;
        }}
        .trades-section {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            overflow-x: auto;
        }}
        .trades-section h2 {{
            font-size: 18px;
            margin-bottom: 15px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f5f5f5;
            font-weight: 600;
        }}
        tr:hover {{
            background: #fafafa;
        }}
        .positive {{
            color: #4caf50;
        }}
        .negative {{
            color: #f44336;
        }}
        footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{strategy_name} - {ticker}</h1>
            <p>Backtest Report - Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </header>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">Initial Capital</div>
                <div class="value">${initial_capital:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Final Equity</div>
                <div class="value {'positive' if final_equity >= initial_capital else 'negative'}">${final_equity:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Total P&L</div>
                <div class="value {'positive' if total_pnl >= 0 else 'negative'}">${total_pnl:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Total Return</div>
                <div class="value {'positive' if total_return >= 0 else 'negative'}">{total_return:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Total Trades</div>
                <div class="value">{total_trades}</div>
            </div>
            <div class="metric-card">
                <div class="label">Win Rate</div>
                <div class="value {'positive' if win_rate >= 50 else 'negative'}">{win_rate:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Avg Win</div>
                <div class="value positive">${avg_win:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Avg Loss</div>
                <div class="value negative">${avg_loss:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Profit Factor</div>
                <div class="value {'positive' if profit_factor >= 1 else 'negative'}">{profit_factor:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Max Drawdown</div>
                <div class="value negative">{max_drawdown:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Sharpe Ratio</div>
                <div class="value {'positive' if sharpe_ratio >= 0 else 'negative'}">{sharpe_ratio:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Avg Bars Held</div>
                <div class="value">{avg_bars_held:.1f}</div>
            </div>
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">Best Trade</div>
                <div class="value positive">${best_trade:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Worst Trade</div>
                <div class="value negative">${worst_trade:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Max Consecutive Wins</div>
                <div class="value">{max_consecutive_wins}</div>
            </div>
            <div class="metric-card">
                <div class="label">Max Consecutive Losses</div>
                <div class="value">{max_consecutive_losses}</div>
            </div>
        </div>

        <div class="chart-section">
            <h2>Equity Curve</h2>
            {equity_chart}
        </div>

        <div class="chart-section">
            <h2>Drawdown</h2>
            {drawdown_chart}
        </div>

        <div class="trades-section">
            <h2>Trade Log ({total_trades} trades)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Side</th>
                        <th>Qty</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>P&L</th>
                        <th>Bars Held</th>
                    </tr>
                </thead>
                <tbody>
                    {trades_html}
                </tbody>
            </table>
        </div>

        <footer>
            <p>Generated by IBKR Backtest System</p>
        </footer>
    </div>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(html)

    print(f"Report saved to: {output_path}")


def run_all_backtests_and_generate_reports():
    """Run all backtests and generate HTML reports."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    reports_dir = Path(__file__).parent.parent / "reports"

    # ES Scalp
    print("\n" + "="*60)
    print("Running ES_scalp backtest...")
    print("="*60)
    from backtest.strategies.es_scalp_momentum import run_backtest as run_es_scalp
    es_scalp_results, _ = run_es_scalp()
    generate_html_report(
        es_scalp_results,
        "ES Momentum Scalp",
        "ES",
        reports_dir / "es_scalp_report.html"
    )

    # ES 4h
    print("\n" + "="*60)
    print("Running ES_4h backtest...")
    print("="*60)
    from backtest.strategies.es_4h import run_backtest as run_es_4h
    es_4h_results, _ = run_es_4h()
    generate_html_report(
        es_4h_results,
        "ES 4-Hour Strategy",
        "ES",
        reports_dir / "es_4h_report.html"
    )

    # GC Buy Dip
    print("\n" + "="*60)
    print("Running GC buy-the-dip backtest...")
    print("="*60)
    from backtest.strategies.gc_buy_dip import run_backtest as run_gc_dip
    gc_dip_results, _ = run_gc_dip()
    generate_html_report(
        gc_dip_results,
        "GC Buy-the-Dip",
        "GC",
        reports_dir / "gc_buy_dip_report.html"
    )

    print("\n" + "="*60)
    print("All reports generated!")
    print("="*60)
    print(f"Reports saved to: {reports_dir}")


if __name__ == "__main__":
    run_all_backtests_and_generate_reports()
