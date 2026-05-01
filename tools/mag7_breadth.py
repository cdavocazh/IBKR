#!/usr/bin/env python3
"""
MAG7 Mega-Cap Breadth Indicator for ES Trading (Phase 4 partial)

Computes breadth indicators across the MAG7 (and optional Top-20) mega caps —
the stocks that drive the bulk of S&P 500 daily moves. ES futures track these
closely, so MAG7 breadth often LEADS ES direction at the intraday timeframe.

Indicators emitted (per snapshot):
  - pct_above_5d_ma   : % of MAG7 trading above their 5-day SMA
  - pct_above_20d_ma  : % above 20-day SMA (medium-term breadth)
  - pct_above_50d_ma  : % above 50-day SMA (cycle breadth)
  - pct_green_today   : % positive on the day so far
  - mag7_eq_weight_chg: equal-weighted MAG7 % change vs prev close
  - mag7_market_chg   : market-cap-weighted MAG7 % change (proxy for SPX-top-7 contribution)
  - breadth_momentum  : (pct_above_5d_ma - pct_above_5d_ma_15min_ago)
  - leader_count      : # of MAG7 making new 20-day highs today
  - laggard_count     : # making new 20-day lows

Two modes:
  - Live (IBKR): pulls real-time bars via IBKR API on each call
  - Historical (yfinance): for backfill / backtest enrichment

Usage:
    python tools/mag7_breadth.py                     # Live snapshot via IBKR
    python tools/mag7_breadth.py --source yfinance   # yfinance fallback
    python tools/mag7_breadth.py --append-csv        # Append to data/es/mag7_breadth.csv
    python tools/mag7_breadth.py --backfill 30       # Backfill 30 days via yfinance

The CSV is consumed by autoresearch/verify_strategy.py via a `MAG7_BREADTH_WEIGHT`
config param (added in the Phase 4 backtest integration step).
"""
from __future__ import annotations

import argparse
import csv
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_CSV = PROJECT_ROOT / "data" / "es" / "mag7_breadth.csv"

# The 7 mega caps that move the S&P 500 most. Approximate SPX weights (Apr 2026):
MAG7 = [
    ("AAPL",  7.2),
    ("MSFT",  7.0),
    ("NVDA",  6.5),
    ("GOOGL", 4.0),  # Class A; we'll combine GOOG+GOOGL on the IBKR side if needed
    ("AMZN",  3.8),
    ("META",  2.5),
    ("TSLA",  1.8),
]

DEFAULT_PORTS = [4001, 4002, 7496, 7497]


# ─── yfinance source (historical / fallback) ─────────────────

def _snapshot_via_yfinance(symbols: list[str]) -> dict[str, dict]:
    """Return dict of symbol → {close, prev_close, sma_5, sma_20, sma_50,
    high_20, low_20}. Uses yfinance — handy for backfill and as fallback
    when IBKR isn't reachable."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    out = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False)
            if hist is None or hist.empty or len(hist) < 50:
                continue
            closes = hist["Close"].values
            highs = hist["High"].values
            lows = hist["Low"].values
            out[sym] = {
                "close": float(closes[-1]),
                "prev_close": float(closes[-2]),
                "sma_5":  float(closes[-5:].mean()),
                "sma_20": float(closes[-20:].mean()),
                "sma_50": float(closes[-50:].mean()),
                "high_20": float(highs[-20:].max()),
                "low_20":  float(lows[-20:].min()),
            }
        except Exception:
            continue
    return out


# ─── IBKR source (live) ──────────────────────────────────────

def _snapshot_via_ibkr(symbols: list[str], host: str = "127.0.0.1",
                      port: Optional[int] = None, client_id: int = 28) -> dict[str, dict]:
    """Use IBKR API to pull last 50 daily bars for each symbol."""
    try:
        from ib_async import IB, Stock
        IB_LIB = "ib_async"
    except ImportError:
        try:
            from ib_insync import IB, Stock
            IB_LIB = "ib_insync"
        except ImportError:
            return {}

    ports = [port] if port else DEFAULT_PORTS
    ib = None
    for p in ports:
        try:
            ib = IB()
            ib.connect(host, p, clientId=client_id, readonly=True, timeout=8)
            break
        except Exception:
            try:
                ib.disconnect()
            except Exception:
                pass
            ib = None
    if ib is None:
        return {}

    out = {}
    try:
        for sym in symbols:
            try:
                contract = Stock(sym, "SMART", "USD")
                qualified = ib.qualifyContracts(contract)
                if not qualified:
                    continue
                bars = ib.reqHistoricalData(
                    qualified[0],
                    endDateTime="",
                    durationStr="3 M",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                )
                if not bars or len(bars) < 50:
                    continue
                closes = [b.close for b in bars]
                highs = [b.high for b in bars]
                lows = [b.low for b in bars]
                out[sym] = {
                    "close": closes[-1],
                    "prev_close": closes[-2],
                    "sma_5":  sum(closes[-5:]) / 5,
                    "sma_20": sum(closes[-20:]) / 20,
                    "sma_50": sum(closes[-50:]) / 50,
                    "high_20": max(highs[-20:]),
                    "low_20":  min(lows[-20:]),
                }
            except Exception:
                continue
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
    return out


# ─── Breadth math ────────────────────────────────────────────

def compute_breadth(snapshots: dict[str, dict]) -> dict:
    """Aggregate per-symbol snapshots into MAG7 breadth indicators."""
    out = {"ts_utc": datetime.now(timezone.utc).isoformat()}
    if not snapshots:
        return {**out, "n_symbols": 0, "data_source": "none"}

    total = len(snapshots)
    above_5 = sum(1 for s in snapshots.values() if s["close"] > s["sma_5"])
    above_20 = sum(1 for s in snapshots.values() if s["close"] > s["sma_20"])
    above_50 = sum(1 for s in snapshots.values() if s["close"] > s["sma_50"])
    green = sum(1 for s in snapshots.values() if s["close"] > s["prev_close"])
    new_high = sum(1 for s in snapshots.values() if s["close"] >= s["high_20"])
    new_low = sum(1 for s in snapshots.values() if s["close"] <= s["low_20"])

    out["n_symbols"] = total
    out["pct_above_5d_ma"] = round(above_5 / total, 4)
    out["pct_above_20d_ma"] = round(above_20 / total, 4)
    out["pct_above_50d_ma"] = round(above_50 / total, 4)
    out["pct_green_today"] = round(green / total, 4)
    out["leader_count"] = new_high
    out["laggard_count"] = new_low

    # Equal-weighted % change
    eq_chgs = []
    weighted_chgs = []
    weights_sum = 0.0
    for sym, s in snapshots.items():
        chg = (s["close"] - s["prev_close"]) / s["prev_close"] if s["prev_close"] else 0.0
        eq_chgs.append(chg)
        weight = next((w for sym2, w in MAG7 if sym2 == sym), 1.0)
        weighted_chgs.append(chg * weight)
        weights_sum += weight
    out["mag7_eq_weight_chg"] = round(sum(eq_chgs) / total, 5) if eq_chgs else 0.0
    out["mag7_market_chg"] = round(sum(weighted_chgs) / weights_sum, 5) if weights_sum else 0.0

    return out


def compute_breadth_momentum(latest_csv_path: Path = OUTPUT_CSV,
                             current: Optional[dict] = None,
                             lookback_min: int = 15) -> Optional[float]:
    """Look back in the CSV for a row from ~lookback_min ago.
    Return delta in pct_above_5d_ma. None if insufficient history."""
    if not latest_csv_path.exists() or current is None:
        return None
    try:
        with latest_csv_path.open() as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        cur_ts = datetime.fromisoformat(current["ts_utc"])
        target = cur_ts - timedelta(minutes=lookback_min)
        # find closest row with ts <= target
        candidate = None
        for r in reversed(rows):
            try:
                rts = datetime.fromisoformat(r["ts_utc"])
            except ValueError:
                continue
            if rts <= target:
                candidate = r
                break
        if candidate is None:
            return None
        prev_pct = float(candidate.get("pct_above_5d_ma", 0) or 0)
        cur_pct = current.get("pct_above_5d_ma", 0)
        return round(cur_pct - prev_pct, 4)
    except Exception:
        return None


# ─── CSV append ──────────────────────────────────────────────

def append_csv(row: dict, csv_path: Path = OUTPUT_CSV):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "ts_utc", "data_source", "n_symbols",
        "pct_above_5d_ma", "pct_above_20d_ma", "pct_above_50d_ma",
        "pct_green_today", "leader_count", "laggard_count",
        "mag7_eq_weight_chg", "mag7_market_chg",
        "breadth_momentum_15m",
    ]
    file_exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerow(row)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MAG7 mega-cap breadth indicator for ES")
    parser.add_argument("--source", choices=["ibkr", "yfinance", "auto"], default="auto",
                        help="Data source. 'auto' = try IBKR, fall back to yfinance")
    parser.add_argument("--port", type=int, default=None, help="IBKR port override")
    parser.add_argument("--client-id", type=int,
                        default=int(os.environ.get("IB_BREADTH_CLIENT_ID", "28")),
                        help="IBKR client ID (default 28 — reserved for breadth)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (default: MAG7)")
    parser.add_argument("--append-csv", action="store_true")
    parser.add_argument("--csv", type=str, default=str(OUTPUT_CSV))
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else [m for m, _ in MAG7]

    snaps = {}
    source_used = None
    if args.source in ("ibkr", "auto"):
        snaps = _snapshot_via_ibkr(symbols, port=args.port, client_id=args.client_id)
        if snaps:
            source_used = "ibkr"
    if not snaps and args.source in ("yfinance", "auto"):
        snaps = _snapshot_via_yfinance(symbols)
        if snaps:
            source_used = "yfinance"
    if not snaps:
        print("ERROR: Could not fetch data from any source")
        sys.exit(2)

    row = compute_breadth(snaps)
    row["data_source"] = source_used
    momentum = compute_breadth_momentum(Path(args.csv), row, lookback_min=15)
    row["breadth_momentum_15m"] = momentum

    print(f"  source={source_used}  n={row['n_symbols']}")
    print(f"  pct_above_5d_ma={row.get('pct_above_5d_ma')}")
    print(f"  pct_above_20d_ma={row.get('pct_above_20d_ma')}")
    print(f"  pct_green_today={row.get('pct_green_today')}")
    print(f"  mag7_market_chg={row.get('mag7_market_chg')}")
    print(f"  leader/laggard={row.get('leader_count')}/{row.get('laggard_count')}")
    print(f"  breadth_momentum_15m={momentum}")

    if args.append_csv:
        append_csv(row, csv_path=Path(args.csv))
        print(f"  → appended to {args.csv}")


if __name__ == "__main__":
    main()
