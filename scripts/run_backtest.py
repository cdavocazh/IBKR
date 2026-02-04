#!/usr/bin/env python3
"""
Run Backtest on ES Futures Data

Usage:
    python scripts/run_backtest.py --strategy ma_crossover
    python scripts/run_backtest.py --strategy rsi --start 2023-01-01 --end 2024-01-01
    python scripts/run_backtest.py --strategy breakout --timeframe 5min
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

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


STRATEGIES = {
    "ma_crossover": lambda: MovingAverageCrossover(fast_period=10, slow_period=30),
    "ma_crossover_fast": lambda: MovingAverageCrossover(fast_period=5, slow_period=15),
    "rsi": lambda: RSIMeanReversion(period=14, oversold=30, overbought=70),
    "rsi_extreme": lambda: RSIMeanReversion(period=14, oversold=20, overbought=80),
    "breakout": lambda: BreakoutStrategy(lookback=20),
    "breakout_long": lambda: BreakoutStrategy(lookback=50),
    "bollinger": lambda: BollingerBandStrategy(period=20, std_dev=2.0),
    "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
}


def main():
    parser = argparse.ArgumentParser(description="Run ES futures backtest")
    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES.keys()),
        default="ma_crossover",
        help="Strategy to backtest",
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default="data/es/ES_combined_1min.parquet",
        help="Path to data file",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1min",
        help="Resample to timeframe (1min, 5min, 15min, 1hour)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital",
    )
    parser.add_argument(
        "--commission",
        type=float,
        default=2.25,
        help="Commission per contract",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("ES FUTURES BACKTEST")
    print("=" * 60)
    print(f"Strategy: {args.strategy}")
    print(f"Data file: {args.data_file}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Capital: ${args.capital:,.2f}")
    print()

    # Load data
    data_path = Path(args.data_file)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        print("Run 'python scripts/download_es_data.py' first to download data.")
        sys.exit(1)

    import pandas as pd
    df = pd.read_parquet(data_path)
    print(f"Loaded {len(df):,} bars")

    # Resample if needed
    if args.timeframe != "1min":
        store = DataStore()
        df = store.resample(df, args.timeframe)
        print(f"Resampled to {args.timeframe}: {len(df):,} bars")

    # Filter by date
    if args.start:
        df = df[df.index >= args.start]
    if args.end:
        df = df[df.index <= args.end]

    print(f"Date range: {df.index.min()} to {df.index.max()}")
    print(f"Bars to process: {len(df):,}")
    print()

    # Create strategy and engine
    strategy = STRATEGIES[args.strategy]()
    engine = BacktestEngine(
        data=df,
        initial_capital=args.capital,
        commission_per_contract=args.commission,
    )

    # Run backtest
    print("Running backtest...")
    results = engine.run(strategy=strategy)

    # Generate analytics report
    analytics = PerformanceAnalytics(
        equity_curve=results["equity_curve"],
        trades=results["trades"],
        initial_capital=args.capital,
    )

    metrics = analytics.calculate_metrics()
    analytics.print_report(metrics)

    # Save results
    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"ES_{args.strategy}_{args.timeframe}_{timestamp}"

    # Save equity curve
    results["equity_curve"].to_parquet(output_dir / f"{base_name}_equity.parquet")

    # Save trades
    if not results["trades"].empty:
        results["trades"].to_parquet(output_dir / f"{base_name}_trades.parquet")

    print(f"\nResults saved to {output_dir}/")


if __name__ == "__main__":
    main()
