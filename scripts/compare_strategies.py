#!/usr/bin/env python3
"""
Compare Multiple Strategies on ES Futures

Runs multiple strategies on the same data and compares performance.

Usage:
    python scripts/compare_strategies.py
    python scripts/compare_strategies.py --timeframe 5min
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.data_store import DataStore
from backtest.engine import BacktestEngine
from backtest.strategy import (
    MovingAverageCrossover,
    RSIMeanReversion,
    BreakoutStrategy,
    BollingerBandStrategy,
    MACDStrategy,
)
from backtest.analytics import PerformanceAnalytics


def main():
    parser = argparse.ArgumentParser(description="Compare ES futures strategies")
    parser.add_argument(
        "--data-file",
        type=str,
        default="data/es/ES_combined_1min.parquet",
        help="Path to data file",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="5min",
        help="Resample to timeframe",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital",
    )

    args = parser.parse_args()

    # Load and prepare data
    data_path = Path(args.data_file)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)

    df = pd.read_parquet(data_path)

    if args.timeframe != "1min":
        store = DataStore()
        df = store.resample(df, args.timeframe)

    print("=" * 80)
    print("ES FUTURES STRATEGY COMPARISON")
    print("=" * 80)
    print(f"Data: {len(df):,} bars ({args.timeframe})")
    print(f"Period: {df.index.min()} to {df.index.max()}")
    print(f"Capital: ${args.capital:,.2f}")
    print()

    # Define strategies to compare
    strategies = [
        ("MA Cross (10/30)", MovingAverageCrossover(10, 30)),
        ("MA Cross (5/20)", MovingAverageCrossover(5, 20)),
        ("RSI (14)", RSIMeanReversion(14, 30, 70)),
        ("RSI (7)", RSIMeanReversion(7, 25, 75)),
        ("Breakout (20)", BreakoutStrategy(20)),
        ("Breakout (50)", BreakoutStrategy(50)),
        ("Bollinger (20,2)", BollingerBandStrategy(20, 2.0)),
        ("MACD", MACDStrategy(12, 26, 9)),
    ]

    results_summary = []

    for name, strategy in strategies:
        print(f"Testing {name}...", end=" ", flush=True)

        engine = BacktestEngine(
            data=df.copy(),
            initial_capital=args.capital,
        )

        try:
            results = engine.run(strategy=strategy)

            analytics = PerformanceAnalytics(
                equity_curve=results["equity_curve"],
                trades=results["trades"],
                initial_capital=args.capital,
            )
            metrics = analytics.calculate_metrics()

            results_summary.append({
                "Strategy": name,
                "Total Return %": metrics.total_return,
                "Max Drawdown %": metrics.max_drawdown,
                "Sharpe": metrics.sharpe_ratio,
                "Sortino": metrics.sortino_ratio,
                "Win Rate %": metrics.win_rate,
                "Profit Factor": metrics.profit_factor,
                "Trades": metrics.total_trades,
                "Avg Trade $": metrics.avg_trade_pnl,
            })
            print("Done")

        except Exception as e:
            print(f"Error: {e}")
            results_summary.append({
                "Strategy": name,
                "Total Return %": 0,
                "Max Drawdown %": 0,
                "Sharpe": 0,
                "Sortino": 0,
                "Win Rate %": 0,
                "Profit Factor": 0,
                "Trades": 0,
                "Avg Trade $": 0,
            })

    # Display comparison table
    print("\n" + "=" * 80)
    print("RESULTS COMPARISON")
    print("=" * 80)

    comparison_df = pd.DataFrame(results_summary)
    comparison_df = comparison_df.set_index("Strategy")

    # Format columns
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)

    print(comparison_df.to_string())

    # Highlight best performers
    print("\n" + "-" * 80)
    print("BEST PERFORMERS:")
    print(f"  Highest Return:     {comparison_df['Total Return %'].idxmax()}")
    print(f"  Best Sharpe:        {comparison_df['Sharpe'].idxmax()}")
    print(f"  Best Win Rate:      {comparison_df['Win Rate %'].idxmax()}")
    print(f"  Lowest Drawdown:    {comparison_df['Max Drawdown %'].idxmin()}")
    print("=" * 80)


if __name__ == "__main__":
    main()
