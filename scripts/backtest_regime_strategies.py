#!/usr/bin/env python3
"""
Backtest Regime-Specific Strategies on ES Futures

Tests three strategies:
1. Buy the Dip (for bullish regimes)
2. Sell the Rip (for bearish regimes)
3. Mean Reversion Extremes (for neutral regimes)
4. Adaptive Strategy (switches based on regime)

Uses Yahoo Finance data for 5 years of history.

Usage:
    python scripts/backtest_regime_strategies.py
    python scripts/backtest_regime_strategies.py --years 3
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from ibkr.yahoo_data import YahooESData
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


def run_single_backtest(df: pd.DataFrame, strategy, capital: float) -> dict:
    """Run backtest for a single strategy."""
    engine = BacktestEngine(
        data=df.copy(),
        initial_capital=capital,
        commission_per_contract=2.25,
        slippage_ticks=1,
    )
    return engine.run(strategy=strategy)


def main():
    parser = argparse.ArgumentParser(description="Backtest regime strategies on ES")
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Years of data to use",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1d",
        help="Timeframe (1d or 1h)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("ES FUTURES REGIME STRATEGY BACKTEST")
    print("=" * 70)

    # Download data
    print("\nDownloading ES data from Yahoo Finance...")
    yahoo = YahooESData()

    if args.timeframe == "1h":
        df = yahoo.download_es_data(period="2y", interval="1h", save=True)
    else:
        df = yahoo.download_es_data(period=f"{args.years}y", interval="1d", save=True)

    if df.empty:
        print("Failed to download data")
        return

    print(f"\nData loaded: {len(df)} bars")
    print(f"Period: {df.index.min()} to {df.index.max()}")
    print(f"Initial Capital: ${args.capital:,.2f}")

    # First, analyze regime distribution
    print("\n--- ANALYZING MARKET REGIMES ---")
    detector = RegimeDetector()
    df_regime = detector.detect_regime(df)

    regime_counts = df_regime["regime"].value_counts()
    total_days = len(df_regime.dropna(subset=["regime"]))
    print("\nRegime Distribution:")
    for regime, count in regime_counts.items():
        pct = count / total_days * 100
        print(f"  {regime}: {count} days ({pct:.1f}%)")

    # Define strategies
    strategies = [
        ("Buy the Dip", BuyTheDipStrategy()),
        ("Sell the Rip", SellTheRipStrategy()),
        ("Mean Reversion", MeanReversionExtremesStrategy()),
        ("Adaptive (Auto)", AdaptiveRegimeStrategy()),
    ]

    results_summary = []

    print("\n--- RUNNING BACKTESTS ---")
    for name, strategy in strategies:
        print(f"\nTesting {name}...", end=" ", flush=True)

        try:
            results = run_single_backtest(df, strategy, args.capital)

            if len(results["trades"]) > 0:
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
                    "Final Equity": results["final_equity"],
                })
                print(f"Done ({metrics.total_trades} trades)")
            else:
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
                    "Final Equity": args.capital,
                })
                print("Done (0 trades)")

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
                "Final Equity": args.capital,
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
    if len(comparison_df[comparison_df["Trades"] > 0]) > 0:
        active = comparison_df[comparison_df["Trades"] > 0]
        print("\n" + "-" * 70)
        print("BEST PERFORMERS (among strategies with trades):")
        print(f"  Highest Return:     {active['Total Return %'].idxmax()}")
        print(f"  Best Sharpe:        {active['Sharpe'].idxmax()}")
        print(f"  Best Win Rate:      {active['Win Rate %'].idxmax()}")
        print(f"  Lowest Drawdown:    {active['Max Drawdown %'].idxmin()}")

    # Current regime recommendation
    print("\n" + "=" * 70)
    print("CURRENT MARKET ANALYSIS")
    print("=" * 70)

    current_regime, indicators = detector.get_current_regime(df)
    print(f"\nCurrent Regime: {current_regime.value}")
    print(f"Regime Confidence: {indicators.regime_strength:.1f}%")

    print(f"\nRecommended Strategy: ", end="")
    if current_regime == MarketRegime.BULLISH:
        print("BUY THE DIP")
        print("  - Wait for RSI(7) < 30")
        print("  - Entry near SMA20 or lower Bollinger Band")
        print("  - Stop loss: 2x ATR below entry")
    elif current_regime == MarketRegime.BEARISH:
        print("SELL THE RIP")
        print("  - Wait for RSI(7) > 70")
        print("  - Entry near SMA20 or upper Bollinger Band")
        print("  - Stop loss: 2x ATR above entry")
    else:
        print("MEAN REVERSION AT EXTREMES")
        print("  - Buy when RSI(7) < 25 at lower Bollinger")
        print("  - Sell when RSI(7) > 75 at upper Bollinger")
        print("  - Exit at middle Bollinger (mean)")

    print("\n--- KEY INDICATORS ---")
    print(f"RSI(14): {indicators.rsi_14:.1f}")
    print(f"RSI(7): {indicators.rsi_7:.1f}")
    print(f"ADX: {indicators.adx:.1f}")
    print(f"ATR%: {indicators.atr_percent:.2f}%")

    print("=" * 70)


if __name__ == "__main__":
    main()
