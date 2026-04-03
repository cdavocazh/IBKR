#!/usr/bin/env python3
"""
Distance-correlation analysis of technical indicators vs ES forward returns.

Computes distance correlation (dcor) between each indicator and forward returns
at multiple horizons, per regime. Identifies which indicators have genuine
predictive power and which are noise.

Output: data/es/tuneta_indicator_ranking.csv + console recommendations.

Usage:
    python scripts/tuneta_analysis.py
    python scripts/tuneta_analysis.py --horizons 12,48,288
"""

import argparse
import sys
from pathlib import Path

import dcor
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def compute_rsi(prices: np.ndarray, period: int) -> np.ndarray:
    """Vectorized RSI computation."""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    rsi = np.full(len(prices), np.nan)
    for i in range(period, len(deltas)):
        avg_gain = np.mean(gains[i - period:i])
        avg_loss = np.mean(losses[i - period:i])
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rsi[i + 1] = 100 - (100 / (1 + avg_gain / avg_loss))
    return rsi


def compute_sma(prices: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    sma = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        sma[i] = np.mean(prices[i - period + 1:i + 1])
    return sma


def compute_bb_position(prices: np.ndarray, period: int, std_mult: float) -> np.ndarray:
    """Bollinger Band position: (price - lower) / (upper - lower), 0 to 1."""
    bb_pos = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1:i + 1]
        sma = np.mean(window)
        std = np.std(window)
        if std > 0:
            upper = sma + std_mult * std
            lower = sma - std_mult * std
            bb_pos[i] = (prices[i] - lower) / (upper - lower)
    return bb_pos


def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    """Average True Range."""
    atr = np.full(len(closes), np.nan)
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        if i >= period:
            trs = []
            for j in range(i - period + 1, i + 1):
                t = max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
                trs.append(t)
            atr[i] = np.mean(trs)
    return atr


def compute_momentum(prices: np.ndarray, lookback: int) -> np.ndarray:
    """Price momentum as percent change."""
    mom = np.full(len(prices), np.nan)
    for i in range(lookback, len(prices)):
        if prices[i - lookback] > 0:
            mom[i] = (prices[i] - prices[i - lookback]) / prices[i - lookback] * 100
    return mom


def compute_volume_ratio(volumes: np.ndarray, lookback: int) -> np.ndarray:
    """Volume relative to moving average."""
    vr = np.full(len(volumes), np.nan)
    for i in range(lookback, len(volumes)):
        avg = np.mean(volumes[i - lookback:i])
        if avg > 0:
            vr[i] = volumes[i] / avg
    return vr


def classify_regime(closes: np.ndarray, sma_fast: int = 30, sma_slow: int = 50) -> np.ndarray:
    """Simple regime classification: 1=BULL, -1=BEAR, 0=SIDEWAYS."""
    fast = compute_sma(closes, sma_fast)
    slow = compute_sma(closes, sma_slow)
    sma200 = compute_sma(closes, 200)

    regime = np.zeros(len(closes))
    for i in range(len(closes)):
        if np.isnan(fast[i]) or np.isnan(slow[i]):
            continue
        score = 0
        if fast[i] > slow[i]:
            score += 1
        elif fast[i] < slow[i]:
            score -= 1
        if not np.isnan(sma200[i]):
            if closes[i] > sma200[i]:
                score += 1
            elif closes[i] < sma200[i]:
                score -= 1
        if score > 0:
            regime[i] = 1
        elif score < 0:
            regime[i] = -1
    return regime


def safe_dcor(x: np.ndarray, y: np.ndarray) -> float:
    """Distance correlation with NaN handling."""
    mask = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
    x_clean = x[mask]
    y_clean = y[mask]
    if len(x_clean) < 30:
        return np.nan
    try:
        return float(dcor.distance_correlation(x_clean, y_clean))
    except Exception:
        return np.nan


def run_analysis(horizons: list[int] = None):
    """Run distance-correlation analysis on all indicators."""
    if horizons is None:
        horizons = [12, 48, 288]  # 1hr, 4hr, 1day on 5-min bars

    # Load data
    data_path = PROJECT_ROOT / "data" / "es" / "ES_combined_5min.parquet"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(data_path).sort_index()
    print(f"Loaded {len(df)} 5-min bars: {df.index[0]} to {df.index[-1]}")

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values

    # Compute all indicators
    print("\nComputing indicators...")
    indicators = {}

    # RSI at multiple periods
    for period in [7, 14, 21]:
        indicators[f"RSI_{period}"] = compute_rsi(closes, period)

    # Fast RSI
    indicators["RSI_3"] = compute_rsi(closes, 3)

    # SMA crossover signals (fast - slow as % of slow)
    for fast, slow in [(10, 50), (20, 50), (30, 50), (30, 80), (50, 200)]:
        sma_f = compute_sma(closes, fast)
        sma_s = compute_sma(closes, slow)
        cross = np.full(len(closes), np.nan)
        for i in range(len(closes)):
            if not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]) and sma_s[i] > 0:
                cross[i] = (sma_f[i] - sma_s[i]) / sma_s[i] * 100
        indicators[f"SMA_{fast}_{slow}_cross"] = cross

    # Price vs SMA200 (distance in %)
    sma200 = compute_sma(closes, 200)
    dist_200 = np.full(len(closes), np.nan)
    for i in range(len(closes)):
        if not np.isnan(sma200[i]) and sma200[i] > 0:
            dist_200[i] = (closes[i] - sma200[i]) / sma200[i] * 100
    indicators["Price_vs_SMA200_pct"] = dist_200

    # Bollinger Band position
    for period in [10, 15, 20]:
        indicators[f"BB_pos_{period}"] = compute_bb_position(closes, period, 2.0)
    indicators["BB_pos_15_wide"] = compute_bb_position(closes, 15, 2.5)

    # Momentum at multiple lookbacks
    for lb in [6, 12, 24, 48]:
        indicators[f"Momentum_{lb}bar"] = compute_momentum(closes, lb)

    # ATR (normalized by price)
    for period in [14, 28]:
        atr = compute_atr(highs, lows, closes, period)
        atr_pct = np.full(len(closes), np.nan)
        for i in range(len(closes)):
            if not np.isnan(atr[i]) and closes[i] > 0:
                atr_pct[i] = atr[i] / closes[i] * 100
        indicators[f"ATR_{period}_pct"] = atr_pct

    # Volume ratio
    for lb in [20, 50]:
        indicators[f"Vol_ratio_{lb}"] = compute_volume_ratio(volumes, lb)

    # Raw volume
    indicators["Volume"] = volumes.astype(float)

    # Compute forward returns
    print("Computing forward returns...")
    forward_returns = {}
    for h in horizons:
        fwd = np.full(len(closes), np.nan)
        for i in range(len(closes) - h):
            if closes[i] > 0:
                fwd[i] = (closes[i + h] - closes[i]) / closes[i] * 100
        forward_returns[f"fwd_{h}bar"] = fwd

    # Classify regime
    regime = classify_regime(closes)

    # Run distance correlation analysis
    print("\nComputing distance correlations...")
    regime_names = {1: "BULLISH", -1: "BEARISH", 0: "SIDEWAYS"}
    results = []

    for ind_name, ind_vals in indicators.items():
        for h_name, fwd_vals in forward_returns.items():
            # Overall
            dc = safe_dcor(ind_vals, fwd_vals)
            results.append({
                "indicator": ind_name,
                "horizon": h_name,
                "regime": "ALL",
                "dcor": dc,
                "n_samples": int(np.sum(~(np.isnan(ind_vals) | np.isnan(fwd_vals)))),
            })

            # Per regime
            for r_val, r_name in regime_names.items():
                mask = regime == r_val
                if mask.sum() < 100:
                    continue
                dc_r = safe_dcor(ind_vals[mask], fwd_vals[mask])
                results.append({
                    "indicator": ind_name,
                    "horizon": h_name,
                    "regime": r_name,
                    "dcor": dc_r,
                    "n_samples": int(np.sum(mask & ~(np.isnan(ind_vals) | np.isnan(fwd_vals)))),
                })

    results_df = pd.DataFrame(results)

    # Save full results
    out_path = PROJECT_ROOT / "data" / "es" / "tuneta_indicator_ranking.csv"
    results_df.to_csv(out_path, index=False)
    print(f"\nFull results saved to {out_path}")

    # Print summary tables
    print("\n" + "=" * 80)
    print("DISTANCE CORRELATION RANKINGS (higher = more predictive)")
    print("=" * 80)

    for regime in ["ALL", "BULLISH", "BEARISH", "SIDEWAYS"]:
        print(f"\n--- {regime} regime ---")
        for horizon in [f"fwd_{h}bar" for h in horizons]:
            subset = results_df[
                (results_df["regime"] == regime) &
                (results_df["horizon"] == horizon)
            ].sort_values("dcor", ascending=False).head(10)

            if subset.empty:
                continue

            h_bars = int(horizon.split("_")[1].replace("bar", ""))
            h_label = f"{h_bars * 5}min" if h_bars < 60 else f"{h_bars * 5 // 60}hr"
            print(f"\n  Forward {h_label} returns ({horizon}):")
            for _, row in subset.iterrows():
                dc_val = row["dcor"]
                if np.isnan(dc_val):
                    continue
                bar = "#" * int(dc_val * 50)
                print(f"    {row['indicator']:30s} dcor={dc_val:.4f} (n={row['n_samples']:,}) {bar}")

    # Print current strategy weights vs dcor rankings
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS: Current weights vs predictive power")
    print("=" * 80)

    # Map strategy indicators to dcor indicators
    indicator_map = {
        "RSI": ["RSI_7", "RSI_14", "RSI_21", "RSI_3"],
        "Trend (SMA)": ["SMA_30_50_cross", "SMA_10_50_cross", "SMA_20_50_cross", "Price_vs_SMA200_pct"],
        "Momentum": ["Momentum_6bar", "Momentum_12bar", "Momentum_24bar", "Momentum_48bar"],
        "Bollinger Bands": ["BB_pos_10", "BB_pos_15", "BB_pos_20", "BB_pos_15_wide"],
        "Volume": ["Vol_ratio_20", "Vol_ratio_50", "Volume"],
        "ATR/Volatility": ["ATR_14_pct", "ATR_28_pct"],
    }

    current_weights = {
        "BULLISH": {"RSI": 0.10, "Trend (SMA)": 0.35, "Momentum": 0.10, "Bollinger Bands": 0.05, "Volume": 0.15},
        "BEARISH": {"RSI": 0.20, "Trend (SMA)": 0.10, "Momentum": 0.05, "Bollinger Bands": 0.20, "Volume": 0.15},
        "SIDEWAYS": {"RSI": 0.15, "Trend (SMA)": 0.10, "Momentum": 0.25, "Bollinger Bands": 0.25, "Volume": 0.15},
    }

    # For the 4hr horizon (most relevant to strategy's holding period)
    horizon_key = f"fwd_{horizons[1]}bar" if len(horizons) > 1 else f"fwd_{horizons[0]}bar"

    for regime in ["BULLISH", "BEARISH", "SIDEWAYS"]:
        print(f"\n  {regime} regime (4hr forward returns):")
        regime_data = results_df[
            (results_df["regime"] == regime) &
            (results_df["horizon"] == horizon_key)
        ]

        group_scores = {}
        for group_name, ind_list in indicator_map.items():
            scores = []
            for ind in ind_list:
                row = regime_data[regime_data["indicator"] == ind]
                if not row.empty and not np.isnan(row.iloc[0]["dcor"]):
                    scores.append(row.iloc[0]["dcor"])
            group_scores[group_name] = max(scores) if scores else 0.0

        # Normalize to sum=1 for comparison
        total = sum(group_scores.values())
        if total > 0:
            suggested = {k: round(v / total, 2) for k, v in group_scores.items()}
        else:
            suggested = group_scores

        weights = current_weights.get(regime, {})
        print(f"    {'Indicator':25s} {'Current Wt':>12s} {'dcor-based':>12s} {'Delta':>8s}")
        print(f"    {'-' * 60}")
        for group_name in indicator_map:
            curr = weights.get(group_name, 0)
            sugg = suggested.get(group_name, 0)
            delta = sugg - curr
            arrow = "^" if delta > 0.03 else ("v" if delta < -0.03 else "=")
            print(f"    {group_name:25s} {curr:12.2f} {sugg:12.2f} {delta:+8.2f} {arrow}")

    return results_df


def main():
    parser = argparse.ArgumentParser(description="TuneTA-style indicator analysis")
    parser.add_argument("--horizons", type=str, default="12,48,288",
                        help="Comma-separated forward return horizons in bars (default: 12,48,288)")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    run_analysis(horizons)


if __name__ == "__main__":
    main()
