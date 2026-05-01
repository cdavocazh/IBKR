#!/usr/bin/env python3
"""
Headline Persistence Layer — IBKR News DB
==========================================
SQLite store for all raw IBKR news headlines with per-headline NLP scores.

Schema design:
  - article_id is PRIMARY KEY (IBKR's globally unique articleId)
  - INSERT OR IGNORE: perfectly idempotent — safe to re-run backfill or cron
  - Separate tables for raw headlines vs run metadata
  - Indexed for fast (ticker, date) slices needed by news-event drift backtesting

Usage:
    from tools.news_db import NewsDB

    db = NewsDB()                          # opens data/news/headlines.db
    db.upsert_headlines(headlines)         # list of dicts from fetch_headlines()
    db.upsert_analyzed(analyzed)           # list of dicts from analyze_headlines()

    # Query
    rows = db.query(tickers=["AAPL"], since="2025-01-01", provider="BRFG")
    meta = db.backfill_status()            # per-ticker oldest/newest/count
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _to_scalar(v):
    """Coerce dicts/lists to JSON strings so SQLite can bind them."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v

# Default DB location mirrors the existing data/news/ layout
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "news" / "headlines.db"


DDL = """
CREATE TABLE IF NOT EXISTS headlines (
    article_id          TEXT PRIMARY KEY,
    fetched_at          TEXT NOT NULL,       -- UTC ISO-8601 timestamp of fetch
    published_at        TEXT,                -- IBKR h.time (article publication time)
    provider            TEXT NOT NULL,
    ticker              TEXT NOT NULL,       -- ticker symbol used for the fetch
    headline            TEXT NOT NULL,
    keywords            TEXT,                -- IBKR metadata {K:...}
    ibkr_confidence     REAL,               -- IBKR metadata {C:...}
    -- NLP scores (populated by upsert_analyzed; NULL until scored) --
    sentiment_label     TEXT,               -- BULLISH / BEARISH / NEUTRAL
    sentiment_score     REAL,               -- net score, -1.0 to +1.0
    sentiment_confidence REAL,
    analyst_action      TEXT,               -- UPGRADE / DOWNGRADE / NEUTRAL / null
    macro_signal        TEXT,               -- key macro theme flagged
    actionability       REAL,               -- 0–10 actionability index
    run_id              TEXT                -- UUID of the ingest run
);

CREATE INDEX IF NOT EXISTS idx_hl_ticker_pub
    ON headlines (ticker, published_at);

CREATE INDEX IF NOT EXISTS idx_hl_published
    ON headlines (published_at);

CREATE INDEX IF NOT EXISTS idx_hl_provider
    ON headlines (provider);

CREATE INDEX IF NOT EXISTS idx_hl_ticker_provider
    ON headlines (ticker, provider);

CREATE TABLE IF NOT EXISTS backfill_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    provider        TEXT NOT NULL,
    earliest_seen   TEXT,           -- ISO-8601 UTC of oldest headline fetched
    latest_seen     TEXT,           -- ISO-8601 UTC of newest headline fetched
    articles_stored INTEGER DEFAULT 0,
    run_at          TEXT NOT NULL,
    exhausted       INTEGER DEFAULT 0  -- 1 if provider returned < 300 (no more history)
);

CREATE INDEX IF NOT EXISTS idx_bf_ticker_provider
    ON backfill_log (ticker, provider);
"""


class NewsDB:
    """SQLite-backed headline store."""

    def __init__(self, db_path: Optional[Path] = None):
        self.path = Path(db_path or _DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connection ─────────────────────────────────────────────

    def connect(self) -> "NewsDB":
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(DDL)
            self._conn.commit()
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()

    # ── Write ───────────────────────────────────────────────────

    def upsert_headlines(self, headlines: list[dict], run_id: Optional[str] = None) -> int:
        """
        Insert raw headlines (no NLP scores yet).
        Idempotent: article_id PRIMARY KEY with INSERT OR IGNORE.

        headlines: list of dicts with keys:
            headline, provider, time, articleId, ticker, metadata
            (same structure as fetch_headlines() in run_sentiment.py)

        Returns: number of newly inserted rows.
        """
        if not headlines:
            return 0
        run_id = run_id or str(uuid.uuid4())
        fetched_at = datetime.now(timezone.utc).isoformat()

        rows = []
        for h in headlines:
            meta = h.get("metadata", {})
            rows.append((
                h["articleId"],                      # article_id
                fetched_at,                          # fetched_at
                str(h.get("time", "")),              # published_at
                h.get("provider", ""),               # provider
                h.get("ticker", ""),                 # ticker
                h.get("headline", ""),               # headline
                meta.get("keywords"),                # keywords
                meta.get("confidence"),              # ibkr_confidence
                run_id,                              # run_id
            ))

        conn = self._ensure_connected()
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO headlines
                (article_id, fetched_at, published_at, provider, ticker,
                 headline, keywords, ibkr_confidence, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return cursor.rowcount

    def upsert_analyzed(self, analyzed: list[dict]) -> int:
        """
        Write NLP scores back into existing headline rows.
        Expects the list returned by analyze_headlines() — each item must have
        'articleId' (or 'article_id') so we can match to the right row.

        Only updates rows that already exist (scores not overwritten if row missing).
        Returns: number of rows updated.
        """
        if not analyzed:
            return 0

        rows = []
        for h in analyzed:
            article_id = h.get("articleId") or h.get("article_id")
            if not article_id:
                continue
            sentiment = h.get("sentiment", {})
            rows.append((
                _to_scalar(sentiment.get("label")),          # sentiment_label
                _to_scalar(sentiment.get("score")),          # sentiment_score
                _to_scalar(sentiment.get("confidence")),     # sentiment_confidence
                _to_scalar(h.get("analyst_action")),         # analyst_action
                _to_scalar(h.get("macro_signal")),           # macro_signal (may be dict)
                _to_scalar(h.get("actionability")),          # actionability
                article_id,
            ))

        conn = self._ensure_connected()
        cursor = conn.executemany(
            """
            UPDATE headlines SET
                sentiment_label      = ?,
                sentiment_score      = ?,
                sentiment_confidence = ?,
                analyst_action       = ?,
                macro_signal         = ?,
                actionability        = ?
            WHERE article_id = ?
            """,
            rows,
        )
        conn.commit()
        return cursor.rowcount

    def log_backfill(
        self,
        ticker: str,
        provider: str,
        earliest: Optional[str],
        latest: Optional[str],
        count: int,
        exhausted: bool = False,
    ):
        """Record a backfill pass for a (ticker, provider) pair."""
        conn = self._ensure_connected()
        conn.execute(
            """
            INSERT INTO backfill_log
                (ticker, provider, earliest_seen, latest_seen, articles_stored, run_at, exhausted)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, provider, earliest, latest, count, datetime.now(timezone.utc).isoformat(), int(exhausted)),
        )
        conn.commit()

    # ── Read ────────────────────────────────────────────────────

    def query(
        self,
        tickers: Optional[list[str]] = None,
        providers: Optional[list[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        min_actionability: Optional[float] = None,
        limit: int = 10_000,
    ) -> list[dict]:
        """
        Flexible query returning a list of headline dicts sorted by published_at DESC.

        Args:
            tickers: filter to specific tickers (OR logic)
            providers: filter to specific providers (OR logic)
            since: ISO date string e.g. "2025-01-01"
            until: ISO date string e.g. "2025-12-31"
            min_actionability: only rows with actionability >= this value
            limit: max rows returned

        Returns:
            List of dicts (sqlite3.Row coerced to dict).
        """
        where = []
        params: list = []

        if tickers:
            placeholders = ",".join("?" * len(tickers))
            where.append(f"ticker IN ({placeholders})")
            params.extend(tickers)
        if providers:
            placeholders = ",".join("?" * len(providers))
            where.append(f"provider IN ({placeholders})")
            params.extend(providers)
        if since:
            where.append("published_at >= ?")
            params.append(since)
        if until:
            where.append("published_at <= ?")
            params.append(until)
        if min_actionability is not None:
            where.append("actionability >= ?")
            params.append(min_actionability)

        sql = "SELECT * FROM headlines"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)

        conn = self._ensure_connected()
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def backfill_status(self) -> list[dict]:
        """
        Per-(ticker, provider) summary: oldest headline, newest headline, count.
        Useful for deciding what still needs backfilling.
        """
        conn = self._ensure_connected()
        rows = conn.execute(
            """
            SELECT
                ticker,
                provider,
                MIN(published_at) AS oldest,
                MAX(published_at) AS newest,
                COUNT(*)          AS total
            FROM headlines
            GROUP BY ticker, provider
            ORDER BY ticker, provider
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def oldest_per_ticker(self, ticker: str, provider: str) -> Optional[str]:
        """Return the oldest published_at for (ticker, provider), or None if no rows."""
        conn = self._ensure_connected()
        row = conn.execute(
            "SELECT MIN(published_at) FROM headlines WHERE ticker=? AND provider=?",
            (ticker, provider),
        ).fetchone()
        return row[0] if row else None

    def stats(self) -> dict:
        """Quick DB health stats."""
        conn = self._ensure_connected()
        total = conn.execute("SELECT COUNT(*) FROM headlines").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM headlines WHERE sentiment_label IS NOT NULL"
        ).fetchone()[0]
        providers = conn.execute(
            "SELECT provider, COUNT(*) FROM headlines GROUP BY provider"
        ).fetchall()
        tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM headlines").fetchone()[0]
        oldest = conn.execute("SELECT MIN(published_at) FROM headlines").fetchone()[0]
        newest = conn.execute("SELECT MAX(published_at) FROM headlines").fetchone()[0]
        return {
            "total_headlines": total,
            "scored": scored,
            "unscored": total - scored,
            "unique_tickers": tickers,
            "oldest": oldest,
            "newest": newest,
            "by_provider": {r[0]: r[1] for r in providers},
        }

    # ── Internal ────────────────────────────────────────────────

    def _ensure_connected(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn  # type: ignore[return-value]


# ── Convenience factory used by run_sentiment.py ─────────────────

def get_db(db_path: Optional[Path] = None) -> NewsDB:
    """Return a connected NewsDB instance (caller must close or use as context manager)."""
    return NewsDB(db_path).connect()
