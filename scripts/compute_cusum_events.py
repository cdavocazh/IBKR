#!/usr/bin/env python3
"""
CUSUM event filter for ES strategy entry timing.

Implements the CUSUM (Cumulative Sum) filter from Lopez de Prado's
"Advances in Financial Machine Learning" (Chapter 2).

Instead of fixed cooldown periods, CUSUM triggers entries only when
cumulative returns exceed a threshold — naturally adapting to market conditions:
- More entries during trending periods (large cumulative moves)
- Fewer entries during chop (moves cancel out)

Output: data/es/cusum_events.csv (timestamps where CUSUM triggered)

Usage:
    python scripts/compute_cusum_events.py
    python scripts/compute_cusum_events.py --threshold 0.005
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def cusum_filter(close: np.ndarray, timestamps: np.ndarray,
                  h: float = 0.005) -> list[dict]:
    """CUSUM filter for structural break detection.

    Monitors cumulative upward (S+) and downward (S-) deviations.
    Triggers an event when either exceeds threshold h.

    Args:
        close: Array of close prices
        timestamps: Array of timestamps
        h: Threshold for CUSUM trigger (as fraction of price, e.g., 0.005 = 0.5%)

    Returns:
        List of events with timestamp, direction, and magnitude
    """
    events = []
    s_pos = 0.0  # Cumulative positive deviation
    s_neg = 0.0  # Cumulative negative deviation

    for i in range(1, len(close)):
        # Log return
        ret = np.log(close[i] / close[i - 1])

        # Update cumulative sums
        s_pos = max(0, s_pos + ret)
        s_neg = min(0, s_neg + ret)

        # Check for event
        if s_pos > h:
            events.append({
                "timestamp": timestamps[i],
                "direction": "UP",
                "magnitude": s_pos,
                "bar_index": i,
            })
            s_pos = 0.0  # Reset after trigger

        elif s_neg < -h:
            events.append({
                "timestamp": timestamps[i],
                "direction": "DOWN",
                "magnitude": abs(s_neg),
                "bar_index": i,
            })
            s_neg = 0.0  # Reset after trigger

    return events


def adaptive_cusum_filter(close: np.ndarray, timestamps: np.ndarray,
                           h_base: float = 0.005,
                           vol_lookback: int = 100) -> list[dict]:
    """Volatility-adaptive CUSUM filter.

    Threshold scales with recent realized volatility:
    - Low vol periods: lower threshold (more sensitive)
    - High vol periods: higher threshold (less noise)
    """
    events = []
    s_pos = 0.0
    s_neg = 0.0

    for i in range(1, len(close)):
        ret = np.log(close[i] / close[i - 1])

        # Adaptive threshold based on recent volatility
        if i >= vol_lookback:
            recent_rets = np.diff(np.log(close[max(0, i - vol_lookback):i + 1]))
            vol = np.std(recent_rets) if len(recent_rets) > 1 else h_base
            h = max(h_base * 0.5, h_base * vol / 0.01)  # Scale relative to 1% vol baseline
        else:
            h = h_base

        s_pos = max(0, s_pos + ret)
        s_neg = min(0, s_neg + ret)

        if s_pos > h:
            events.append({
                "timestamp": timestamps[i],
                "direction": "UP",
                "magnitude": s_pos,
                "h_used": h,
                "bar_index": i,
            })
            s_pos = 0.0

        elif s_neg < -h:
            events.append({
                "timestamp": timestamps[i],
                "direction": "DOWN",
                "magnitude": abs(s_neg),
                "h_used": h,
                "bar_index": i,
            })
            s_neg = 0.0

    return events


def main():
    parser = argparse.ArgumentParser(description="CUSUM event filter")
    parser.add_argument("--threshold", type=float, default=0.003,
                        help="CUSUM threshold (default: 0.003 = 0.3%%)")
    parser.add_argument("--adaptive", action="store_true", default=True,
                        help="Use volatility-adaptive threshold")
    args = parser.parse_args()

    # Load 5-min data (same as backtest)
    data_path = PROJECT_ROOT / "data" / "es" / "ES_1min.parquet"
    df = pd.read_parquet(data_path)
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    has_range = (df_5m["high"] - df_5m["low"]) > 0
    has_volume = df_5m["volume"] > 0
    df_5m = df_5m[has_range | has_volume].copy()

    print(f"Loaded {len(df_5m)} 5-min bars")
    print(f"Date range: {df_5m.index[0]} to {df_5m.index[-1]}")

    close = df_5m["close"].values
    timestamps = df_5m.index.values

    if args.adaptive:
        print(f"\nRunning adaptive CUSUM filter (base h={args.threshold})...")
        events = adaptive_cusum_filter(close, timestamps, h_base=args.threshold)
    else:
        print(f"\nRunning fixed CUSUM filter (h={args.threshold})...")
        events = cusum_filter(close, timestamps, h=args.threshold)

    events_df = pd.DataFrame(events)
    print(f"Generated {len(events_df)} CUSUM events")

    if len(events_df) > 0:
        up_events = (events_df["direction"] == "UP").sum()
        down_events = (events_df["direction"] == "DOWN").sum()
        print(f"  UP events: {up_events}")
        print(f"  DOWN events: {down_events}")
        print(f"  Avg magnitude: {events_df['magnitude'].mean():.6f}")

        # Compute inter-event statistics
        if len(events_df) > 1:
            events_df["timestamp"] = pd.to_datetime(events_df["timestamp"])
            intervals = events_df["timestamp"].diff().dt.total_seconds() / 3600  # hours
            print(f"  Avg inter-event: {intervals.mean():.1f} hours")
            print(f"  Min inter-event: {intervals.min():.1f} hours")
            print(f"  Max inter-event: {intervals.max():.1f} hours")

        # Save
        out_path = PROJECT_ROOT / "data" / "es" / "cusum_events.csv"
        events_df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")

        # Also create a per-bar lookup (True/False for each 5-min bar)
        event_bars = set(events_df["bar_index"].values)
        cusum_signal = np.zeros(len(df_5m), dtype=int)
        cusum_direction = np.zeros(len(df_5m), dtype=int)
        for _, ev in events_df.iterrows():
            idx = int(ev["bar_index"])
            cusum_signal[idx] = 1
            cusum_direction[idx] = 1 if ev["direction"] == "UP" else -1

        lookup_df = pd.DataFrame({
            "timestamp": df_5m.index,
            "cusum_event": cusum_signal,
            "cusum_direction": cusum_direction,
        })
        lookup_path = PROJECT_ROOT / "data" / "es" / "cusum_bar_lookup.csv"
        lookup_df.to_csv(lookup_path, index=False)
        print(f"Saved bar-level lookup to {lookup_path}")
    else:
        print("No events generated — threshold may be too high")


if __name__ == "__main__":
    main()
