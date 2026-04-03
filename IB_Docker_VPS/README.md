# IB Gateway Docker — VPS Deployment

Dockerized IB Gateway with IBC auto-login for headless VPS deployment. Currently deployed on **Hostinger VPS** (187.77.136.160).

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Hostinger VPS (187.77.136.160)                 │
│                                                 │
│  ┌───────────────────────────────────┐          │
│  │  Docker: ghcr.io/gnzsnz/ib-gateway│          │
│  │                                   │          │
│  │  IB Gateway + IBC auto-login      │          │
│  │  ├─ API: 127.0.0.1:4001 (live)   │          │
│  │  ├─ API: 127.0.0.1:4002 (paper)  │          │
│  │  └─ VNC: 127.0.0.1:5900 (debug)  │          │
│  └───────────────────────────────────┘          │
│                    ▲                            │
│                    │ localhost                   │
│  ┌─────────────────┴─────────────────┐          │
│  │  Python trading scripts           │          │
│  │  Connect to 127.0.0.1:4001        │          │
│  └───────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
         ▲
         │ SSH tunnel (encrypted)
         │
┌────────┴────────────────────────────────────────┐
│  Your Mac                                       │
│  ssh -L 4001:127.0.0.1:4001 root@187.77.136.160│
│  → localhost:4001 on Mac ──► VPS IB Gateway     │
└─────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Docker config (template — credentials redacted) |
| `ibc-config/config.ini` | IBC auto-login and 2FA settings |
| `health_check.sh` | Quick health check script |
| `README.md` | This file |

## VPS Setup (From Scratch)

### 1. Install Docker

```bash
ssh root@187.77.136.160

apt update && apt install -y docker.io docker-compose-plugin
systemctl enable docker
```

### 2. Create Directory & Config

```bash
mkdir -p ~/ib-gateway/ibc-config
cd ~/ib-gateway
```

Copy `docker-compose.yml` and `ibc-config/config.ini` from this repo, then fill in credentials:

```bash
# Edit docker-compose.yml — replace:
#   YOUR_IBKR_USERNAME → your IBKR login
#   YOUR_IBKR_PASSWORD → your IBKR password
#   YOUR_VNC_PASSWORD  → pick a VNC password

# Lock down permissions
chmod 600 ~/ib-gateway/docker-compose.yml
```

### 3. Start IB Gateway

```bash
cd ~/ib-gateway
docker compose up -d
```

### 4. First-Time 2FA

IBC will auto-fill credentials and click login. Your **IBKR Mobile app** will receive a 2FA notification — tap **Approve**.

Check logs to confirm:
```bash
docker compose logs -f ib-gateway
```

Look for: `IBC: Click button: Log In` → then 2FA prompt on phone → approve → connected.

### 5. Verify API

```bash
nc -z 127.0.0.1 4001 && echo "API UP" || echo "API DOWN"
```

## Day-to-Day Operations

### Check Status
```bash
docker compose -f ~/ib-gateway/docker-compose.yml ps
docker compose -f ~/ib-gateway/docker-compose.yml logs --tail 20
```

### Restart (Triggers Re-Auth + 2FA)
```bash
cd ~/ib-gateway
docker compose restart
# → Check phone for 2FA approval
```

### Stop
```bash
docker compose -f ~/ib-gateway/docker-compose.yml down
```

### VNC Debug Access (From Mac)
```bash
# SSH tunnel
ssh -L 5900:127.0.0.1:5900 root@187.77.136.160

# Open VNC viewer
open vnc://localhost:5900
```

## Reconnecting After Being Kicked Out

When you log into IBKR Mobile, the VPS gateway gets kicked. Here's what happens:

1. **IBC detects disconnect** → auto-reconnects with `ExistingSessionDetectedAction=primary`
2. **2FA prompt sent** → tap Approve on IBKR Mobile
3. **Gateway reconnects** → no SSH needed

If auto-reconnect fails:
```bash
# Option A: VNC (see GUI)
ssh -L 5900:127.0.0.1:5900 root@187.77.136.160
open vnc://localhost:5900

# Option B: Full restart
ssh root@187.77.136.160 'cd ~/ib-gateway && docker compose restart'
# → Approve 2FA on phone
```

## Scheduled Events

| Event | When | Action Required |
|-------|------|-----------------|
| Daily soft restart | 23:45 UTC | None (IBC handles it) |
| Weekly cold restart (IBKR reset) | Sunday ~01:00 ET | Tap IBKR Mobile 2FA |
| Crash / disconnect | Rare | Docker auto-restarts → 2FA tap |

## Connecting Trading Code

### From VPS (Recommended)
```python
from ibapi.client import EClient
app.connect("127.0.0.1", 4001, clientId=1)  # Live
app.connect("127.0.0.1", 4002, clientId=1)  # Paper
```

### From Mac (SSH Tunnel)
```bash
# Terminal 1
ssh -L 4001:127.0.0.1:4001 root@187.77.136.160

# Terminal 2
python my_script.py  # connects to localhost:4001
```

## Current Config

- **Mode**: Live (read-only API)
- **VPS**: Hostinger 187.77.136.160
- **Docker image**: `ghcr.io/gnzsnz/ib-gateway:latest`
- **Credential file**: `/root/ib-gateway/docker-compose.yml` (chmod 600)
- **IBC config**: `/root/ib-gateway/ibc-config/config.ini`

## Switching to Full Trading

Edit `docker-compose.yml` on VPS:
```yaml
READ_ONLY_API: "no"   # was "yes"
```

Edit `ibc-config/config.ini` on VPS:
```ini
ReadOnlyLogin=no       # was yes
```

Then restart:
```bash
cd ~/ib-gateway && docker compose down && docker compose up -d
```

## Telegram Bot → Claude Code Bridge

A Telegram bot that triggers Claude Code financial agent sessions headlessly on the VPS.

### Files

| File | Purpose |
|------|---------|
| `telegram_claude_bot.py` | Bot code (deployed to `/root/Finl_Agent_CC/`) |
| `telegram_claude_bot.service` | systemd service unit |

### Setup

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. **Get your chat ID** via [@userinfobot](https://t.me/userinfobot) → `/start` → copy the number
3. **Add credentials to .env** on VPS:

```bash
ssh root@187.77.136.160

# Append to the agent's .env
cat >> /root/Finl_Agent_CC/.env << 'EOF'
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
EOF
```

4. **Ensure Claude Code is authenticated** on VPS:
```bash
claude auth login
# or
claude setup-token
```

5. **Start the bot**:
```bash
systemctl daemon-reload
systemctl enable telegram-claude-bot
systemctl start telegram-claude-bot
systemctl status telegram-claude-bot
```

### Telegram Commands

**Macro & Regime:**
- `/scan` / `/scan full` — Indicator scan
- `/macro` — Macro regime
- `/stress` — Financial stress score
- `/bonds` — Bond market analysis
- `/latecycle` — Late cycle detection
- `/consumer` — Consumer health
- `/synthesize` — Full macro synthesis
- `/full_report` — 8-step briefing chain

**Equity:**
- `/analyze NVDA` — Equity analysis
- `/compare AAPL,MSFT` — Peer comparison
- `/graham AAPL` — Graham value analysis

**Technical Analysis:**
- `/ta gold` — Technical analysis
- `/rsi SPY` — RSI analysis
- `/quickta AAPL` — Quick TA snapshot

**BTC:**
- `/btc` — BTC futures analysis

**Commodity:**
- `/commodity gold` — Commodity outlook
- `/oil` — Oil analysis

**Freeform:**
- `/ask Why is VIX elevated today?` — Any question

**System:**
- `/health` — IB Gateway + services status
- `/status` — Bot uptime + RAM

### How It Works

```
You send /scan on Telegram
  → Bot receives message via long-polling
  → Bot spawns: claude -p "run /fin scan" --dangerously-skip-permissions
  → Claude Code reads CLAUDE.md, runs python tools/run.py scan
  → Claude Code interprets results like a senior analyst
  → Bot sends the analysis back to Telegram
```

Each command runs in its own thread. Duplicate commands are blocked until the previous one finishes. Max timeout: 5 minutes per command.

### Logs

- Bot log: `/root/Finl_Agent_CC/logs/telegram_bot.log`
- Run records: `/root/Finl_Agent_CC/logs/runs-YYYY-MM-DD.log`

## Memory Usage

IB Gateway Docker uses ~300-500 MB RAM. Hostinger VPS has 7.8 GB total, so no concerns.
