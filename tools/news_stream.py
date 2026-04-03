"""
News Streaming Module — Multi-Provider Financial News Aggregation

Providers:
  1. IBGatewayProvider   — IB Gateway via ib_insync/ib_async (free, real-time)
  2. FinnhubProvider     — Finnhub REST + WebSocket (free tier: 60 req/min)
  3. BenzingaProvider    — Benzinga REST + WebSocket (free tier: headlines + teasers)
  4. BriefingProvider    — Briefing.com (IB-only, no standalone API)
  5. FinlightProvider    — finlight.me REST + WebSocket (free: 5K req/mo, 12hr delay)

Usage:
    from tools.news_stream import get_news, get_news_sentiment, search_news

    # Fetch recent headlines
    articles = get_news(tickers=["AAPL", "ES"], hours_back=24)

    # Aggregate sentiment
    sentiment = get_news_sentiment("AAPL")

    # Search
    results = search_news("fed rate decision", days_back=7)
"""

import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from tools.config import PROJECT_ROOT

# ─── Common Article Schema ─────────────────────────────────────

def _make_article(
    id: str,
    provider: str,
    headline: str,
    summary: Optional[str] = None,
    body: Optional[str] = None,
    url: Optional[str] = None,
    source: str = "",
    published_at: str = "",
    tickers: Optional[list] = None,
    categories: Optional[list] = None,
    sentiment_label: str = "unknown",
    sentiment_score: float = 0.0,
    sentiment_confidence: float = 0.0,
    sentiment_method: str = "provider",
    raw: Optional[dict] = None,
) -> dict:
    """Create a normalised article dict."""
    return {
        "id": id,
        "provider": provider,
        "headline": headline,
        "summary": summary,
        "body": body,
        "url": url,
        "source": source,
        "published_at": published_at,
        "tickers": tickers or [],
        "categories": categories or [],
        "sentiment": {
            "label": sentiment_label,
            "score": sentiment_score,
            "confidence": sentiment_confidence,
            "method": sentiment_method,
        },
        "raw": raw or {},
    }


# ─── News Cache ────────────────────────────────────────────────

class NewsCache:
    """Simple TTL-based in-memory cache for news articles."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: dict = {}  # key -> (timestamp, data)

    def get(self, key: str):
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self.ttl:
                return data
            del self._cache[key]
        return None

    def set(self, key: str, data):
        self._cache[key] = (time.time(), data)

    def clear(self):
        self._cache.clear()


_cache = NewsCache(ttl_seconds=300)


# ─── Abstract Base Provider ────────────────────────────────────

class NewsProvider(ABC):
    """Abstract base class for news providers."""

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if provider has required API keys / connections."""
        pass

    @abstractmethod
    def fetch_news(
        self,
        tickers: Optional[list] = None,
        category: Optional[str] = None,
        limit: int = 20,
        hours_back: int = 24,
    ) -> list[dict]:
        """Fetch recent headlines. Returns list of normalised article dicts."""
        pass

    def fetch_sentiment(self, ticker: str) -> Optional[dict]:
        """Fetch sentiment for a ticker. Override if provider supports it."""
        return None

    def search(self, query: str, days_back: int = 7, limit: int = 50) -> list[dict]:
        """Search news by keyword. Override if provider supports it."""
        return []


# ─── Provider 1: IB Gateway ───────────────────────────────────

class IBGatewayProvider(NewsProvider):
    """News via Interactive Brokers Gateway (ib_insync or ib_async).

    Free providers: BRFG (Briefing.com), BRFUPDN (Analyst Actions), DJNL (Dow Jones)
    Requires IB Gateway running locally.
    """

    name = "ibkr"

    # Free IB news provider codes
    DEFAULT_PROVIDERS = "BRFG+BRFUPDN+DJNL"

    def __init__(self):
        self._ib = None
        self.host = os.environ.get("IB_GATEWAY_HOST", os.environ.get("IBKR_HOST", "127.0.0.1"))
        self.port = int(os.environ.get("IB_GATEWAY_PORT", os.environ.get("IBKR_PORT", "4001")))
        self.client_id = int(os.environ.get("IB_NEWS_CLIENT_ID", "10"))

    def is_configured(self) -> bool:
        return True  # IB Gateway just needs to be running

    def _connect(self):
        """Connect to IB Gateway if not connected."""
        if self._ib is not None and self._ib.isConnected():
            return self._ib

        try:
            # Try ib_async first, fall back to ib_insync
            try:
                from ib_async import IB
            except ImportError:
                from ib_insync import IB

            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id, readonly=True)
            return self._ib
        except Exception as e:
            print(f"[IBGateway] Connection failed: {e}")
            return None

    def _disconnect(self):
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    def fetch_news(self, tickers=None, category=None, limit=20, hours_back=24):
        ib = self._connect()
        if ib is None:
            return []

        articles = []
        try:
            if tickers:
                # Fetch news for specific contracts
                try:
                    from ib_async import Stock, Future
                except ImportError:
                    from ib_insync import Stock, Future

                for ticker in tickers[:5]:  # Limit to avoid rate issues
                    # Try as stock first, then as future
                    contract = Stock(ticker, "SMART", "USD")
                    qualified = ib.qualifyContracts(contract)
                    if not qualified:
                        contract = Future(ticker, exchange="CME", currency="USD")
                        qualified = ib.qualifyContracts(contract)
                    if not qualified:
                        continue

                    contract = qualified[0]
                    headlines = ib.reqHistoricalNews(
                        conId=contract.conId,
                        providerCodes=self.DEFAULT_PROVIDERS,
                        startDateTime="",
                        endDateTime="",
                        totalResults=min(limit, 100),
                    )

                    for h in headlines:
                        articles.append(_make_article(
                            id=f"ibkr:{h.articleId}",
                            provider="ibkr",
                            headline=h.headline,
                            source=h.providerCode,
                            published_at=str(h.time),
                            tickers=[ticker],
                            sentiment_method="agent",  # IB doesn't provide sentiment
                            raw={"articleId": h.articleId, "providerCode": h.providerCode},
                        ))
                    time.sleep(1)
            else:
                # Broad tape: all headlines from free providers
                for provider_code in ["BRFG", "BRFUPDN"]:
                    try:
                        from ib_async import Contract
                    except ImportError:
                        from ib_insync import Contract

                    news_contract = Contract()
                    news_contract.symbol = f"{provider_code}:{provider_code}_ALL"
                    news_contract.secType = "NEWS"
                    news_contract.exchange = provider_code

                    # Use historical headlines for REST-style access
                    headlines = ib.reqHistoricalNews(
                        conId=0,  # 0 for broadtape
                        providerCodes=provider_code,
                        startDateTime="",
                        endDateTime="",
                        totalResults=min(limit, 100),
                    )

                    for h in headlines:
                        articles.append(_make_article(
                            id=f"ibkr:{h.articleId}",
                            provider="ibkr",
                            headline=h.headline,
                            source=h.providerCode,
                            published_at=str(h.time),
                            sentiment_method="agent",
                            raw={"articleId": h.articleId, "providerCode": h.providerCode},
                        ))
                    time.sleep(1)

        except Exception as e:
            print(f"[IBGateway] Error fetching news: {e}")
        finally:
            self._disconnect()

        return articles[:limit]

    def list_providers(self) -> list:
        """List available news providers on this IB account."""
        ib = self._connect()
        if ib is None:
            return []
        try:
            providers = ib.reqNewsProviders()
            return [{"code": p.code, "name": p.name} for p in providers]
        except Exception as e:
            print(f"[IBGateway] Error listing providers: {e}")
            return []
        finally:
            self._disconnect()


# ─── Provider 2: Finnhub ──────────────────────────────────────

class FinnhubProvider(NewsProvider):
    """Finnhub REST API for news + sentiment.

    Free tier: 60 calls/min, WebSocket for 50 symbols.
    API key required: FINNHUB_API_KEY in .env
    """

    name = "finnhub"
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self):
        self.api_key = os.environ.get("FINNHUB_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, endpoint: str, params: dict = None) -> dict:
        import requests
        params = params or {}
        params["token"] = self.api_key
        resp = requests.get(f"{self.BASE_URL}/{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def fetch_news(self, tickers=None, category=None, limit=20, hours_back=24):
        articles = []

        if tickers:
            for ticker in tickers[:5]:
                now = datetime.now()
                from_date = (now - timedelta(hours=hours_back)).strftime("%Y-%m-%d")
                to_date = now.strftime("%Y-%m-%d")
                try:
                    data = self._request("company-news", {
                        "symbol": ticker,
                        "from": from_date,
                        "to": to_date,
                    })
                    for item in data[:limit]:
                        articles.append(self._normalize(item, ticker))
                except Exception as e:
                    print(f"[Finnhub] Error for {ticker}: {e}")
        else:
            cat = category or "general"
            try:
                data = self._request("news", {"category": cat})
                for item in data[:limit]:
                    articles.append(self._normalize(item))
            except Exception as e:
                print(f"[Finnhub] Error fetching general news: {e}")

        return articles[:limit]

    def fetch_sentiment(self, ticker: str) -> Optional[dict]:
        try:
            data = self._request("news-sentiment", {"symbol": ticker})
            if not data:
                return None
            sentiment = data.get("sentiment", {})
            score = data.get("companyNewsScore", 0)
            label = "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral")
            return {
                "ticker": ticker,
                "label": label,
                "score": score,
                "bullish_pct": sentiment.get("bullishPercent", 0),
                "bearish_pct": sentiment.get("bearishPercent", 0),
                "buzz": data.get("buzz", {}).get("buzz", 0),
                "articles_last_week": data.get("buzz", {}).get("articlesInLastWeek", 0),
            }
        except Exception as e:
            print(f"[Finnhub] Sentiment error for {ticker}: {e}")
            return None

    def search(self, query: str, days_back=7, limit=50):
        # Finnhub doesn't have keyword search; use general news
        return self.fetch_news(category="general", limit=limit, hours_back=days_back * 24)

    def _normalize(self, item: dict, ticker: str = "") -> dict:
        ts = item.get("datetime", 0)
        published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
        related = item.get("related", "")
        tickers = [t.strip() for t in related.split(",") if t.strip()] if related else []
        if ticker and ticker not in tickers:
            tickers.insert(0, ticker)

        return _make_article(
            id=f"finnhub:{item.get('id', '')}",
            provider="finnhub",
            headline=item.get("headline", ""),
            summary=item.get("summary"),
            url=item.get("url"),
            source=item.get("source", ""),
            published_at=published,
            tickers=tickers,
            categories=[item.get("category", "")],
            raw=item,
        )


# ─── Provider 3: Benzinga ────────────────────────────────────

class BenzingaProvider(NewsProvider):
    """Benzinga REST API for news headlines.

    Free tier: headlines + teasers. Full body requires paid tier.
    API key required: BENZINGA_API_KEY in .env
    """

    name = "benzinga"
    BASE_URL = "https://api.benzinga.com/api/v2/news"

    def __init__(self):
        self.api_key = os.environ.get("BENZINGA_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_news(self, tickers=None, category=None, limit=20, hours_back=24):
        import requests

        params = {
            "token": self.api_key,
            "pageSize": min(limit, 100),
        }
        if tickers:
            params["tickers"] = ",".join(tickers)
        if category:
            params["channels"] = category

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return [self._normalize(item) for item in data[:limit]]
        except Exception as e:
            print(f"[Benzinga] Error: {e}")
            return []

    def search(self, query: str, days_back=7, limit=50):
        # Benzinga doesn't have keyword search in free tier
        return self.fetch_news(limit=limit, hours_back=days_back * 24)

    def _normalize(self, item: dict) -> dict:
        tickers = [s.get("name", "") for s in item.get("stocks", []) if s.get("name")]
        created = item.get("created", "")

        return _make_article(
            id=f"benzinga:{item.get('id', '')}",
            provider="benzinga",
            headline=item.get("title", ""),
            summary=item.get("teaser"),
            body=item.get("body"),
            url=item.get("url"),
            source="Benzinga",
            published_at=created,
            tickers=tickers,
            categories=item.get("channels", []),
            sentiment_method="agent",  # Benzinga doesn't provide sentiment
            raw=item,
        )


# ─── Provider 4: Briefing.com (IB-only) ──────────────────────

class BriefingProvider(NewsProvider):
    """Briefing.com via IB Gateway.

    No standalone API. Accessed through IBGatewayProvider with BRFG/BRFUPDN codes.
    This is a thin wrapper that delegates to IBGatewayProvider.
    """

    name = "briefing"

    def __init__(self):
        self._ib_provider = IBGatewayProvider()

    def is_configured(self) -> bool:
        return True  # Same as IB Gateway

    def fetch_news(self, tickers=None, category=None, limit=20, hours_back=24):
        return self._ib_provider.fetch_news(tickers=tickers, limit=limit, hours_back=hours_back)


# ─── Provider 5: finlight.me ─────────────────────────────────

class FinlightProvider(NewsProvider):
    """finlight.me REST API for news + sentiment.

    Free tier: 5K req/mo, 12-hr delay, no sentiment.
    Paid tiers: real-time, sentiment, WebSocket.
    API key required: FINLIGHT_API_KEY in .env
    """

    name = "finlight"
    BASE_URL = "https://api.finlight.me/v2/articles"

    def __init__(self):
        self.api_key = os.environ.get("FINLIGHT_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_news(self, tickers=None, category=None, limit=20, hours_back=24):
        import requests

        now = datetime.now(tz=timezone.utc)
        from_dt = (now - timedelta(hours=hours_back)).isoformat()

        body = {
            "pageSize": min(limit, 50),
            "from": from_dt,
            "language": "en",
            "order": "DESC",
        }
        if tickers:
            body["tickers"] = tickers

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.BASE_URL, json=body, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            articles = data if isinstance(data, list) else data.get("articles", [])
            return [self._normalize(item) for item in articles[:limit]]
        except Exception as e:
            print(f"[Finlight] Error: {e}")
            return []

    def search(self, query: str, days_back=7, limit=50):
        import requests

        now = datetime.now(tz=timezone.utc)
        from_dt = (now - timedelta(days=days_back)).isoformat()

        body = {
            "query": query,
            "from": from_dt,
            "pageSize": min(limit, 50),
            "language": "en",
            "order": "DESC",
        }

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.BASE_URL, json=body, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            articles = data if isinstance(data, list) else data.get("articles", [])
            return [self._normalize(item) for item in articles[:limit]]
        except Exception as e:
            print(f"[Finlight] Search error: {e}")
            return []

    def _normalize(self, item: dict) -> dict:
        sentiment = item.get("sentiment", {})
        label = sentiment.get("polarity", "unknown") if sentiment else "unknown"
        score = sentiment.get("score", 0.0) if sentiment else 0.0
        confidence = sentiment.get("confidence", 0.0) if sentiment else 0.0

        return _make_article(
            id=f"finlight:{item.get('id', '')}",
            provider="finlight",
            headline=item.get("title", ""),
            summary=item.get("description"),
            body=item.get("content"),
            url=item.get("url"),
            source=item.get("source", {}).get("name", "") if isinstance(item.get("source"), dict) else str(item.get("source", "")),
            published_at=item.get("publishedAt", ""),
            tickers=item.get("tickers", []),
            categories=item.get("categories", []),
            sentiment_label=label,
            sentiment_score=score,
            sentiment_confidence=confidence,
            sentiment_method="provider" if sentiment else "agent",
            raw=item,
        )


# ─── News Aggregator ─────────────────────────────────────────

class NewsAggregator:
    """Fan-out across providers, deduplicate, merge."""

    # Provider priority chain
    PROVIDER_CLASSES = [
        IBGatewayProvider,
        FinnhubProvider,
        FinlightProvider,
        BenzingaProvider,
    ]

    def __init__(self):
        self.providers = [cls() for cls in self.PROVIDER_CLASSES]

    def get_configured_providers(self) -> list[NewsProvider]:
        return [p for p in self.providers if p.is_configured()]

    def get_provider(self, name: str) -> Optional[NewsProvider]:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def fetch_news(
        self,
        tickers: Optional[list] = None,
        category: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 20,
        hours_back: int = 24,
    ) -> list[dict]:
        """Fetch news from configured providers."""
        cache_key = f"news:{','.join(tickers or [])}:{category}:{provider}:{hours_back}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached[:limit]

        if provider:
            p = self.get_provider(provider)
            if p and p.is_configured():
                articles = p.fetch_news(tickers, category, limit, hours_back)
            else:
                print(f"Provider '{provider}' not configured")
                articles = []
        else:
            # Fan out to all configured providers
            articles = []
            for p in self.get_configured_providers():
                try:
                    result = p.fetch_news(tickers, category, limit, hours_back)
                    articles.extend(result)
                except Exception as e:
                    print(f"[{p.name}] Error: {e}")

        # Deduplicate by headline similarity (simple: exact match)
        seen = set()
        deduped = []
        for a in articles:
            key = a["headline"].lower().strip()[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(a)

        # Sort by published_at descending
        deduped.sort(key=lambda a: a.get("published_at", ""), reverse=True)

        _cache.set(cache_key, deduped)
        return deduped[:limit]

    def get_sentiment(self, ticker: str) -> dict:
        """Aggregate sentiment from all providers that support it."""
        results = {}
        for p in self.get_configured_providers():
            sent = p.fetch_sentiment(ticker)
            if sent:
                results[p.name] = sent

        if not results:
            return {"ticker": ticker, "providers": {}, "composite_score": 0, "composite_label": "unknown"}

        # Compute composite
        scores = [v.get("score", 0) for v in results.values() if v.get("score") is not None]
        composite = sum(scores) / len(scores) if scores else 0
        label = "positive" if composite > 0.2 else ("negative" if composite < -0.2 else "neutral")

        return {
            "ticker": ticker,
            "providers": results,
            "composite_score": round(composite, 4),
            "composite_label": label,
        }

    def search(self, query: str, days_back: int = 7, provider: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Search across providers."""
        if provider:
            p = self.get_provider(provider)
            if p and p.is_configured():
                return p.search(query, days_back, limit)
            return []

        articles = []
        for p in self.get_configured_providers():
            try:
                articles.extend(p.search(query, days_back, limit))
            except Exception:
                pass

        articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)
        return articles[:limit]


# ─── Module-Level Convenience Functions ───────────────────────

_aggregator = None

def _get_aggregator():
    global _aggregator
    if _aggregator is None:
        _aggregator = NewsAggregator()
    return _aggregator


def get_news(
    tickers: Optional[list] = None,
    category: Optional[str] = None,
    provider: Optional[str] = None,
    limit: int = 20,
    hours_back: int = 24,
) -> list[dict]:
    """Fetch recent news headlines with sentiment. Uses provider priority chain."""
    return _get_aggregator().fetch_news(tickers, category, provider, limit, hours_back)


def get_news_sentiment(ticker: str) -> dict:
    """Aggregate sentiment across all providers for a ticker."""
    return _get_aggregator().get_sentiment(ticker)


def search_news(
    query: str,
    days_back: int = 7,
    provider: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Keyword search across news providers."""
    return _get_aggregator().search(query, days_back, provider, limit)


def list_providers() -> list[dict]:
    """List all providers and their configuration status."""
    agg = _get_aggregator()
    return [
        {"name": p.name, "configured": p.is_configured()}
        for p in agg.providers
    ]


# ─── CLI Entry Point ─────────────────────────────────────────

def main():
    """CLI for testing news functions."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python news_stream.py [news|sentiment|search|providers] [args]")
        return

    cmd = sys.argv[1]

    if cmd == "providers":
        for p in list_providers():
            status = "configured" if p["configured"] else "NOT configured"
            print(f"  {p['name']}: {status}")

    elif cmd == "news":
        tickers = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        articles = get_news(tickers=tickers, limit=10)
        for a in articles:
            print(f"[{a['provider']}] {a['published_at'][:16]} | {a['headline'][:80]}")
            if a["tickers"]:
                print(f"  Tickers: {', '.join(a['tickers'])}")

    elif cmd == "sentiment":
        ticker = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
        result = get_news_sentiment(ticker)
        print(json.dumps(result, indent=2))

    elif cmd == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "market"
        results = search_news(query, limit=10)
        for a in results:
            print(f"[{a['provider']}] {a['published_at'][:16]} | {a['headline'][:80]}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
