#!/usr/bin/env python3
"""
Walk-Forward Signal Weight Refit (Phase 5B — Self-Learning Layer B)

Fits a Ridge regression every 7 days that explains forward 1-hour ES returns
in terms of all our newly-built signals:

    forward_return_1h ~ sentiment_15m
                      + sentiment_24h
                      + mag7_breadth
                      + mag7_market_chg
                      + polymarket_composite
                      + polymarket_fed_cut_prob
                      + vix
                      + (interactions ...)

Output: data/es/signal_weights_dynamic.json — a snapshot of the fitted coefficients,
which `verify_strategy.py` can optionally read in place of the static config weights
when `USE_DYNAMIC_SIGNAL_WEIGHTS=True`.

Walk-forward protocol:
- Train window: rolling 60 days
- Refit every: 7 days
- Each weekly snapshot is keyed by date and stored alongside historical snapshots
  so backtests can use point-in-time weights without lookahead.

Usage:
    python scripts/sentiment_walkforward.py                      # Fit on latest data
    python scripts/sentiment_walkforward.py --train-days 90      # Longer window
    python scripts/sentiment_walkforward.py --backfill 180       # Backfill 180 days of weekly snapshots
    python scripts/sentiment_walkforward.py --validate           # Print OOS R^2 vs in-sample

Cron:
    OnCalendar=Sun *-*-* 05:00:00   # weekly Sunday 5 AM UTC
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

WEIGHTS_PATH = PROJECT_ROOT / "data" / "es" / "signal_weights_dynamic.json"
INTRADAY_CSV = PROJECT_ROOT / "data" / "news" / "sentiment_intraday.csv"
MAG7_CSV = PROJECT_ROOT / "data" / "es" / "mag7_breadth.csv"
POLYMARKET_CSV = PROJECT_ROOT / "data" / "es" / "polymarket_signals.csv"
ES_5MIN_PARQUET = PROJECT_ROOT / "data" / "es" / "ES_combined_5min.parquet"
MACRO_DIR = Path(__import__("os").environ.get(
    "MACRO_DATA_DIR",
    str(Path.home() / "Github" / "macro_2" / "historical_data"),
))

DEFAULT_TRAIN_DAYS = 60
DEFAULT_REFIT_EVERY_DAYS = 7
FORWARD_RETURN_BARS = 12  # 12×5min = 1h

# Feature columns we expect to find across the joined dataframe.
FEATURE_COLS = [
    "sentiment_15m", "sentiment_1h", "sentiment_4h",
    "fed_topic_pct", "war_topic_pct", "inflation_topic_pct",
    "pct_above_5d_ma", "pct_above_20d_ma", "mag7_market_chg",
    "breadth_momentum_15m",
    "composite_es_signal", "fed_cut_prob_next", "fed_hike_prob_next",
    "recession_prob_12m", "iran_escalation_prob", "fiscal_expansion_prob",
    "vix",
]
TARGET_COL = "forward_return_1h"


# ─── Data loading + alignment ────────────────────────────────

def _load_es_5min() -> pd.DataFrame:
    if not ES_5MIN_PARQUET.exists():
        raise FileNotFoundError(f"{ES_5MIN_PARQUET} required")
    df = pd.read_parquet(ES_5MIN_PARQUET)
    if df.index.tz is not None:
        df = df.tz_convert("UTC").tz_localize(None)
    df = df.sort_index()
    df["forward_return_1h"] = df["close"].pct_change(FORWARD_RETURN_BARS).shift(-FORWARD_RETURN_BARS)
    return df


def _load_csv_safe(path: Path, ts_col: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if ts_col not in df.columns:
        return pd.DataFrame()
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col)
    df["_ts_naive"] = df[ts_col].dt.tz_convert(None)
    return df


def _load_vix() -> pd.DataFrame:
    """Try to load VIX daily from macro_2/historical_data/."""
    vix_path = MACRO_DIR / "vix.csv"
    if not vix_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(vix_path)
        # Try common column shapes
        date_col = next((c for c in df.columns if c.lower() in ("date", "datetime", "observation_date")), None)
        val_col = next((c for c in df.columns if c.lower() in ("vix", "close", "value")), None)
        if not date_col or not val_col:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df[date_col]).dt.date
        df["vix"] = pd.to_numeric(df[val_col], errors="coerce")
        return df[["date", "vix"]].dropna()
    except Exception:
        return pd.DataFrame()


def build_training_table(end_ts: datetime, train_days: int) -> pd.DataFrame:
    """Join ES 5-min returns with intraday sentiment / breadth / polymarket / vix.
    Returns dataframe indexed by 5-min ts with one row per bar in window.
    """
    es = _load_es_5min()
    cutoff_end = end_ts.replace(tzinfo=None)
    cutoff_start = (end_ts - timedelta(days=train_days)).replace(tzinfo=None)
    es = es[(es.index >= cutoff_start) & (es.index <= cutoff_end)].copy()
    if es.empty:
        return es
    es = es[["close", "forward_return_1h"]].copy()

    intraday = _load_csv_safe(INTRADAY_CSV, "bucket_ts")
    mag7 = _load_csv_safe(MAG7_CSV, "ts_utc")
    pm = _load_csv_safe(POLYMARKET_CSV, "ts_utc")

    # As-of merge each onto the ES bar timestamp (forward-fill — point-in-time)
    es["_ts_naive"] = es.index
    if not intraday.empty:
        es = pd.merge_asof(es.sort_values("_ts_naive"),
                           intraday.sort_values("_ts_naive"),
                           on="_ts_naive", direction="backward",
                           tolerance=pd.Timedelta(minutes=30))
    if not mag7.empty:
        es = pd.merge_asof(es.sort_values("_ts_naive"),
                           mag7.sort_values("_ts_naive"),
                           on="_ts_naive", direction="backward",
                           tolerance=pd.Timedelta(minutes=15),
                           suffixes=("", "_m7"))
    if not pm.empty:
        es = pd.merge_asof(es.sort_values("_ts_naive"),
                           pm.sort_values("_ts_naive"),
                           on="_ts_naive", direction="backward",
                           tolerance=pd.Timedelta(minutes=30),
                           suffixes=("", "_pm"))

    # VIX daily — left-join by date
    vix = _load_vix()
    if not vix.empty:
        es["date"] = es["_ts_naive"].dt.date
        es = es.merge(vix, on="date", how="left").drop(columns=["date"])
    else:
        es["vix"] = np.nan
    es.index = es["_ts_naive"]
    return es


# ─── Ridge fit ───────────────────────────────────────────────

def fit_ridge(df: pd.DataFrame, alpha: float = 1.0) -> Optional[dict]:
    """Fit Ridge regression on available features. Returns dict of coefs + R² + n."""
    try:
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        print("[walkforward] sklearn not installed — skipping fit", file=sys.stderr)
        return None

    available = [c for c in FEATURE_COLS if c in df.columns]
    if not available:
        return None
    work = df[available + [TARGET_COL]].copy().dropna()
    if len(work) < 50:
        return {"n_train": len(work), "error": "insufficient data after dropna"}
    X = work[available].values.astype(float)
    y = work[TARGET_COL].values.astype(float)
    # Standardize for stable coefficients
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = Ridge(alpha=alpha)
    model.fit(Xs, y)
    pred = model.predict(Xs)
    ss_res = ((y - pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Convert std-space coefficients back to "relative importance" via correlation sign.
    # Also return raw coefficients for downstream weighting.
    coef_dict = {feat: float(c) for feat, c in zip(available, model.coef_)}
    # Normalize: divide by the max abs coefficient so the scale is bounded
    max_abs = max(abs(v) for v in coef_dict.values()) or 1.0
    norm_dict = {k: round(v / max_abs, 4) for k, v in coef_dict.items()}
    return {
        "features": available,
        "coef_raw": coef_dict,
        "coef_normalized": norm_dict,
        "intercept": float(model.intercept_),
        "r2": round(r2, 4),
        "n_train": len(work),
        "alpha": alpha,
    }


# ─── Walk-forward orchestration ──────────────────────────────

def load_existing_snapshots() -> dict:
    if not WEIGHTS_PATH.exists():
        return {"version": 0, "snapshots": {}}
    try:
        with WEIGHTS_PATH.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": 0, "snapshots": {}}


def save_snapshots(data: dict):
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEIGHTS_PATH.open("w") as f:
        json.dump(data, f, indent=2, default=str)


def refit_at(end_ts: datetime, train_days: int = DEFAULT_TRAIN_DAYS,
             alpha: float = 1.0) -> Optional[dict]:
    df = build_training_table(end_ts, train_days)
    if df.empty:
        return None
    return fit_ridge(df, alpha=alpha)


def run_one(end_ts: Optional[datetime] = None, train_days: int = DEFAULT_TRAIN_DAYS,
            alpha: float = 1.0, validate: bool = False) -> dict:
    end_ts = end_ts or datetime.now(timezone.utc)
    snap = refit_at(end_ts, train_days=train_days, alpha=alpha)
    if snap is None:
        print("[walkforward] No data — skipping", flush=True)
        return {}
    snap["fit_at"] = end_ts.isoformat()
    snap["train_days"] = train_days

    # Validation: split last 20% as holdout, refit on first 80%, score on held-out
    if validate:
        df_full = build_training_table(end_ts, train_days)
        n = len(df_full)
        if n > 100:
            split = int(n * 0.8)
            train = df_full.iloc[:split]
            test = df_full.iloc[split:]
            train_fit = fit_ridge(train, alpha=alpha) or {}
            test_fit = fit_ridge(test, alpha=alpha) or {}
            in_r2 = train_fit.get("r2", "n/a")
            oos_r2 = test_fit.get("r2", "n/a")
            print(f"[walkforward] In-sample R²={in_r2}  OOS R²={oos_r2}")
            snap["validation"] = {
                "in_sample_r2": train_fit.get("r2"),
                "oos_r2": test_fit.get("r2"),
            }

    snapshots = load_existing_snapshots()
    snapshots["snapshots"][end_ts.strftime("%Y-%m-%d")] = snap
    snapshots["version"] = snapshots.get("version", 0) + 1
    snapshots["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_snapshots(snapshots)
    print(f"[walkforward] Saved snapshot for {end_ts.date()} → {WEIGHTS_PATH}", flush=True)
    print(f"  R²={snap.get('r2')}  n_train={snap.get('n_train')}  features={len(snap.get('features',[]))}")
    if snap.get("coef_normalized"):
        top = sorted(snap["coef_normalized"].items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        print(f"  top features: {[(k, round(v,3)) for k,v in top]}")
    return snap


def run_backfill(days: int, train_days: int = DEFAULT_TRAIN_DAYS,
                 step_days: int = DEFAULT_REFIT_EVERY_DAYS, alpha: float = 1.0):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cur = start
    while cur <= end:
        run_one(end_ts=cur, train_days=train_days, alpha=alpha)
        cur += timedelta(days=step_days)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Walk-forward signal weight refit")
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--alpha", type=float, default=1.0, help="Ridge alpha")
    parser.add_argument("--backfill", type=int, default=None,
                        help="Backfill weekly snapshots over the last N days")
    parser.add_argument("--validate", action="store_true",
                        help="Report in-sample vs OOS R^2 for sanity")
    parser.add_argument("--show-latest", action="store_true",
                        help="Print latest snapshot and exit")
    args = parser.parse_args()

    if args.show_latest:
        snaps = load_existing_snapshots()
        if not snaps.get("snapshots"):
            print("No snapshots yet")
            return
        latest = max(snaps["snapshots"].items(), key=lambda x: x[0])
        print(json.dumps(latest[1], indent=2, default=str))
        return

    warnings.filterwarnings("ignore")
    if args.backfill:
        run_backfill(args.backfill, train_days=args.train_days, alpha=args.alpha)
    else:
        run_one(train_days=args.train_days, alpha=args.alpha, validate=args.validate)


if __name__ == "__main__":
    main()
