#!/usr/bin/env python3
"""
Backtest Regime-Specific Strategies on ES Minute Data

Uses IBKR minute-level data for more granular backtesting.
Detects regime on higher timeframe, trades on lower timeframe.

Usage:
    python scripts/backtest_regime_minute.py
    python scripts/backtest_regime_minute.py --data-file data/es/ES_combined_5min.parquet
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from ibkr.data_store import DataStore
from backtest.engine import BacktestEngine
from backtest.regime import RegimeDetector, MarketRegime
from backtest.regime_strategies import (
    BuyTheDipStrategy,
    SellTheRipStrategy,
    MeanReversionExtremesStrategy,
    AdaptiveRegimeStrategy,
)
from backtest.analytics import PerformanceAnalytics


def load_minute_data(data_file: str) -> pd.DataFrame:
    """Load minute-level data from file."""
    filepath = Path(data_file)

    if not filepath.exists():
        print(f"Data file not found: {filepath}")
        print("\nPlease download data first:")
        print("  python scripts/download_es_minute_data.py --bar-size 5min")
        sys.exit(1)

    df = pd.read_parquet(filepath)
    print(f"Loaded {len(df):,} bars from {filepath.name}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")

    return df


def analyze_regime_on_daily(minute_df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample to daily and detect regimes.
    Then map regime back to minute data.
    """
    # Resample to daily
    daily_df = minute_df.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    # Detect regime on daily
    detector = RegimeDetector()
    daily_regime = detector.detect_regime(daily_df)

    # Create regime lookup by date
    regime_by_date = daily_regime["regime"].to_dict()

    # Map to minute data
    minute_df = minute_df.copy()
    minute_df["date"] = minute_df.index.date
    minute_df["regime"] = minute_df["date"].map(
        lambda d: regime_by_date.get(pd.Timestamp(d), "NEUTRAL")
    )

    return minute_df, daily_regime


def run_backtest(df: pd.DataFrame, strategy, capital: float) -> dict:
    """Run backtest on minute data."""
    engine = BacktestEngine(
        data=df.copy(),
        initial_capital=capital,
        commission_per_contract=2.25,
        slippage_ticks=1,
    )
    return engine.run(strategy=strategy)


def main():
    parser = argparse.ArgumentParser(
        description="Backtest regime strategies on ES minute data"
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default="data/es/ES_combined_5min.parquet",
        help="Path to minute data file",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital",
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

    args = parser.parse_args()

    print("=" * 70)
    print("ES MINUTE-LEVEL REGIME STRATEGY BACKTEST")
    print("=" * 70)

    # Load data
    df = load_minute_data(args.data_file)

    # Filter by date if specified
    if args.start:
        df = df[df.index >= args.start]
    if args.end:
        df = df[df.index <= args.end]

    print(f"\nBacktest period: {df.index.min()} to {df.index.max()}")
    print(f"Total bars: {len(df):,}")
    print(f"Initial Capital: ${args.capital:,.2f}")

    # Analyze regime on daily timeframe
    print("\n--- ANALYZING MARKET REGIMES (Daily) ---")
    df_with_regime, daily_regime = analyze_regime_on_daily(df)

    regime_counts = daily_regime["regime"].value_counts()
    total_days = len(daily_regime.dropna(subset=["regime"]))
    print("\nRegime Distribution:")
    for regime, count in regime_counts.items():
        pct = count / total_days * 100
        print(f"  {regime}: {count} days ({pct:.1f}%)")

    # Get current regime
    detector = RegimeDetector()
    current_regime, indicators = detector.get_current_regime(daily_regime)
    print(f"\nCurrent Regime: {current_regime.value}")
    print(f"Confidence: {indicators.regime_strength:.1f}%")

    # Strategies to test
    strategies = [
        ("Buy the Dip", BuyTheDipStrategy()),
        ("Sell the Rip", SellTheRipStrategy()),
        ("Mean Reversion", MeanReversionExtremesStrategy()),
        ("Adaptive (Auto)", AdaptiveRegimeStrategy()),
    ]

    results_summary = []

    print("\n--- RUNNING BACKTESTS ON MINUTE DATA ---")
    for name, strategy in strategies:
        print(f"\nTesting {name}...", end=" ", flush=True)

        try:
            # Use clean copy without regime column for backtesting
            df_clean = df[["open", "high", "low", "close", "volume"]].copy()
            results = run_backtest(df_clean, strategy, args.capital)

            if len(results["trades"]) > 0:
                analytics = PerformanceAnalytics(
                    equity_curve=results["equity_curve"],
                    trades=results["trades"],
                    initial_capital=args.capital,
                    periods_per_year=252 * 78,  # 5-min bars: 78 per day
                )
                metrics = analytics.calculate_metrics()

                results_summary.append({
                    "Strategy": name,
                    "Total Return %": metrics.total_return,
                    "Ann. Return %": metrics.annualized_return,
                    "Max DD %": metrics.max_drawdown,
                    "Sharpe": metrics.sharpe_ratio,
                    "Sortino": metrics.sortino_ratio,
                    "Win Rate %": metrics.win_rate,
                    "Profit Factor": metrics.profit_factor,
                    "Trades": metrics.total_trades,
                    "Avg Trade $": metrics.avg_trade_pnl,
                })
                print(f"Done ({metrics.total_trades} trades)")
            else:
                results_summary.append({
                    "Strategy": name,
                    "Total Return %": 0,
                    "Ann. Return %": 0,
                    "Max DD %": 0,
                    "Sharpe": 0,
                    "Sortino": 0,
                    "Win Rate %": 0,
                    "Profit Factor": 0,
                    "Trades": 0,
                    "Avg Trade $": 0,
                })
                print("Done (0 trades)")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            results_summary.append({
                "Strategy": name,
                "Total Return %": 0,
                "Ann. Return %": 0,
                "Max DD %": 0,
                "Sharpe": 0,
                "Sortino": 0,
                "Win Rate %": 0,
                "Profit Factor": 0,
                "Trades": 0,
                "Avg Trade $": 0,
            })

    # Display comparison
    print("\n" + "=" * 70)
    print("RESULTS COMPARISON")
    print("=" * 70)

    comparison_df = pd.DataFrame(results_summary)
    comparison_df = comparison_df.set_index("Strategy")

    pd.set_option("display.float_format", lambda x: f"{x:.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)

    print(comparison_df.to_string())

    # Best performers
    active = comparison_df[comparison_df["Trades"] > 0]
    if len(active) > 0:
        print("\n" + "-" * 70)
        print("BEST PERFORMERS:")
        print(f"  Highest Return:     {active['Total Return %'].idxmax()}")
        print(f"  Best Sharpe:        {active['Sharpe'].idxmax()}")
        print(f"  Best Win Rate:      {active['Win Rate %'].idxmax()}")
        print(f"  Lowest Drawdown:    {active['Max DD %'].idxmin()}")

    # Trading recommendations based on current regime
    print("\n" + "=" * 70)
    print("TRADING RECOMMENDATIONS")
    print("=" * 70)
    print(f"\nCurrent Regime: {current_regime.value}")

    print("\n--- KEY ENTRY/EXIT INDICATORS ---")
    if current_regime == MarketRegime.BULLISH:
        print("\nBULLISH - Buy the Dip:")
        print(f"  Current RSI(7): {indicators.rsi_7:.1f}")
        print(f"  Entry Signal: RSI(7) < 30")
        print(f"  Support Level: SMA20 = {indicators.sma_20:.2f}")
        print(f"  Stop Loss: 2x ATR ({indicators.atr_14 * 2:.2f} points)")
        print(f"  Target: 3x ATR ({indicators.atr_14 * 3:.2f} points)")

    elif current_regime == MarketRegime.BEARISH:
        print("\nBEARISH - Sell the Rip:")
        print(f"  Current RSI(7): {indicators.rsi_7:.1f}")
        print(f"  Entry Signal: RSI(7) > 70")
        print(f"  Resistance Level: SMA20 = {indicators.sma_20:.2f}")
        print(f"  Stop Loss: 2x ATR ({indicators.atr_14 * 2:.2f} points)")
        print(f"  Target: 3x ATR ({indicators.atr_14 * 3:.2f} points)")

    else:  # NEUTRAL
        print("\nNEUTRAL - Mean Reversion:")
        print(f"  Current RSI(7): {indicators.rsi_7:.1f}")
        print(f"  Long Entry: RSI(7) < 25")
        print(f"  Short Entry: RSI(7) > 75")
        print(f"  Exit: Middle Bollinger Band")
        print(f"  ADX: {indicators.adx:.1f} (ranging market)")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
