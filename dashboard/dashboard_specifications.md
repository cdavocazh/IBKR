# IBKR Dashboard — Specifications

## Table of Contents
- [Local Development](#local-development)
- [VPS Production Deployment](#vps-production-deployment)
- [Backend Architecture](#backend-architecture)
- [API Endpoints](#api-endpoints)
- [WebSocket Protocol](#websocket-protocol)
- [Frontend Architecture](#frontend-architecture)
- [Authentication](#authentication)
- [IB Thread Queue Pattern](#ib-thread-queue-pattern)
- [Position Data Model](#position-data-model)

---

## Local Development

### Start
```bash
bash dashboard/start.sh    # Auto-finds available ports, starts backend + frontend
```
Opens at `http://localhost:5173` (Vite dev server proxies API to backend on port 8888).

### Vite Config (`frontend/vite.config.ts`)
- `base: '/IBKR_KZ/'` — sub-path for deployment
- Dev proxy: `/IBKR_KZ/api/*` → `http://localhost:8888/api/*` (rewrite strips prefix)
- Dev proxy: `/IBKR_KZ/ws` → `ws://localhost:8888/ws` (rewrite strips prefix)

### Environment
- `VITE_API_PORT` — backend port (default: 8888)
- `DASHBOARD_PORT` — backend listen port (default: 8888)
- `DASHBOARD_CLIENT_ID` — ib_async client ID (default: 20)

---

## VPS Production Deployment

### URL
`http://187.77.136.160/IBKR_KZ/`

### Service
```
ibkr-dashboard.service
  Port: 8888
  ClientId: 30
  WorkingDirectory: /root/IBKR
  Venv: /root/IBKR/venv/bin/python
```

### Nginx (`/etc/nginx/sites-enabled/dashboards`)
| Location | Target | Notes |
|----------|--------|-------|
| `/IBKR_KZ/api/*` | `proxy → 127.0.0.1:8888/api/*` | `auth_basic off` (app handles auth) |
| `/IBKR_KZ/ws` | `proxy → 127.0.0.1:8888/ws` | WebSocket upgrade headers |
| `/IBKR_KZ/assets/` | Static files from `dist/assets/` | Immutable cache (1 year) |
| `/IBKR_KZ/` | SPA fallback to `dist/index.html` | `try_files $uri $uri/ /IBKR_KZ/index.html` |

### Deploy Workflow
```bash
# 1. Build frontend locally
cd dashboard/frontend && npx vite build

# 2. Rsync to VPS
rsync -avz --delete dashboard/ root@187.77.136.160:/root/IBKR/dashboard/ \
  --exclude='__pycache__' --exclude='node_modules' --exclude='.vite'

# 3. Restart service
ssh root@187.77.136.160 "systemctl restart ibkr-dashboard.service"
```

### IB Gateway Connection
Backend connects to IB Gateway Docker container via `127.0.0.1:4001` (host) → `4003` (container socat) → `4001` (IB Gateway API).

See `VPS_Hostinger_setup.md` for Docker config, session management, health monitoring, and Telegram commands.

---

## Backend Architecture

**File:** `dashboard/server.py`
**Framework:** FastAPI + uvicorn
**IBKR Connection:** ib_async in a dedicated thread with auto-reconnect

### Startup Flow
1. Initialize SQLite database (`dashboard.db`) with users, watchlists, watchlist_instruments tables
2. Migrate from legacy `watchlists.json` if present
3. Start IB connection thread (tries ports 7496 → 7497 → 4001 → 4002)
4. Once connected: subscribe to news, start portfolio refresh loop
5. Mount static files from `frontend/dist/` for production serving

### Data Storage
- **SQLite** (`dashboard.db`): Users, watchlists, watchlist instruments
- **In-memory**: Portfolio state, news headlines (deque, max 500), WebSocket clients

---

## API Endpoints

### Auth
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | No | Create user account |
| POST | `/api/auth/login` | No | Login, returns JWT-like token |
| GET | `/api/auth/me` | Bearer | Validate token |

### Portfolio & Market Data
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/accounts` | No | List connected account IDs |
| GET | `/api/portfolio` | No | Full multi-account portfolio (positions + summary + orders) |
| GET | `/api/status` | No | Connection status (connected, position_count, live_mode) |
| POST | `/api/live?enabled=true` | No | Toggle live mode (per-second price refresh) |
| GET | `/api/live` | No | Current live mode state |
| GET | `/api/chart?conId=X&barSize=Y` | No | Historical OHLCV bars. barSize: 1min/5min/15min/1hour/1day/1week. 30s timeout |

### News & Sentiment
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/news?count=50` | No | Recent cached headlines |
| GET | `/api/news/article?articleId=X&provider=Y` | No | Full article text via `reqNewsArticle`. 15s timeout |
| GET | `/api/sentiment` | No | Latest NLP sentiment analysis (from file or memory) |
| GET | `/api/sentiment/history` | No | Sentiment timeseries CSV as JSON array |

### Watchlists (all require Bearer auth)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlists` | List user's watchlists |
| POST | `/api/watchlists` | Create watchlist `{name}` |
| PUT | `/api/watchlists/{id}` | Rename watchlist `{name}` |
| DELETE | `/api/watchlists/{id}` | Delete watchlist |
| GET | `/api/watchlists/{id}/instruments` | List instruments (with live prices if connected) |
| POST | `/api/watchlists/{id}/instruments` | Add instrument `{conId, symbol, localSymbol, secType, exchange, currency, name}` |
| DELETE | `/api/watchlists/{id}/instruments/{instrumentId}` | Remove instrument |

### Search & Details
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/search?q=X` | Bearer | Search instruments (IBKR `reqMatchingSymbols` + Yahoo fallback). 15s timeout |
| GET | `/api/instrument-details?conId=X` | No | Contract details + delivery months (for FUT/IND) + open interest (nearest 6). 30s timeout |

---

## WebSocket Protocol

**Endpoint:** `/ws?token=<auth_token>`

### Client → Server
| Type | Payload | Effect |
|------|---------|--------|
| `toggle_live` | `{enabled: bool}` | Toggle per-second price refresh |
| `ping` | — | Keep-alive (sent every 30s by client) |

### Server → Client
| Type | Payload | Frequency |
|------|---------|-----------|
| `portfolio` | `{accounts, portfolios: {[acctId]: {summary, positions}}, orders: {[acctId]: Order[]}}` | Every 10s (1s in live mode) |
| `news` | Single `NewsHeadline` object | Real-time |
| `news_batch` | Array of `NewsHeadline` objects | On connect (initial batch) |
| `status` | `{connected, position_count, account_count, last_update, live_mode}` | With each portfolio update |
| `live_mode` | `{enabled: bool}` | On toggle |

---

## Frontend Architecture

**Stack:** React 19 + TypeScript + Tailwind CSS + Vite
**Chart Library:** lightweight-charts (TradingView)
**Routing:** React Router v7

### Component Tree
```
App.tsx
├── LoginPage.tsx                 # Auth gate (login/register form)
└── Dashboard (authenticated)
    ├── Header                    # Title, LIVE toggle, user info, ConnectionStatus
    ├── AccountSidebar.tsx        # Account list + watchlist list (left 208px)
    └── Routes
        ├── AccountPage.tsx       # /account/:accountId
        │   ├── PortfolioSummaryCards  # 6-7 summary cards (NetLiq, P&L, etc.)
        │   ├── OrdersTable.tsx        # Open orders (if any)
        │   ├── PortfolioTable.tsx      # Positions table (sortable, filterable)
        │   ├── SentimentPanel.tsx      # ES sentiment (right sidebar)
        │   ├── NewsFeed.tsx            # News headlines (right sidebar, clickable for article)
        │   └── PriceChart.tsx          # Modal chart (on symbol click)
        └── WatchlistPage.tsx     # /watchlist/:watchlistId
            └── AddInstrumentModal.tsx  # Search + add instruments
```

### Key Modules
| File | Purpose |
|------|---------|
| `config.ts` | `API()` path helper, `WS_URL()`, `authFetch()`, `authHeaders()` |
| `hooks/useWebSocket.ts` | WebSocket connection, auto-reconnect (exponential backoff), state management |
| `hooks/useAuth.ts` | Auth context provider, login/register/logout, token persistence in localStorage |
| `types.ts` | TypeScript interfaces (Position, Order, NewsHeadline, PortfolioSummary, etc.) |

### Components Detail

**PortfolioTable.tsx**
- 13 sortable columns: Symbol, Type, P/C, Strike, Expiry, Pos, Avg Cost, Current, Prev Close, Mkt Value, Day P&L, Unreal P&L, P&L%
- Options columns (P/C, Strike, Expiry) auto-shown when any position is OPT or FOP
- Type filter buttons (ALL/STK/OPT/FUT/FOP/etc.) shown when multiple types present
- Daily P&L banner shows total across filtered positions
- Default sort: unrealized_pnl descending
- Click symbol → opens PriceChart modal

**PriceChart.tsx**
- Modal overlay with candlestick chart (lightweight-charts)
- Bar sizes: 1m, 5m, 15m, 1H, 1D, 1W
- Auto-refresh in live mode: 5s (1m), 10s (5m), 30s (15m), 60s (1H), 300s (1D/1W)
- Uses `series.update()` for incremental bar updates (no full redraw)
- LIVE/PAUSED toggle when live mode active

**NewsFeed.tsx**
- Scrollable headline list (max 200), provider badges color-coded
- Click headline → fetches full article via `/api/news/article`, displays as expanded text
- HTML stripped to plain text for display

**SentimentPanel.tsx**
- Fetches from `/api/sentiment` on mount
- Shows: direction badge, confidence, sentiment scores, key levels grid, positioning data
- Expandable themes & insights section
- Signal history timeline with visual bars

**AddInstrumentModal.tsx**
- Debounced search (300ms) via `/api/search`
- Click result → expands to show contract details via `/api/instrument-details`
- For futures: shows delivery months table with open interest + individual Add buttons

---

## Authentication

- **Token format:** Base64-encoded JSON payload + HMAC-SHA256 signature (`{payload_b64}.{signature}`)
- **Payload:** `{uid, u(sername), t(imestamp)}`
- **Secret:** `DASHBOARD_SECRET` env var or random on startup
- **Storage:** `ibkr_token` and `ibkr_username` in localStorage
- **Password hashing:** PBKDF2-HMAC-SHA256 with random salt (100,000 iterations)
- **SQLite:** `dashboard.db` with `users`, `watchlists`, `watchlist_instruments` tables

---

## IB Thread Queue Pattern

All IBKR API calls must execute on the dedicated IB thread (ib_async is not thread-safe). API endpoints submit requests via a shared queue:

```python
# Queue definition
_chart_request_queue: list = []
_chart_request_lock = threading.Lock()

# IB thread loop (every 0.5s)
with _chart_request_lock:
    pending = list(_chart_request_queue)
    _chart_request_queue.clear()
for req in pending:
    if "fn" in req:       # Generic function call
        req["fn"]()
        req["event"].set()
    else:                  # Chart-specific request
        _process_chart_request(ib, cache, req)
```

**Usage from API endpoint:**
```python
result_holder = {"data": None}
done_event = threading.Event()

def _work():
    result_holder["data"] = ib.someIBCall(...)

req = {"fn": _work, "event": done_event}
with _chart_request_lock:
    _chart_request_queue.append(req)

await loop.run_in_executor(None, lambda: done_event.wait(timeout=30))
```

**Endpoints using this pattern:** `/api/chart`, `/api/news/article`, `/api/search`, `/api/instrument-details`, `/api/watchlists/{id}/instruments` (price fetch)

---

## Position Data Model

```typescript
interface Position {
  symbol: string           // e.g. "ES"
  local_symbol: string     // e.g. "ESM5"
  sec_type: string         // STK, OPT, FUT, FOP, WAR, CASH
  exchange: string
  currency: string
  position_size: number    // +long / -short
  avg_cost: number
  multiplier: number       // e.g. 50 for ES futures
  current_price: number | null
  prev_close: number | null
  market_price: number | null
  market_value: number | null
  unrealized_pnl: number | null
  realized_pnl: number | null
  pnl_pct: number | null
  daily_pnl: number | null     // (current - prev_close) * position * multiplier
  account: string
  con_id: number
  mark_price: number | null
  futures_oi: number | null
  // Options fields (null for non-options)
  strike: number | null        // e.g. 6000
  right: string | null         // "C" (call) or "P" (put)
  expiry: string | null        // "20250620" (YYYYMMDD)
}
```
