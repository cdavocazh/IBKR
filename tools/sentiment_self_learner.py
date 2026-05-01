#!/usr/bin/env python3
"""
Online Lexicon Weight Learner (Phase 5A — Self-Learning Layer A)

Updates the keyword weights used by `tools/news_sentiment_nlp.py::classify_macro_sentiment`
based on how each keyword's appearance correlates with subsequent ES forward returns.

Approach (lightweight; runs nightly):
  1. Read the past 30 days of intraday sentiment buckets (from sentiment_intraday.csv).
  2. For each historical 15-min bucket, look up which BEARISH/BULLISH keywords were dominant
     (top themes column) and compute the forward 1-hour ES return.
  3. Per-keyword regression: forward_return ~ keyword_appearance_count
  4. Smoothly update weights (EMA blend with prior weights) into
     data/news/keyword_weights.json.
  5. news_sentiment_nlp.py reads from this JSON when present, else falls back
     to the hardcoded constants. (Wiring for that read happens in Phase 5A integration.)

Why "online": weights drift as the macro narrative changes. "Tariff" might be
weakly bearish in 2024 but strongly bearish during a 2026 trade war.

Usage:
    python tools/sentiment_self_learner.py --window-days 30 --update
    python tools/sentiment_self_learner.py --report-only        # No file write

Cron (VPS):
    OnCalendar=*-*-* 04:00:00   # daily at 4 AM UTC
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.news_sentiment_nlp import (  # noqa: E402
    BEARISH_MACRO_KEYWORDS,
    BULLISH_MACRO_KEYWORDS,
)

WEIGHTS_JSON = PROJECT_ROOT / "data" / "news" / "keyword_weights.json"
INTRADAY_CSV = PROJECT_ROOT / "data" / "news" / "sentiment_intraday.csv"
ES_5MIN_PARQUET = PROJECT_ROOT / "data" / "es" / "ES_combined_5min.parquet"

# How aggressively to update (EMA decay). 0.1 = slow, 0.5 = fast.
DEFAULT_LR = 0.20
# Prior weights anchor — keep this fraction of old weight even when learning rate is high
WEIGHT_FLOOR = 0.05
# Saturate updates (per-step max delta)
MAX_DELTA_PER_RUN = 0.30
# Forward-return horizon for the regression target
FORWARD_RETURN_BARS = 12  # 12 × 5-min bars = 1 hour


# ─── Data loading ────────────────────────────────────────────

def _load_es_5min() -> Optional[pd.DataFrame]:
    if not ES_5MIN_PARQUET.exists():
        print(f"WARNING: {ES_5MIN_PARQUET} missing — cannot compute forward returns",
              file=sys.stderr)
        return None
    df = pd.read_parquet(ES_5MIN_PARQUET)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df = df.sort_index()
    return df


def _load_intraday_buckets(window_days: int) -> pd.DataFrame:
    """Load last N days of intraday sentiment buckets."""
    if not INTRADAY_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(INTRADAY_CSV)
    df["bucket_ts"] = pd.to_datetime(df["bucket_ts"], utc=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    df = df[df["bucket_ts"] >= cutoff].copy()
    return df


def _forward_return(es_df: pd.DataFrame, ts_utc, n_bars: int = FORWARD_RETURN_BARS) -> Optional[float]:
    """Lookup forward N-bar return on the ES 5-min series at ts_utc."""
    if es_df is None or es_df.empty:
        return None
    ts_naive = ts_utc.replace(tzinfo=None) if ts_utc.tzinfo else ts_utc
    # Find next bar at or after ts_naive
    idx = es_df.index.searchsorted(ts_naive)
    if idx >= len(es_df) - n_bars:
        return None
    p_now = es_df.iloc[idx]["close"]
    p_fwd = es_df.iloc[idx + n_bars]["close"]
    if p_now <= 0:
        return None
    return (p_fwd - p_now) / p_now


# ─── Weight update ───────────────────────────────────────────

def load_current_weights() -> dict:
    """Return current weights — from JSON if present, else from constants."""
    if WEIGHTS_JSON.exists():
        try:
            with WEIGHTS_JSON.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": 0,
        "updated_at": None,
        "bearish": dict(BEARISH_MACRO_KEYWORDS),
        "bullish": dict(BULLISH_MACRO_KEYWORDS),
        "training_metadata": {},
    }


def save_weights(weights: dict):
    WEIGHTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with WEIGHTS_JSON.open("w") as f:
        json.dump(weights, f, indent=2, default=str)


def _ema_update(old: float, new: float, lr: float) -> float:
    """EMA blend, with floor and per-step delta cap."""
    blended = (1 - lr) * old + lr * new
    delta = blended - old
    if abs(delta) > MAX_DELTA_PER_RUN:
        delta = math.copysign(MAX_DELTA_PER_RUN, delta)
        blended = old + delta
    return max(WEIGHT_FLOOR, min(1.0, blended))


def update_weights(window_days: int = 30, lr: float = DEFAULT_LR,
                   dry_run: bool = False) -> dict:
    """Compute per-keyword regression coefficients and EMA-update the weights."""
    print(f"[learner] Loading last {window_days} days of buckets...", flush=True)
    df = _load_intraday_buckets(window_days)
    if df.empty:
        print("[learner] No intraday sentiment data yet — nothing to learn.", flush=True)
        return load_current_weights()

    es_df = _load_es_5min()
    if es_df is None:
        print("[learner] No ES 5-min data — cannot compute forward returns.", flush=True)
        return load_current_weights()

    # Per-keyword: collect (occurrences_in_bucket, forward_return) pairs
    # We use the themes_top5_24h column which already has the dominant keywords
    bear_obs: dict[str, list[tuple[int, float]]] = defaultdict(list)
    bull_obs: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for _, row in df.iterrows():
        ts = row["bucket_ts"].to_pydatetime()
        fwd_ret = _forward_return(es_df, ts)
        if fwd_ret is None:
            continue
        themes = str(row.get("themes_top5_24h", "") or "")
        if not themes:
            continue
        # Themes format from sentiment_intraday.py: pipe-separated keyword tokens
        kws = [t.strip().lower() for t in themes.split("|") if t.strip()]
        for kw in kws:
            # Match against current lexicon (substring matching, since keywords are phrases)
            for bear_kw in BEARISH_MACRO_KEYWORDS:
                if bear_kw.lower() in kw:
                    bear_obs[bear_kw].append((1, fwd_ret))
            for bull_kw in BULLISH_MACRO_KEYWORDS:
                if bull_kw.lower() in kw:
                    bull_obs[bull_kw].append((1, fwd_ret))

    current = load_current_weights()
    new_weights = {
        "version": current.get("version", 0) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "bearish": dict(current.get("bearish", BEARISH_MACRO_KEYWORDS)),
        "bullish": dict(current.get("bullish", BULLISH_MACRO_KEYWORDS)),
        "training_metadata": {
            "window_days": window_days,
            "n_buckets": len(df),
            "lr": lr,
        },
    }

    # Per-keyword update: target weight = abs(mean fwd return × sign correctness)
    bear_updates = []
    for kw, obs in bear_obs.items():
        if len(obs) < 5:
            continue
        # Bearish keyword: should correlate with NEGATIVE forward returns
        rets = [r for _, r in obs]
        mean_ret = sum(rets) / len(rets)
        # Sign match: keyword bearish, forward return negative → reinforce
        sign_match_score = max(0.0, -mean_ret * 100)  # convert to bps
        # Map to a target weight in [WEIGHT_FLOOR, 1.0]
        target = min(1.0, sign_match_score / 5.0)  # 5 bps fwd loss = full weight
        old_weight = new_weights["bearish"].get(kw, 0.5)
        new_weight = _ema_update(old_weight, target, lr)
        new_weights["bearish"][kw] = round(new_weight, 4)
        bear_updates.append((kw, old_weight, new_weight, mean_ret * 100, len(obs)))

    bull_updates = []
    for kw, obs in bull_obs.items():
        if len(obs) < 5:
            continue
        rets = [r for _, r in obs]
        mean_ret = sum(rets) / len(rets)
        # Bullish keyword: should correlate with POSITIVE forward returns
        sign_match_score = max(0.0, mean_ret * 100)
        target = min(1.0, sign_match_score / 5.0)
        old_weight = new_weights["bullish"].get(kw, 0.5)
        new_weight = _ema_update(old_weight, target, lr)
        new_weights["bullish"][kw] = round(new_weight, 4)
        bull_updates.append((kw, old_weight, new_weight, mean_ret * 100, len(obs)))

    # Print top movers
    bear_updates.sort(key=lambda t: abs(t[2] - t[1]), reverse=True)
    bull_updates.sort(key=lambda t: abs(t[2] - t[1]), reverse=True)
    print(f"\n[learner] Top BEARISH keyword updates (n_buckets={len(df)}):")
    print(f"  {'keyword':<28} {'old':>6} → {'new':>6}  fwd_ret_bps={'mean':>7}  obs={'n':>4}")
    for kw, old, new, mean_bps, n in bear_updates[:10]:
        print(f"  {kw:<28} {old:>6.3f} → {new:>6.3f}  {mean_bps:>14.2f}  {n:>5}")
    print(f"\n[learner] Top BULLISH keyword updates:")
    print(f"  {'keyword':<28} {'old':>6} → {'new':>6}  fwd_ret_bps={'mean':>7}  obs={'n':>4}")
    for kw, old, new, mean_bps, n in bull_updates[:10]:
        print(f"  {kw:<28} {old:>6.3f} → {new:>6.3f}  {mean_bps:>14.2f}  {n:>5}")

    if not dry_run:
        save_weights(new_weights)
        print(f"\n[learner] Saved → {WEIGHTS_JSON} (version {new_weights['version']})", flush=True)
    else:
        print(f"\n[learner] --report-only — weights NOT saved", flush=True)

    return new_weights


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Online lexicon weight learner")
    parser.add_argument("--window-days", type=int, default=30,
                        help="Lookback window (default 30 days)")
    parser.add_argument("--lr", type=float, default=DEFAULT_LR,
                        help="EMA learning rate (default 0.20)")
    parser.add_argument("--report-only", action="store_true",
                        help="Print updates but don't write keyword_weights.json")
    parser.add_argument("--show-current", action="store_true",
                        help="Print current weights and exit")
    args = parser.parse_args()

    if args.show_current:
        print(json.dumps(load_current_weights(), indent=2, default=str))
        return

    update_weights(window_days=args.window_days, lr=args.lr, dry_run=args.report_only)


if __name__ == "__main__":
    main()
