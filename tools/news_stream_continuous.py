#!/usr/bin/env python3
"""
Continuous IBKR Broadtape News Streamer (Phase 1)

Long-running daemon that subscribes to IBKR news broadtape across all 7 providers
and persists each headline to data/news/headlines.db immediately as it arrives.

Foundation for higher-frequency sentiment aggregation (Phase 2 — 15-min buckets).

Differs from scripts/run_sentiment.py:
- run_sentiment.py: Batch — fetches historical headlines 3x daily via reqHistoricalNews
- this script:    Stream — subscribes via reqMktData + tickNews; writes one row per headline

Designed to run as systemd service `ibkr-broadtape.service` on the VPS:
    Restart=always
    ExecStart=/usr/bin/python3 /root/IBKR/tools/news_stream_continuous.py

Usage:
    python tools/news_stream_continuous.py
    python tools/news_stream_continuous.py --client-id 27 --providers BRFG,DJ-N
    python tools/news_stream_continuous.py --reconnect-on-error --log-every 60

ClientId allocation (avoid conflicts):
    11/20/23 — local IBKR sentiment runs (per CLAUDE.md)
    26      — tools/news_stream.py (multi-provider news aggregation)
    27      — THIS SCRIPT (persistent broadtape) [reserved by this commit]
    30      — ibkr-dashboard.service (VPS)
    98      — scripts/run_sentiment.py (standalone batch)
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

# Reuse parse_headline + connection pattern from existing harness
from scripts.ib_news_stream import parse_headline  # noqa: E402

try:
    from ib_async import IB, Contract
    IB_LIB = "ib_async"
except ImportError:
    from ib_insync import IB, Contract
    IB_LIB = "ib_insync"

from tools.news_db import get_db, NewsDB  # noqa: E402


# All 7 providers we have access to (per CLAUDE.md)
DEFAULT_PROVIDERS = ["BRFG", "BRFUPDN", "DJ-N", "DJ-RT", "DJ-RTA", "DJ-RTE", "DJ-RTG"]

# Default IBKR connection — auto-detect ports in priority order
DEFAULT_PORTS = [4001, 4002, 7496, 7497]


# ─── Connection ──────────────────────────────────────────────

def _connect(host: str, port: Optional[int], client_id: int) -> Optional[IB]:
    """Connect to IBKR Gateway. If port is None, auto-detect."""
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


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ─── Headline → DB conversion ────────────────────────────────

def _news_tick_to_dict(news_tick, provider_fallback: str) -> dict:
    """Convert an IBKR newsTick event into the dict shape expected by NewsDB.upsert_headlines."""
    raw_headline = getattr(news_tick, "headline", str(news_tick))
    parsed = parse_headline(raw_headline)
    article_id = (
        getattr(news_tick, "articleId", None)
        or parsed["metadata"].get("articleId")
        or f"{provider_fallback}:{int(time.time()*1000)}"  # fallback so PK is never null
    )
    provider = getattr(news_tick, "providerCode", provider_fallback) or provider_fallback
    # IBKR tickNews has a `time` field (epoch ms) on some versions
    pub_time_raw = getattr(news_tick, "time", None)
    if pub_time_raw is not None:
        try:
            pub_iso = datetime.fromtimestamp(int(pub_time_raw) / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pub_iso = str(pub_time_raw)
    else:
        pub_iso = datetime.now(timezone.utc).isoformat()

    return {
        "articleId": article_id,
        "headline": parsed["headline"],
        "provider": provider,
        "time": pub_iso,
        "ticker": "",  # broadtape has no specific ticker
        "metadata": parsed["metadata"],
    }


# ─── Streaming loop ──────────────────────────────────────────

class BroadtapeDaemon:
    def __init__(self, host: str, port: Optional[int], client_id: int,
                 providers: list[str], db: NewsDB, log_every_sec: int = 60):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.providers = providers
        self.db = db
        self.log_every_sec = log_every_sec
        self.ib: Optional[IB] = None
        self._stop = False
        self._headline_count = 0
        self._last_log = time.time()
        # Buffer headlines briefly to amortize SQLite writes
        self._buffer: list[dict] = []
        self._buffer_flush_sec = 5

    def stop(self, *_):
        print(f"[{_ts()}] Stop signal received — shutting down", flush=True)
        self._stop = True

    def subscribe_all(self) -> list[str]:
        """Subscribe to broadtape for each configured provider."""
        subscribed = []
        for code in self.providers:
            news_contract = Contract()
            news_contract.symbol = f"{code}:{code}_ALL"
            news_contract.secType = "NEWS"
            news_contract.exchange = code
            try:
                self.ib.reqMktData(news_contract, genericTickList="mdoff,292")
                subscribed.append(code)
                print(f"[{_ts()}]   Subscribed to broadtape: {code}", flush=True)
            except Exception as e:
                print(f"[{_ts()}]   Failed to subscribe to {code}: {e}", flush=True)
        return subscribed

    def _on_news_tick(self, news_tick):
        """Callback for each incoming headline."""
        try:
            provider = getattr(news_tick, "providerCode", "?") or "?"
            row = _news_tick_to_dict(news_tick, provider_fallback=provider)
            self._buffer.append(row)
            self._headline_count += 1
        except Exception as e:
            print(f"[{_ts()}] ERROR parsing news tick: {e}", flush=True)

    def _flush_buffer(self):
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        try:
            n = self.db.upsert_headlines(batch)
            if n > 0:
                print(f"[{_ts()}]   Flushed {len(batch)} headlines, {n} new to DB", flush=True)
        except Exception as e:
            print(f"[{_ts()}] ERROR flushing to DB: {e}", flush=True)
            # Re-buffer on failure so we don't lose them
            self._buffer = batch + self._buffer

    def _log_status(self):
        now = time.time()
        if now - self._last_log >= self.log_every_sec:
            try:
                stats = self.db.stats()
                print(f"[{_ts()}] [HEARTBEAT] received={self._headline_count} "
                      f"db_total={stats.get('total_headlines', '?')} "
                      f"oldest={stats.get('earliest_published', '?')} "
                      f"newest={stats.get('latest_published', '?')}",
                      flush=True)
            except Exception:
                print(f"[{_ts()}] [HEARTBEAT] received={self._headline_count}", flush=True)
            self._last_log = now

    def run(self, reconnect_on_error: bool = True):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        while not self._stop:
            self.ib = _connect(self.host, self.port, self.client_id)
            if self.ib is None:
                if not reconnect_on_error:
                    print(f"[{_ts()}] Connection failed — exiting (reconnect disabled)", flush=True)
                    return
                print(f"[{_ts()}] Connect failed — retry in 30s", flush=True)
                time.sleep(30)
                continue

            subscribed = self.subscribe_all()
            if not subscribed:
                print(f"[{_ts()}] No broadtape subscriptions — disconnecting and retrying", flush=True)
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                time.sleep(30)
                continue

            # Wire up the news tick event
            if hasattr(self.ib, "newsTicks"):
                # ib_async / ib_insync expose .newsTicks ListEvent
                self.ib.newsTicks.updateEvent += self._on_news_tick
            elif hasattr(self.ib, "newsTickEvent"):
                self.ib.newsTickEvent += self._on_news_tick
            else:
                print(f"[{_ts()}] WARNING: cannot find news tick event on {IB_LIB}", flush=True)

            print(f"[{_ts()}] Streaming {len(subscribed)} providers — Ctrl+C to stop", flush=True)
            last_flush = time.time()
            try:
                while not self._stop:
                    self.ib.sleep(0.5)
                    if (time.time() - last_flush) >= self._buffer_flush_sec:
                        self._flush_buffer()
                        last_flush = time.time()
                    self._log_status()
            except Exception as e:
                print(f"[{_ts()}] ERROR in stream loop: {e}", flush=True)

            # Cleanup before reconnect
            self._flush_buffer()
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self.ib = None

            if self._stop:
                break

            if reconnect_on_error:
                print(f"[{_ts()}] Reconnecting in 15s...", flush=True)
                time.sleep(15)
            else:
                break

        # Final flush on exit
        self._flush_buffer()
        print(f"[{_ts()}] Daemon stopped. Total received: {self._headline_count}", flush=True)


# ─── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Continuous IBKR broadtape news streamer")
    parser.add_argument("--host", default=os.environ.get("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=None,
                        help="IBKR Gateway port (auto-detect if omitted)")
    parser.add_argument("--client-id", type=int, default=int(os.environ.get("IB_NEWS_CLIENT_ID", "27")),
                        help="IBKR client ID (default 27 — reserved for broadtape)")
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS),
                        help="Comma-separated provider codes")
    parser.add_argument("--reconnect-on-error", action="store_true", default=True,
                        help="Auto-reconnect on connection loss (default: True)")
    parser.add_argument("--no-reconnect", dest="reconnect_on_error", action="store_false")
    parser.add_argument("--log-every", type=int, default=60,
                        help="Heartbeat log interval in seconds (default 60)")
    parser.add_argument("--db-path", type=str, default=None,
                        help="Override SQLite path (default data/news/headlines.db)")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else None
    db = get_db(db_path).connect()
    print(f"[{_ts()}] News DB ready: {db.path}", flush=True)
    print(f"[{_ts()}] Initial stats: {db.stats()}", flush=True)

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    daemon = BroadtapeDaemon(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        providers=providers,
        db=db,
        log_every_sec=args.log_every,
    )
    try:
        daemon.run(reconnect_on_error=args.reconnect_on_error)
    finally:
        db.close()


if __name__ == "__main__":
    main()
