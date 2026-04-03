#!/usr/bin/env python3
"""
Out-of-sample validation: test the 5-min optimized strategy's regime logic
on hourly pre-period data (Apr 2023 - Jan 2025).

NOT expecting profitability — measuring:
1. Regime accuracy: classified regime vs actual forward return sign
2. Signal quality: when composite > threshold, was direction correct?
3. Per-regime accuracy breakdown

Usage:
    python scripts/validate_regime_oos.py
    python scripts/validate_regime_oos.py --forward-bars 40
"""

import argparse
import datetime as dt
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from autoresearch.verify_strategy import (
    compute_atr,
    compute_rsi,
    compute_sma,
    load_config,
    load_daily_es_trend,
    load_daily_sentiment,
    load_garch_forecast,
    load_hourly_regime_features,
    load_macro_data,
    load_particle_regime,
    ESAutoResearchStrategy,
)


def load_oos_hourly_data(cutoff_date="2025-01-01"):
    """Load hourly data filtered to pre-period only (OOS)."""
    path = PROJECT_ROOT / "data" / "es" / "ES_combined_hourly_extended.parquet"
    df = pd.read_parquet(path).sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    cutoff = pd.Timestamp(cutoff_date)
    oos = df[df.index < cutoff].copy()
    print(f"OOS data: {len(oos)} hourly bars, {oos.index.min()} to {oos.index.max()}")
    return oos


def run_validation(forward_bars=40):
    """Walk through OOS hourly bars, classify regime, measure accuracy."""
    cfg = load_config()
    macro_data = load_macro_data()
    daily_trend = load_daily_es_trend()
    daily_sentiment = load_daily_sentiment()
    garch_forecast = load_garch_forecast()
    particle_regime = load_particle_regime()
    hourly_regime = load_hourly_regime_features()

    # Create strategy instance (mock — we won't execute trades)
    strategy = ESAutoResearchStrategy(
        cfg, macro_data,
        nlp_regime={"regime": "SIDEWAYS", "net_sentiment": 0.0, "confidence": 0.0},
        digest_ctx={"trend": "SIDEWAYS", "vix_tier": 2},
        daily_trend=daily_trend,
        daily_sentiment=daily_sentiment,
        garch_forecast=garch_forecast,
        particle_regime=particle_regime,
        hourly_regime=hourly_regime,
    )
    # Force bar scale for hourly
    strategy._bar_scale = 12

    oos_df = load_oos_hourly_data()
    if len(oos_df) < 100:
        print("ERROR: Not enough OOS data")
        sys.exit(1)

    closes = oos_df["close"].values
    timestamps = oos_df.index

    # Track daily regime classifications
    regime_records = []  # (date, regime, forward_return)
    signal_records = []  # (date, side, composite, forward_return)

    # Walk bar by bar, feeding data to strategy
    buf_size = max(250, cfg.SMA_SLOW + 50, getattr(cfg, "SMA_200", 200) + 50)
    warmup = buf_size + 10

    for i in range(len(oos_df)):
        bar_ts = timestamps[i]

        # Feed bar data to strategy's buffers
        strategy.closes.append(float(oos_df["close"].iloc[i]))
        strategy.highs.append(float(oos_df["high"].iloc[i]))
        strategy.lows.append(float(oos_df["low"].iloc[i]))
        strategy.volumes.append(float(oos_df["volume"].iloc[i]))

        if i < warmup:
            continue

        # Classify regime
        try:
            regime = strategy._classify_regime(bar_ts)
        except Exception:
            continue

        # Compute forward return
        if i + forward_bars < len(closes):
            fwd_return = (closes[i + forward_bars] - closes[i]) / closes[i] * 100
        else:
            continue

        # Record daily regime (one per day, last bar)
        bar_date = bar_ts.date() if hasattr(bar_ts, "date") else bar_ts
        regime_records.append({
            "date": bar_date,
            "regime": regime,
            "forward_return": fwd_return,
            "close": closes[i],
        })

        # Try to compute composite score for potential signals
        try:
            # Determine side based on regime
            if regime == "BULLISH":
                rp = {
                    "side": "LONG", "rsi_oversold": cfg.BULL_RSI_OVERSOLD,
                    "rsi_overbought": cfg.BULL_RSI_OVERBOUGHT,
                    "w_rsi": cfg.BULL_WEIGHT_RSI, "w_trend": cfg.BULL_WEIGHT_TREND,
                    "w_momentum": cfg.BULL_WEIGHT_MOMENTUM, "w_bb": cfg.BULL_WEIGHT_BB,
                    "w_vix": cfg.BULL_WEIGHT_VIX, "w_macro": cfg.BULL_WEIGHT_MACRO,
                    "composite_threshold": cfg.BULL_COMPOSITE_THRESHOLD,
                }
                side = "LONG"
            elif regime == "BEARISH":
                rp = {
                    "side": "SHORT", "rsi_oversold": cfg.BEAR_RSI_OVERSOLD,
                    "rsi_overbought": cfg.BEAR_RSI_OVERBOUGHT,
                    "w_rsi": cfg.BEAR_WEIGHT_RSI, "w_trend": cfg.BEAR_WEIGHT_TREND,
                    "w_momentum": cfg.BEAR_WEIGHT_MOMENTUM, "w_bb": cfg.BEAR_WEIGHT_BB,
                    "w_vix": cfg.BEAR_WEIGHT_VIX, "w_macro": cfg.BEAR_WEIGHT_MACRO,
                    "composite_threshold": cfg.BEAR_COMPOSITE_THRESHOLD,
                }
                side = "SHORT"
            else:
                continue  # Skip SIDEWAYS for signal quality

            composite = strategy._compute_composite(side, bar_ts, rp)

            if composite >= rp["composite_threshold"]:
                # Signal fired — record it
                if side == "LONG":
                    signal_return = fwd_return
                else:
                    signal_return = -fwd_return  # Invert for shorts

                signal_records.append({
                    "date": bar_date,
                    "side": side,
                    "composite": composite,
                    "forward_return": signal_return,
                    "raw_return": fwd_return,
                })
        except Exception:
            pass

    # Aggregate to daily (use last bar of each day)
    regime_df = pd.DataFrame(regime_records)
    daily_regime = regime_df.groupby("date").last().reset_index()

    # Compute regime accuracy
    def regime_correct(row):
        if row["regime"] == "BULLISH":
            return row["forward_return"] > 0
        elif row["regime"] == "BEARISH":
            return row["forward_return"] < 0
        else:  # SIDEWAYS
            return abs(row["forward_return"]) < 0.5
        return False

    daily_regime["correct"] = daily_regime.apply(regime_correct, axis=1)

    # Per-regime stats
    regime_stats = {}
    for r in ["BULLISH", "BEARISH", "SIDEWAYS"]:
        subset = daily_regime[daily_regime["regime"] == r]
        if len(subset) > 0:
            regime_stats[r] = {
                "count": len(subset),
                "pct": len(subset) / len(daily_regime) * 100,
                "accuracy": subset["correct"].mean() * 100,
                "avg_fwd_return": subset["forward_return"].mean(),
            }
        else:
            regime_stats[r] = {"count": 0, "pct": 0, "accuracy": 0, "avg_fwd_return": 0}

    overall_accuracy = daily_regime["correct"].mean() * 100

    # Signal quality
    signal_df = pd.DataFrame(signal_records) if signal_records else pd.DataFrame()
    if len(signal_df) > 0:
        signal_hits = (signal_df["forward_return"] > 0).sum()
        signal_hit_rate = signal_hits / len(signal_df) * 100
        avg_signal_return = signal_df["forward_return"].mean()
        avg_hit_return = signal_df[signal_df["forward_return"] > 0]["forward_return"].mean() if signal_hits > 0 else 0
        avg_miss_return = signal_df[signal_df["forward_return"] <= 0]["forward_return"].mean() if len(signal_df) - signal_hits > 0 else 0
    else:
        signal_hit_rate = 0
        avg_signal_return = 0
        avg_hit_return = 0
        avg_miss_return = 0
        signal_hits = 0

    # Verdict
    if overall_accuracy > 50 and signal_hit_rate > 50:
        verdict = "PASS"
    elif overall_accuracy >= 45 or signal_hit_rate >= 45:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    # Print report
    print(f"\n{'='*60}")
    print(f"  OUT-OF-SAMPLE VALIDATION: Apr 2023 - Jan 2025")
    print(f"  Forward look: {forward_bars} hourly bars (~{forward_bars/8:.1f} trading days)")
    print(f"{'='*60}")

    print(f"\nRegime Classification ({len(daily_regime)} trading days):")
    for r in ["BULLISH", "BEARISH", "SIDEWAYS"]:
        s = regime_stats[r]
        print(f"  {r:10s}: {s['count']:3d} days ({s['pct']:.0f}%), "
              f"accuracy: {s['accuracy']:.1f}%, "
              f"avg fwd return: {s['avg_fwd_return']:+.2f}%")
    print(f"  {'Overall':10s}: accuracy: {overall_accuracy:.1f}%")

    print(f"\nSignal Quality ({len(signal_df)} signals fired):")
    print(f"  Hit rate: {signal_hit_rate:.1f}%")
    print(f"  Avg forward return: {avg_signal_return:+.3f}%")
    print(f"  Avg return on hits: {avg_hit_return:+.3f}%")
    print(f"  Avg return on misses: {avg_miss_return:+.3f}%")
    if len(signal_df) > 0:
        print(f"  LONG signals: {(signal_df['side'] == 'LONG').sum()}")
        print(f"  SHORT signals: {(signal_df['side'] == 'SHORT').sum()}")

    print(f"\n  VERDICT: {verdict}")
    print(f"{'='*60}")

    # Save results
    results = {
        "oos_period": "Apr 2023 - Jan 2025",
        "forward_bars": forward_bars,
        "trading_days": len(daily_regime),
        "overall_regime_accuracy_pct": round(overall_accuracy, 2),
        "regime_stats": {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in regime_stats.items()},
        "signal_count": len(signal_df),
        "signal_hit_rate_pct": round(signal_hit_rate, 2),
        "avg_signal_return_pct": round(avg_signal_return, 4),
        "avg_hit_return_pct": round(avg_hit_return, 4),
        "avg_miss_return_pct": round(avg_miss_return, 4),
        "verdict": verdict,
    }

    out_path = PROJECT_ROOT / "data" / "es" / "oos_validation_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OOS regime validation")
    parser.add_argument("--forward-bars", type=int, default=40,
                        help="Forward bars for return measurement (default: 40 hourly = ~5 trading days)")
    args = parser.parse_args()
    run_validation(forward_bars=args.forward_bars)
