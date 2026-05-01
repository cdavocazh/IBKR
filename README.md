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

### 3. ES Sentiment Pipeline (Two-tier)

**Tier 1 — 3x daily batch** (`scripts/run_sentiment.py`):
- Fetches ~4000 headlines from 7 IBKR providers
- NLP sentiment analysis (bullish/bearish polarity, analyst actions, regime signals)
- Merges with newsletter context from `/digest_ES` (40% NLP + 60% newsletters)
- Outputs: `data/news/sentiment_analysis.json` + `data/news/sentiment_timeseries.csv`
- Scheduled 3x daily (11am, 8pm, 11pm)

**Tier 2 — continuous + 15-min rolling** (NEW May 2026, deployed on VPS):
- `tools/news_stream_continuous.py` — long-running daemon (clientId 27) polls
  `reqHistoricalNews` every 90s, persists to `data/news/headlines.db` (SQLite)
- `tools/sentiment_intraday.py` — 15-min cron aggregates rolling sentiment over
  5 windows (15m / 30m / 1h / 4h / 24h) plus topic-mix % (fed / war / inflation / earnings)
  → `data/news/sentiment_intraday.csv`
- `tools/sentiment_finbert.py` + `tools/sentiment_hybrid.py` — optional
  FinBERT/DistilRoBERTa transformer scorer; gracefully falls back to regex
  when `transformers`/`torch` not installed

### 4. Multi-Input ES Signal Stack (NEW May 2026)

Three additional ES-relevant inputs feeding `verify_strategy.py::_compute_composite()`:
- `tools/mag7_breadth.py` — MAG7 mega-cap breadth (% above 5/20/50d MA, market-cap-weighted % chg);
  systemd `ibkr-mag7-breadth.timer` runs every 5 min (clientId 28)
- `tools/polymarket_signal.py` — read-only consumer of `~/Github/market-tracker/data_cache/all_indicators.json`;
  extracts Fed cut prob, recession prob, geopolitics escalation, fiscal expansion, etc.
- `tools/macro_calendar.py` — FOMC/CPI/NFP/PCE/ISM-PMI + mega-cap earnings blackout windows;
  reads `~/Github/macro_2/historical_data/earnings_calendar.csv`

All four feeds are wired into the backtest behind sweepable config flags (default OFF):
`INTRADAY_SENTIMENT_*`, `MAG7_BREADTH_*`, `POLYMARKET_*`, `MACRO_BLACKOUT_*`.

### 5. Self-Learning Framework (NEW May 2026, three layers)

- **Layer A** — `tools/sentiment_self_learner.py`: nightly EMA update of
  macro keyword weights based on per-keyword regression vs forward 1-hour ES returns.
  Writes `data/news/keyword_weights.json` (read by `news_sentiment_nlp.py` when present).
  Systemd: `ibkr-keyword-learner.timer` (04:00 UTC daily).
- **Layer B** — `scripts/sentiment_walkforward.py`: weekly Ridge regression
  `forward_return_1h ~ {sentiment, breadth, polymarket, vix}` →
  `data/es/signal_weights_dynamic.json`.
- **Layer C** — `scripts/sentiment_rl_agent.py`: PPO ensemble agent
  (Stable-Baselines3) wrapping the new step-callable `BacktestRunner`. 12-dim
  state, 4-dim continuous action (position size, sentiment weight, MR weight,
  blackout strict mode). Optional deps: `stable-baselines3`, `gymnasium`.

### 6. Autoresearch (`autoresearch/`)

Automated ES strategy optimization via hill-climbing parameter search:
- Sequential decision pipeline: Regime classification -> Macro filter -> Daily trend -> Technical composite -> Adaptive entry/exit
- Single-parameter variations, backtest, score, KEEP or REVERT
- Current best (extended data, MR-only ATR=1.6): **-0.03% return, 1.99% DD, 6 trades, 83% WR, PF 16.9** (~$32 from breakeven on $100K)
- Pre-war best: +14.73% return, 28.88% DD, 34% WR, 44 trades
- Algorithm versioning in `versions/` (immutable snapshots per logical change)
- Step-callable `BacktestRunner` in `verify_strategy.py` (used by Phase 5C PPO env)

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

| File | Bars | Range | Notes |
|------|------|-------|-------|
| `data/es/ES_1min.parquet` | 241K | Jan 2025 - Mar 2026 | High-resolution intraday |
| `data/es/ES_combined_5min.parquet` | 50.7K | Jan 31 2025 - Apr 2 2026 | Primary backtest (extended through Iran war) |
| `data/es/ES_daily.parquet` | 649 | Aug 2023 - Apr 2 2026 | Daily overlay |
| `data/es/ES_combined_hourly_extended.parquet` | 7.1K | Apr 2023 - Mar 2026 | SPY-converted + real ES hourly |
| `data/es/ml_entry_signal.csv` | 330 | Dec 2024 - Apr 2026 | Walk-forward LightGBM predictions |
| `data/es/mag7_breadth.csv` | live | May 2026+ | MAG7 breadth (5-min cadence; gitignored) |
| `data/es/polymarket_signals.csv` | live | May 2026+ | Polymarket probabilities (gitignored) |
| `data/news/headlines.db` | 6.4K+ | 2023-2026 | SQLite headline store (gitignored, grows continuously) |
| `data/news/sentiment_intraday.csv` | live | May 2026+ | 15-min rolling sentiment (gitignored) |

## Key Commands

### Slash commands (Claude Code skills)
| Command | Description |
|---------|-------------|
| `/fin scan` | Quick macro scan (27 indicators) |
| `/fin macro` | Macro regime classification |
| `/fin stress` | Financial stress score (0-10) |
| `/fin ta ES=F` | Technical analysis (Murphy 13-framework) |
| `/fin sl ES 6000 long` | Stop-loss framework (Fidenza 10-rule) |
| `/fin full_report` | 8-step analysis chain |
| `/digest` | Read newsletters → `guides/market_context.md` |
| `/digest_ES` | Read ES-focused newsletters → `guides/market_context_ES.md` |

### Sentiment + multi-input CLI tools
```bash
# 3x daily ES sentiment batch (the existing pipeline)
python scripts/run_sentiment.py                    # auto-detect IBKR port
python scripts/run_sentiment.py --port 7496 --days 14
python scripts/run_sentiment.py --dry-run          # use cached headlines

# Continuous IBKR news polling (the new May 2026 daemon — runs on VPS)
python tools/news_stream_continuous.py --interval 60      # every 60s
python tools/news_stream_continuous.py --tickers AAPL,NVDA,SPY --client-id 27

# 15-min rolling sentiment aggregator
python tools/sentiment_intraday.py --bucket-now            # current bucket
python tools/sentiment_intraday.py --since 2026-05-01 --until 2026-05-02

# FinBERT/DistilRoBERTa hybrid scorer (Phase 3)
python tools/sentiment_hybrid.py "Goldman upgrades NVDA to Buy"
python tools/sentiment_finbert.py --bench                  # benchmark on 20 sample headlines
HYBRID_DISABLE_FINBERT=1 python tools/sentiment_hybrid.py "..."  # force regex-only mode

# MAG7 mega-cap breadth indicator
python tools/mag7_breadth.py --source auto --append-csv    # IBKR or yfinance
python tools/mag7_breadth.py --source yfinance --symbols AAPL,MSFT,NVDA

# Polymarket prediction-market signals (reads market-tracker cache)
python tools/polymarket_signal.py --append-csv
python tools/polymarket_signal.py --history --n 20

# Macro release calendar — blackout windows
python tools/macro_calendar.py --next 10                   # next 10 high-impact releases
python tools/macro_calendar.py --check NOW                 # is now in a blackout?
python tools/macro_calendar.py --check 2026-05-12T13:30 --lookback 30 --lookahead 60

# Self-learning layers (Phase 5)
python tools/sentiment_self_learner.py --report-only       # nightly keyword weight EMA
python scripts/sentiment_walkforward.py --validate         # weekly Ridge refit + OOS R²
python scripts/sentiment_rl_agent.py --check               # PPO dependency check
python scripts/sentiment_rl_agent.py --train --steps 100000 --train-days 90
python scripts/sentiment_rl_agent.py --inference           # one-shot agent action

# News streaming raw harness (low-level)
python scripts/ib_news_stream.py verify                    # full IBKR news API check
python scripts/ib_news_stream.py providers                 # list 7 providers
python scripts/ib_news_stream.py headlines AAPL --count 50
python scripts/ib_news_stream.py stream AAPL,NVDA --duration 300
```

### Backtest commands
```bash
# Composite + MR strategy backtest
cd autoresearch && python verify_strategy.py               # outputs SCORE
python autoresearch.py status                              # latest iteration state
python batch_iterate.py 1000 --report-every 50             # run 1000-iter sweep

# Standalone MR scalper
python scripts/backtest_mr_scalper.py
python scripts/backtest_mr_scalper.py --sweep              # 47-config grid

# Dual-system equity-curve combiner (composite + MR scalper)
python scripts/backtest_dual_system.py
```

### Env variable knobs
| Var | Effect |
|-----|--------|
| `IBKR_HOST` | Override IBKR Gateway host (default `127.0.0.1`) |
| `IBKR_PORT` | Override IBKR Gateway port (auto-detects 4001/4002/7496/7497) |
| `IB_NEWS_CLIENT_ID` | clientId for `news_stream_continuous.py` (default 27) |
| `IB_BREADTH_CLIENT_ID` | clientId for `mag7_breadth.py` (default 28) |
| `MACRO_DATA_DIR` | Override `~/Github/macro_2/historical_data/` location |
| `PYTHON_INTERPRETER` | Override Python path used by subprocess calls in scripts |
| `HYBRID_DISABLE_FINBERT` | Set to `1` to force regex-only sentiment scoring |
| `DASHBOARD_SECRET` | Override the dashboard auth secret (defaults to file-stored) |

### VPS systemd units (deployed to Hostinger)
| Unit | Cadence | Purpose |
|------|---------|---------|
| `ibkr-dashboard.service` | continuous | Portfolio dashboard (FastAPI + WebSocket, port 8888) |
| `ibkr-broadtape.service` | continuous (every 90s poll) | Persistent IBKR news polling → `headlines.db` |
| `ibkr-sentiment.timer` | 03:00, 12:00, 15:00 UTC | 3x daily batch sentiment + NLP |
| `ibkr-sentiment-15min.timer` | every 15 min | Intraday sentiment aggregation |
| `ibkr-mag7-breadth.timer` | every 5 min | MAG7 breadth snapshot |
| `ibkr-keyword-learner.timer` | 04:00 UTC daily | Self-learning keyword weight EMA |
| `finl-digest-es.timer` | 00:00, 12:00 UTC | ES newsletter digest via Claude Code |
| `ib-health-monitor.timer` | every 15 min | IB Gateway health check + auto-restart |

To deploy a new unit: `scp systemd/<unit> root@VPS:/etc/systemd/system/ && ssh root@VPS "systemctl daemon-reload && systemctl enable --now <unit>"`. See [`VPS_Hostinger_setup.md`](VPS_Hostinger_setup.md) for full deployment workflow.

### Recent user-impacting changes
- **2026-05-01** — `tools/news_stream_continuous.py` switched from broadtape subscription to `reqHistoricalNews` polling (legacy broadtape was already broken with current ib_async). Now deployed on VPS as `ibkr-broadtape.service`.
- **2026-05-01** — Added `BacktestRunner` step-callable interface to `verify_strategy.py` for use by Phase 5C PPO env. `run_backtest()` behavior unchanged.
- **2026-05-01** — `news_sentiment_nlp.py::classify_macro_sentiment` now reads learned weights from `data/news/keyword_weights.json` when present (file is regenerated nightly by `sentiment_self_learner.py`). Falls back to hardcoded constants if missing.
- **2026-04-12** — Combined Strategy v2 with independent MR state achieved best result on extended dataset (-0.03% return, 1.99% DD, 83% WR, PF 16.9).

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
