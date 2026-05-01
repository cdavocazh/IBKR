#!/usr/bin/env python3
"""
IBKR Dashboard Backend — FastAPI + WebSocket

Connects to IBKR Gateway via ib_async, serves portfolio data and
streams news headlines to the React frontend.

Endpoints:
  GET  /api/portfolio  — positions + account summary
  GET  /api/news       — recent headlines
  GET  /api/status     — connection status
  WS   /ws             — real-time portfolio updates + news stream
"""

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ─── SQLite Database + Auth ──────────────────────────────────

_DB_PATH = Path(__file__).parent / "dashboard.db"
_AUTH_SECRET_PATH = Path(__file__).parent / ".dashboard_auth_secret"


def _load_auth_secret() -> str:
    """Return a stable auth secret so browser sessions survive restarts."""
    env_secret = os.environ.get("DASHBOARD_SECRET", "").strip()
    if env_secret:
        return env_secret

    try:
        if _AUTH_SECRET_PATH.exists():
            file_secret = _AUTH_SECRET_PATH.read_text().strip()
            if file_secret:
                return file_secret

        secret = secrets.token_hex(32)
        _AUTH_SECRET_PATH.write_text(secret)
        try:
            os.chmod(_AUTH_SECRET_PATH, 0o600)
        except OSError:
            pass
        return secret
    except OSError:
        return secrets.token_hex(32)


_AUTH_SECRET = _load_auth_secret()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS watchlists (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS watchlist_instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id TEXT NOT NULL,
            con_id INTEGER,
            symbol TEXT NOT NULL,
            local_symbol TEXT,
            sec_type TEXT DEFAULT 'STK',
            exchange TEXT DEFAULT '',
            currency TEXT DEFAULT 'USD',
            name TEXT DEFAULT '',
            FOREIGN KEY (watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # Migrate from watchlists.json if it has data
    json_path = Path(__file__).parent / "watchlists.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text())
            wls = data.get("watchlists", [])
            if wls:
                # Check if we already migrated (any watchlists exist)
                count = conn.execute("SELECT COUNT(*) FROM watchlists").fetchone()[0]
                if count == 0:
                    # Create a default migration user
                    salt = secrets.token_hex(16)
                    pw_hash = hashlib.pbkdf2_hmac("sha256", b"changeme", salt.encode(), 100000).hex()
                    conn.execute(
                        "INSERT OR IGNORE INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                        ("admin", pw_hash, salt),
                    )
                    conn.commit()
                    user_row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
                    uid = user_row[0]
                    for wl in wls:
                        conn.execute(
                            "INSERT INTO watchlists (id, user_id, name) VALUES (?, ?, ?)",
                            (wl["id"], uid, wl["name"]),
                        )
                        for inst in wl.get("instruments", []):
                            conn.execute(
                                "INSERT INTO watchlist_instruments (watchlist_id, con_id, symbol, local_symbol, sec_type, exchange, currency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (wl["id"], inst.get("conId"), inst["symbol"], inst.get("localSymbol", inst["symbol"]), inst.get("secType", "STK"), inst.get("exchange", ""), inst.get("currency", "USD")),
                            )
                    conn.commit()
        except Exception:
            pass
    conn.close()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def _create_token(user_id: int, username: str) -> str:
    payload = json.dumps({"uid": user_id, "u": username, "t": int(time.time())})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_token(token: str) -> dict | None:
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(_AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload
    except Exception:
        return None


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_data = _verify_token(auth[7:])
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token_data


# ─── Headline Parser (from scripts/ib_news_stream.py) ────────

def parse_headline(raw_headline: str) -> dict:
    metadata = {}
    headline = raw_headline
    if raw_headline.startswith("{"):
        # BRFG format: {C:0.97:K:tech}!Headline text
        if "}!" in raw_headline:
            meta_str, headline = raw_headline.split("}!", 1)
            meta_str = meta_str[1:]
            parts = meta_str.split(":")
            for i in range(0, len(parts) - 1, 2):
                key, val = parts[i], parts[i + 1]
                if key == "C":
                    try:
                        metadata["confidence"] = round(float(val), 2)
                    except ValueError:
                        pass
                elif key == "K":
                    metadata["keywords"] = val
        # DJ format: {A:800015:L:en:K:0.97:C:0.97}Headline text
        elif "}" in raw_headline:
            meta_str, headline = raw_headline.split("}", 1)
            meta_str = meta_str[1:]
            parts = meta_str.split(":")
            for i in range(0, len(parts) - 1, 2):
                key, val = parts[i], parts[i + 1]
                if key == "C":
                    try:
                        metadata["confidence"] = round(float(val), 2)
                    except ValueError:
                        pass
                elif key == "K":
                    try:
                        metadata["keywords"] = val
                    except Exception:
                        pass
    return {"headline": headline.strip(), "metadata": metadata}


# ─── Global State ─────────────────────────────────────────────

class DashboardState:
    def __init__(self):
        self.connected = False
        self.accounts: list[str] = []  # List of account IDs
        self.account_portfolios: dict[str, dict] = {}  # account_id -> {summary, positions}
        self.account_orders: dict[str, list] = {}  # account_id -> [orders]
        self.news_buffer = deque(maxlen=200)
        self.last_update = None
        self.ws_clients: set = set()
        self.live_mode = False  # Per-second refresh toggle
        self._lock = threading.Lock()

    def update_portfolio(self, account_portfolios: dict[str, dict], accounts: list[str], account_orders: dict[str, list] | None = None):
        with self._lock:
            self.accounts = accounts
            self.account_portfolios = account_portfolios
            if account_orders is not None:
                self.account_orders = account_orders
            self.last_update = datetime.now().isoformat()

    def add_headline(self, headline_dict):
        with self._lock:
            self.news_buffer.appendleft(headline_dict)

    def get_accounts(self):
        with self._lock:
            return list(self.accounts)

    def get_portfolio(self, account: str | None = None):
        with self._lock:
            if account and account in self.account_portfolios:
                return dict(self.account_portfolios[account])
            # Return first account as default
            if self.accounts and self.accounts[0] in self.account_portfolios:
                return dict(self.account_portfolios[self.accounts[0]])
            return {"summary": {}, "positions": []}

    def get_all_portfolios(self):
        """Return full multi-account data for WebSocket broadcast."""
        with self._lock:
            return {
                "accounts": list(self.accounts),
                "portfolios": {k: dict(v) for k, v in self.account_portfolios.items()},
                "orders": {k: list(v) for k, v in self.account_orders.items()},
            }

    def get_news(self, count=50):
        with self._lock:
            return list(self.news_buffer)[:count]

    def get_status(self):
        total_positions = sum(
            len(p.get("positions", [])) for p in self.account_portfolios.values()
        )
        return {
            "connected": self.connected,
            "position_count": total_positions,
            "account_count": len(self.accounts),
            "last_update": self.last_update,
            "live_mode": self.live_mode,
            "library": "ib_async",
        }


state = DashboardState()

# Global refs for chart API access from the FastAPI thread
_ib_ref = None  # Set by IB thread after connect
_contract_cache_ref = None  # Shared contract cache
_chart_request_queue: list = []  # Chart requests from API thread
_chart_request_lock = threading.Lock()


# ─── News Extraction + NLP Sentiment ─────────────────────────

# All available providers (discovered via reqNewsProviders)
_ALL_NEWS_PROVIDERS = "BRFG:BRFUPDN:DJ-N:DJ-RT:DJ-RTA:DJ-RTE:DJ-RTG"

# Sentiment results stored in state
_sentiment_results: dict = {}
_sentiment_lock = threading.Lock()

def _fetch_historical_news_and_sentiment(ib):
    """Fetch 1 week of headlines from all providers, run NLP sentiment, save results."""
    from datetime import timedelta

    try:
        from ib_async import Stock as _Stock
    except ImportError:
        from ib_insync import Stock as _Stock

    now = datetime.utcnow()
    start_str = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S.0")
    end_str = now.strftime("%Y-%m-%d %H:%M:%S.0")

    all_headlines = []
    seen_article_ids = set()

    # Fetch contract-specific headlines for major tickers + top portfolio holdings
    base_tickers = ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "SPY", "QQQ"]

    # Add top 12 portfolio tickers by market value
    portfolio_tickers = []
    try:
        positions = ib.positions()
        # Sort by abs(position * avgCost) as proxy for holding value
        sorted_pos = sorted(
            positions,
            key=lambda p: abs(p.position * p.avgCost * (float(p.contract.multiplier) if p.contract.multiplier else 1.0)),
            reverse=True,
        )
        for p in sorted_pos[:12]:
            sym = p.contract.symbol
            if sym not in base_tickers and sym not in portfolio_tickers:
                portfolio_tickers.append(sym)
    except Exception:
        pass

    tickers = base_tickers + portfolio_tickers
    print(f"[IB] Fetching news for {len(tickers)} tickers: {', '.join(tickers)}")
    for ticker in tickers:
        try:
            c = _Stock(ticker, "SMART", "USD")
            qual = ib.qualifyContracts(c)
            if not qual:
                continue
            con_id = qual[0].conId

            # Query each provider individually (more reliable than combined)
            for provider in _ALL_NEWS_PROVIDERS.split(":"):
                try:
                    headlines = ib.reqHistoricalNews(
                        con_id, provider, start_str, end_str, 100
                    )
                    if headlines:
                        for h in headlines:
                            if h.articleId in seen_article_ids:
                                continue
                            seen_article_ids.add(h.articleId)
                            parsed = parse_headline(h.headline)
                            headline_dict = {
                                "headline": parsed["headline"],
                                "provider": h.providerCode,
                                "time": str(h.time),
                                "articleId": h.articleId,
                                "ticker": ticker,
                                "metadata": parsed["metadata"],
                            }
                            all_headlines.append(headline_dict)
                            state.add_headline(headline_dict)
                except Exception:
                    pass
                time.sleep(0.3)  # Rate limit between provider queries
        except Exception:
            pass
        time.sleep(0.5)  # Rate limit between tickers

    print(f"[IB] Loaded {len(all_headlines)} headlines (1-week history, {len(seen_article_ids)} unique)")

    # Run NLP sentiment analysis
    if all_headlines:
        _run_sentiment_analysis(all_headlines)


def _run_sentiment_analysis(headlines: list):
    """Run NLP sentiment engine on headlines and save results."""
    global _sentiment_results

    try:
        from tools.news_sentiment_nlp import (
            analyze_headlines,
            get_regime_signal,
            enrich_with_market_context,
        )
    except ImportError as e:
        print(f"[Sentiment] Import error: {e}")
        return

    try:
        # Analyze all headlines
        analyzed = analyze_headlines(headlines)

        # Get regime signals for different time windows
        regime_24h = get_regime_signal(analyzed, hours_back=24)
        regime_24h = enrich_with_market_context(regime_24h)

        regime_72h = get_regime_signal(analyzed, hours_back=72)
        regime_7d = get_regime_signal(analyzed, hours_back=168)

        # Build ES trading direction summary
        # Unified signal blends NLP headlines (40%) + newsletter context (60%)
        unified_regime = regime_24h.get("unified_regime", regime_24h["regime"])
        unified_sentiment = regime_24h.get("unified_sentiment", regime_24h["net_sentiment"])
        newsletter_score = regime_24h.get("newsletter_sentiment_score", 0.0)

        result = {
            "timestamp": datetime.now().isoformat(),
            "headline_count": len(analyzed),
            "regime_24h": regime_24h,
            "regime_72h": regime_72h,
            "regime_7d": regime_7d,
            "es_trading_direction": {
                "signal": unified_regime,
                "signal_source": "unified (NLP 40% + newsletters 60%)",
                "confidence": regime_24h["confidence"],
                "unified_sentiment": unified_sentiment,
                "newsletter_sentiment": newsletter_score,
                "nlp_sentiment_24h": regime_24h["net_sentiment"],
                "net_sentiment_24h": regime_24h["net_sentiment"],
                "net_sentiment_72h": regime_72h["net_sentiment"],
                "net_sentiment_7d": regime_7d["net_sentiment"],
                "dominant_category": regime_24h["dominant_category"],
                "key_themes": regime_24h["key_themes"],
                "context_themes": regime_24h.get("context_themes", []),
                "context_trend": regime_24h.get("context_trend"),
                "context_levels": regime_24h.get("context_levels", {}),
                "context_positioning": regime_24h.get("context_positioning", {}),
                "context_key_risks": regime_24h.get("context_key_risks"),
                "context_vix_tier": regime_24h.get("context_vix_tier"),
                "cross_validated": regime_24h.get("cross_validated"),
                "actionable_insights": regime_24h["actionable_insights"],
            },
            "analyzed_headlines": [
                {k: v for k, v in h.items() if k != "raw"}
                for h in sorted(analyzed, key=lambda x: x.get("actionability", 0), reverse=True)[:100]
            ],
        }

        # Store in memory for API access
        with _sentiment_lock:
            _sentiment_results.update(result)

        # Save to JSON file
        output_path = PROJECT_ROOT / "data" / "news" / "sentiment_analysis.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, default=str)

        # Also save a CSV summary for easy consumption
        csv_path = PROJECT_ROOT / "data" / "news" / "sentiment_timeseries.csv"
        _append_sentiment_csv(csv_path, result)

        direction = result["es_trading_direction"]
        newsletter_part = f", newsletter={direction.get('newsletter_sentiment', 0):+.3f}" if direction.get("newsletter_sentiment") else ""
        print(
            f"[Sentiment] ES direction: {direction['signal']} "
            f"(unified={direction.get('unified_sentiment', 0):+.3f}, "
            f"NLP_24h={direction['net_sentiment_24h']:+.3f}{newsletter_part}, "
            f"confidence={direction['confidence']:.0%})"
        )
        if direction.get("context_trend"):
            print(f"[Sentiment] Newsletter trend: {direction['context_trend']}, cross_validated={direction.get('cross_validated')}")
        if direction.get("context_levels"):
            print(f"[Sentiment] Key levels: {direction['context_levels']}")

    except Exception as e:
        print(f"[Sentiment] Analysis error: {e}")
        import traceback
        traceback.print_exc()


def _append_sentiment_csv(csv_path: Path, result: dict):
    """Append a row to the sentiment timeseries CSV."""
    import csv

    direction = result["es_trading_direction"]
    r24 = result["regime_24h"]

    row = {
        "timestamp": result["timestamp"],
        "signal": direction["signal"],
        "confidence": direction["confidence"],
        "unified_sentiment": direction.get("unified_sentiment", 0),
        "newsletter_sentiment": direction.get("newsletter_sentiment", 0),
        "nlp_sentiment_24h": direction.get("nlp_sentiment_24h", direction.get("net_sentiment_24h", 0)),
        "net_sentiment_72h": direction.get("net_sentiment_72h", 0),
        "net_sentiment_7d": direction.get("net_sentiment_7d", 0),
        "headline_count": result["headline_count"],
        "bullish_count_24h": r24["bullish_count"],
        "bearish_count_24h": r24["bearish_count"],
        "neutral_count_24h": r24["neutral_count"],
        "upgrade_count_24h": r24["upgrade_count"],
        "downgrade_count_24h": r24["downgrade_count"],
        "dominant_category": direction["dominant_category"],
        "context_trend": direction.get("context_trend", ""),
        "cross_validated": direction.get("cross_validated", ""),
    }

    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ─── IBKR Thread ──────────────────────────────────────────────

def _ib_thread():
    """Run IBKR connection in its own thread with auto-reconnect.

    On every (re)connect:
    1. Auto-detect port (TWS/Gateway)
    2. Fetch 1-week news headlines
    3. Run NLP sentiment analysis
    4. Start portfolio refresh loop
    """
    try:
        from ib_async import IB, Contract, Stock, Future, Option
    except ImportError:
        from ib_insync import IB, Contract, Stock, Future, Option

    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    client_id = int(os.environ.get("DASHBOARD_CLIENT_ID", "20"))
    reconnect_delay = 10  # seconds between reconnect attempts

    env_port = os.environ.get("IBKR_PORT")
    ports_to_try = [int(env_port)] if env_port else [7496, 7497, 4001, 4002]

    while True:
        ib = IB()
        global _ib_ref, _contract_cache_ref

        # ── Connect (auto-detect port) ──
        connected = False
        for port in ports_to_try:
            try:
                ib.connect(host, port, clientId=client_id, readonly=True)
                label = {7496: "TWS Live", 7497: "TWS Paper", 4001: "GW Live", 4002: "GW Paper"}.get(port, f"port {port}")
                print(f"[IB] Connected to {host}:{port} ({label}, clientId={client_id})")
                connected = True
                break
            except Exception:
                continue

        if not connected:
            print(f"[IB] Connection failed (tried {ports_to_try}), retrying in {reconnect_delay}s...")
            state.connected = False
            time.sleep(reconnect_delay)
            continue

        state.connected = True

        # ── Post-connect setup ──
        ib.reqMarketDataType(4)
        ib.sleep(3)

        _qualified_contracts: dict[int, Contract] = {}
        _ib_ref = ib
        _contract_cache_ref = _qualified_contracts

        # Initial portfolio refresh (skip prices for fast boot)
        _refresh_portfolio(ib, _qualified_contracts, skip_prices=True)
        print(f"[IB] Initial portfolio: {sum(len(p.get('positions',[])) for p in state.account_portfolios.values())} positions across {len(state.accounts)} accounts")

        # News tick handler
        def on_news_tick(news_tick):
            raw = news_tick.headline if hasattr(news_tick, "headline") else str(news_tick)
            parsed = parse_headline(raw)
            headline_dict = {
                "headline": parsed["headline"],
                "provider": news_tick.providerCode if hasattr(news_tick, "providerCode") else "?",
                "time": str(news_tick.timeStamp) if hasattr(news_tick, "timeStamp") else datetime.now().isoformat(),
                "articleId": news_tick.articleId if hasattr(news_tick, "articleId") else "",
                "metadata": parsed["metadata"],
            }
            state.add_headline(headline_dict)
            if _main_loop:
                asyncio.run_coroutine_threadsafe(
                    _broadcast({"type": "news", "data": headline_dict}),
                    _main_loop,
                )

        # Attach news event
        try:
            if hasattr(ib, "newsTicks") and hasattr(ib.newsTicks, "updateEvent"):
                ib.newsTicks.updateEvent += on_news_tick
            elif hasattr(ib, "wrapper") and hasattr(ib.wrapper, "tickNewsEvent"):
                ib.wrapper.tickNewsEvent += on_news_tick
        except Exception as e:
            print(f"[IB] News event attachment: {e}")

        # ── Fetch news + run sentiment (on every connect) ──
        _fetch_historical_news_and_sentiment(ib)

        # ── Main loop: portfolio refresh ──
        last_portfolio_refresh = 0

        while state.connected and ib.isConnected():
            try:
                ib.sleep(0.5)

                # Process pending chart/search requests from API thread
                with _chart_request_lock:
                    pending = list(_chart_request_queue)
                    _chart_request_queue.clear()
                for req in pending:
                    if "fn" in req:
                        try:
                            req["fn"]()
                        except Exception as e:
                            print(f"[IB] Request error: {e}")
                        finally:
                            req["event"].set()
                    else:
                        _process_chart_request(ib, _qualified_contracts, req)

                refresh_interval = 1.0 if state.live_mode else 10.0
                now = time.time()
                if now - last_portfolio_refresh >= refresh_interval:
                    last_portfolio_refresh = now
                    _refresh_portfolio(ib, _qualified_contracts)

            except Exception as e:
                print(f"[IB] Loop error: {e}")
                break

        # ── Disconnected — clean up and retry ──
        _ib_ref = None
        state.connected = False
        try:
            ib.disconnect()
        except Exception:
            pass
        print(f"[IB] Disconnected, reconnecting in {reconnect_delay}s...")
        time.sleep(reconnect_delay)


def _process_chart_request(ib, contract_cache, req):
    """Process a chart data request on the IB thread."""
    try:
        from ib_async import Contract as _C
    except ImportError:
        from ib_insync import Contract as _C

    con_id = req["con_id"]
    bar_size_setting = req["bar_size_setting"]
    duration = req["duration"]
    result_holder = req["result"]
    done_event = req["event"]

    try:
        # Get or qualify contract
        contract = contract_cache.get(con_id)
        if contract is None:
            contract = _C(conId=con_id)
            try:
                result = ib.qualifyContracts(contract)
                if not result:
                    done_event.set()
                    return
            except Exception:
                done_event.set()
                return

        for what in ("TRADES", "MIDPOINT"):
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size_setting,
                    whatToShow=what,
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    result_holder["bars"] = [
                        {
                            "time": int(b.date.timestamp()) if hasattr(b.date, "timestamp") else int(datetime.combine(b.date, datetime.min.time()).timestamp()) if hasattr(b.date, "year") else 0,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": getattr(b, "volume", 0) or 0,
                        }
                        for b in bars
                    ]
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"[IB] Chart request error: {e}")
    finally:
        done_event.set()


def _qualify_contract(ib, contract, cache):
    """Qualify a contract for market data requests, with caching."""
    try:
        from ib_async import Stock, Future, Option, Contract
    except ImportError:
        from ib_insync import Stock, Future, Option, Contract

    con_id = contract.conId
    if con_id in cache:
        return cache[con_id]

    try:
        # Use conId for all non-USD stocks (HKD, SGD, etc.) since SMART
        # routing doesn't resolve them by symbol alone
        if contract.secType == "STK" and contract.currency == "USD":
            qual = Stock(contract.symbol, "SMART", "USD")
        else:
            # conId-based qualification works for all sec types and exchanges
            qual = Contract(conId=con_id)

        result = ib.qualifyContracts(qual)
        if result:
            cache[con_id] = qual
            return qual
    except Exception:
        pass
    return None


def _fetch_market_prices(ib, position_items, contract_cache):
    """Request market data for all positions and return price dict keyed by conId."""
    try:
        from ib_async import Stock, Contract as _C
    except ImportError:
        from ib_insync import Stock, Contract as _C

    prices: dict[int, dict] = {}  # conId -> {current_price, prev_close}
    tickers = []
    contracts_for_cancel = []

    # Qualify and request market data for each position
    seen_con_ids = set()
    for item in position_items:
        con_id = item.contract.conId
        if con_id in seen_con_ids:
            continue
        seen_con_ids.add(con_id)

        qual = _qualify_contract(ib, item.contract, contract_cache)
        if qual is None:
            continue

        try:
            ticker = ib.reqMktData(qual, "221,588", False, False)
            tickers.append((con_id, ticker))
            contracts_for_cancel.append(qual)
        except Exception:
            pass

    # Wait for data to arrive
    if tickers:
        ib.sleep(3)

    # Extract prices from tickers
    for con_id, ticker in tickers:
        current_price = None
        price_source = None

        # Fallback chain: last > close > mid(bid,ask) > bid
        if ticker.last and ticker.last > 0:
            current_price = ticker.last
            price_source = "last"
        elif ticker.close and ticker.close > 0:
            current_price = ticker.close
            price_source = "close"
        elif ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
            current_price = (ticker.bid + ticker.ask) / 2
            price_source = "mid"
        elif ticker.bid and ticker.bid > 0:
            current_price = ticker.bid
            price_source = "bid"

        prev_close = ticker.close if ticker.close and ticker.close > 0 else None

        # Extract mark price (tick 221) and futures open interest (tick 588)
        mark_price = getattr(ticker, "markPrice", None)
        if mark_price and mark_price > 0:
            pass  # keep as-is
        else:
            mark_price = None
        futures_oi = getattr(ticker, "futuresOpenInterest", None)
        if futures_oi and futures_oi > 0:
            pass
        else:
            futures_oi = None

        prices[con_id] = {
            "current_price": current_price,
            "prev_close": prev_close,
            "price_source": price_source,
            "mark_price": mark_price,
            "futures_oi": futures_oi,
        }

    # Cancel all market data subscriptions
    for qual in contracts_for_cancel:
        try:
            ib.cancelMktData(qual)
        except Exception:
            pass

    return prices


def _refresh_portfolio(ib, contract_cache=None, skip_prices=False):
    """Fetch portfolio and account data from IBKR, grouped by account.

    Uses ib.positions() (always populated) instead of ib.portfolio()
    (requires per-account subscription which blocks on multi-account setups).
    Enriches positions with live market prices via reqMktData snapshots.
    """
    if contract_cache is None:
        contract_cache = {}

    try:
        position_items = ib.positions()

        # Fetch market prices for all positions (skip on initial boot for speed)
        prices = {} if skip_prices else _fetch_market_prices(ib, position_items, contract_cache)

        # Group positions by account
        positions_by_account: dict[str, list] = {}
        for item in position_items:
            c = item.contract
            multiplier = float(c.multiplier) if c.multiplier else 1.0
            con_id = c.conId

            # Get price data
            price_data = prices.get(con_id, {})
            current_price = price_data.get("current_price")
            prev_close = price_data.get("prev_close")
            mark_price = price_data.get("mark_price")
            futures_oi = price_data.get("futures_oi")

            # Compute per-position market value and P&L
            market_value = None
            unrealized_pnl = None
            pnl_pct = None
            if current_price is not None:
                market_value = current_price * item.position * multiplier
                cost_basis = item.avgCost * item.position
                unrealized_pnl = market_value - cost_basis
                if cost_basis != 0:
                    pnl_pct = round(unrealized_pnl / abs(cost_basis) * 100, 2)

            # Daily P&L: (current - prev_close) * position * multiplier
            daily_pnl = None
            if current_price is not None and prev_close is not None and prev_close > 0:
                daily_pnl = round((current_price - prev_close) * item.position * multiplier, 2)

            pos = {
                "symbol": c.symbol,
                "local_symbol": c.localSymbol or c.symbol,
                "sec_type": c.secType,
                "exchange": c.exchange or c.primaryExchange or "",
                "currency": c.currency,
                "position_size": item.position,
                "avg_cost": round(item.avgCost, 4),
                "multiplier": multiplier,
                "current_price": round(current_price, 4) if current_price else None,
                "prev_close": round(prev_close, 4) if prev_close else None,
                "market_price": round(current_price, 4) if current_price else None,
                "market_value": round(market_value, 2) if market_value is not None else None,
                "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                "realized_pnl": None,
                "pnl_pct": pnl_pct,
                "daily_pnl": daily_pnl,
                "account": item.account,
                "con_id": con_id,
                "mark_price": round(mark_price, 4) if mark_price else None,
                "futures_oi": int(futures_oi) if futures_oi else None,
                # Options fields
                "strike": c.strike if c.strike else None,
                "right": c.right if c.right else None,
                "expiry": c.lastTradeDateOrContractMonth if c.lastTradeDateOrContractMonth else None,
            }
            positions_by_account.setdefault(item.account, []).append(pos)

        # Parse account summary (NetLiq, AvailableFunds, GrossPositionValue, MaintMargin, UnrealizedPnL)
        acct_net_liq: dict[str, float] = {}
        acct_avail_funds: dict[str, float] = {}
        acct_total_value: dict[str, float] = {}
        acct_maint_margin: dict[str, float] = {}
        acct_summary_unrealized: dict[str, float] = {}
        try:
            acct_summary = ib.accountSummary()
            for av in acct_summary:
                if av.account == "All":
                    continue
                try:
                    val = float(av.value)
                except (ValueError, TypeError):
                    continue
                if av.tag == "NetLiquidation":
                    acct_net_liq[av.account] = val
                elif av.tag == "AvailableFunds":
                    acct_avail_funds[av.account] = val
                elif av.tag == "GrossPositionValue":
                    acct_total_value[av.account] = val
                elif av.tag == "MaintMarginReq":
                    acct_maint_margin[av.account] = val
                elif av.tag == "UnrealizedPnL":
                    acct_summary_unrealized[av.account] = val
        except Exception:
            pass

        # Parse accountValues for per-account P&L (BASE currency)
        acct_unrealized_pnl: dict[str, float] = {}
        acct_realized_pnl: dict[str, float] = {}
        try:
            acct_values = ib.accountValues()
            for av in acct_values:
                if av.currency != "BASE":
                    continue
                try:
                    val = float(av.value)
                except (ValueError, TypeError):
                    continue
                if av.tag == "UnrealizedPnL":
                    acct_unrealized_pnl[av.account] = val
                elif av.tag == "RealizedPnL":
                    acct_realized_pnl[av.account] = val
        except Exception:
            pass

        # Discover all accounts (from positions + account summary)
        all_accounts = sorted(set(
            list(positions_by_account.keys())
            + list(acct_net_liq.keys())
        ))

        # Build per-account portfolio data
        account_portfolios: dict[str, dict] = {}
        now = datetime.now().isoformat()
        for acct_id in all_accounts:
            positions = positions_by_account.get(acct_id, [])

            total_unrealized = acct_unrealized_pnl.get(acct_id, 0)
            total_realized = acct_realized_pnl.get(acct_id, 0)
            total_market_value = acct_total_value.get(acct_id, 0)

            # Compute cost basis from positions for P&L %
            cost_basis_total = sum(
                abs(p["position_size"]) * p["avg_cost"] for p in positions
            )

            # Prefer accountSummary UnrealizedPnL if available (more accurate)
            summary_unrealized = acct_summary_unrealized.get(acct_id)
            if summary_unrealized is not None:
                total_unrealized = summary_unrealized

            summary = {
                "total_market_value": total_market_value,
                "total_unrealized_pnl": total_unrealized,
                "total_realized_pnl": total_realized,
                "position_count": len(positions),
                "net_liquidation": acct_net_liq.get(acct_id),
                "available_funds": acct_avail_funds.get(acct_id),
                "maint_margin_req": acct_maint_margin.get(acct_id),
                "last_update": now,
                "total_pnl_pct": round(
                    total_unrealized / cost_basis_total * 100, 2
                ) if cost_basis_total > 0 and total_unrealized else None,
            }

            account_portfolios[acct_id] = {
                "summary": summary,
                "positions": positions,
            }

        # Fetch open orders grouped by account
        account_orders: dict[str, list] = {}
        try:
            open_trades = ib.openTrades()
            for trade in open_trades:
                o = trade.order
                s = trade.orderStatus
                c = trade.contract
                acct = o.account or "Unknown"
                order_dict = {
                    "symbol": c.symbol,
                    "local_symbol": c.localSymbol or c.symbol,
                    "sec_type": c.secType,
                    "action": o.action,
                    "order_type": o.orderType,
                    "total_qty": o.totalQuantity,
                    "limit_price": o.lmtPrice if o.lmtPrice and o.lmtPrice > 0 else None,
                    "aux_price": o.auxPrice if o.auxPrice and o.auxPrice > 0 else None,
                    "status": s.status,
                    "filled": s.filled,
                    "remaining": s.remaining,
                    "avg_fill_price": s.avgFillPrice if s.avgFillPrice and s.avgFillPrice > 0 else None,
                    "order_id": o.orderId,
                    "perm_id": o.permId,
                    "tif": o.tif or "DAY",
                }
                account_orders.setdefault(acct, []).append(order_dict)
        except Exception:
            pass

        state.update_portfolio(account_portfolios, all_accounts, account_orders)

        # Broadcast to WebSocket clients
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "portfolio", "data": state.get_all_portfolios()}),
            _main_loop,
        )

    except Exception as e:
        print(f"[IB] Portfolio refresh error: {e}")


# ─── WebSocket Broadcast ─────────────────────────────────────

_main_loop = None

async def _broadcast(message: dict):
    """Broadcast a message to all connected WebSocket clients."""
    if not state.ws_clients:
        return
    msg = json.dumps(message, default=str)
    disconnected = set()
    for ws in state.ws_clients.copy():
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.add(ws)
    state.ws_clients -= disconnected


# ─── FastAPI App ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_event_loop()

    # Init SQLite
    _init_db()

    # Start IBKR thread
    ib_t = threading.Thread(target=_ib_thread, daemon=True)
    ib_t.start()

    yield

    state.connected = False


app = FastAPI(title="IBKR Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth Endpoints ──────────────────────────────────────────

@app.post("/api/auth/register")
async def register(body: dict):
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    if not username or len(username) < 2:
        raise HTTPException(400, "Username must be at least 2 characters")
    if not password or len(password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            raise HTTPException(409, "Username already taken")
        salt = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, pw_hash, salt),
        )
        conn.commit()
        user_id = cursor.lastrowid
        token = _create_token(user_id, username)
        return {"token": token, "username": username}
    finally:
        conn.close()


@app.post("/api/auth/login")
async def login(body: dict):
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    conn = _get_db()
    try:
        row = conn.execute("SELECT id, password_hash, salt FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise HTTPException(401, "User not found — click Register to create an account")
        if _hash_password(password, row["salt"]) != row["password_hash"]:
            raise HTTPException(401, "Wrong password")
        token = _create_token(row["id"], username)
        return {"token": token, "username": username}
    finally:
        conn.close()


@app.get("/api/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return {"username": user["u"], "user_id": user["uid"]}


@app.get("/api/accounts")
async def get_accounts():
    return {"accounts": state.get_accounts()}


@app.get("/api/portfolio")
async def get_portfolio(account: str | None = None):
    return state.get_portfolio(account)


@app.get("/api/news")
async def get_news(count: int = 50):
    return {"headlines": state.get_news(count)}


@app.get("/api/sentiment")
async def get_sentiment():
    """Return latest NLP sentiment analysis for ES trading direction."""
    with _sentiment_lock:
        if _sentiment_results:
            return dict(_sentiment_results)
    # Try loading from saved file
    saved = PROJECT_ROOT / "data" / "news" / "sentiment_analysis.json"
    if saved.exists():
        try:
            return json.loads(saved.read_text())
        except Exception:
            pass
    return {"error": "No sentiment data available yet"}


@app.get("/api/sentiment/history")
async def get_sentiment_history():
    """Return sentiment timeseries (CSV rows as JSON array)."""
    csv_path = PROJECT_ROOT / "data" / "news" / "sentiment_timeseries.csv"
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for k in ("confidence", "unified_sentiment", "newsletter_sentiment",
                       "nlp_sentiment_24h", "net_sentiment_72h", "net_sentiment_7d",
                       "headline_count", "bullish_count_24h", "bearish_count_24h",
                       "neutral_count_24h", "upgrade_count_24h", "downgrade_count_24h"):
                if k in row and row[k]:
                    try:
                        row[k] = float(row[k])
                    except ValueError:
                        pass
            rows.append(row)
    return rows


@app.get("/api/status")
async def get_status():
    return state.get_status()


@app.post("/api/live")
async def toggle_live(enabled: bool = True):
    """Toggle per-second price refresh."""
    state.live_mode = enabled
    await _broadcast({"type": "live_mode", "data": {"enabled": enabled}})
    return {"live_mode": enabled}


@app.get("/api/live")
async def get_live_status():
    return {"live_mode": state.live_mode}


# Bar size mapping: query param -> (IBKR barSizeSetting, default duration)
_BAR_SIZE_MAP = {
    "1min": ("1 min", "1 D"),
    "5min": ("5 mins", "5 D"),
    "15min": ("15 mins", "10 D"),
    "1hour": ("1 hour", "30 D"),
    "1day": ("1 day", "1 Y"),
    "1week": ("1 week", "5 Y"),
}


@app.get("/api/chart")
async def get_chart_data(conId: int, barSize: str = "1hour"):
    """Fetch historical OHLCV bars for a contract."""
    if _ib_ref is None or not state.connected:
        return {"error": "Not connected to IBKR", "bars": []}

    if barSize not in _BAR_SIZE_MAP:
        return {"error": f"Invalid barSize. Use: {', '.join(_BAR_SIZE_MAP.keys())}", "bars": []}

    bar_size_setting, duration = _BAR_SIZE_MAP[barSize]

    # Submit request to the IB thread's queue and wait for result
    result_holder: dict = {"bars": None}
    done_event = threading.Event()

    req = {
        "con_id": conId,
        "bar_size_setting": bar_size_setting,
        "duration": duration,
        "result": result_holder,
        "event": done_event,
    }

    with _chart_request_lock:
        _chart_request_queue.append(req)

    # Wait up to 30s for the IB thread to process the request
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: done_event.wait(timeout=30))

    return {"bars": result_holder["bars"] or []}


@app.get("/api/news/article")
async def get_news_article(articleId: str, provider: str = ""):
    """Fetch full news article text via reqNewsArticle."""
    if _ib_ref is None or not state.connected:
        return {"error": "Not connected to IBKR"}

    result_holder: dict = {"article": None, "error": None}
    done_event = threading.Event()

    def _fetch():
        ib = _ib_ref
        try:
            article = ib.reqNewsArticle(provider, articleId)
            if article:
                result_holder["article"] = {
                    "articleType": getattr(article, 'articleType', ''),
                    "articleText": getattr(article, 'articleText', ''),
                }
            else:
                result_holder["error"] = "No article returned"
        except Exception as e:
            result_holder["error"] = str(e)

    req = {"fn": _fetch, "event": done_event}
    with _chart_request_lock:
        _chart_request_queue.append(req)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: done_event.wait(timeout=15))

    if result_holder["error"]:
        return {"error": result_holder["error"]}
    if result_holder["article"] is None:
        return {"error": "Timeout fetching article"}
    return result_holder["article"]


# ─── Watchlist Endpoints (SQLite + auth) ─────────────────────


@app.get("/api/watchlists")
async def list_watchlists(user: dict = Depends(get_current_user)):
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT w.id, w.name, COUNT(wi.id) as count FROM watchlists w LEFT JOIN watchlist_instruments wi ON w.id = wi.watchlist_id WHERE w.user_id = ? GROUP BY w.id",
            (user["uid"],),
        ).fetchall()
        return {"watchlists": [{"id": r["id"], "name": r["name"], "count": r["count"]} for r in rows]}
    finally:
        conn.close()


@app.post("/api/watchlists")
async def create_watchlist(body: dict, user: dict = Depends(get_current_user)):
    wl_id = f"wl_{int(time.time() * 1000)}"
    name = body.get("name", "New Watchlist")
    conn = _get_db()
    try:
        conn.execute("INSERT INTO watchlists (id, user_id, name) VALUES (?, ?, ?)", (wl_id, user["uid"], name))
        conn.commit()
        return {"id": wl_id, "name": name}
    finally:
        conn.close()


@app.put("/api/watchlists/{wl_id}")
async def update_watchlist(wl_id: str, body: dict, user: dict = Depends(get_current_user)):
    conn = _get_db()
    try:
        result = conn.execute("UPDATE watchlists SET name=? WHERE id=? AND user_id=?", (body.get("name", ""), wl_id, user["uid"]))
        conn.commit()
        if result.rowcount == 0:
            return {"error": "Watchlist not found"}
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/watchlists/{wl_id}")
async def delete_watchlist(wl_id: str, user: dict = Depends(get_current_user)):
    conn = _get_db()
    try:
        conn.execute("DELETE FROM watchlists WHERE id=? AND user_id=?", (wl_id, user["uid"]))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _fetch_yfinance_prices(symbols: list[str]) -> dict:
    """Fetch current prices via yfinance (fallback when IBKR not connected)."""
    import yfinance as yf
    prices = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                info = tickers.tickers[sym].fast_info
                current = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                prices[sym] = {"current_price": current, "prev_close": prev}
            except Exception:
                pass
    except Exception:
        pass
    return prices


@app.get("/api/watchlists/{wl_id}/instruments")
async def get_watchlist_instruments(wl_id: str, user: dict = Depends(get_current_user)):
    """Get instruments with live prices — IBKR if connected, else yfinance fallback."""
    conn = _get_db()
    try:
        wl = conn.execute("SELECT id FROM watchlists WHERE id=? AND user_id=?", (wl_id, user["uid"])).fetchone()
        if not wl:
            return {"error": "Watchlist not found", "instruments": []}
        rows = conn.execute(
            "SELECT con_id, symbol, local_symbol, sec_type, exchange, currency, name FROM watchlist_instruments WHERE watchlist_id=?",
            (wl_id,),
        ).fetchall()
    finally:
        conn.close()

    instruments = [
        {"conId": r["con_id"], "symbol": r["symbol"], "localSymbol": r["local_symbol"] or r["symbol"],
         "secType": r["sec_type"], "exchange": r["exchange"], "currency": r["currency"], "name": r["name"] or ""}
        for r in rows
    ]

    if not instruments:
        return {"instruments": instruments}

    # Try IBKR prices first
    ibkr_prices = {}
    if _ib_ref is not None and state.connected:
        ibkr_instruments = [i for i in instruments if i.get("conId")]
        if ibkr_instruments:
            result_holder: dict = {"prices": None}
            done_event = threading.Event()

            def _fetch():
                try:
                    from ib_async import Contract as _C
                except ImportError:
                    from ib_insync import Contract as _C
                prices = {}
                tickers_list = []
                contracts_cancel = []
                for inst in ibkr_instruments:
                    con_id = inst.get("conId")
                    if not con_id:
                        continue
                    contract = _contract_cache_ref.get(con_id) if _contract_cache_ref else None
                    if contract is None:
                        contract = _C(conId=con_id)
                        try:
                            _ib_ref.qualifyContracts(contract)
                        except Exception:
                            continue
                    try:
                        ticker = _ib_ref.reqMktData(contract, "221,588", False, False)
                        tickers_list.append((con_id, ticker))
                        contracts_cancel.append(contract)
                    except Exception:
                        pass
                if tickers_list:
                    _ib_ref.sleep(2)
                for con_id, ticker in tickers_list:
                    price = None
                    if ticker.last and ticker.last > 0:
                        price = ticker.last
                    elif ticker.close and ticker.close > 0:
                        price = ticker.close
                    elif ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
                        price = (ticker.bid + ticker.ask) / 2
                    prev_close = ticker.close if ticker.close and ticker.close > 0 else None
                    prices[con_id] = {"current_price": price, "prev_close": prev_close}
                for c in contracts_cancel:
                    try:
                        _ib_ref.cancelMktData(c)
                    except Exception:
                        pass
                result_holder["prices"] = prices

            req = {"fn": _fetch, "event": done_event}
            with _chart_request_lock:
                _chart_request_queue.append(req)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: done_event.wait(timeout=15))
            ibkr_prices = result_holder.get("prices") or {}

    # yfinance fallback for instruments without IBKR prices
    yf_symbols = [i["symbol"] for i in instruments if i.get("conId") not in ibkr_prices and i.get("secType") == "STK"]
    yf_prices = {}
    if yf_symbols:
        yf_prices = await asyncio.get_event_loop().run_in_executor(None, _fetch_yfinance_prices, yf_symbols)

    # Enrich
    enriched = []
    for inst in instruments:
        p = ibkr_prices.get(inst.get("conId"), {})
        current = p.get("current_price")
        prev = p.get("prev_close")
        # yfinance fallback
        if current is None and inst["symbol"] in yf_prices:
            yp = yf_prices[inst["symbol"]]
            current = yp.get("current_price")
            prev = yp.get("prev_close")
        change = None
        change_pct = None
        if current is not None and prev is not None and prev > 0:
            change = round(current - prev, 4)
            change_pct = round(change / prev * 100, 2)
        enriched.append({
            **inst,
            "current_price": round(current, 4) if current else None,
            "prev_close": round(prev, 4) if prev else None,
            "change": change,
            "change_pct": change_pct,
        })

    return {"instruments": enriched}


@app.post("/api/watchlists/{wl_id}/instruments")
async def add_watchlist_instrument(wl_id: str, body: dict, user: dict = Depends(get_current_user)):
    """Add an instrument to a watchlist."""
    conn = _get_db()
    try:
        wl = conn.execute("SELECT id FROM watchlists WHERE id=? AND user_id=?", (wl_id, user["uid"])).fetchone()
        if not wl:
            return {"error": "Watchlist not found"}
        symbol = body.get("symbol", "")
        con_id = body.get("conId")
        # Check duplicates by symbol
        existing = conn.execute(
            "SELECT id FROM watchlist_instruments WHERE watchlist_id=? AND symbol=?",
            (wl_id, symbol),
        ).fetchone()
        if existing:
            return {"error": "Instrument already in watchlist"}
        conn.execute(
            "INSERT INTO watchlist_instruments (watchlist_id, con_id, symbol, local_symbol, sec_type, exchange, currency, name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (wl_id, con_id, symbol, body.get("localSymbol", symbol), body.get("secType", "STK"), body.get("exchange", ""), body.get("currency", "USD"), body.get("name", "")),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/watchlists/{wl_id}/instruments/{instrument_id}")
async def remove_watchlist_instrument(wl_id: str, instrument_id: str, user: dict = Depends(get_current_user)):
    """Remove instrument by symbol or conId."""
    conn = _get_db()
    try:
        wl = conn.execute("SELECT id FROM watchlists WHERE id=? AND user_id=?", (wl_id, user["uid"])).fetchone()
        if not wl:
            return {"error": "Watchlist not found"}
        # Try as conId (number) first, then as symbol
        try:
            con_id = int(instrument_id)
            conn.execute("DELETE FROM watchlist_instruments WHERE watchlist_id=? AND con_id=?", (wl_id, con_id))
        except ValueError:
            conn.execute("DELETE FROM watchlist_instruments WHERE watchlist_id=? AND symbol=?", (wl_id, instrument_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ─── Symbol Search (Yahoo Finance + IBKR) ────────────────────

_YF_SEARCH_CACHE: dict = {}
_YF_CACHE_TTL = 300  # 5 minutes


def _yahoo_search(query: str) -> list[dict]:
    """Search symbols via Yahoo Finance autocomplete API."""
    import urllib.request
    import urllib.parse

    cache_key = query.upper()
    cached = _YF_SEARCH_CACHE.get(cache_key)
    if cached and time.time() - cached["t"] < _YF_CACHE_TTL:
        return cached["results"]

    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=12&newsCount=0&listsCount=0&enableFuzzyQuery=false"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        results = []
        for q in data.get("quotes", []):
            sym = q.get("symbol", "")
            qtype = q.get("quoteType", "")
            sec_type = "STK"
            if qtype == "FUTURE":
                sec_type = "FUT"
            elif qtype == "ETF":
                sec_type = "STK"
            elif qtype == "INDEX":
                sec_type = "IND"
            elif qtype == "MUTUALFUND":
                sec_type = "FUND"
            elif qtype == "CRYPTOCURRENCY":
                sec_type = "CRYPTO"
            results.append({
                "symbol": sym.split(".")[0] if "." in sym and qtype != "FUTURE" else sym,
                "localSymbol": sym,
                "name": q.get("shortname") or q.get("longname") or "",
                "secType": sec_type,
                "exchange": q.get("exchange", ""),
                "currency": q.get("currency", "USD") if q.get("currency") else "USD",
                "conId": None,
                "source": "yahoo",
            })
        _YF_SEARCH_CACHE[cache_key] = {"t": time.time(), "results": results}
        return results
    except Exception:
        return []


@app.get("/api/search")
async def search_symbol(q: str):
    """Search symbols — Yahoo Finance + IBKR reqMatchingSymbols (fuzzy, all instrument types)."""
    if not q:
        return {"results": []}

    loop = asyncio.get_event_loop()

    # Run Yahoo Finance and IBKR search in parallel
    yf_results = await loop.run_in_executor(None, _yahoo_search, q)

    ibkr_results = []
    if _ib_ref is not None and state.connected:
        result_holder: dict = {"results": None}
        done_event = threading.Event()

        def _ibkr_search():
            results = []
            try:
                # reqMatchingSymbols: fuzzy search across all instrument types
                # Returns list of ContractDescription with .contract and .derivativeSecTypes
                matches = _ib_ref.reqMatchingSymbols(q.upper())
                if matches:
                    for cd in matches[:10]:
                        c = cd.contract
                        # derivativeSecTypes lists available derivative types (e.g. ['FUT', 'OPT'])
                        desc = getattr(cd, "longName", "") or ""
                        results.append({
                            "conId": c.conId,
                            "symbol": c.symbol,
                            "localSymbol": c.localSymbol or c.symbol,
                            "name": desc,
                            "secType": c.secType,
                            "exchange": c.primaryExchange or c.exchange or "",
                            "currency": c.currency or "USD",
                            "source": "ibkr",
                        })
            except Exception:
                pass
            result_holder["results"] = results

        req = {"fn": _ibkr_search, "event": done_event}
        with _chart_request_lock:
            _chart_request_queue.append(req)
        await loop.run_in_executor(None, lambda: done_event.wait(timeout=8))
        ibkr_results = result_holder.get("results") or []

    # Merge: IBKR results first (with conId), then Yahoo results (deduplicated)
    seen_symbols = set()
    merged = []
    for r in ibkr_results:
        key = f"{r['symbol']}_{r['secType']}_{r.get('currency', '')}"
        if key not in seen_symbols:
            seen_symbols.add(key)
            merged.append(r)
    for r in yf_results:
        key = f"{r['symbol']}_{r['secType']}_{r.get('currency', '')}"
        if key not in seen_symbols:
            seen_symbols.add(key)
            merged.append(r)

    return {"results": merged}


@app.get("/api/instrument-details")
async def instrument_details(conId: int):
    """Fetch full contract details + related delivery months (futures) + open interest."""
    if _ib_ref is None or not state.connected:
        return {"error": "Not connected to IBKR"}

    loop = asyncio.get_event_loop()
    result_holder: dict = {"data": None}
    done_event = threading.Event()

    def _fetch_details():
        try:
            from ib_async import Contract as _C
        except ImportError:
            from ib_insync import Contract as _C

        ib = _ib_ref
        data: dict = {}

        try:
            # 1. Get full contract details for the clicked instrument
            base_contract = _C(conId=conId)
            details_list = ib.reqContractDetails(base_contract)
            if not details_list:
                result_holder["data"] = {"error": "Contract not found"}
                return

            cd = details_list[0]
            c = cd.contract
            data = {
                "conId": c.conId,
                "symbol": c.symbol,
                "localSymbol": c.localSymbol or c.symbol,
                "secType": c.secType,
                "exchange": c.primaryExchange or c.exchange or "",
                "currency": c.currency or "USD",
                "longName": cd.longName or "",
                "category": cd.category or "",
                "subcategory": cd.subcategory or "",
                "multiplier": c.multiplier or "",
                "minTick": cd.minTick or 0,
                "lastTradeDate": c.lastTradeDateOrContractMonth or "",
                "tradingHours": cd.tradingHours or "",
                "relatedContracts": [],
            }

            # 2. For futures (or indices with futures): get all delivery months
            if c.secType in ("FUT", "IND"):
                partial = _C(
                    symbol=c.symbol,
                    secType="FUT",
                    exchange=c.exchange or "",
                    currency=c.currency or "USD",
                )
                all_details = ib.reqContractDetails(partial)
                if all_details:
                    # Sort by expiry date
                    all_details.sort(
                        key=lambda d: d.contract.lastTradeDateOrContractMonth or ""
                    )
                    # Cap at 12 delivery months, OI for nearest 6 only
                    related = all_details[:12]

                    # 3. Fetch open interest for nearest delivery months
                    tickers = []
                    for rd in related[:6]:
                        rc = rd.contract
                        try:
                            ib.qualifyContracts(rc)
                            t = ib.reqMktData(rc, "588", snapshot=True, regulatorySnapshot=False)
                            tickers.append((rd, t))
                        except Exception:
                            tickers.append((rd, None))

                    # Wait for OI data to populate
                    ib.sleep(3)

                    for rd, t in tickers:
                        rc = rd.contract
                        oi = None
                        if t is not None:
                            oi_val = getattr(t, "futuresOpenInterest", None)
                            if oi_val is not None and oi_val > 0:
                                oi = int(oi_val)
                            try:
                                ib.cancelMktData(rc)
                            except Exception:
                                pass

                        data["relatedContracts"].append({
                            "conId": rc.conId,
                            "symbol": rc.symbol,
                            "localSymbol": rc.localSymbol or rc.symbol,
                            "lastTradeDate": rc.lastTradeDateOrContractMonth or "",
                            "multiplier": rc.multiplier or "",
                            "exchange": rc.primaryExchange or rc.exchange or "",
                            "currency": rc.currency or "USD",
                            "name": rd.longName or "",
                            "openInterest": oi,
                        })

        except Exception as e:
            data["error"] = str(e)

        result_holder["data"] = data

    req = {"fn": _fetch_details, "event": done_event}
    with _chart_request_lock:
        _chart_request_queue.append(req)
    await loop.run_in_executor(None, lambda: done_event.wait(timeout=30))

    return result_holder.get("data") or {"error": "Timeout fetching details"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.ws_clients.add(ws)

    # Send initial snapshot
    try:
        await ws.send_text(json.dumps({
            "type": "portfolio",
            "data": state.get_all_portfolios(),
        }, default=str))
        await ws.send_text(json.dumps({
            "type": "news_batch",
            "data": state.get_news(100),
        }, default=str))
        await ws.send_text(json.dumps({
            "type": "status",
            "data": state.get_status(),
        }, default=str))
    except Exception:
        pass

    try:
        while True:
            msg = await ws.receive_text()
            # Handle client commands
            if msg == "ping":
                continue
            try:
                cmd = json.loads(msg)
                if cmd.get("type") == "toggle_live":
                    state.live_mode = cmd.get("enabled", not state.live_mode)
                    await _broadcast({"type": "live_mode", "data": {"enabled": state.live_mode}})
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_clients.discard(ws)


# ─── Base-path API forwarding ────────────────────────────────
# Frontend uses /IBKR_KZ/api/* URLs (matching nginx proxy on VPS).
# Locally, forward these to the real /api/* routes via redirect.
from fastapi.responses import RedirectResponse, HTMLResponse


@app.api_route("/IBKR_KZ/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def forward_api(path: str, request: Request):
    """Forward /IBKR_KZ/api/* to /api/* for local dev (nginx handles this on VPS)."""
    qs = str(request.url.query)
    target = f"/api/{path}" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=target, status_code=307)


@app.websocket("/IBKR_KZ/ws")
async def forward_ws(ws: WebSocket):
    """Forward /IBKR_KZ/ws to /ws for local dev."""
    # Re-dispatch to the real websocket endpoint
    await websocket_endpoint(ws)


# Serve frontend static files in production
dist_path = Path(__file__).parent / "frontend" / "dist"
if dist_path.exists():
    @app.get("/")
    async def redirect_to_app():
        return RedirectResponse(url="/IBKR_KZ/")

    # SPA catch-all: serve index.html for any /IBKR_KZ/* route not matching a static asset
    _index_html = (dist_path / "index.html").read_text()

    @app.get("/IBKR_KZ/{full_path:path}")
    async def spa_catchall(full_path: str):
        # Check if it's a real static file (assets)
        static_file = dist_path / full_path
        if static_file.is_file() and not full_path.endswith(".html"):
            return FileResponse(str(static_file))
        return HTMLResponse(_index_html)

    # Serve static assets
    app.mount("/IBKR_KZ/assets", StaticFiles(directory=str(dist_path / "assets")), name="frontend-assets")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DASHBOARD_PORT", "8888"))
    print(f"Starting dashboard backend on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
