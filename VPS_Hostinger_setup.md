# IBKR VPS Deployment — Hostinger Setup

**VPS:** `187.77.136.160` (Hostinger)
**Project directory:** `/root/IBKR/`
**Python venv:** `/root/IBKR/venv/` (Python 3.13)

---

## Architecture

```
Internet (port 80)
    │
    ▼
nginx (basic auth: /etc/nginx/.htpasswd)
    │
    ├── /IBKR_KZ/api/*  → proxy → 127.0.0.1:8888 (FastAPI backend)
    ├── /IBKR_KZ/ws     → proxy → 127.0.0.1:8888 (WebSocket)
    └── /IBKR_KZ/*      → static files from /root/IBKR/dashboard/frontend/dist/
                                    │
                                    ▼
                          ibkr-dashboard.service (FastAPI + ib_async)
                                    │
                                    ▼
                          127.0.0.1:4001 (host) → 4003 (container socat) → 4001 (IB Gateway API)
                                    │
                          ┌─────────┴─────────┐
                          │  Docker container  │
                          │  ghcr.io/gnzsnz/   │
                          │  ib-gateway:latest  │
                          │                     │
                          │  IBC auto-login     │
                          │  VNC :5900          │
                          └─────────────────────┘
```

---

## Services

| Service | Type | Port | Description |
|---------|------|------|-------------|
| `ibkr-dashboard.service` | long-running | 8888 | Portfolio dashboard (FastAPI + WebSocket) |
| `ibkr-sentiment.service` | oneshot (timer) | — | ES sentiment pipeline (IBKR news + NLP) |
| `finl-digest-es.service` | oneshot (timer) | — | ES newsletter digest via Claude Code |
| `ib-health-monitor.service` | oneshot (timer) | — | IB Gateway health check + auto-restart |
| IB Gateway Docker | container | 4001→4003, 5900 | Interactive Brokers API |

---

## Timers

| Timer | Schedule | What It Does |
|-------|----------|--------------|
| `ib-health-monitor.timer` | Every 15 min | Tests API connectivity; restarts if dead (yields if another session active) |
| `ibkr-sentiment.timer` | 03:00, 12:00, 15:00 UTC | Fetches ~4000 IBKR headlines, runs NLP, saves sentiment analysis |
| `finl-digest-es.timer` | 00:00, 12:00 UTC | Reads ES newsletters (Smashelito, Geo Chen, etc.) via Claude Code |

---

## IB Gateway Docker

### docker-compose.yml (`/root/ib-gateway/`)

```yaml
services:
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:latest
    restart: unless-stopped
    environment:
      TWS_USERID: "..."
      TWS_PASSWORD: "..."
      TRADING_MODE: "live"
      READ_ONLY_API: "yes"
      VNC_SERVER_PASSWORD: "..."
      EXISTING_SESSION_DETECTED_ACTION: "secondary"  # yield to mobile login
      RELOGIN_AFTER_TWOFA_TIMEOUT: "yes"             # retry if 2FA times out
      TWOFA_EXIT_INTERVAL: "60"
      AUTO_RESTART_TIME: "23:45"                     # daily soft restart (no 2FA)
      TWS_COLD_RESTART: "05:00"                      # Sunday cold restart (needs 2FA)
      DISPLAY_WIDTH: "1920"
      DISPLAY_HEIGHT: "1080"
    ports:
      - "127.0.0.1:4001:4003"   # CRITICAL: map to socat port, NOT API port
      - "127.0.0.1:4002:4004"
      - "127.0.0.1:5900:5900"   # VNC (SSH tunnel only)
    volumes:
      - ./ibc-config:/root/ibc
```

### Why host:4001 → container:4003 (not 4001)?

The gnzsnz image runs socat inside the container: `4003 → 127.0.0.1:4001`. This socat connection originates from localhost, which is in `TrustedIPs`. Direct Docker port mapping to 4001 fails because Docker routes traffic through its bridge network (172.18.x.x), which is NOT trusted by IB Gateway.

### Session Management

| Setting | Value | Effect |
|---------|-------|--------|
| `EXISTING_SESSION_DETECTED_ACTION` | `secondary` | VPS yields to mobile login — no conflict |
| `RELOGIN_AFTER_TWOFA_TIMEOUT` | `yes` | If 2FA not approved in 180s, exit and retry |
| `AUTO_RESTART_TIME` | `23:45` | Daily soft restart (session kept, no 2FA) |
| `TWS_COLD_RESTART` | `05:00` | Sunday cold restart (full re-auth, needs 2FA) |

### 2FA Behavior

| Event | 2FA Required? | What Happens |
|-------|---------------|--------------|
| Daily soft restart (23:45 UTC) | No | Session preserved |
| Sunday cold restart (05:00 UTC) | Yes | IBKR Mobile 2FA notification |
| VPS reboot / container crash | Yes | Docker auto-restarts, sends 2FA |
| Mobile login kicks VPS | — | VPS yields (secondary), health monitor auto-recovers |
| `/relogin_ibkr` Telegram command | Yes | Container restart + 2FA |

---

## Health Monitor (`/root/ib-gateway/ib_health_monitor.sh`)

Runs every 15 minutes via `ib-health-monitor.timer`. Tests actual ib_async API connectivity (not just port-open check).

**Flow:**
1. API alive? → Do nothing
2. API dead? → Restart container
3. Check IBC logs for "Existing session detected":
   - **Another session active** (mobile/desktop) → Gateway silently yields, no 2FA sent → Telegram: "Another session active, will retry in 15 min"
   - **No other session** → Telegram: "Approve 2FA on IBKR Mobile" → Waits 90s for re-auth
4. Success → Telegram: "Re-authenticated successfully"
5. Timeout → Telegram: "Send /relogin_ibkr to retry"

All Telegram notifications are sent only to chat_id `1130846055`.

---

## Telegram Integration

### `/relogin_ibkr` Command

Available on both Telegram bots:
- `telegram-claude-bot` (Finl_Agent_CC)
- `claude-oauth-bot` (Claude_OAuth_bot)

**Restricted to chat_id `1130846055` only.** Other users get silent ignore (no response).

**What it does:** Restarts IB Gateway Docker container, waits up to 90s for re-authentication, reports success/failure via Telegram.

---

## Dashboard

### URL
`http://187.77.136.160/IBKR_KZ/` (basic auth: `admin` / password in `/etc/nginx/.htpasswd`)

### Features
- Multi-account portfolio (positions, cost basis, P&L, market value)
- Open orders table
- ES Sentiment Panel (unified direction, confidence, key levels, themes)
- Interactive OHLCV price charts (1m/5m/15m/1h/1d/1w)
- Real-time IBKR news feed (7 providers)
- Custom watchlists with real-time prices
- WebSocket live updates (10s portfolio, 1s in live mode)

### Backend
- `dashboard/server.py` — FastAPI, connects to IB Gateway via ib_async (clientId 30)
- Serves API endpoints + static frontend from `dashboard/frontend/dist/`
- Auto-reconnects to IB Gateway on disconnect

### Frontend
- React 19 + TypeScript + Tailwind CSS + Vite
- Built with `base: '/IBKR_KZ/'` for sub-path deployment
- All fetch/WebSocket calls use `API()` helper from `config.ts`
- Pre-built in `dashboard/frontend/dist/` (450 KB total)

### Nginx Config (in `/etc/nginx/sites-enabled/dashboards`)
```nginx
# IBKR API
location /IBKR_KZ/api/ {
    proxy_pass http://127.0.0.1:8888/api/;
    ...
}
# IBKR WebSocket
location /IBKR_KZ/ws {
    proxy_pass http://127.0.0.1:8888/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    ...
}
# IBKR static assets
location /IBKR_KZ/assets/ {
    alias /root/IBKR/dashboard/frontend/dist/assets/;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
# IBKR SPA fallback
location /IBKR_KZ/ {
    alias /root/IBKR/dashboard/frontend/dist/;
    try_files $uri $uri/ /IBKR_KZ/index.html;
}
```

---

## Sentiment Pipeline

### `scripts/run_sentiment.py`
- Connects to IB Gateway (port 4001, clientId 98)
- Fetches ~4000 headlines from 7 IBKR news providers (BRFG, BRFUPDN, DJ-N, DJ-RT, DJ-RTA, DJ-RTE, DJ-RTG)
- Runs NLP sentiment analysis via `tools/news_sentiment_nlp.py`
- Merges with newsletter context from `/digest_ES` (40% NLP + 60% newsletters)
- Outputs unified ES trading direction (BEARISH/BULLISH/SIDEWAYS)

### Output Files
- `data/news/sentiment_analysis.json` — Full analysis with regime signals, key themes, top headlines
- `data/news/sentiment_timeseries.csv` — One row per run (tracks signal history)

### ES Newsletter Digest (`finl-digest-es.timer`)
- Runs Claude Code with `/digest_ES` skill
- Reads ES-focused emails: Smashelito, Geo Chen/Fidenza, James Bulltard, Daily Rip
- Updates `guides/market_context_ES.md` with current market regime context
- CWD: `/root/Finl_Agent_CC/` (shares newsletter tools with Financial Agent)

---

## Python Dependencies

Key packages in `/root/IBKR/venv/`:

| Package | Version | Purpose |
|---------|---------|---------|
| `ib-async` | 2.1.0 | IB Gateway API client |
| `fastapi` | 0.135.3 | Dashboard backend framework |
| `uvicorn` | 0.42.0 | ASGI server |
| `websockets` | 16.0 | WebSocket support |
| `pandas` | 3.0.1 | Data manipulation |
| `numpy` | 2.4.3 | Numerical operations |

---

## File Map (VPS: `/root/IBKR/`)

```
/root/IBKR/
├── dashboard/
│   ├── server.py              # FastAPI backend (1300 lines)
│   ├── watchlists.json        # Persistent watchlist storage
│   ├── requirements.txt       # Python deps for dashboard
│   ├── start.sh               # Dev launcher (not used in production)
│   └── frontend/
│       ├── dist/              # Pre-built React app (base: /IBKR_KZ/)
│       │   ├── index.html
│       │   └── assets/        # JS + CSS bundles
│       ├── src/               # React source (11 components)
│       ├── vite.config.ts     # Vite config (base: /IBKR_KZ/)
│       └── package.json       # Node deps (not needed in production)
├── scripts/
│   └── run_sentiment.py       # ES sentiment pipeline
├── tools/
│   ├── news_sentiment_nlp.py  # NLP sentiment engine
│   └── config.py              # Shared config
├── data/
│   └── news/
│       ├── sentiment_analysis.json   # Latest analysis
│       └── sentiment_timeseries.csv  # Historical signal log
├── guides/
│   └── market_context_ES.md   # ES newsletter digest (updated by finl-digest-es)
├── venv/                      # Python virtual environment
├── requirements.txt           # Python deps
└── .env                       # API keys (FRED, Finnhub, etc.)

/root/ib-gateway/
├── docker-compose.yml         # IB Gateway Docker config (credentials here)
├── ibc-config/
│   └── config.ini             # IBC auto-login settings
└── ib_health_monitor.sh       # Health check + auto-restart script
```

---

## Systemd Unit Files

All in `/etc/systemd/system/`:

### `ibkr-dashboard.service`
```ini
[Service]
Type=simple
WorkingDirectory=/root/IBKR
Environment=DASHBOARD_PORT=8888
Environment=IBKR_PORT=4001
Environment=IBKR_HOST=127.0.0.1
Environment=DASHBOARD_CLIENT_ID=30
ExecStart=/root/IBKR/venv/bin/python dashboard/server.py
Restart=always
RestartSec=5
```

### `ibkr-sentiment.service` + `ibkr-sentiment.timer`
```ini
# Service
[Service]
Type=oneshot
WorkingDirectory=/root/IBKR
ExecStart=/root/IBKR/venv/bin/python scripts/run_sentiment.py
TimeoutStartSec=120

# Timer — 3x daily (11am, 8pm, 11pm SGT)
[Timer]
OnCalendar=*-*-* 03:00:00
OnCalendar=*-*-* 12:00:00
OnCalendar=*-*-* 15:00:00
Persistent=true
```

### `ib-health-monitor.service` + `ib-health-monitor.timer`
```ini
# Service
[Service]
Type=oneshot
ExecStart=/root/ib-gateway/ib_health_monitor.sh
TimeoutStartSec=180

# Timer — every 15 minutes
[Timer]
OnCalendar=*:0/15
Persistent=true
RandomizedDelaySec=60
```

### `finl-digest-es.service` + `finl-digest-es.timer`
```ini
# Service (runs in Finl_Agent_CC context)
[Service]
Type=oneshot
WorkingDirectory=/root/Finl_Agent_CC
ExecStart=/usr/bin/claude -p --allowedTools "Bash(python*) Read Write Edit Glob Grep" --model sonnet "Run the /digest_ES skill..."
TimeoutStartSec=900

# Timer — 2x daily (8am, 8pm SGT)
[Timer]
OnCalendar=*-*-* 00:00:00
OnCalendar=*-*-* 12:00:00
Persistent=true
```

---

## Firewall (UFW)

```
22/tcp    ALLOW   (SSH)
80/tcp    ALLOW   (nginx — all dashboards behind basic auth)
```

No other ports are exposed. IB Gateway API (4001) and dashboard backend (8888) are localhost-only.

---

## Quick Reference

```bash
# Start everything
systemctl start ibkr-dashboard
cd /root/ib-gateway && docker compose up -d   # → approve 2FA
systemctl enable --now ib-health-monitor.timer ibkr-sentiment.timer finl-digest-es.timer

# Check status
systemctl status ibkr-dashboard
/root/ib-gateway/ib_health_monitor.sh --check
curl -u admin:PASSWORD http://127.0.0.1/IBKR_KZ/api/status

# Re-login IB Gateway
# From Telegram: /relogin_ibkr
# From SSH: cd /root/ib-gateway && docker compose restart

# View logs
journalctl -u ibkr-dashboard -f
journalctl -u ibkr-sentiment --since "1 hour ago"
journalctl -u ib-health-monitor --since "1 hour ago"
docker logs ib-gateway-ib-gateway-1 --tail 20

# Run sentiment manually
cd /root/IBKR && venv/bin/python scripts/run_sentiment.py

# VNC debug (from Mac)
ssh -L 5900:127.0.0.1:5900 root@187.77.136.160
open vnc://localhost:5900
```
