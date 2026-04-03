# News Streaming Skill — Architecture & Provider Requirements

**Version:** 1.0 | **Date:** 2026-03-22 | **Status:** Design Phase

---

## 1. Skill Architecture

### 1.1 Purpose

Add a `tools/news_stream.py` module that ingests financial news headlines from one or more providers, normalises them into a common schema, and exposes sentiment-scored articles to the agent for macro/equity/commodity analysis. The module follows the same patterns as `tools/web_search.py` (primary provider + fallback) and `tools/fred_data.py` (local-first data hierarchy with caching).

### 1.2 Where It Fits in the Data Hierarchy

Current hierarchy (from CLAUDE.md):

1. Local CSVs (`/macro_2/historical_data/`)
2. FRED API fallback
3. yfinance on-demand
4. Newsletter digest (`guides/market_context.md`)
5. Web search + Twitter search

**Proposed update — insert at position 4.5:**

1. Local CSVs
2. FRED API fallback
3. yfinance on-demand
4. Newsletter digest (`guides/market_context.md`)
5. **News stream** (`tools/news_stream.py`) — structured, real-time/near-real-time headlines with sentiment
6. Web search + Twitter search — unstructured, on-demand

### 1.3 Module Design

```
tools/news_stream.py
├── NewsProvider (abstract base)
│   ├── IBGatewayProvider        # IB Gateway via ib_insync
│   ├── FinnhubProvider          # Finnhub REST + WebSocket
│   ├── BenzingaProvider         # Benzinga REST + WebSocket
│   ├── BriefingProvider         # Briefing.com (IB-only, no standalone API)
│   └── FinlightProvider         # finlight.me REST + WebSocket
├── NewsAggregator               # Fan-out across providers, dedup, merge
├── SentimentScorer              # Normalise provider sentiment to common scale
└── NewsCache                    # TTL-based cache (same pattern as fred_data.py ETF cache)
```

### 1.4 Common Article Schema (Normalised Output)

Every provider's raw response maps to this common dict:

```python
{
    "id": str,                    # Provider-prefixed unique ID (e.g., "finnhub:abc123")
    "provider": str,              # "ibkr" | "finnhub" | "benzinga" | "briefing" | "finlight"
    "headline": str,              # Article title / headline
    "summary": str | None,        # Teaser or snippet (if available)
    "body": str | None,           # Full text (if available and entitled)
    "url": str | None,            # Link to original article
    "source": str,                # Publisher name (e.g., "Reuters", "CNBC")
    "published_at": str,          # ISO 8601 timestamp
    "tickers": list[str],         # Related ticker symbols
    "categories": list[str],      # News categories (e.g., "earnings", "macro", "M&A")
    "sentiment": {
        "label": str,             # "positive" | "neutral" | "negative" | "unknown"
        "score": float,           # Normalised -1.0 to +1.0
        "confidence": float,      # 0.0 to 1.0 (1.0 = high confidence)
        "method": str             # "provider" | "agent" (who computed it)
    },
    "raw": dict                   # Original provider response (for debugging)
}
```

### 1.5 Public API Functions

```python
# Fetch recent headlines (REST polling)
def get_news(tickers: list[str] | None = None,
             category: str | None = None,
             provider: str | None = None,
             limit: int = 20,
             hours_back: int = 24) -> list[dict]:
    """Fetch recent news headlines with sentiment. Uses provider priority chain."""

# Stream headlines in real-time (WebSocket — for scheduled/background use)
def stream_news(tickers: list[str] | None = None,
                callback: callable = None,
                provider: str | None = None) -> None:
    """Start real-time news stream. Calls callback(article_dict) on each headline."""

# Get sentiment summary for a ticker or topic
def get_news_sentiment(ticker: str,
                       hours_back: int = 24) -> dict:
    """Aggregate sentiment across all providers for a ticker. Returns composite score."""

# Search historical headlines
def search_news(query: str,
                days_back: int = 7,
                provider: str | None = None,
                limit: int = 50) -> list[dict]:
    """Keyword search across news providers."""
```

### 1.6 Provider Priority Chain

```
1. IB Gateway (if connected) — free, already entitled, real-time streaming
2. Finnhub (if API key present) — generous free tier, WebSocket streaming
3. finlight (if API key present) — best sentiment quality (confidence scores)
4. Benzinga (if API key present) — deepest coverage, institutional-grade
```

If no provider is explicitly specified, the aggregator fans out to all configured providers, deduplicates by headline similarity, and merges sentiment scores.

### 1.7 Configuration (additions to config.py and .env)

```env
# .env additions
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4001
IB_CLIENT_ID=10
FINNHUB_API_KEY=your_finnhub_api_key_here
FINLIGHT_API_KEY=your_finlight_api_key_here
BENZINGA_API_KEY=your_benzinga_api_key_here
```

### 1.8 CLI Entry Point (additions to run.py)

```bash
python tools/run.py news                      # Recent headlines (all providers)
python tools/run.py news NVDA                  # Headlines for specific ticker
python tools/run.py news --provider finnhub    # Force specific provider
python tools/run.py news_sentiment AAPL        # Aggregate sentiment for ticker
python tools/run.py news_search "fed rate"     # Keyword search
```

---

## 2. Provider 1 — Interactive Brokers Gateway

### 2.1 Overview

| Attribute | Detail |
|-----------|--------|
| **Access method** | Socket API via IB Gateway (headless) or TWS (GUI) |
| **Authentication** | IB account login on Gateway; no separate API key |
| **Python library** | `ib_insync` (v0.9.86+) or `ib_async` (v2.1.0+, community fork) |
| **Cost** | Free (default providers); $35–75/mo for premium providers |
| **Real-time streaming** | Yes, via `tickNews` event callback |
| **Sentiment built-in** | No — headlines only, sentiment must be computed by agent |

### 2.2 Prerequisites

1. **Interactive Brokers account** (live or paper trading)
2. **IB Gateway installed** — download from [interactivebrokers.com](https://www.interactivebrokers.com/)
   - Minimum version: v10.19+ (API v973.02+ required for full news API)
   - IB Gateway is lighter than TWS (~40% resource usage)
3. **API access enabled** in IB Gateway configuration:
   - Launch IB Gateway → Configure → Settings → API → **Enable ActiveX and Socket Clients** ✓
   - Note the socket port: **4001** (live) or **4002** (paper)
4. **Python dependency**: `pip install ib-insync`
5. **IB Gateway must be running** as a local process before the skill can connect

### 2.3 Connection Details

| Parameter | Value |
|-----------|-------|
| Host | `127.0.0.1` (localhost) |
| Port (live) | `4001` |
| Port (paper) | `4002` |
| Client ID | Any unique integer 0–32 (use dedicated ID for news, e.g., `10`) |
| Max concurrent clients | 32 per Gateway instance |
| Timeout | 4 seconds (default) |

### 2.4 Free News Providers (Default, No Additional Subscription)

These are enabled by default since TWS v966:

| Code | Provider | Content |
|------|----------|---------|
| `BRFG` | Briefing.com General Market Columns | Market commentary, daily summaries |
| `BRFUPDN` | Briefing.com Analyst Actions | Upgrades, downgrades, initiations |
| `DJNL` | Dow Jones Newsletters | DJ market newsletters |

### 2.5 Paid News Providers (Require Subscription via Account Management)

| Code | Provider | Approx. Cost |
|------|----------|-------------|
| `BZ` | Benzinga Pro | ~$35/mo (API-specific) |
| `FLY` | Fly on the Wall | ~$45–75/mo |
| `BT` | Briefing Trader | Contact Briefing.com |
| `DJ-RT` | Dow Jones Real-Time | Contact IB |

Subscriptions are managed at: **Account Management → Trade Configuration → Market Data**

**Important:** API news subscriptions are separate from TWS platform subscriptions and carry different data fees. An "invalid tick type" error means you lack the API-specific subscription for that provider.

### 2.6 API Methods

#### Discovery: List Available Providers
```python
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4001, clientId=10)
providers = ib.reqNewsProviders()
# Returns: [NewsProvider(code='BRFG', name='Briefing.com General Market Columns'), ...]
```

#### Real-Time Headline Streaming (Contract-Specific)
```python
from ib_insync import Stock

# Subscribe to news for a specific stock
contract = Stock('AAPL', 'SMART', 'USD')
ib.qualifyContracts(contract)
ib.reqMktData(contract, genericTickList='mdoff,292:BRFG+DJNL')

# Event handler for incoming headlines
def on_news_tick(news_tick):
    print(f"[{news_tick.providerCode}] {news_tick.headline}")

ib.newsTicks.updateEvent += on_news_tick
```

#### Real-Time BroadTape Streaming (All Headlines from a Provider)
```python
from ib_insync import Contract

contract = Contract()
contract.symbol = "BRFG:BRFG_ALL"   # All Briefing.com General news
contract.secType = "NEWS"
contract.exchange = "BRFG"

ib.reqMktData(contract, genericTickList='mdoff,292')
# Headlines arrive via ib.newsTicks.updateEvent callback
```

#### Historical Headlines
```python
# Fetch up to 300 historical headlines for a contract
contract = Stock('AAPL', 'SMART', 'USD')
ib.qualifyContracts(contract)

headlines = ib.reqHistoricalNews(
    conId=contract.conId,
    providerCodes='BRFG+DJNL',
    startDateTime='',               # Empty = no start bound
    endDateTime='',                  # Empty = no end bound
    totalResults=100                 # Max 300 per request
)
# Returns: [HistoricalNews(time, providerCode, articleId, headline), ...]
```

#### Fetch Full Article Body
```python
article = ib.reqNewsArticle(
    providerCode='BRFG',
    articleId='BRFG$04fb9da2'        # From headline's articleId field
)
# Returns: NewsArticle with full HTML/text body
```

#### IB News Bulletins (IB-Specific Announcements)
```python
ib.reqNewsBulletins(allMessages=True)
ib.sleep(5)
bulletins = ib.newsBulletins()
# Returns: List of NewsBulletin objects (IB system messages, not market news)
```

### 2.7 Callback Data Format

The `tickNews` callback delivers:

| Field | Type | Description |
|-------|------|-------------|
| `tickerId` | int | Subscription identifier |
| `timeStamp` | long | Unix timestamp (milliseconds) |
| `providerCode` | str | Provider code (e.g., `"BRFG"`, `"BZ"`) |
| `articleId` | str | Unique article ID (use for `reqNewsArticle`) |
| `headline` | str | Headline text |
| `extraData` | str | Additional metadata |

### 2.8 Rate Limits & Constraints

- **Historical headlines**: 300 max per `reqHistoricalNews()` request
- **Market data lines**: 100 by default (news subscriptions count against this)
- **Concurrent connections**: 32 max per Gateway instance
- **No explicit per-minute rate limit** documented for news methods, but rapid bursts may trigger throttling

### 2.9 Verification Steps After Setup

```python
# Step 1: Verify connection
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4001, clientId=10)
print(f"Connected: {ib.isConnected()}")

# Step 2: List entitled news providers
providers = ib.reqNewsProviders()
for p in providers:
    print(f"  {p.code}: {p.name}")

# Step 3: Test headline fetch
from ib_insync import Stock
aapl = Stock('AAPL', 'SMART', 'USD')
ib.qualifyContracts(aapl)
headlines = ib.reqHistoricalNews(aapl.conId, 'BRFG+DJNL', '', '', 10)
for h in headlines:
    print(f"  [{h.providerCode}] {h.time}: {h.headline}")

# Step 4: Test article body fetch
if headlines:
    article = ib.reqNewsArticle(headlines[0].providerCode, headlines[0].articleId)
    print(f"  Article body length: {len(str(article))} chars")

# Step 5: Test real-time streaming
def on_tick(tick):
    print(f"  LIVE: [{tick.providerCode}] {tick.headline}")

ib.newsTicks.updateEvent += on_tick
ib.reqMktData(aapl, genericTickList='mdoff,292:BRFG')
ib.sleep(60)  # Wait 60s for any headlines
```

---

## 3. Provider 2 — Finnhub

### 3.1 Overview

| Attribute | Detail |
|-----------|--------|
| **Access method** | REST API + WebSocket |
| **Base URL (REST)** | `https://finnhub.io/api/v1` |
| **Base URL (WebSocket)** | `wss://ws.finnhub.io?token=YOUR_API_KEY` |
| **Authentication** | API key via query param `token=` or header `X-Finnhub-Token:` |
| **Python library** | `finnhub-python` (official) |
| **Cost** | Free tier (generous) → paid ($50–100/mo) |
| **Real-time streaming** | Yes, WebSocket (50 symbol limit on free tier) |
| **Sentiment built-in** | Yes — bullish/bearish %, composite score, buzz metric |

### 3.2 Prerequisites

1. **API key**: Register at [finnhub.io](https://finnhub.io/) (free, instant approval)
2. **Python dependency**: `pip install finnhub-python`
3. **WebSocket dependency** (if streaming): `pip install websocket-client`
4. Add `FINNHUB_API_KEY=` to `.env`

### 3.3 Rate Limits

| Tier | REST Calls | WebSocket Symbols | Cost |
|------|------------|-------------------|------|
| **Free** | 60/minute | 50 | $0 |
| **Paid (All-in-one)** | 300/minute | Unlimited | $50–100/mo |

- Hard cap: 30 calls/second across all tiers
- Exceeded: HTTP 429 (implement exponential backoff)
- All endpoints available on free tier (no feature gating)

### 3.4 REST Endpoints

#### Market News (General)
```
GET /api/v1/news?category={category}&token={key}
```

| Parameter | Required | Values |
|-----------|----------|--------|
| `category` | No | `general` (default), `forex`, `crypto`, `merger` |
| `minId` | No | Pagination cursor (return articles after this ID) |

**Response schema:**
```json
[
  {
    "category": "technology",
    "datetime": 1596589501,
    "headline": "Article headline here",
    "id": 5085164,
    "image": "https://...",
    "related": "AAPL",
    "source": "CNBC",
    "summary": "Short summary...",
    "url": "https://..."
  }
]
```

#### Company News (Ticker-Specific)
```
GET /api/v1/company-news?symbol={ticker}&from={date}&to={date}&token={key}
```

| Parameter | Required | Format |
|-----------|----------|--------|
| `symbol` | Yes | Ticker (e.g., `AAPL`) |
| `from` | Yes | `YYYY-MM-DD` |
| `to` | Yes | `YYYY-MM-DD` |

- Max 1-year lookback
- North America coverage only

**Response:** Same schema as Market News, but filtered to the ticker.

#### News Sentiment
```
GET /api/v1/news-sentiment?symbol={ticker}&token={key}
```

| Parameter | Required | Notes |
|-----------|----------|-------|
| `symbol` | Yes | US companies only |

**Response schema:**
```json
{
  "buzz": {
    "articlesInLastWeek": 20,
    "weeklyAverage": 15.5,
    "buzz": 1.29
  },
  "companyNewsScore": 0.65,
  "sectorAverageBullishPercent": 0.55,
  "sectorAverageNewsScore": 0.52,
  "sentiment": {
    "bearishPercent": 0.15,
    "bullishPercent": 0.85
  },
  "symbol": "AAPL"
}
```

| Field | Range | Description |
|-------|-------|-------------|
| `bullishPercent` | 0.0–1.0 | Proportion of bullish articles |
| `bearishPercent` | 0.0–1.0 | Proportion of bearish articles |
| `companyNewsScore` | -1.0 to +1.0 | Composite sentiment metric |
| `buzz` | 0.0–∞ | Current / historical weekly article ratio |

### 3.5 WebSocket Streaming

```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(data)

def on_open(ws):
    ws.send(json.dumps({"type": "subscribe-news", "symbol": "AAPL"}))

ws = websocket.WebSocketApp(
    "wss://ws.finnhub.io?token=YOUR_API_KEY",
    on_message=on_message,
    on_open=on_open
)
ws.run_forever()
```

- Free tier: 50 symbols max
- Paid tier: unlimited symbols
- Push-based (eliminates polling latency)

### 3.6 Python SDK Usage

```python
import finnhub

client = finnhub.Client(api_key="YOUR_API_KEY")

# Market news
news = client.general_news('general', min_id=0)

# Company news
news = client.company_news('AAPL', _from='2026-03-15', to='2026-03-22')

# Sentiment
sentiment = client.news_sentiment('AAPL')
```

### 3.7 News Sources

Reuters, Bloomberg, CNBC, AP, Wall Street Journal, Seeking Alpha, PR Newswire, Globe Newswire, BusinessWire, and others (exact list not fully published by Finnhub).

### 3.8 Mapping to Common Schema

| Finnhub Field | Common Schema Field |
|---------------|---------------------|
| `id` | `id` (prefix with `"finnhub:"`) |
| `headline` | `headline` |
| `summary` | `summary` |
| (not available) | `body` → `None` |
| `url` | `url` |
| `source` | `source` |
| `datetime` (unix) | `published_at` (convert to ISO 8601) |
| `related` | `tickers` (split on comma) |
| `category` | `categories` |
| `companyNewsScore` | `sentiment.score` |
| `bullishPercent` | `sentiment.confidence` (proxy) |
| (computed) | `sentiment.label` (derive from score: >0.2=positive, <-0.2=negative, else neutral) |

---

## 4. Provider 3 — Benzinga

### 4.1 Overview

| Attribute | Detail |
|-----------|--------|
| **Access method** | REST API + WebSocket + TCP + Webhook + Flat File |
| **Base URL (REST)** | `https://api.benzinga.com/api/v2/news` |
| **Base URL (WebSocket)** | `wss://api.benzinga.com/api/v1/news/stream` |
| **Authentication** | API key via query param `token=` |
| **Token format** | `bz.production***` |
| **Python library** | `benzinga` (official, PyPI) |
| **Cost** | Free tier (headlines + teasers) → custom enterprise pricing |
| **Real-time streaming** | Yes, WebSocket (1 connection per token) |
| **Sentiment built-in** | No — headline/body only, sentiment must be computed by agent |

### 4.2 Prerequisites

1. **API key**: Register at Benzinga developer portal (free tier available)
   - Free tier via AWS Marketplace: "Benzinga Basic Financial News API"
   - Paid/custom: Contact `partners@benzinga.com` or `licensing@benzinga.com`
2. **Python dependency**: `pip install benzinga`
3. **WebSocket examples**: [github.com/Benzinga/websocket-feed-examples](https://github.com/Benzinga/websocket-feed-examples)
4. Add `BENZINGA_API_KEY=` to `.env`

**Note:** The Benzinga direct API key is separate from the IB-bundled Benzinga subscription ($35/mo through IB). The direct API has its own free tier and pricing.

### 4.3 Rate Limits

| Constraint | Limit |
|------------|-------|
| REST pagination ceiling | 10,000 items per query |
| WebSocket connections | 1 per API token |
| PageSize | Max 100 per request |
| Delta ingestion | Use `updatedSince` with 5-second lookback |

No documented per-minute REST rate limit, but the pagination ceiling is the practical constraint.

### 4.4 REST Endpoint

```
GET /api/v2/news?token={key}&tickers={tickers}&channels={channels}&pageSize={n}&displayOutput={mode}
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `token` | Yes | API key |
| `tickers` | No | Comma-separated symbols (e.g., `AAPL,MSFT`) |
| `channels` | No | Category filter (e.g., `Earnings`, `M&A`, `WIIM`, `Markets`) |
| `pageSize` | No | Results per page (default 15, max 100) |
| `page` | No | Pagination offset (default 0) |
| `displayOutput` | No | `"full"` for complete HTML body; omit for teaser only |
| `dateFrom` / `dateTo` | No | ISO 8601 date filtering |
| `updatedSince` | No | Unix timestamp for delta ingestion (set 5 seconds earlier) |
| `last_id` | No | Cursor-based pagination (preferred over offset) |

**Response schema:**
```json
[
  {
    "id": 12345678,
    "title": "Headline text",
    "teaser": "Short summary...",
    "body": "<p>Full HTML content</p>",
    "author": "Author Name",
    "created": "Wed, 17 May 2026 14:20:15 -0400",
    "updated": 1716000015,
    "url": "https://www.benzinga.com/...",
    "image": "https://...",
    "channels": ["Earnings", "Tech"],
    "tags": ["revenue-beat", "guidance-raised"],
    "stocks": [
      {
        "name": "AAPL",
        "cusip": "037833100",
        "isin": "US0378331005",
        "exchange": "NASDAQ"
      }
    ]
  }
]
```

**Free tier content:** Headline + teaser + link to Benzinga.com. Full embeddable body requires paid tier (`displayOutput=full`).

### 4.5 WebSocket Streaming

```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    # data["action"]: "created" | "updated" | "deleted"
    # data["data"]: article object (same schema as REST)
    print(f"[{data['action']}] {data['data']['title']}")

ws = websocket.WebSocketApp(
    "wss://api.benzinga.com/api/v1/news/stream?token=YOUR_TOKEN",
    on_message=on_message,
    on_ping=lambda ws, msg: ws.send("pong", websocket.ABNF.OPCODE_PONG)
)
ws.run_forever(ping_interval=30)
```

- Server sends ping every 10 seconds; client must respond with pong
- Recommend client-side ping every 30–60 seconds
- Implement exponential backoff for reconnections
- **Only 1 WebSocket connection per API token** (strict)

### 4.6 Additional Delivery Methods

| Method | Use Case |
|--------|----------|
| **TCP** (`python-bztcp`) | Ultra-low latency direct socket |
| **Webhook** | Push-based HTTP POST to your endpoint |
| **Flat File** | Scheduled CSV/JSON via FTP or S3 |

These are enterprise features; contact Benzinga for access.

### 4.7 Ticker Coverage

- Wilshire 5000 (broad US market)
- TSX (Canadian equities)
- ~1,000 popular international tickers

### 4.8 Channels (Category Filters)

Full list: `https://www.benzinga.com/api/v2/channels`

Common values: `Equities`, `Markets`, `Tech`, `WIIM` (Why Is It Moving), `Earnings`, `M&A`, `Crypto`, `Analyst Ratings`, `Press Releases`, `IPOs`.

### 4.9 Python SDK Usage

```python
from benzingaorg import news_data

api = news_data.News("YOUR_API_KEY")

# General news
result = api.news()

# Ticker-specific
result = api.news(tickers="AAPL,NVDA", pageSize=20, displayOutput="full")

# Channel-filtered
result = api.news(channels="Earnings", pageSize=10)
```

### 4.10 Mapping to Common Schema

| Benzinga Field | Common Schema Field |
|----------------|---------------------|
| `id` | `id` (prefix with `"benzinga:"`) |
| `title` | `headline` |
| `teaser` | `summary` |
| `body` | `body` (paid tier only; `None` on free) |
| `url` | `url` |
| `author` | (not in common schema, store in `raw`) |
| `created` | `published_at` (parse RFC 2822 → ISO 8601) |
| `stocks[].name` | `tickers` |
| `channels` | `categories` |
| (not available) | `sentiment` → compute via agent |

---

## 5. Provider 4 — Briefing.com

### 5.1 Overview

| Attribute | Detail |
|-----------|--------|
| **Access method** | IB TWS API only (no standalone public API) |
| **Authentication** | Via IB Gateway connection (no separate API key) |
| **Python library** | `ib_insync` (same as Provider 1) |
| **Cost** | Free (BRFG + BRFUPDN via IB) |
| **Real-time streaming** | Yes, via IB `tickNews` callback |
| **Sentiment built-in** | No |

### 5.2 Key Finding

**Briefing.com does not offer a standalone public API.** All programmatic access is through the Interactive Brokers TWS API. A private API exists for Briefing Trader subscribers (contact: `dbeasley@briefing.com`), but it is undocumented and requires case-by-case approval.

### 5.3 What's Available for Free via IB

| Provider Code | Content | Free? |
|---------------|---------|-------|
| `BRFG` | General Market Columns — daily market commentary and summaries | Yes |
| `BRFUPDN` | Analyst Actions — upgrades, downgrades, initiations, target changes | Yes |

### 5.4 What's Available for a Fee via IB

| Provider Code | Content | Cost |
|---------------|---------|------|
| `BT` (Briefing Trader) | InPlay headlines, day/swing trading ideas | Contact Briefing.com |

### 5.5 Integration Approach

Briefing.com is accessed through the **same IB Gateway connection** as Provider 1. No additional setup is needed beyond the IB Gateway prerequisites. The `IBGatewayProvider` class handles Briefing.com as one of the available IB news sources.

```python
# Briefing.com via IB Gateway (same connection as Section 2)
headlines = ib.reqHistoricalNews(
    conId=contract.conId,
    providerCodes='BRFG+BRFUPDN',   # Free Briefing.com sources
    startDateTime='',
    endDateTime='',
    totalResults=50
)
```

### 5.6 Content Characteristics

- **BRFG (General Market Columns):** Market summaries and commentary pieces. Published throughout the trading day. Useful for qualitative macro context (similar to newsletter digest).
- **BRFUPDN (Analyst Actions):** Structured data about analyst rating changes. High signal-to-noise ratio for equity analysis. Contains: analyst firm, action type (upgrade/downgrade/initiate), prior rating, new rating, price target.

### 5.7 Limitations

- No direct API key or standalone endpoint
- Historical depth: ~30 days (provider-dependent)
- Content is market commentary, not raw news wire — fewer headlines but higher context per article
- No sentiment scores provided; must be computed by agent

### 5.8 Alternative Access (Private API, Not Recommended for Initial Build)

For full InPlay access:
1. Subscribe to Briefing Trader ($50/mo for InPlay, $240+/mo for full Trader)
2. Email `dbeasley@briefing.com` to apply for API entitlement
3. Receive private API documentation (undocumented publicly)
4. Data format: likely JSON (unconfirmed)

**Recommendation:** Use the free IB-bundled BRFG + BRFUPDN for initial build. Evaluate whether the private API is worth pursuing after testing IB's free tier.

---

## 6. Provider 5 — finlight.me

### 6.1 Overview

| Attribute | Detail |
|-----------|--------|
| **Access method** | REST API + WebSocket + Webhooks |
| **Base URL (REST)** | `https://api.finlight.me/v2/articles` |
| **Base URL (WebSocket)** | `wss://wss.finlight.me` |
| **Authentication** | API key via header `X-API-KEY:` |
| **Python library** | `finlight-client` (official, PyPI) |
| **Cost** | Free (5K req/mo, 12-hr delay) → $24+/mo (real-time) |
| **Real-time streaming** | Yes, WebSocket (paid tiers only) |
| **Sentiment built-in** | Yes — polarity label + confidence score (paid tiers for full access) |

### 6.2 Prerequisites

1. **API key**: Register at [app.finlight.me](https://app.finlight.me) (free tier available)
2. **Python dependency**: `pip install finlight-client`
3. Add `FINLIGHT_API_KEY=` to `.env`

### 6.3 Pricing Tiers

| Tier | Monthly Requests | Real-Time | WebSocket | Sentiment | Cost |
|------|------------------|-----------|-----------|-----------|------|
| **Launchpad (Free)** | 5,000 | 12-hr delay | No | No | $0 |
| **Pro Light** | 10,000 | Yes | 5K dispatches/mo | No | ~$24/mo |
| **Pro Standard** | 50,000 | Yes | 25K dispatches/mo | Yes | ~$49/mo |
| **Pro Scale** | 150,000 | Yes | Unlimited | Yes | ~$99/mo |
| **Enterprise** | Unlimited | Yes | Unlimited | Yes | Custom |

**Key constraint:** Free tier has a **12-hour delay** on all articles and **no sentiment analysis**. Real-time access and sentiment require a paid tier.

### 6.4 REST Endpoint

```
POST /v2/articles
Headers: X-API-KEY: {key}
Content-Type: application/json
```

**Request body:**
```json
{
  "query": "(ticker:AAPL OR ticker:NVDA) AND content:earnings",
  "tickers": ["AAPL", "NVDA"],
  "sources": ["www.reuters.com", "www.cnbc.com"],
  "excludeSources": ["www.tabloid.com"],
  "language": "en",
  "countries": ["US"],
  "from": "2026-03-15T00:00:00Z",
  "to": "2026-03-22T23:59:59Z",
  "pageSize": 50,
  "page": 1,
  "order": "DESC",
  "includeContent": true,
  "includeEntities": true,
  "excludeEmptyContent": true
}
```

**Query syntax** supports boolean operators: `AND`, `OR`, `NOT`, parentheses, and field-level filters: `source:`, `country:`, `exchange:`, `ticker:`, `content:`.

**Response schema:**
```json
{
  "status": "ok",
  "articles": [
    {
      "link": "https://...",
      "source": "www.reuters.com",
      "title": "Article headline",
      "summary": "Article summary...",
      "content": "Full article text (paid tier)",
      "publishDate": "2026-03-22T18:17:40.000Z",
      "createdAt": "2026-03-22T18:20:00.000Z",
      "language": "en",
      "sentiment": "positive",
      "confidence": 0.9999,
      "images": ["https://..."],
      "countries": ["US"],
      "categories": ["Technology"],
      "companies": [
        {
          "ticker": "NVDA",
          "exchange": "XNSD",
          "isin": "US5980302001",
          "name": "NVIDIA Corporation"
        }
      ]
    }
  ],
  "total": 1250,
  "page": 1,
  "pageSize": 50
}
```

### 6.5 WebSocket Streaming (Paid Tiers Only)

```python
from finlight_client import FinlightApi

api = FinlightApi(api_key="YOUR_API_KEY")

def on_article(article):
    print(f"[{article['sentiment']}] {article['title']}")

api.websocket.connect(
    query={"query": "Tesla", "language": "en", "tickers": ["TSLA"], "extended": True},
    on_message=on_article
)
```

**Connection details:**

| Parameter | Value |
|-----------|-------|
| Endpoint | `wss://wss.finlight.me` |
| Auth header | `x-api-key: YOUR_API_KEY` |
| Max connection lifetime | 2 hours (auto-disconnect) |
| Inactivity timeout | 10 minutes |
| Ping interval | ~8 minutes (SDK default: 25 seconds) |
| Pong timeout | 60 seconds |
| Reconnection | Exponential backoff, base 0.5s, max 10s |

**Subscribe message:**
```json
{
  "action": "subscribe",
  "query": "Tesla",
  "sources": ["www.reuters.com"],
  "language": "en",
  "tickers": ["TSLA"],
  "countries": ["US"],
  "extended": true,
  "includeEntities": true
}
```

**Unsubscribe:**
```json
{ "action": "unsubscribe" }
```

### 6.6 Webhook Integration (Paid Tiers Only)

- Configure at: `https://app.finlight.me/news-webhooks`
- Security: HMAC-SHA256 signature in `X-Webhook-Signature` header
- Replay protection: 5-minute timestamp tolerance
- Auth options: None, Basic Auth, Custom Header (`X-Finlight-Key`), or Signature Validation
- Response time requirement: < 5 seconds

### 6.7 Sentiment Analysis

| Attribute | Detail |
|-----------|--------|
| Labels | `"positive"`, `"neutral"`, `"negative"` |
| Confidence | Float 0.0–1.0 (e.g., `0.9999`) |
| Scope | Applied to full article text, not just headline |
| Method | NLP/deep learning (CNN-based, per-language models) |
| Availability | **Free tier: No.** Requires Pro Standard ($49/mo) or higher |

### 6.8 Python SDK Usage

```python
from finlight_client import FinlightApi

api = FinlightApi(api_key="YOUR_API_KEY")

# REST: Fetch articles
articles = api.articles.fetch_articles(
    query="NVDA earnings",
    tickers=["NVDA"],
    language="en",
    page_size=20,
    include_content=True
)

# WebSocket: Real-time stream (paid)
api.websocket.connect(
    query={"query": "macro Fed rate", "language": "en", "extended": True},
    on_message=lambda article: print(article["title"])
)

# Webhook: Verify signature
from finlight_client import WebhookService
is_valid = WebhookService.verify_signature(payload, signature, secret)
```

### 6.9 News Sources

Default set includes Reuters, Bloomberg, WSJ, BBC, and other major global outlets. Filterable by domain, country, exchange, and language.

### 6.10 Mapping to Common Schema

| finlight Field | Common Schema Field |
|----------------|---------------------|
| `link` | `id` (hash of URL, prefix with `"finlight:"`) |
| `title` | `headline` |
| `summary` | `summary` |
| `content` | `body` (paid tier; `None` on free) |
| `link` | `url` |
| `source` | `source` |
| `publishDate` | `published_at` (already ISO 8601) |
| `companies[].ticker` | `tickers` |
| `categories` | `categories` |
| `sentiment` | `sentiment.label` |
| `confidence` | `sentiment.confidence` |
| (derived) | `sentiment.score` (map: positive=+0.8, neutral=0.0, negative=-0.8, scaled by confidence) |

---

## 7. Provider Comparison Matrix

| Capability | IB Gateway | Finnhub | Benzinga | Briefing.com | finlight |
|------------|-----------|---------|----------|--------------|---------|
| **Free tier** | Yes (3 sources) | Yes (60 req/min) | Yes (headline + teaser) | Yes (via IB only) | Yes (5K/mo, 12-hr delay) |
| **Real-time streaming** | Yes (tickNews) | Yes (WebSocket) | Yes (WebSocket) | Yes (via IB tickNews) | Paid only |
| **REST polling** | No (socket only) | Yes | Yes | No | Yes |
| **Sentiment built-in** | No | Yes (composite score) | No | No | Yes (label + confidence) |
| **Full article body** | Yes (reqNewsArticle) | No | Paid only | Yes (via IB) | Paid only |
| **Ticker filtering** | Yes (contract-based) | Yes (symbol param) | Yes (tickers param) | Yes (via IB contract) | Yes (tickers param) |
| **Category filtering** | By provider code | 4 categories | 15+ channels | By provider code | Via query DSL |
| **Historical lookback** | ~300 headlines | 1 year | Unlimited (paid) | ~30 days | Varies by tier |
| **Python SDK** | ib_insync | finnhub-python | benzinga | ib_insync | finlight-client |
| **Requires local process** | Yes (IB Gateway) | No | No | Yes (IB Gateway) | No |
| **API key needed** | No (IB login) | Yes | Yes | No (IB login) | Yes |

---

## 8. Implementation Phases

### Phase 1: Foundation (Recommended Starting Point)

- Implement `IBGatewayProvider` using `ib_insync`
- Implement `FinnhubProvider` using `finnhub-python`
- Build `NewsCache` with 30-min TTL (same pattern as `fred_data.py`)
- Build common schema normalisation
- Add `get_news()` and `search_news()` to `run.py`
- Agent-side sentiment scoring for providers without built-in sentiment (IB, Benzinga free)

**Dependencies:** `ib-insync`, `finnhub-python`
**API keys needed:** `FINNHUB_API_KEY` (free), IB account login
**Cost:** $0

### Phase 2: Coverage Expansion

- Implement `BenzingaProvider` (free tier: headlines + teasers)
- Implement `FinlightProvider` (free tier: 12-hr delayed articles)
- Build `NewsAggregator` with cross-provider deduplication
- Add `get_news_sentiment()` to `run.py`
- Integrate news sentiment into `macro_synthesis.py` as an additional signal

**Dependencies:** `benzinga`, `finlight-client`
**API keys needed:** `BENZINGA_API_KEY`, `FINLIGHT_API_KEY` (both free tiers)
**Cost:** $0

### Phase 3: Real-Time Streaming (Optional, Paid)

- Implement WebSocket streaming for Finnhub and/or finlight
- Background headline ingestion with local storage
- Implement `stream_news()` function
- Add scheduled news digest (similar to `/digest` skill for newsletters)
- Webhook endpoint for finlight push delivery

**Cost:** Finnhub paid ($50–100/mo) or finlight Pro ($24–99/mo)

---

## 9. Documentation References

### IB Gateway / TWS API
- Official TWS API News: https://interactivebrokers.github.io/tws-api/news.html
- ib_insync API Docs: https://ib-insync.readthedocs.io/api.html
- ib_insync Recipes: https://ib-insync.readthedocs.io/recipes.html
- IBKR Campus: https://ibkrcampus.com/ibkr-api-page/trader-workstation-api/
- IB Gateway Download: https://www.interactivebrokers.com/

### Finnhub
- API Docs: https://finnhub.io/docs/api
- Market News: https://finnhub.io/docs/api/market-news
- Company News: https://finnhub.io/docs/api/company-news
- News Sentiment: https://finnhub.io/docs/api/news-sentiment
- Pricing: https://finnhub.io/pricing
- Python SDK: https://github.com/Finnhub-Stock-API/finnhub-python

### Benzinga
- API Docs: https://docs.benzinga.com/
- Newsfeed v2: https://docs.benzinga.com/benzinga-apis/newsfeed-v2/newsfeed-v2
- WebSocket Stream: https://docs.benzinga.com/ws-reference/data-websocket/get-news-stream
- Python SDK: https://github.com/Benzinga/benzinga-python-client
- WebSocket Examples: https://github.com/Benzinga/websocket-feed-examples
- Pricing: Contact `partners@benzinga.com`

### Briefing.com
- IB Integration: https://www.interactivebrokers.com/en/trading/providers/briefing.php
- Private API Contact: `dbeasley@briefing.com`
- No standalone public documentation available

### finlight.me
- API Docs: https://docs.finlight.me/
- REST Basics: https://docs.finlight.me/v2/rest-basics/
- WebSocket: https://docs.finlight.me/v2/websocket-subscribe/
- Webhooks: https://docs.finlight.me/v2/webhooks/
- Python SDK: https://github.com/jubeiargh/finlight-client-py
- Pricing: https://finlight.me/pricing
