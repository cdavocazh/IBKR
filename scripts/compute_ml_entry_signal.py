#!/usr/bin/env python3
"""
Walk-forward ML entry classifier for ES futures.

Uses tsfresh features + technical indicators + macro data to predict
next-day return direction. Walk-forward training ensures no lookahead bias.

Output: data/es/ml_entry_signal.csv (date, ml_long_prob, ml_short_prob, ml_confidence)
"""
import os
import sys
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

import os as _os
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "es"
# Default to ~/Github/macro_2; override via MACRO_DATA_DIR env var.
MACRO_DIR = Path(_os.environ.get(
    "MACRO_DATA_DIR",
    str(Path.home() / "Github" / "macro_2" / "historical_data"),
))

MIN_TRAIN_DAYS = 120    # 6 months minimum training window
RETRAIN_EVERY = 20      # Retrain model every 20 trading days
PREDICT_HORIZON = 1     # Predict next-day return


def load_features():
    """Build feature matrix from tsfresh + technical + macro data."""
    # 1. tsfresh features (27 statistically significant features)
    tsfresh_path = DATA_DIR / "tsfresh_daily_features.csv"
    if tsfresh_path.exists():
        tsfresh = pd.read_csv(tsfresh_path, parse_dates=["date"])
        tsfresh.set_index("date", inplace=True)
    else:
        print("WARNING: tsfresh_daily_features.csv not found, using signal only")
        signal_path = DATA_DIR / "tsfresh_daily_signal.csv"
        if signal_path.exists():
            tsfresh = pd.read_csv(signal_path, parse_dates=["date"])
            tsfresh.set_index("date", inplace=True)
        else:
            tsfresh = pd.DataFrame()

    # 2. Daily ES data (RSI, SMA trend, BB position, ATR, momentum)
    daily_path = DATA_DIR / "ES_daily.parquet"
    if daily_path.exists():
        daily = pd.read_parquet(daily_path)
        daily.index = pd.to_datetime(daily.index)
        if daily.index.tz is not None:
            daily.index = daily.index.tz_localize(None)
        daily.index.name = "date"

        # Compute technical indicators
        daily["returns"] = daily["close"].pct_change()
        daily["rsi_14"] = _compute_rsi(daily["close"], 14)
        daily["sma_20"] = daily["close"].rolling(20).mean()
        daily["sma_50"] = daily["close"].rolling(50).mean()
        daily["sma_200"] = daily["close"].rolling(200).mean()
        daily["sma_trend"] = (daily["sma_20"] - daily["sma_50"]) / daily["sma_50"]
        daily["price_vs_sma200"] = (daily["close"] - daily["sma_200"]) / daily["sma_200"]
        daily["momentum_12"] = daily["close"].pct_change(12)
        daily["momentum_5"] = daily["close"].pct_change(5)
        daily["atr_14"] = _compute_atr(daily, 14)
        daily["atr_pct"] = daily["atr_14"] / daily["close"] * 100
        daily["bb_upper"] = daily["sma_20"] + 2 * daily["close"].rolling(20).std()
        daily["bb_lower"] = daily["sma_20"] - 2 * daily["close"].rolling(20).std()
        daily["bb_position"] = (daily["close"] - daily["bb_lower"]) / (daily["bb_upper"] - daily["bb_lower"])
        daily["vol_ratio"] = daily["volume"] / daily["volume"].rolling(20).mean()
        daily["range_pct"] = (daily["high"] - daily["low"]) / daily["close"] * 100

        tech_features = daily[["returns", "rsi_14", "sma_trend", "price_vs_sma200",
                               "momentum_12", "momentum_5", "atr_pct", "bb_position",
                               "vol_ratio", "range_pct"]].copy()
    else:
        tech_features = pd.DataFrame()

    # 3. Macro data (VIX, DXY, HY OAS)
    macro_features = pd.DataFrame()
    for fname, col in [("vix_move.csv", "vix"), ("dxy.csv", "dxy"), ("hy_oas.csv", "hy_oas")]:
        fpath = MACRO_DIR / fname
        if fpath.exists():
            mdf = pd.read_csv(fpath)
            date_col = "date" if "date" in mdf.columns else mdf.columns[0]
            mdf["date"] = pd.to_datetime(mdf[date_col], errors="coerce")
            mdf = mdf.dropna(subset=["date"])
            mdf.set_index("date", inplace=True)
            if col in mdf.columns:
                macro_features[col] = mdf[col].astype(float)
            elif len(mdf.columns) >= 2:
                macro_features[col] = mdf.iloc[:, 0].astype(float)

    # Compute VIX derivatives
    if "vix" in macro_features.columns:
        macro_features["vix_change"] = macro_features["vix"].pct_change()
        macro_features["vix_ma5"] = macro_features["vix"].rolling(5).mean()
        macro_features["vix_z"] = (macro_features["vix"] - macro_features["vix"].rolling(60).mean()) / macro_features["vix"].rolling(60).std()

    # 4. Sentiment data
    sent_path = DATA_DIR.parent / "news" / "daily_sentiment.csv"
    if sent_path.exists():
        sent = pd.read_csv(sent_path, parse_dates=["date"])
        sent.set_index("date", inplace=True)
        if "composite_sentiment" in sent.columns:
            macro_features["sentiment"] = sent["composite_sentiment"]

    # Merge all features
    all_dfs = [df for df in [tsfresh, tech_features, macro_features] if len(df) > 0]
    if not all_dfs:
        raise ValueError("No feature data available")

    features = all_dfs[0]
    for df in all_dfs[1:]:
        features = features.join(df, how="outer")

    # Forward fill macro data (published daily but may have gaps)
    features = features.ffill().dropna(how="all")

    # Build target: next-day return > 0
    if daily_path.exists():
        daily_clean = pd.read_parquet(daily_path)
        daily_clean.index = pd.to_datetime(daily_clean.index)
        if daily_clean.index.tz is not None:
            daily_clean.index = daily_clean.index.tz_localize(None)
        features["target"] = (daily_clean["close"].shift(-PREDICT_HORIZON) > daily_clean["close"]).astype(int)
    else:
        raise ValueError("ES_daily.parquet needed for target computation")

    # Drop rows with NaN features or target
    features = features.dropna()

    print(f"Feature matrix: {features.shape[0]} rows, {features.shape[1]-1} features")
    print(f"Date range: {features.index.min().date()} to {features.index.max().date()}")
    print(f"Target balance: {features['target'].mean():.1%} positive")

    return features


def _compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _compute_atr(df, period=14):
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def walk_forward_train(features):
    """Walk-forward training with expanding window."""
    try:
        import lightgbm as lgb
        use_lgb = True
        print("Using LightGBM classifier")
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        use_lgb = False
        print("Using sklearn GradientBoostingClassifier (fallback)")

    feature_cols = [c for c in features.columns if c != "target"]
    dates = features.index.sort_values()
    predictions = []

    model = None
    last_train_idx = -1

    for i in range(MIN_TRAIN_DAYS, len(dates)):
        current_date = dates[i]

        # Retrain periodically
        if model is None or (i - last_train_idx) >= RETRAIN_EVERY:
            train_data = features.iloc[:i]
            X_train = train_data[feature_cols].values
            y_train = train_data["target"].values

            # Z-score normalize using training statistics
            train_mean = np.nanmean(X_train, axis=0)
            train_std = np.nanstd(X_train, axis=0)
            train_std[train_std == 0] = 1.0
            X_train = (X_train - train_mean) / train_std

            # Handle remaining NaN
            X_train = np.nan_to_num(X_train, nan=0.0)

            if use_lgb:
                model = lgb.LGBMClassifier(
                    n_estimators=100, max_depth=4, learning_rate=0.1,
                    subsample=0.8, colsample_bytree=0.8,
                    min_child_samples=20, verbose=-1,
                    random_state=42
                )
            else:
                model = GradientBoostingClassifier(
                    n_estimators=100, max_depth=4, learning_rate=0.1,
                    subsample=0.8, random_state=42
                )

            model.fit(X_train, y_train)
            last_train_idx = i
            _stored_mean = train_mean
            _stored_std = train_std

            if i == MIN_TRAIN_DAYS:
                print(f"First model trained on {len(X_train)} samples")

        # Predict current day (using only prior data for features, no lookahead)
        X_pred = features.iloc[i:i+1][feature_cols].values
        X_pred = (X_pred - _stored_mean) / _stored_std
        X_pred = np.nan_to_num(X_pred, nan=0.0)

        prob = model.predict_proba(X_pred)[0]
        # prob[0] = P(target=0), prob[1] = P(target=1)
        ml_long_prob = float(prob[1]) if len(prob) > 1 else 0.5
        ml_short_prob = 1.0 - ml_long_prob
        ml_confidence = abs(ml_long_prob - 0.5) * 2

        predictions.append({
            "date": current_date,
            "ml_long_prob": ml_long_prob,
            "ml_short_prob": ml_short_prob,
            "ml_confidence": ml_confidence,
        })

    result = pd.DataFrame(predictions)
    print(f"\nPredictions: {len(result)} days")
    print(f"Mean long_prob: {result['ml_long_prob'].mean():.3f}")
    print(f"Mean confidence: {result['ml_confidence'].mean():.3f}")
    print(f"High confidence (>0.3) days: {(result['ml_confidence'] > 0.3).sum()}")

    return result


def main():
    print("=" * 60)
    print("  ML Entry Classifier — Walk-Forward Training")
    print("=" * 60)

    features = load_features()
    predictions = walk_forward_train(features)

    # Save
    out_path = DATA_DIR / "ml_entry_signal.csv"
    predictions.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")

    # Quick accuracy check (on training data — informational only)
    merged = features.join(predictions.set_index("date")[["ml_long_prob"]], how="inner")
    if len(merged) > 0:
        merged["pred_correct"] = ((merged["ml_long_prob"] > 0.5) == (merged["target"] == 1))
        accuracy = merged["pred_correct"].mean()
        print(f"Walk-forward accuracy: {accuracy:.1%} ({len(merged)} samples)")


if __name__ == "__main__":
    main()
