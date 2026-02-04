#!/usr/bin/env python3
"""
Analyze Current ES Market Regime

Downloads ES data from Yahoo Finance and determines:
1. Current market regime (Bullish/Neutral/Bearish)
2. Key indicators for the regime
3. Recommended trading approach

Usage:
    python scripts/analyze_regime.py
    python scripts/analyze_regime.py --period 2y
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.yahoo_data import YahooESData
from backtest.regime import RegimeDetector, MarketRegime


def main():
    parser = argparse.ArgumentParser(description="Analyze ES market regime")
    parser.add_argument(
        "--period",
        type=str,
        default="1y",
        help="Data period (1y, 2y, 5y)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("ES FUTURES MARKET REGIME ANALYSIS")
    print("=" * 60)

    # Download data
    print("\nDownloading ES data from Yahoo Finance...")
    yahoo = YahooESData()
    df = yahoo.download_es_data(period=args.period, interval="1d", save=True)

    if df.empty:
        print("Failed to download data")
        return

    print(f"\nData loaded: {len(df)} daily bars")
    print(f"Period: {df.index.min().date()} to {df.index.max().date()}")
    print(f"Current Price: {df['close'].iloc[-1]:.2f}")

    # Detect regime
    detector = RegimeDetector()
    detector.print_regime_report(df)

    # Show regime history
    df_regime = detector.detect_regime(df)

    print("\n--- REGIME HISTORY (Last 20 Days) ---")
    recent = df_regime[["close", "regime", "regime_strength", "rsi_14", "adx"]].tail(20)
    print(recent.to_string())

    # Regime distribution
    print("\n--- REGIME DISTRIBUTION (Full Period) ---")
    regime_counts = df_regime["regime"].value_counts()
    total = len(df_regime.dropna(subset=["regime"]))
    for regime, count in regime_counts.items():
        pct = count / total * 100
        print(f"  {regime}: {count} days ({pct:.1f}%)")


if __name__ == "__main__":
    main()
