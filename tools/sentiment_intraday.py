#!/usr/bin/env python3
"""
15-minute Rolling Sentiment Aggregator (Phase 2)

Reads headlines from data/news/headlines.db (populated by news_stream_continuous.py)
and computes rolling sentiment over multiple windows aligned to 15-min buckets:
  - 15min, 30min, 1hr, 4hr, 24hr lookbacks

Each call appends one row per bucket to data/news/sentiment_intraday.csv,
giving the backtest a high-frequency sentiment signal time-aligned to ES bars.

Reuses tools/news_sentiment_nlp.py — same scoring functions used by run_sentiment.py.
This module just changes the time-windowing.

Typical invocation (every 15 min via cron/systemd timer):
    python tools/sentiment_intraday.py --bucket-now

Backfill historical buckets (after streamer has been running for a while):
    python tools/sentiment_intraday.py --since 2026-05-01 --until 2026-05-02

Returns dict and writes to CSV.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.news_sentiment_nlp import analyze_headline  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "news" / "headlines.db"
CSV_PATH = PROJECT_ROOT / "data" / "news" / "sentiment_intraday.csv"

# Windows we compute, in minutes
WINDOWS_MIN = [15, 30, 60, 240, 1440]  # 15m, 30m, 1h, 4h, 24h


# ─── Macro topic detection (lightweight, on top of analyzed headline) ───

FED_KEYWORDS = ["fed", "fomc", "powell", "rate cut", "rate hike", "interest rate",
                "monetary policy", "jerome powell", "central bank", "hawkish", "dovish"]
WAR_KEYWORDS = ["war", "iran", "ukraine", "russia", "israel", "missile", "strike",
                "military", "invasion", "ceasefire", "geopolitical", "tensions"]
INFLATION_KEYWORDS = ["cpi", "inflation", "ppi", "core pce", "pce", "deflation",
                      "stagflation", "consumer prices"]
EARNINGS_KEYWORDS = ["earnings", "eps", "guidance", "revenue beat", "revenue miss",
                     "beat estimates", "missed estimates"]


def _topic_pct(headlines: list[str], keywords: list[str]) -> float:
    """% of headlines mentioning any of the topic keywords (case-insensitive)."""
    if not headlines:
        return 0.0
    n = sum(1 for h in headlines if any(kw in h.lower() for kw in keywords))
    return round(n / len(headlines), 4)


# ─── DB read ─────────────────────────────────────────────────

def _fetch_headlines(end_ts: datetime, window_min: int, db_path: Path = DB_PATH) -> list[dict]:
    """Read headlines from SQLite in [end_ts - window_min, end_ts]."""
    if not db_path.exists():
        return []
    start_ts = end_ts - timedelta(minutes=window_min)
    # published_at is ISO string; lexicographic compare works for ISO-8601
    start_iso = start_ts.isoformat()
    end_iso = end_ts.isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT article_id, published_at, provider, ticker, headline, keywords
              FROM headlines
             WHERE published_at >= ?
               AND published_at <= ?
            """,
            (start_iso, end_iso),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "articleId": r["article_id"],
            "headline": r["headline"],
            "provider": r["provider"],
            "time": r["published_at"],
            "ticker": r["ticker"] or "",
            "metadata": {"keywords": r["keywords"]},
        }
        for r in rows
    ]


# ─── Aggregation ─────────────────────────────────────────────

def aggregate_bucket(end_ts: datetime, db_path: Path = DB_PATH) -> dict:
    """Compute sentiment metrics across all configured windows ending at end_ts.

    Returns a single dict with one set of columns per window, ready for CSV.
    """
    out = {
        "bucket_ts": end_ts.replace(microsecond=0).isoformat(),
    }
    # 24h headlines drive topic % (cheaper than re-fetching for each window)
    cached_24h = None
    for win in WINDOWS_MIN:
        headlines = _fetch_headlines(end_ts, win, db_path=db_path)
        if win == 1440:
            cached_24h = headlines
        analyzed = [analyze_headline(h) for h in headlines] if headlines else []

        if not analyzed:
            net_sent = 0.0
            bull = bear = neut = 0
            dom_cat = "none"
            top_themes = []
        else:
            # Net sentiment weighted by actionability (matches get_regime_signal logic)
            weights = [max(0.1, a.get("actionability", 0.5)) for a in analyzed]
            scores = [a["sentiment"]["score"] for a in analyzed]
            net_sent = round(sum(s * w for s, w in zip(scores, weights)) / sum(weights), 4)
            labels = Counter(a["sentiment"]["label"] for a in analyzed)
            bull = labels.get("bullish", 0)
            bear = labels.get("bearish", 0)
            neut = labels.get("neutral", 0)
            cats = Counter(a["macro_signal"]["category"] for a in analyzed
                           if a["macro_signal"]["category"] != "none")
            dom_cat = cats.most_common(1)[0][0] if cats else "none"
            # Top themes (bearish + bullish keywords)
            bear_kw = []
            bull_kw = []
            for a in analyzed:
                bear_kw.extend(a["macro_signal"].get("bearish_keywords", []))
                bull_kw.extend(a["macro_signal"].get("bullish_keywords", []))
            top_themes = [k for k, _ in Counter(bear_kw + bull_kw).most_common(5)]

        win_label = _win_label(win)
        out[f"sentiment_{win_label}"] = net_sent
        out[f"hl_count_{win_label}"] = len(analyzed)
        out[f"bull_count_{win_label}"] = bull
        out[f"bear_count_{win_label}"] = bear
        out[f"neut_count_{win_label}"] = neut
        if win == 1440:
            out["dominant_cat_24h"] = dom_cat
            out["themes_top5_24h"] = "|".join(top_themes)

    # Topic mix on the 24h horizon
    headlines_24h_text = [h["headline"] for h in (cached_24h or [])]
    out["fed_topic_pct"] = _topic_pct(headlines_24h_text, FED_KEYWORDS)
    out["war_topic_pct"] = _topic_pct(headlines_24h_text, WAR_KEYWORDS)
    out["inflation_topic_pct"] = _topic_pct(headlines_24h_text, INFLATION_KEYWORDS)
    out["earnings_topic_pct"] = _topic_pct(headlines_24h_text, EARNINGS_KEYWORDS)

    return out


def _win_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 1440:
        return f"{minutes // 60}h"
    return f"{minutes // 1440}d"


# ─── CSV output ──────────────────────────────────────────────

def append_csv(row: dict, csv_path: Path = CSV_PATH):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    # Stable column order
    columns = ["bucket_ts"]
    for win in WINDOWS_MIN:
        wl = _win_label(win)
        columns.extend([
            f"sentiment_{wl}",
            f"hl_count_{wl}",
            f"bull_count_{wl}",
            f"bear_count_{wl}",
            f"neut_count_{wl}",
        ])
    columns.extend(["dominant_cat_24h", "themes_top5_24h",
                    "fed_topic_pct", "war_topic_pct",
                    "inflation_topic_pct", "earnings_topic_pct"])

    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerow(row)


# ─── Bucket alignment ───────────────────────────────────────

def floor_to_15min(ts: datetime) -> datetime:
    minute = (ts.minute // 15) * 15
    return ts.replace(minute=minute, second=0, microsecond=0)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="15-min rolling ES sentiment aggregator")
    parser.add_argument("--bucket-now", action="store_true",
                        help="Compute the current 15-min bucket and append to CSV")
    parser.add_argument("--since", type=str, default=None,
                        help="Backfill from this UTC date (e.g. 2026-05-01)")
    parser.add_argument("--until", type=str, default=None,
                        help="Backfill until this UTC date")
    parser.add_argument("--db", type=str, default=str(DB_PATH))
    parser.add_argument("--csv", type=str, default=str(CSV_PATH))
    parser.add_argument("--print-only", action="store_true",
                        help="Print the row but don't write CSV")
    args = parser.parse_args()

    db_path = Path(args.db)
    csv_path = Path(args.csv)

    if args.since and args.until:
        # Backfill mode — iterate in 15-min steps
        start = floor_to_15min(datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc))
        end = floor_to_15min(datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc))
        cur = start
        n_written = 0
        while cur <= end:
            row = aggregate_bucket(cur, db_path=db_path)
            if not args.print_only:
                append_csv(row, csv_path=csv_path)
            n_written += 1
            cur += timedelta(minutes=15)
        print(f"Backfill complete: {n_written} buckets written to {csv_path}")
        return

    # Default: current bucket (suitable for cron --bucket-now)
    end_ts = floor_to_15min(datetime.now(timezone.utc))
    row = aggregate_bucket(end_ts, db_path=db_path)
    print(f"[{end_ts.isoformat()}] sentiment_15m={row.get('sentiment_15m')} "
          f"hl_count_15m={row.get('hl_count_15m')} "
          f"sentiment_24h={row.get('sentiment_1d')} "
          f"hl_count_24h={row.get('hl_count_1d')} "
          f"dominant={row.get('dominant_cat_24h')}")
    if not args.print_only:
        append_csv(row, csv_path=csv_path)
        print(f"  → appended to {csv_path}")


if __name__ == "__main__":
    main()
