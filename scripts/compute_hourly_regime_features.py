#!/usr/bin/env python3
"""
Compute daily regime features from hourly ES data.

Uses ES_combined_hourly_extended.parquet (7,119 hourly bars, Apr 2023 - Mar 2026)
to compute daily regime signals:
  - hourly_trend: SMA(20h) vs SMA(50h) → +1/0/-1
  - hourly_atr_percentile: 14-period hourly ATR percentile rank over trailing 252 days
  - hourly_momentum_z: 20-bar ROC z-scored over trailing 60 days
  - hourly_vol_regime: "low"/<25th, "normal"/25-75th, "high"/>75th

Output: data/es/hourly_regime_features.csv (one row per trading day, using EOD values)
Uses PREVIOUS day's values only — no lookahead bias.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "es"


def compute_features():
    path = DATA_DIR / "ES_combined_hourly_extended.parquet"
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(path).sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    print(f"Loaded {len(df)} hourly bars: {df.index.min()} to {df.index.max()}")

    # Compute hourly indicators on the full series
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # SMA 20h and 50h
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()

    # ATR 14-period (hourly)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_14 = tr.rolling(14).mean()

    # ROC 20-bar
    roc_20 = close.pct_change(20) * 100  # percent

    # Group by trading day — use the last bar of each day
    df["date"] = df.index.date
    daily_last_idx = df.groupby("date").apply(lambda x: x.index[-1])

    rows = []
    for date_val, bar_idx in daily_last_idx.items():
        loc = df.index.get_loc(bar_idx)

        # Hourly trend: SMA20 vs SMA50
        s20 = sma_20.iloc[loc] if loc < len(sma_20) else np.nan
        s50 = sma_50.iloc[loc] if loc < len(sma_50) else np.nan
        if pd.notna(s20) and pd.notna(s50):
            if s20 > s50:
                trend = 1
            elif s20 < s50:
                trend = -1
            else:
                trend = 0
        else:
            trend = 0

        # ATR value at this bar
        atr_val = atr_14.iloc[loc] if loc < len(atr_14) else np.nan

        # ROC z-score (20-bar ROC, z-scored over trailing 60 days of hourly data)
        roc_val = roc_20.iloc[loc] if loc < len(roc_20) else np.nan

        rows.append({
            "date": date_val,
            "hourly_trend": trend,
            "hourly_atr": atr_val,
            "hourly_roc_20": roc_val,
        })

    result = pd.DataFrame(rows).set_index("date").sort_index()

    # ATR percentile rank over trailing 252 trading days
    result["hourly_atr_percentile"] = result["hourly_atr"].rolling(
        window=252, min_periods=20
    ).apply(lambda x: (x.iloc[-1] > x.iloc[:-1]).sum() / (len(x) - 1) * 100 if len(x) > 1 else 50)

    # Momentum z-score over trailing 60 days
    roc_rolling_mean = result["hourly_roc_20"].rolling(60, min_periods=10).mean()
    roc_rolling_std = result["hourly_roc_20"].rolling(60, min_periods=10).std()
    result["hourly_momentum_z"] = (result["hourly_roc_20"] - roc_rolling_mean) / roc_rolling_std.replace(0, np.nan)
    result["hourly_momentum_z"] = result["hourly_momentum_z"].fillna(0).clip(-3, 3)

    # Vol regime from ATR percentile
    def classify_vol(pct):
        if pd.isna(pct):
            return "normal"
        if pct < 25:
            return "low"
        elif pct > 75:
            return "high"
        return "normal"

    result["hourly_vol_regime"] = result["hourly_atr_percentile"].apply(classify_vol)

    # Fill NaN percentiles
    result["hourly_atr_percentile"] = result["hourly_atr_percentile"].fillna(50)

    # Keep only the columns we need
    output = result[["hourly_trend", "hourly_atr_percentile", "hourly_momentum_z", "hourly_vol_regime"]].copy()

    out_path = DATA_DIR / "hourly_regime_features.csv"
    output.to_csv(out_path)
    print(f"\nSaved {len(output)} daily rows to {out_path}")
    print(f"Date range: {output.index.min()} to {output.index.max()}")
    print(f"\nTrend distribution:")
    print(f"  Bullish (+1): {(output['hourly_trend'] == 1).sum()}")
    print(f"  Bearish (-1): {(output['hourly_trend'] == -1).sum()}")
    print(f"  Neutral (0):  {(output['hourly_trend'] == 0).sum()}")
    print(f"\nVol regime distribution:")
    print(output["hourly_vol_regime"].value_counts().to_string())
    print(f"\nMomentum z-score stats:")
    print(output["hourly_momentum_z"].describe().to_string())

    return output


if __name__ == "__main__":
    compute_features()
