# IBKR — ES Futures Trading System + Financial Analysis Agent

A comprehensive trading system built around Interactive Brokers, featuring a React dashboard with real-time portfolio monitoring, an ES sentiment pipeline (NLP + newsletter fusion), automated strategy optimization (autoresearch), and a full financial analysis agent with 20+ tools.

## Quick Start

```bash
# React Dashboard (auto-finds ports, starts backend + frontend)
bash dashboard/start.sh                   # Opens at http://localhost:5173

# ES Sentiment Pipeline
python scripts/run_sentiment.py           # Fetch IBKR headlines + run NLP
python scripts/run_sentiment.py --dry-run # Use cached headlines

# Financial Analysis Agent
# Use /fin <command> in Claude Code session

# Autoresearch (ES Strategy Optimization)
cd autoresearch
python autoresearch.py init               # Establish baseline
python batch_iterate.py 1000              # Run parameter sweep
```

## Components

### 1. React Dashboard (`dashboard/`)

Multi-account portfolio viewer with real-time updates:
- **Portfolio** — Account selector, positions table with daily P&L, unrealized P&L, P&L%. Options positions show Put/Call, strike, expiry columns automatically. Instrument type filter (STK/OPT/FUT/FOP/etc.)
- **Open Orders** — Pending orders (symbol, action, type, qty, limit/stop price, status)
- **ES Sentiment Panel** — Unified direction (BEARISH/BULLISH/SIDEWAYS), Smashlevel pivot, VIX tier, JPM z-score, NAAIM, key levels
- **Price Charts** — Click any symbol for OHLCV chart (1m/5m/15m/1h/1d/1w). Auto-refreshing in live mode with LIVE/PAUSED toggle
- **News Feed** — Real-time IBKR headlines from 7 providers. Click any headline to read the full article (via `reqNewsArticle`)
- **Watchlists** — Custom instrument lists with real-time prices, expandable instrument details with delivery months and open interest
- **Search** — IBKR symbol search with expandable contract details, delivery month browser for futures, per-contract OI display

Backend: FastAPI + ib_async with auto-port detection (7496/7497/4001/4002).
Frontend: Vite + React + TypeScript + Tailwind CSS.
Deployed on VPS at `http://187.77.136.160/IBKR_KZ/`.

### 2. Financial Analysis Agent (`tools/`, `guides/`)

20 Python analysis tool modules callable via `/fin <command>`:
- Macro scan (27 indicators), regime classification, financial stress (0-10), late-cycle detection
- Equity analysis (~500 S&P 500 companies), Graham value, Murphy TA (13 frameworks)
- Commodity analysis, BTC futures, pro-trader frameworks (risk premium, cross-asset, PM regime, USD regime)
- Stop-loss framework (Fidenza 10-rule), macro synthesis with contradiction detection
- ES sentiment (NLP + newsletter fusion), news streaming from IBKR

### 3. ES Sentiment Pipeline (`scripts/run_sentiment.py`)

Fuses IBKR news headlines with newsletter context:
- Fetches ~4000 headlines from 7 IBKR providers
- NLP sentiment analysis (bullish/bearish polarity, analyst actions, regime signals)
- Merges with newsletter context from `/digest_ES` (40% NLP + 60% newsletters)
- Outputs: `data/news/sentiment_analysis.json` + `data/news/sentiment_timeseries.csv`
- Scheduled 3x daily (11am, 8pm, 11pm)

### 4. Autoresearch (`autoresearch/`)

Automated ES strategy optimization via hill-climbing parameter search:
- Sequential decision pipeline: Regime classification -> Macro filter -> Daily trend -> Technical composite -> Adaptive entry/exit
- Single-parameter variations, backtest, score, KEEP or REVERT
- Current best: +10.61% return, 22.46% max DD, 36% win rate (Jan 2025 - Mar 2026)
- Algorithm versioning in `versions/` (immutable snapshots per logical change)

## Core Market Data Library (`ibkr/`)

```python
from ibkr import IBKRConnection, ContractFactory, MarketDataService

conn = IBKRConnection()
with conn.session() as ib:
    mds = MarketDataService(ib)
    quote = mds.get_quote(ContractFactory.gold_future())
    print(f"Gold: ${quote.last:,.2f}")
```

Supports: Precious metals (GC, SI, HG, PL, PA), Treasuries (ZN, ZB, ZF, ZT, UB), Equity indices (ES, NQ, YM, RTY + micros), Energy (CL, NG, MCL).

## ES Data Files

| File | Bars | Range |
|------|------|-------|
| ES_1min.parquet | 241K | Jan 2025 - Mar 2026 |
| ES_combined_5min.parquet | 48K | Jan 2025 - Mar 2026 |
| ES_daily.parquet | 638 | Aug 2023 - Mar 2026 |

## Key Commands

| Command | Description |
|---------|-------------|
| `/fin scan` | Quick macro scan (27 indicators) |
| `/fin macro` | Macro regime classification |
| `/fin stress` | Financial stress score (0-10) |
| `/fin ta ES=F` | Technical analysis (Murphy 13-framework) |
| `/fin full_report` | 8-step analysis chain |
| `/digest` | Read newsletters -> market context |
| `/digest_ES` | Read ES-focused newsletters |

## Documentation

### Dashboard
| Document | Description |
|----------|-------------|
| [`dashboard/dashboard_specifications.md`](dashboard/dashboard_specifications.md) | Full dashboard specs — API endpoints, WebSocket protocol, frontend components, authentication, IB thread queue pattern, deploy workflow |

### VPS & Infrastructure
| Document | Description |
|----------|-------------|
| [`VPS_Hostinger_setup.md`](VPS_Hostinger_setup.md) | Hostinger VPS deployment — Docker IB Gateway config, nginx routing, systemd services/timers, health monitoring, Telegram `/relogin_ibkr` command, 2FA session management |
| [`IB_Docker_VPS/README.md`](IB_Docker_VPS/README.md) | Docker-specific setup details and Telegram bot configuration |

### Guides (`guides/`)
Interpretation and framework references used by the `/fin` analysis agent:

| Guide | Description |
|-------|-------------|
| [`guides/macro_framework.md`](guides/macro_framework.md) | Macro regime classification framework — indicator interpretation, regime definitions, cycle positioning |
| [`guides/ta_guide.md`](guides/ta_guide.md) | Technical analysis guide — Murphy 13-framework methodology for `/fin ta` |
| [`guides/interpretation.md`](guides/interpretation.md) | How to interpret analysis outputs — reading scores, signals, and regime labels |
| [`guides/thresholds.md`](guides/thresholds.md) | Threshold values for indicators — what levels trigger bullish/bearish/neutral signals |
| [`guides/workflows.md`](guides/workflows.md) | Analysis workflows — how to chain `/fin` commands for comprehensive research |
| [`guides/self_evaluation.md`](guides/self_evaluation.md) | Agent self-evaluation criteria — quality checks for analysis outputs |
| [`guides/market_context.md`](guides/market_context.md) | Latest general market context (auto-updated by `/digest`) |
| [`guides/market_context_ES.md`](guides/market_context_ES.md) | Latest ES-specific market context from newsletter digests (auto-updated by `/digest_ES`) |
| [`guides/news_streaming_requirements.md`](guides/news_streaming_requirements.md) | News streaming architecture and provider requirements |
| [`guides/ml_quant_tools_evaluation.md`](guides/ml_quant_tools_evaluation.md) | Evaluation of ML/quant tools and libraries for strategy development |

### Technical Documentation (`docs/`)
| Document | Description |
|----------|-------------|
| [`docs/BACKTEST_GUIDE.md`](docs/BACKTEST_GUIDE.md) | Backtesting methodology — how to run backtests, interpret results, avoid common pitfalls |
| [`docs/ES_DATA_SOURCES.md`](docs/ES_DATA_SOURCES.md) | ES data pipeline — parquet file schemas, data ranges, how to update/extend historical data |
| [`docs/ibkr_available_metrics.md`](docs/ibkr_available_metrics.md) | Available IBKR API metrics — account summary tags, market data tick types, contract details fields |

### Autoresearch
| Document | Description |
|----------|-------------|
| [`autoresearch/STRATEGY_CONTEXT.md`](autoresearch/STRATEGY_CONTEXT.md) | Strategy architecture — decision pipeline, tunable parameter ranges, active features, prior strategy approaches |
| [`autoresearch/NEXT_STEPS.md`](autoresearch/NEXT_STEPS.md) | Current roadmap — next steps, ideas to try, exhausted/abandoned approaches |
| [`autoresearch/SCORING.md`](autoresearch/SCORING.md) | Scoring formula — how iterations are scored, diagnostic flowchart for zero-score results |
| [`autoresearch/SKILL.md`](autoresearch/SKILL.md) | Full iteration protocol — step-by-step procedure for running autoresearch iterations |
| [`AR_exp_log.md`](AR_exp_log.md) | Complete experiment history — every major experiment, structural change, and strategy decision |

### Other
| Document | Description |
|----------|-------------|
| [`DATA_SOURCES.md`](DATA_SOURCES.md) | FRED API series IDs and local CSV data map — all 56 economic series + 120+ local CSV files |
| [`ES Trading Approach.md`](ES%20Trading%20Approach.md) | High-level ES trading approach and philosophy |

## Prerequisites

- TWS or IB Gateway running with API enabled (port 7496/7497)
- Python 3.11+, Node.js (for React dashboard)
- API keys: FRED_API_KEY, TAVILY_API_KEY (optional), TWITTERAPI_IO_KEY (optional)

## Downstream consumer: Opportunity_scanner

[`Opportunity_scanner/`](../Opportunity_scanner/) consumes outputs of this repo read-only under a **parallel-pipeline contract** — no edits to scripts, schemas, output paths, or timers in this repo. Scanner either reads cache files or runs its own IBKR client with a distinct clientId (99/100/101 reserved). See [`Opportunity_scanner/CLAUDE.md`](../Opportunity_scanner/CLAUDE.md) for the full design rule and per-strategy mappings.

Scanner strategies that depend on this repo:
- [strategy 01 — news-event equity overlay](../Opportunity_scanner/strategies/01_news_event_equity_overlay/README.md) (own per-ticker fetcher with clientId 99 + read-only sentiment cross-validation)
- [strategy 03 — HIP-3 ↔ IBKR equity basis](../Opportunity_scanner/strategies/03_hip3_ibkr_basis/README.md) (own live-quote fetcher with clientId 100)
- [strategy 04 — ES newsletter sentiment overlay](../Opportunity_scanner/strategies/04_es_newsletter_sentiment/README.md) (read-only of `data/news/sentiment_*` and `data/es/ES_combined_5min.parquet`)
- [strategy 05 — Treasury curve / COT extremes](../Opportunity_scanner/strategies/05_treasury_curve_cot/README.md) (own treasury-futures fetcher with clientId 101)
