#!/usr/bin/env python3
"""
One-Time BRFG Historical Headline Backfill
==========================================
Fetches as much headline history as IBKR will give for a list of tickers,
pages backward until the provider returns < 300 articles (exhausted),
and writes everything into data/news/headlines.db via tools/news_db.py.

Supported providers for deep backfill:
  BRFG    — Briefing.com (years of history)
  BRFUPDN — Briefing upgrades/downgrades (years of history)
  DJ-N    — Dow Jones (weeks to months; variable)

Run once after setting up the DB. The script is idempotent:
article_id PRIMARY KEY with INSERT OR IGNORE means re-runs are safe.

Usage:
    # Default: BRFG for top-50 S&P tickers + ES/GC/SI
    python scripts/backfill_headlines.py

    # Choose providers and tickers
    python scripts/backfill_headlines.py --providers BRFG,BRFUPDN --days-hint 365

    # Resume from where a prior run stopped (skip tickers already exhausted)
    python scripts/backfill_headlines.py --resume

    # Dry-run: show what would run, don't connect to IBKR
    python scripts/backfill_headlines.py --dry-run

    # Custom ticker file (one per line)
    python scripts/backfill_headlines.py --tickers-file my_tickers.txt

    # Single ticker quick-test
    python scripts/backfill_headlines.py --tickers AAPL --providers BRFG
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Default ticker universe ──────────────────────────────────────
# Top ~50 S&P 500 by market cap + key ETFs + futures you already track.
# Extend freely; IBKR rate limits (not this list) are the constraint.
DEFAULT_TICKERS = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "ADBE",
    "ORCL", "CRM", "INTC", "QCOM", "TXN", "NFLX", "NOW", "AMAT", "INTU", "MU",
    # Financials
    "JPM", "BAC", "GS", "WFC", "MS", "BLK", "C", "AXP", "PNC", "SPGI",
    "V", "MA",
    # Health / biotech
    "UNH", "LLY", "JNJ", "MRK", "ABBV", "TMO", "DHR", "GILD", "ISRG", "AMGN", "ZTS",
    # Industrials / energy
    "XOM", "CVX", "CAT", "GE", "HON", "RTX", "DE", "UPS", "LIN", "NEE",
    # Consumer / retail
    "WMT", "HD", "MCD", "COST", "KO", "PEP", "PG", "LOW",
    # Broad indices / ETFs (high news volume)
    "SPY", "QQQ", "IWM", "DIA", "XLE", "XLF", "XLK",
]

# Futures for which IBKR news is most relevant
DEFAULT_FUTURES = ["ES"]  # GC and SI generate fewer headlines; add if desired


# ── IBKR pacing constants ────────────────────────────────────────
# IBKR enforces ~6 historical-data requests per second globally.
# Being conservative: 0.4s between provider calls, 0.5s between tickers.
SLEEP_BETWEEN_PROVIDERS = 0.4   # seconds
SLEEP_BETWEEN_TICKERS   = 0.5   # seconds
SLEEP_BETWEEN_PAGES     = 0.6   # seconds (paginating backward within a ticker)
MAX_PER_REQUEST         = 300   # IBKR hard cap on reqHistoricalNews results


def connect_ibkr(port=None, client_id=97):
    """Connect to IBKR Gateway (auto-detect port)."""
    from ib_async import IB
    ib = IB()
    ports = [port] if port else [4001, 4002, 7496, 7497]
    for p in ports:
        try:
            ib.connect("127.0.0.1", p, clientId=client_id, readonly=True)
            label = {7496: "TWS Live", 7497: "TWS Paper", 4001: "GW Live", 4002: "GW Paper"}.get(p, f"port {p}")
            print(f"[IBKR] Connected to {label} (port {p})")
            return ib
        except Exception:
            continue
    print(f"[IBKR] ERROR: Could not connect on any of {ports}")
    return None


def qualify_stock(ib, ticker: str):
    """Qualify a ticker as a Stock contract."""
    from ib_async import Stock
    c = Stock(ticker, "SMART", "USD")
    q = ib.qualifyContracts(c)
    return q[0] if q else None


def qualify_future(ib, ticker: str):
    """Qualify a futures ticker with the nearest quarterly expiry."""
    from ib_async import Future
    now = datetime.now()
    for m in [3, 6, 9, 12]:
        if now.month <= m:
            front = f"{now.year}{m:02d}"
            break
    else:
        front = f"{now.year + 1}03"
    c = Future(ticker, lastTradeDateOrContractMonth=front, exchange="CME", currency="USD")
    q = ib.qualifyContracts(c)
    return q[0] if q else None


def parse_headline(raw: str) -> dict:
    """Strip IBKR metadata prefix from headline text."""
    meta, headline = {}, raw
    if raw.startswith("{"):
        sep = "}!" if "}!" in raw else ("}" if "}" in raw else None)
        if sep:
            parts = raw.split(sep, 1)
            meta_str = parts[0][1:]
            headline = parts[1] if len(parts) > 1 else raw
            tokens = meta_str.split(":")
            for i in range(0, len(tokens) - 1, 2):
                k, v = tokens[i], tokens[i + 1]
                if k == "C":
                    try:
                        meta["confidence"] = float(v)
                    except ValueError:
                        pass
                elif k == "K":
                    meta["keywords"] = v
    return {"headline": headline.strip(), "metadata": meta}


def fetch_all_pages(ib, con_id: int, provider: str, ticker: str, run_id: str) -> list[dict]:
    """
    Fetch ALL available headlines for (con_id, provider) by paging backward.
    Returns a flat list of headline dicts.
    """
    all_headlines = []
    seen_ids: set[str] = set()
    end_dt = ""   # empty = latest; will shrink each page

    page = 0
    while True:
        page += 1
        try:
            batch = ib.reqHistoricalNews(con_id, provider, "", end_dt, MAX_PER_REQUEST)
        except Exception as e:
            print(f"    [WARN] reqHistoricalNews failed for {ticker}/{provider}: {e}")
            break

        if not batch:
            break

        new_in_batch = 0
        oldest_time = None

        for h in batch:
            if h.articleId in seen_ids:
                continue
            seen_ids.add(h.articleId)
            parsed = parse_headline(h.headline)
            all_headlines.append({
                "articleId": h.articleId,
                "headline":  parsed["headline"],
                "provider":  h.providerCode,
                "time":      str(h.time),
                "ticker":    ticker,
                "metadata":  parsed["metadata"],
                "run_id":    run_id,
            })
            new_in_batch += 1
            t = str(h.time)
            if oldest_time is None or t < oldest_time:
                oldest_time = t

        print(f"    page {page}: +{new_in_batch} headlines (total={len(all_headlines)}, oldest={oldest_time})")

        # Stop if we got fewer than the cap → exhausted this provider's history
        if len(batch) < MAX_PER_REQUEST:
            print(f"    → Exhausted (returned {len(batch)} < {MAX_PER_REQUEST})")
            break

        # Advance end_dt to just before the oldest headline we saw
        if oldest_time:
            # IBKR expects format: "YYYY-MM-DD HH:MM:SS.0"
            try:
                dt = datetime.fromisoformat(oldest_time.replace("Z", "+00:00"))
                dt_back = dt - timedelta(seconds=1)
                end_dt = dt_back.strftime("%Y-%m-%d %H:%M:%S.0")
            except Exception:
                # If we can't parse the time, stop to avoid infinite loop
                break
        else:
            break

        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_headlines


def run_nlp_scoring(headlines: list[dict]) -> list[dict]:
    """
    Run the existing NLP engine over a batch of raw headlines.
    Returns the scored list (same format as analyze_headlines() output).
    """
    try:
        from tools.news_sentiment_nlp import analyze_headlines
        return analyze_headlines(headlines)
    except ImportError:
        print("    [WARN] news_sentiment_nlp not available — skipping NLP scoring")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Backfill IBKR news headlines into data/news/headlines.db",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[1] if "Usage:" in __doc__ else "",
    )
    parser.add_argument(
        "--providers", default="BRFG,BRFUPDN",
        help="Comma-separated providers to backfill (default: BRFG,BRFUPDN)",
    )
    parser.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers to override default list",
    )
    parser.add_argument(
        "--tickers-file", default="",
        help="Path to a text file with one ticker per line",
    )
    parser.add_argument(
        "--futures", default=",".join(DEFAULT_FUTURES),
        help=f"Comma-separated futures tickers (default: {','.join(DEFAULT_FUTURES)})",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="IBKR port (auto-detect if omitted)",
    )
    parser.add_argument(
        "--client-id", type=int, default=97,
        help="IBKR client ID (default: 97, avoid conflict with run_sentiment=98)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip (ticker, provider) pairs already marked exhausted in backfill_log",
    )
    parser.add_argument(
        "--score", action="store_true", default=True,
        help="Run NLP scoring on fetched headlines (default: True)",
    )
    parser.add_argument(
        "--no-score", dest="score", action="store_false",
        help="Skip NLP scoring (faster; score later with --score-only)",
    )
    parser.add_argument(
        "--score-only", action="store_true",
        help="Don't fetch new headlines; just score existing unscored rows in DB and exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would run without connecting to IBKR",
    )
    parser.add_argument(
        "--db", default="",
        help="Override DB path (default: data/news/headlines.db)",
    )

    args = parser.parse_args()

    # ── Resolve ticker list ──────────────────────────────────
    if args.tickers:
        stock_tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.tickers_file:
        stock_tickers = [
            line.strip().upper()
            for line in Path(args.tickers_file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    else:
        stock_tickers = DEFAULT_TICKERS

    futures_tickers = [t.strip().upper() for t in args.futures.split(",") if t.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    print(f"\n{'='*70}")
    print(f"  IBKR Headline Backfill")
    print(f"{'='*70}")
    print(f"  Stocks  : {len(stock_tickers)} tickers")
    print(f"  Futures : {futures_tickers}")
    print(f"  Providers: {providers}")
    print(f"  Resume  : {args.resume}")
    print(f"  Score   : {args.score}")
    print(f"  Dry-run : {args.dry_run}")
    print()

    # ── Open DB ──────────────────────────────────────────────
    from tools.news_db import NewsDB
    db_path = Path(args.db) if args.db else None
    db = NewsDB(db_path).connect()

    # ── Score-only mode ──────────────────────────────────────
    if args.score_only:
        print("[score-only] Loading unscored headlines from DB...")
        unscored = db.query(limit=100_000)
        unscored = [h for h in unscored if h.get("sentiment_label") is None]
        print(f"  {len(unscored)} unscored rows found")
        if unscored:
            analyzed = run_nlp_scoring(unscored)
            n = db.upsert_analyzed(analyzed)
            print(f"  Scored and updated {n} rows")
        db.close()
        return

    # ── Dry-run ───────────────────────────────────────────────
    if args.dry_run:
        print("[dry-run] Would backfill:")
        for ticker in stock_tickers:
            for prov in providers:
                print(f"  {ticker:8s} x {prov}")
        for ticker in futures_tickers:
            for prov in providers:
                print(f"  {ticker:8s} x {prov} (future)")
        stats = db.stats()
        print(f"\n[DB] Current stats: {stats}")
        db.close()
        return

    # ── Connect to IBKR ──────────────────────────────────────
    ib = connect_ibkr(port=args.port, client_id=args.client_id)
    if not ib:
        db.close()
        sys.exit(1)

    # ── Build exhausted-pairs set if --resume ─────────────────
    exhausted_pairs: set[tuple[str, str]] = set()
    if args.resume:
        conn = db._ensure_connected()
        rows = conn.execute(
            "SELECT ticker, provider FROM backfill_log WHERE exhausted=1"
        ).fetchall()
        exhausted_pairs = {(r[0], r[1]) for r in rows}
        print(f"[resume] Skipping {len(exhausted_pairs)} exhausted (ticker, provider) pairs\n")

    run_id = str(uuid.uuid4())
    total_inserted = 0
    total_scored   = 0

    # ── Process stocks ────────────────────────────────────────
    for i, ticker in enumerate(stock_tickers, 1):
        print(f"[{i}/{len(stock_tickers)}] {ticker}")

        contract = qualify_stock(ib, ticker)
        if not contract:
            print(f"  SKIP: could not qualify {ticker}")
            time.sleep(SLEEP_BETWEEN_TICKERS)
            continue

        for provider in providers:
            if (ticker, provider) in exhausted_pairs:
                print(f"  SKIP (exhausted): {provider}")
                continue

            print(f"  Provider: {provider}")
            headlines = fetch_all_pages(ib, contract.conId, provider, ticker, run_id)

            if not headlines:
                print(f"    No headlines returned")
                time.sleep(SLEEP_BETWEEN_PROVIDERS)
                continue

            # Persist raw
            n = db.upsert_headlines(headlines, run_id=run_id)
            total_inserted += n
            print(f"    → {n} new rows inserted (total DB: {total_inserted})")

            # NLP scoring
            if args.score and headlines:
                analyzed = run_nlp_scoring(headlines)
                scored = db.upsert_analyzed(analyzed)
                total_scored += scored
                print(f"    → {scored} rows scored")

            # Log backfill pass
            times = [h["time"] for h in headlines if h.get("time")]
            earliest = min(times) if times else None
            latest_t = max(times) if times else None
            exhausted_flag = len(headlines) > 0  # simplified; set True by page exhaustion logic
            db.log_backfill(ticker, provider, earliest, latest_t, n, exhausted=True)

            time.sleep(SLEEP_BETWEEN_PROVIDERS)

        time.sleep(SLEEP_BETWEEN_TICKERS)

    # ── Process futures ───────────────────────────────────────
    print(f"\n[Futures]")
    for ticker in futures_tickers:
        print(f"  {ticker}")
        contract = qualify_future(ib, ticker)
        if not contract:
            print(f"  SKIP: could not qualify futures {ticker}")
            continue

        for provider in providers:
            if (ticker, provider) in exhausted_pairs:
                print(f"    SKIP (exhausted): {provider}")
                continue

            print(f"    Provider: {provider}")
            headlines = fetch_all_pages(ib, contract.conId, provider, ticker, run_id)

            if not headlines:
                time.sleep(SLEEP_BETWEEN_PROVIDERS)
                continue

            n = db.upsert_headlines(headlines, run_id=run_id)
            total_inserted += n
            print(f"    → {n} new rows inserted")

            if args.score and headlines:
                analyzed = run_nlp_scoring(headlines)
                scored = db.upsert_analyzed(analyzed)
                total_scored += scored

            times = [h["time"] for h in headlines if h.get("time")]
            earliest = min(times) if times else None
            latest_t = max(times) if times else None
            db.log_backfill(ticker, provider, earliest, latest_t, n, exhausted=True)
            time.sleep(SLEEP_BETWEEN_PROVIDERS)

    # ── Summary ───────────────────────────────────────────────
    try:
        ib.disconnect()
    except Exception:
        pass

    stats = db.stats()
    db.close()

    print(f"\n{'='*70}")
    print(f"  BACKFILL COMPLETE")
    print(f"{'='*70}")
    print(f"  Headlines inserted this run : {total_inserted}")
    print(f"  Headlines scored  this run  : {total_scored}")
    print(f"  DB total                    : {stats['total_headlines']}")
    print(f"  DB scored                   : {stats['scored']}")
    print(f"  DB unique tickers           : {stats['unique_tickers']}")
    print(f"  DB date range               : {stats['oldest']}  →  {stats['newest']}")
    print(f"\n  By provider:")
    for prov, cnt in sorted(stats["by_provider"].items()):
        print(f"    {prov:<12} {cnt:>6} headlines")
    print()
    print(f"  DB location: {PROJECT_ROOT / 'data' / 'news' / 'headlines.db'}")
    print()
    print(f"  Next: re-run periodically with --resume to pick up any new history,")
    print(f"        or let run_sentiment.py --persist keep the DB current going forward.")


if __name__ == "__main__":
    main()
