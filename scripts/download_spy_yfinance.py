#!/usr/bin/env python3
"""
Download SPY data via yfinance and convert to ES-equivalent format.

Since ES 1-min data only covers Jan 2025+, this downloads SPY hourly data
going back to Apr 2023 to fill the gap for walk-forward validation.

SPY→ES conversion applies a scaling factor based on the ES/SPY ratio
during the overlap period (Jan-Mar 2026).

Usage:
    python scripts/download_spy_yfinance.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).parent.parent


def download_spy_data():
    """Download SPY hourly + daily data via yfinance."""
    spy = yf.Ticker("SPY")

    # 1-hour bars: ~3 years
    print("Downloading SPY 1-hour data...")
    df_1h = spy.history(period="730d", interval="1h")
    print(f"  1-hour: {len(df_1h)} bars, {df_1h.index[0]} to {df_1h.index[-1]}")

    # Daily bars: 5 years
    print("Downloading SPY daily data...")
    df_daily = spy.history(period="5y", interval="1d")
    print(f"  Daily: {len(df_daily)} bars, {df_daily.index[0]} to {df_daily.index[-1]}")

    # 5-min bars: ~60 days (for recent overlap calibration)
    print("Downloading SPY 5-min data (recent)...")
    df_5m = spy.history(period="60d", interval="5m")
    print(f"  5-min: {len(df_5m)} bars, {df_5m.index[0]} to {df_5m.index[-1]}")

    return df_1h, df_daily, df_5m


def compute_spy_to_es_ratio(spy_daily: pd.DataFrame) -> float:
    """Compute SPY→ES price ratio from overlapping ES daily data."""
    es_path = PROJECT_ROOT / "data" / "es" / "ES_daily.parquet"
    if not es_path.exists():
        print("  WARNING: No ES daily data for calibration, using default ratio")
        return 10.0  # Approximate ES/SPY ratio

    es_daily = pd.read_parquet(es_path).sort_index()

    # Find overlapping dates
    spy_dates = set(spy_daily.index.normalize().date)
    es_dates = set(d.date() if hasattr(d, "date") else d for d in es_daily.index)
    overlap = sorted(spy_dates & es_dates)

    if len(overlap) < 10:
        print(f"  WARNING: Only {len(overlap)} overlapping dates, using default ratio")
        return 10.0

    # Compute ratio for last 60 overlapping days
    recent_overlap = overlap[-60:]
    ratios = []
    for d in recent_overlap:
        spy_row = spy_daily[spy_daily.index.normalize().date == d]
        es_row = es_daily[[dd.date() == d if hasattr(dd, "date") else dd == d for dd in es_daily.index]]
        if len(spy_row) > 0 and len(es_row) > 0:
            spy_close = spy_row["Close"].iloc[0]
            es_close = es_row["close"].iloc[0]
            if spy_close > 0:
                ratios.append(es_close / spy_close)

    if ratios:
        ratio = np.median(ratios)
        print(f"  ES/SPY ratio: {ratio:.4f} (from {len(ratios)} days)")
        return ratio
    return 10.0


def convert_spy_to_es(df: pd.DataFrame, ratio: float) -> pd.DataFrame:
    """Convert SPY OHLCV to ES-equivalent prices.

    Applies the ES/SPY price ratio and scales volume by ES point value.
    """
    col_map = {c: c.lower() for c in df.columns}
    df = df.rename(columns=col_map)

    result = pd.DataFrame(index=df.index)
    result["open"] = df["open"] * ratio
    result["high"] = df["high"] * ratio
    result["low"] = df["low"] * ratio
    result["close"] = df["close"] * ratio
    result["volume"] = df["volume"] / 1000  # Scale down SPY volume (much higher than ES)

    # Round to ES tick size (0.25)
    for col in ["open", "high", "low", "close"]:
        result[col] = (result[col] / 0.25).round() * 0.25

    return result


def main():
    df_1h, df_daily, df_5m = download_spy_data()

    # Compute conversion ratio
    print("\nCalibrating SPY→ES conversion...")
    ratio = compute_spy_to_es_ratio(df_daily)

    # Convert hourly to ES-equivalent
    print("\nConverting SPY → ES-equivalent...")
    es_1h = convert_spy_to_es(df_1h, ratio)
    es_daily_spy = convert_spy_to_es(df_daily, ratio)
    es_5m_spy = convert_spy_to_es(df_5m, ratio)

    # Filter to pre-ES period only (before Jan 2025) for hourly
    es_data_start = pd.Timestamp("2025-01-31", tz=es_1h.index.tz) if es_1h.index.tz else pd.Timestamp("2025-01-31")
    es_1h_gap = es_1h[es_1h.index < es_data_start]

    print(f"\n  ES-equivalent hourly (gap fill): {len(es_1h_gap)} bars")
    if len(es_1h_gap) > 0:
        print(f"    Date range: {es_1h_gap.index[0]} to {es_1h_gap.index[-1]}")
    print(f"  ES-equivalent hourly (all): {len(es_1h)} bars")
    print(f"  ES-equivalent daily (all): {len(es_daily_spy)} bars")
    print(f"  ES-equivalent 5-min (recent): {len(es_5m_spy)} bars")

    # Save all versions
    save_dir = PROJECT_ROOT / "data" / "es"

    # Hourly gap-fill (pre-Jan 2025)
    if len(es_1h_gap) > 0:
        path = save_dir / "SPY_as_ES_hourly_gap.parquet"
        es_1h_gap.to_parquet(path)
        print(f"\n  Saved gap fill: {path}")

    # Full hourly
    path = save_dir / "SPY_as_ES_hourly_full.parquet"
    es_1h.to_parquet(path)
    print(f"  Saved full hourly: {path}")

    # Full daily
    path = save_dir / "SPY_as_ES_daily_full.parquet"
    es_daily_spy.to_parquet(path)
    print(f"  Saved full daily: {path}")

    # Recent 5-min
    path = save_dir / "SPY_as_ES_5min_recent.parquet"
    es_5m_spy.to_parquet(path)
    print(f"  Saved recent 5-min: {path}")

    # Create combined dataset: SPY hourly (pre-2025) + ES 1-min resampled to hourly (2025+)
    print("\nCreating combined hourly dataset (SPY gap + ES)...")
    es_1min_path = PROJECT_ROOT / "data" / "es" / "ES_1min.parquet"
    if es_1min_path.exists():
        es_1min = pd.read_parquet(es_1min_path)
        es_hourly = es_1min.resample("1h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        # Ensure timezone compatibility
        if es_1h_gap.index.tz is not None and es_hourly.index.tz is None:
            es_1h_gap.index = es_1h_gap.index.tz_localize(None)
        elif es_1h_gap.index.tz is None and es_hourly.index.tz is not None:
            es_hourly.index = es_hourly.index.tz_localize(None)

        combined = pd.concat([es_1h_gap, es_hourly]).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]  # ES data takes priority in overlap

        path = save_dir / "ES_combined_hourly_extended.parquet"
        combined.to_parquet(path)
        print(f"  Combined: {len(combined)} hourly bars")
        print(f"  Date range: {combined.index[0]} to {combined.index[-1]}")
        print(f"  Saved: {path}")

    # Summary
    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"  SPY hourly bars (gap fill, pre-2025): {len(es_1h_gap)}")
    print(f"  SPY hourly bars (full):               {len(es_1h)}")
    print(f"  ES/SPY price ratio used:              {ratio:.4f}")
    print(f"  Combined hourly dataset:              ES_combined_hourly_extended.parquet")
    print(f"\n  NOTE: SPY data covers regular hours only (9:30am-4pm ET).")
    print(f"  ES overnight session (4pm-9:30am) is not represented.")
    print(f"  Use for walk-forward OOS testing, not as primary backtest data.")


if __name__ == "__main__":
    main()
