#!/usr/bin/env python3
"""
tsfresh feature extraction for ES strategy.

Extracts statistically significant time-series features from daily ES data
and macro indicators. Filters by Benjamini-Hochberg FDR correction.

Output: data/es/tsfresh_daily_features.csv

Usage:
    python scripts/compute_tsfresh_features.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    from tsfresh import extract_features
    from tsfresh.feature_extraction import MinimalFCParameters, EfficientFCParameters
    from tsfresh.utilities.dataframe_functions import impute

    # Load daily data
    daily_path = PROJECT_ROOT / "data" / "es" / "ES_daily.parquet"
    df = pd.read_parquet(daily_path).sort_index()
    print(f"Loaded {len(df)} daily bars")

    # Create forward returns (target) — 5-day forward return
    df["fwd_5d_return"] = df["close"].pct_change(5).shift(-5)
    df = df.dropna(subset=["fwd_5d_return"])

    # Create rolling window time-series for tsfresh
    # Each "id" is a day, each window is the prior N days of OHLCV
    window_size = 20  # 20-day lookback
    rows = []
    dates = []
    targets = []

    for i in range(window_size, len(df)):
        day_id = i
        window = df.iloc[i - window_size:i]
        for j, (idx, row) in enumerate(window.iterrows()):
            rows.append({
                "id": day_id,
                "time": j,
                "close": row["close"],
                "high": row["high"],
                "low": row["low"],
                "volume": row["volume"],
                "range": row["high"] - row["low"],
                "log_return": np.log(row["close"] / df.iloc[i - window_size + j - 1]["close"]) if j > 0 else 0,
            })
        dates.append(df.index[i])
        targets.append(df.iloc[i]["fwd_5d_return"])

    ts_df = pd.DataFrame(rows)
    target_series = pd.Series(targets, index=range(window_size, window_size + len(targets)))

    print(f"Created {len(dates)} windows of {window_size} bars each")
    print(f"Total rows: {len(ts_df)}")

    # Extract features using efficient settings (not all 794 — too slow)
    print("\nExtracting features (EfficientFCParameters)...")
    features = extract_features(
        ts_df,
        column_id="id",
        column_sort="time",
        default_fc_parameters=EfficientFCParameters(),
        n_jobs=0,  # Single process for stability
        disable_progressbar=False,
    )

    # Impute NaN/inf
    impute(features)
    print(f"Extracted {features.shape[1]} features")

    # Filter significant features
    from tsfresh.feature_selection.relevance import calculate_relevance_table

    print("\nFiltering statistically significant features...")
    relevance = calculate_relevance_table(
        features,
        target_series,
        ml_task="regression",
        fdr_level=0.1,  # 10% FDR
    )

    significant = relevance[relevance["relevant"] == True].sort_values("p_value")
    print(f"\nFound {len(significant)} significant features (FDR < 0.1)")

    if len(significant) > 0:
        print("\nTop 20 features:")
        for _, row in significant.head(20).iterrows():
            print(f"  {row['feature']:60s} p={row['p_value']:.6f}")

    # Save top features as daily values
    top_features = significant.head(20)["feature"].tolist() if len(significant) > 0 else []

    if top_features:
        feature_df = features[top_features].copy()
        feature_df["date"] = dates[:len(feature_df)]
        feature_df.to_csv(PROJECT_ROOT / "data" / "es" / "tsfresh_daily_features.csv", index=False)
        print(f"\nSaved top {len(top_features)} features to data/es/tsfresh_daily_features.csv")
    else:
        print("\nNo significant features found at FDR=0.1")
        # Save all features anyway for manual inspection
        all_top = relevance.sort_values("p_value").head(20)["feature"].tolist()
        feature_df = features[all_top].copy()
        feature_df["date"] = dates[:len(feature_df)]
        feature_df.to_csv(PROJECT_ROOT / "data" / "es" / "tsfresh_daily_features.csv", index=False)
        print(f"Saved top 20 features by p-value (for manual review)")

    # Print feature summary
    print("\n" + "=" * 60)
    print("TSFRESH FEATURE SUMMARY")
    print("=" * 60)
    print(f"  Total features extracted: {features.shape[1]}")
    print(f"  Significant (FDR<0.1): {len(significant)}")
    print(f"  Feature categories found:")

    # Categorize features
    categories = {}
    for feat in (significant["feature"].tolist() if len(significant) > 0 else
                 relevance.sort_values("p_value").head(20)["feature"].tolist()):
        col = feat.split("__")[0] if "__" in feat else "unknown"
        categories[col] = categories.get(col, 0) + 1
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count} features")


if __name__ == "__main__":
    main()
