#!/usr/bin/env python3
"""
Continuous IBKR News Polling Daemon (Phase 1)

Long-running daemon that polls reqHistoricalNews across all 7 providers + a
ticker watchlist every N seconds and persists each headline to
data/news/headlines.db. The PRIMARY KEY on article_id makes the upsert
idempotent — duplicates are silently dropped.

Why polling instead of broadtape subscription:
  IBKR broadtape via reqMktData(secType=NEWS) requires a `conId` that the API
  doesn't always return for NEWS contracts. ib_async raises a hashable-key
  error when subscribing without one (the legacy cmd_broadtape in
  scripts/ib_news_stream.py hits the same wall). reqHistoricalNews works
  reliably and returns the same articles, just batched. At a 60-120s poll
  interval we get near-real-time coverage with proven-working API calls.

Differs from scripts/run_sentiment.py (the existing batch job):
  - run_sentiment.py: 3x daily, multi-day lookback, NLP scoring inline
  - this daemon:      every 60-120s, last-hour lookback, raw persistence
                      (NLP scoring done by sentiment_intraday.py at 15-min step)

Designed to run as systemd service `ibkr-broadtape.service` on the VPS:
    Restart=always
    ExecStart=/root/IBKR/venv/bin/python /root/IBKR/tools/news_stream_continuous.py

Usage:
    python tools/news_stream_continuous.py
    python tools/news_stream_continuous.py --interval 60 --lookback-min 30
    python tools/news_stream_continuous.py --tickers AAPL,NVDA,MSFT,SPY

ClientId allocation:
    27 — THIS DAEMON (continuous news polling)
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse parse_headline from existing harness
from scripts.ib_news_stream import parse_headline  # noqa: E402

try:
    from ib_async import IB, Stock, Future
    IB_LIB = "ib_async"
except ImportError:
    from ib_insync import IB, Stock, Future
    IB_LIB = "ib_insync"

from tools.news_db import get_db, NewsDB  # noqa: E402

# 7 providers we have access to (per CLAUDE.md)
DEFAULT_PROVIDERS = ["BRFG", "BRFUPDN", "DJ-N", "DJ-RT", "DJ-RTA", "DJ-RTE", "DJ-RTG"]
# IBKR concatenates with `+` for multi-provider in one call
PROVIDER_CODES_STR = "+".join(DEFAULT_PROVIDERS)

# Tickers to fetch headlines for (separate from broadtape; ticker-specific feeds)
DEFAULT_TICKERS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]

DEFAULT_PORTS = [4001, 4002, 7496, 7497]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect(host: str, port: Optional[int], client_id: int) -> Optional[IB]:
    ports = [port] if port else DEFAULT_PORTS
    for p in ports:
        ib = IB()
        try:
            ib.connect(host, p, clientId=client_id, readonly=True, timeout=10)
            print(f"[{_ts()}] Connected via {IB_LIB} to {host}:{p} (clientId={client_id})", flush=True)
            return ib
        except Exception as e:
            print(f"[{_ts()}] Connect to {host}:{p} failed: {e}", flush=True)
            try:
                ib.disconnect()
            except Exception:
                pass
    return None


def _qualify_ticker(ib, ticker: str):
    """Stock first, then futures (ES front month)."""
    contract = Stock(ticker, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if qualified:
        return qualified[0]
    # Try as futures front-month
    now = datetime.now()
    expiry_months = [3, 6, 9, 12]
    front = None
    for m in expiry_months:
        if now.month <= m:
            front = f"{now.year}{m:02d}"
            break
    if front is None:
        front = f"{now.year + 1}03"
    contract = Future(ticker, lastTradeDateOrContractMonth=front, exchange="CME", currency="USD")
    qualified = ib.qualifyContracts(contract)
    return qualified[0] if qualified else None


def _fetch_provider_headlines(ib, provider_codes_str: str = PROVIDER_CODES_STR,
                              count: int = 200) -> list[dict]:
    """reqHistoricalNews with conId=0 returns broad-tape headlines (no ticker filter).

    Some IBKR Gateway versions reject conId=0 — in that case we fall back to
    per-ticker fetches in _fetch_ticker_headlines.
    """
    rows = []
    try:
        # IBKR convention: conId=0 means "all news for these providers"
        headlines = ib.reqHistoricalNews(0, provider_codes_str, "", "", count)
        for h in headlines:
            parsed = parse_headline(h.headline if hasattr(h, "headline") else str(h))
            rows.append({
                "articleId": getattr(h, "articleId", None) or f"BT:{int(time.time()*1000)}",
                "headline": parsed["headline"],
                "provider": getattr(h, "providerCode", "?"),
                "time": str(getattr(h, "time", datetime.now(timezone.utc).isoformat())),
                "ticker": "",
                "metadata": parsed["metadata"],
            })
    except Exception as e:
        # conId=0 not supported — caller will fall back to per-ticker fetches
        if "conId" not in str(e).lower():
            print(f"[{_ts()}] broadtape fetch error: {e}", flush=True)
    return rows


def _fetch_ticker_headlines(ib, ticker_contract, ticker: str,
                            provider_codes_str: str = PROVIDER_CODES_STR,
                            count: int = 50) -> list[dict]:
    if ticker_contract is None:
        return []
    rows = []
    try:
        headlines = ib.reqHistoricalNews(
            ticker_contract.conId, provider_codes_str, "", "", count
        )
        for h in headlines:
            parsed = parse_headline(h.headline if hasattr(h, "headline") else str(h))
            rows.append({
                "articleId": getattr(h, "articleId", None) or f"{ticker}:{int(time.time()*1000)}",
                "headline": parsed["headline"],
                "provider": getattr(h, "providerCode", "?"),
                "time": str(getattr(h, "time", datetime.now(timezone.utc).isoformat())),
                "ticker": ticker,
                "metadata": parsed["metadata"],
            })
    except Exception as e:
        print(f"[{_ts()}]   {ticker} fetch error: {e}", flush=True)
    return rows


class NewsPollDaemon:
    def __init__(self, host: str, port: Optional[int], client_id: int,
                 db: NewsDB, tickers: list[str],
                 interval_sec: int = 90, log_every_sec: int = 300):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.db = db
        self.tickers = tickers
        self.interval_sec = interval_sec
        self.log_every_sec = log_every_sec
        self.ib: Optional[IB] = None
        self._stop = False
        self._poll_count = 0
        self._inserted_total = 0
        self._last_log = time.time()
        # Cache qualified contracts (refresh hourly to handle ES front-month rolls)
        self._contracts: dict[str, object] = {}
        self._contracts_refreshed_at = 0.0

    def stop(self, *_):
        print(f"[{_ts()}] Stop signal received — shutting down", flush=True)
        self._stop = True

    def _refresh_contracts(self):
        """Re-qualify ticker contracts (hourly)."""
        now = time.time()
        if self._contracts and (now - self._contracts_refreshed_at) < 3600:
            return
        self._contracts.clear()
        for tkr in self.tickers:
            try:
                c = _qualify_ticker(self.ib, tkr)
                if c is not None:
                    self._contracts[tkr] = c
            except Exception as e:
                print(f"[{_ts()}]   qualify {tkr} failed: {e}", flush=True)
        self._contracts_refreshed_at = now
        print(f"[{_ts()}] Qualified {len(self._contracts)} tickers: "
              f"{list(self._contracts.keys())}", flush=True)

    def _poll_once(self) -> int:
        all_rows: list[dict] = []
        # 1. Try broadtape (conId=0). If unsupported, falls back silently.
        all_rows.extend(_fetch_provider_headlines(self.ib))
        # 2. Per-ticker fetches
        for tkr, contract in self._contracts.items():
            all_rows.extend(_fetch_ticker_headlines(self.ib, contract, tkr))
        # Persist (idempotent — article_id PK)
        if not all_rows:
            return 0
        try:
            n = self.db.upsert_headlines(all_rows)
            self._inserted_total += n
            return n
        except Exception as e:
            print(f"[{_ts()}] DB upsert error: {e}", flush=True)
            return 0

    def _log_status(self, force: bool = False):
        now = time.time()
        if force or (now - self._last_log) >= self.log_every_sec:
            try:
                stats = self.db.stats()
                print(f"[{_ts()}] [HEARTBEAT] polls={self._poll_count} "
                      f"inserted_total={self._inserted_total} "
                      f"db_total={stats.get('total_headlines', '?')} "
                      f"newest={stats.get('newest', '?')}",
                      flush=True)
            except Exception:
                print(f"[{_ts()}] [HEARTBEAT] polls={self._poll_count} "
                      f"inserted_total={self._inserted_total}", flush=True)
            self._last_log = now

    def run(self, reconnect_on_error: bool = True):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        while not self._stop:
            self.ib = _connect(self.host, self.port, self.client_id)
            if self.ib is None:
                if not reconnect_on_error:
                    print(f"[{_ts()}] Connection failed — exiting", flush=True)
                    return
                print(f"[{_ts()}] Connect failed — retry in 30s", flush=True)
                time.sleep(30)
                continue

            try:
                self._refresh_contracts()
            except Exception as e:
                print(f"[{_ts()}] Initial qualify failed: {e}", flush=True)

            print(f"[{_ts()}] Polling every {self.interval_sec}s (Ctrl+C to stop)", flush=True)

            while not self._stop:
                try:
                    self._refresh_contracts()  # noop if recently refreshed
                    n = self._poll_once()
                    self._poll_count += 1
                    if n > 0:
                        print(f"[{_ts()}] poll #{self._poll_count}: +{n} new headlines", flush=True)
                    self._log_status()
                except Exception as e:
                    print(f"[{_ts()}] Poll error: {e}", flush=True)
                # Sleep responsive to stop signal
                slept = 0
                while slept < self.interval_sec and not self._stop:
                    time.sleep(min(1, self.interval_sec - slept))
                    slept += 1

            try:
                self.ib.disconnect()
            except Exception:
                pass
            self.ib = None
            if not self._stop and reconnect_on_error:
                print(f"[{_ts()}] Reconnecting in 15s...", flush=True)
                time.sleep(15)
            else:
                break

        self._log_status(force=True)
        print(f"[{_ts()}] Daemon stopped. Total inserted: {self._inserted_total}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Continuous IBKR news polling daemon")
    parser.add_argument("--host", default=os.environ.get("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--client-id", type=int,
                        default=int(os.environ.get("IB_NEWS_CLIENT_ID", "27")))
    parser.add_argument("--interval", type=int, default=90,
                        help="Poll interval in seconds (default 90)")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS),
                        help="Comma-separated ticker watchlist")
    parser.add_argument("--log-every", type=int, default=300)
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument("--reconnect-on-error", action="store_true", default=True)
    parser.add_argument("--no-reconnect", dest="reconnect_on_error", action="store_false")
    args = parser.parse_args()

    db = get_db(Path(args.db_path) if args.db_path else None).connect()
    print(f"[{_ts()}] News DB ready: {db.path}", flush=True)
    print(f"[{_ts()}] Initial stats: {db.stats()}", flush=True)

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    daemon = NewsPollDaemon(
        host=args.host, port=args.port, client_id=args.client_id,
        db=db, tickers=tickers,
        interval_sec=args.interval, log_every_sec=args.log_every,
    )
    try:
        daemon.run(reconnect_on_error=args.reconnect_on_error)
    finally:
        db.close()


if __name__ == "__main__":
    main()
