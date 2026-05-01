# IBKR Project Status

**Last Updated:** 2026-05-01

## Overview

This repository contains:
1. **Autoresearch** — Automated parameter optimization for ES futures trading strategies (~24,100 iterations)
2. **React Dashboard** — Real-time portfolio monitoring + ES sentiment + price charts
3. **Financial Analysis Agent** — `/fin` skill with 20 analysis tools, `/digest` and `/digest_ES` newsletter readers
4. **ES Sentiment Pipeline** — IBKR news + newsletter NLP analysis
5. **VPS Deployment** — Hostinger VPS running IB Gateway + dashboard + Telegram bots
6. **Higher-Frequency Sentiment Stack** *(NEW — May 2026)* — Persistent broadtape streamer, 15-min rolling sentiment, MAG7 breadth, Polymarket signals, macro release calendar blackouts

---

## Current Strategy Status (Autoresearch)

### Best Results

| Config | Score | Return | DD | Trades | WR | PF | Period |
|--------|-------|--------|-----|--------|-----|-----|--------|
| **Composite (pre-war Mar 2026)** | **10.47** | **+14.73%** | 28.88% | 44 | 34% | — | Jan 2025 – Mar 20 2026 |
| **Combined v2 (extended)** | -0.03 | -0.03% | **1.99%** | 6 | **83%** | **16.9** | Jan 2025 – Apr 2 2026 |
| **MR Scalper standalone** | — | +4.25% | 4.4% | 51 | 43% | — | High-vol days only |
| **Dual-system (20/80 split)** | — | +3.39% | ~3.9% | 57 | — | — | Combined equity curves |

### What Happened
The composite strategy peaked at **+14.73%** on data ending March 20 2026. When data was extended through April 2 2026 (Iran war period, ES dropped ~8%), the strategy collapsed to negative. **21,000+ post-extension iterations across 28 sweep batches yielded 0 positive scores.**

The breakthrough came with **Combined Strategy v2** (Apr 6 2026): independent state routing where MR scalper and composite each have their own cooldown, trade counter, and circuit breaker. This achieved **-0.03 score with 83% WR and PF 16.9** on the war-extended dataset.

### Total Iterations
**~24,100** across 34 sweep batches (Jan – Apr 2026)

---

## Data Inventory

### ES Futures (`data/es/`)
| File | Bars | Date Range | Notes |
|------|------|------------|-------|
| `ES_combined_5min.parquet` | 50,760 | Jan 31 2025 – Apr 2 2026 | Primary backtest |
| `ES_1min.parquet` | 241,009 | Jan 2025 – Mar 2026 | High-res |
| `ES_daily.parquet` | 649 | Aug 2023 – Apr 2 2026 | Daily overlay |
| `ES_combined_hourly_extended.parquet` | 7,119 | Apr 2023 – Mar 2026 | SPY-converted + real |
| `ES_implied_volatility_daily.parquet` | 401 | Aug 2024 – Mar 2026 | IV |
| `ES_historical_volatility_daily.parquet` | 265 | Mar 2025 – Mar 2026 | HV |
| `ml_entry_signal.csv` | 330 | Dec 2024 – Apr 2026 | Walk-forward LightGBM predictions |
| `tsfresh_daily_features.csv` | — | — | 27 statistically significant features |
| `garch_daily_forecast.csv` | — | through Mar 20 | GARCH(1,1) conditional variance |
| `particle_regime_daily.csv` | — | — | Bayesian SMC regime probabilities |
| `cusum_events.csv` | — | — | Structural break events |

### Other Instruments
- **GC (Gold)**: 1-min, 5-min, IV, HV (data through early 2026)
- **SI (Silver)**: 1-min, 5-min, IV, HV
- Less actively used — focus shifted to ES autoresearch

### News & Sentiment (`data/news/`)
| File | Content |
|------|---------|
| `daily_sentiment.csv` | 345 days WSJ + DJ-N composite sentiment |
| `wsj_subjects.json` | 298 WSJ Markets A.M./P.M. subjects |
| `sample_headlines.json` | 291 IBKR DJ-N headlines |
| `sentiment_analysis.json` | Latest full ES sentiment analysis |
| `sentiment_timeseries.csv` | Historical signal log (one row per run) |

---

## Active Components

### Autoresearch (`autoresearch/`)
- **Status**: Active hill-climbing, currently exhausted on extended data
- **Best mutable file**: `es_strategy_config.py` (~470 lines, ~120 params)
- **Backtest engine**: `verify_strategy.py` (~2,300 lines)
- **Combined Strategy v2 method**: `_handle_mr_entry_combined()` with independent MR state
- **Results log**: `autoresearch-results.tsv` (18,101+ rows)

### React Dashboard (`dashboard/`)
- **Status**: Production on VPS at `http://187.77.136.160/IBKR_KZ/`
- **Local**: `bash dashboard/start.sh` → `http://localhost:5173`
- **Service**: `ibkr-dashboard.service` (port 8888, clientId 30)
- **Features**: Multi-account portfolio, ES sentiment panel, price charts, news feed, watchlists

### Financial Analysis (`tools/`, `guides/`, `.claude/skills/`)
- **20 analysis tools**: macro, equity, TA, pro-trader frameworks
- **Skills**: `/fin`, `/digest`, `/digest_ES`
- **Scheduled tasks**: ES sentiment runs at 11am, 8pm, 11pm daily

### IBKR Library (`ibkr/`)
- Connection management (`connection.py`)
- Contracts factory (`contracts.py`)
- Market data + streaming (`market_data.py`, `streaming.py`)
- Historical data (`futures_data.py`, `es_data.py`)
- Storage (`data_store.py`)

### Higher-Frequency Sentiment Stack (NEW — May 2026)
Phase 1+2+4 of the multi-input ES signal framework. Foundation work for moving sentiment from 3x daily → 15-min granularity, plus three new ES-relevant inputs:

| Component | Cadence | Output | Source |
|---|---|---|---|
| `tools/news_stream_continuous.py` | **Continuous** (clientId 27) | `data/news/headlines.db` (SQLite) | IBKR broadtape (7 providers) |
| `tools/sentiment_intraday.py` | **Every 15 min** | `data/news/sentiment_intraday.csv` (5 windows × topic %) | Reads `headlines.db` |
| `tools/mag7_breadth.py` | Every 5 min (clientId 28) | `data/es/mag7_breadth.csv` | IBKR / yfinance |
| `tools/polymarket_signal.py` | On-demand (5-min upstream) | `data/es/polymarket_signals.csv` | `~/Github/market-tracker/data_cache/all_indicators.json` |
| `tools/macro_calendar.py` | In-memory | `MacroCalendar.is_blackout_window(ts)` | `~/Github/macro_2/historical_data/earnings_calendar.csv` + computed BLS/BEA dates |

VPS systemd units (under `systemd/`):
- `ibkr-broadtape.service` — Restart=always
- `ibkr-sentiment-15min.{service,timer}` — `OnCalendar=*:0/15`
- `ibkr-mag7-breadth.{service,timer}` — `OnCalendar=*:0/5`

**ES-trading inputs covered** (per user requirements):
- Mega-cap movements → `mag7_breadth.py` (% above 5/20/50d MA, market-cap-weighted % chg)
- Sentiment (war, rates, inflation, fiscal): `sentiment_intraday.py` (topic-tagged % per window) + `polymarket_signal.py` (Fed cut/hike, recession, fiscal expansion, geopolitics)
- Macroeconomic releases: `macro_calendar.py` (FOMC, CPI, NFP, PCE, GDP, ISM PMI + mega-cap earnings)
- Prediction markets: `polymarket_signal.py` (consumes market-tracker repo's launchd cache)

**Pending**: Phase 3 (FinBERT/DistilRoBERTa NLP upgrade), Phase 5 (self-learning framework — online lexicon, weekly walk-forward refit, RL ensemble agent), backtest integration of new signals into `verify_strategy.py`.

---

## Recent Session Highlights (Apr 2026)

### Combined Strategy v2 Discovery
Built `_handle_mr_entry_combined()` with fully independent MR state (separate cooldown, trade counter, circuit breaker). Multi-param jump progression:

| Step | Score | Trades | WR | PF |
|------|-------|--------|-----|-----|
| Composite only | -0.07 | 6 | 33% | 0.69 |
| + Combined routing | -0.38 | 35 | 57% | 1.66 |
| + MR stop 3.0× ATR | -0.20 | 34 | 59% | 1.54 |
| + MR 1 trade/day | -0.15 | 23 | 70% | 2.43 |
| + ATR threshold 1.8% | -0.07 | 6 | 33% | 0.69 |
| + Multi-param jumps | -0.04 | 6 | 33% | 1.56 |
| **+ ATR=1.6 MR-only** | **-0.03** | **6** | **83%** | **16.9** |

### MR-Only Discovery
Setting composite thresholds to 0.99 (effectively MR-only) with ATR=1.6 produced 6 trades with 83% WR and PF 16.9 — only $32 from breakeven on the war-extended dataset.

### New Scripts Added
- `scripts/backtest_mr_scalper.py` — Standalone scalper
- `scripts/backtest_dual_system.py` — Equity-curve combiner
- `scripts/compute_ml_entry_signal.py` — Walk-forward LightGBM
- `scripts/walk_forward_validation.py` — Anchored 3-fold IS/OOS

---

## Project Structure

```
IBKR/
├── autoresearch/                  # ES strategy optimization (PRIMARY WORK)
│   ├── es_strategy_config.py     # ONLY MUTABLE FILE
│   ├── verify_strategy.py        # Backtest engine
│   ├── batch_iterate.py          # Sweep runner
│   ├── autoresearch-results.tsv  # Full iteration log (18K+ rows)
│   ├── NEXT_STEPS.md             # Curated roadmap
│   ├── STRATEGY_CONTEXT.md       # Architecture docs
│   ├── SKILL.md                  # Iteration protocol
│   └── SCORING.md                # Scoring formula
│
├── dashboard/                     # React + FastAPI
│   ├── server.py                 # FastAPI backend
│   ├── frontend/                 # Vite + React + TS
│   ├── start.sh                  # Auto-port launcher
│   └── dashboard_specifications.md
│
├── tools/                         # 20 financial analysis tools
│   ├── news_stream.py            # Multi-provider news aggregation
│   ├── news_sentiment_nlp.py     # NLP sentiment engine
│   └── (macro, equity, TA, pro-trader tools)
│
├── ibkr/                         # Core market data library
│   ├── connection.py
│   ├── contracts.py
│   ├── market_data.py
│   ├── streaming.py
│   └── data_store.py
│
├── scripts/                       # Executable scripts
│   ├── run_sentiment.py          # ES sentiment pipeline
│   ├── ib_news_stream.py         # News streaming harness
│   ├── update_es_data.py         # ES data refresher
│   ├── backtest_mr_scalper.py    # Standalone MR scalper
│   ├── backtest_dual_system.py   # Dual-system combiner
│   ├── compute_ml_entry_signal.py # Walk-forward ML
│   └── walk_forward_validation.py # OOS validation
│
├── data/
│   ├── es/                       # ES OHLCV + ML features
│   ├── gc/                       # Gold (less active)
│   ├── si/                       # Silver (less active)
│   └── news/                     # Sentiment + headlines
│
├── guides/                        # Interpretation/framework guides
├── .claude/skills/               # /fin, /digest, /digest_ES
├── AR_exp_log.md                 # Complete experiment history
├── CLAUDE.md                     # Project instructions
└── STATUS.md                     # This file
```

---

## VPS Deployment

- **URL**: `http://187.77.136.160/IBKR_KZ/`
- **IB Gateway**: Docker container, socat 4003 (not 4001 — VPS quirk)
- **Dashboard service**: `ibkr-dashboard.service`
- **Health monitoring**: systemd timer + Telegram alerts
- **Telegram bots**:
  - `@FAzzh_CC_bot` (different repo: `Finl_Agent_CC`)
  - VPS interactive surface for trading commands
- **Setup docs**: `VPS_Hostinger_setup.md`, `IB_Docker_VPS/README.md`

---

## Scheduled Tasks (when Claude Code is active)

| Task | Schedule | Purpose |
|------|----------|---------|
| `es-sentiment-11am` | 11:03 AM daily | `/digest_ES` + `run_sentiment.py` |
| `es-sentiment-8pm` | 8:02 PM daily | `/digest_ES` + `run_sentiment.py` |
| `es-sentiment-11pm` | 11:04 PM daily | `/digest_ES` + `run_sentiment.py` |

Output: `data/news/sentiment_analysis.json`, `data/news/sentiment_timeseries.csv`

---

## Key Documents

| File | Purpose |
|------|---------|
| `AR_exp_log.md` | Complete experiment history (586 lines, 34 sweep batches) |
| `CLAUDE.md` | Project instructions for Claude Code |
| `autoresearch/NEXT_STEPS.md` | Current roadmap + exhausted approaches |
| `autoresearch/STRATEGY_CONTEXT.md` | Strategy architecture + parameter ranges |
| `autoresearch/SKILL.md` | Iteration protocol |
| `autoresearch/SCORING.md` | Scoring formula + diagnostic flowchart |
| `dashboard/dashboard_specifications.md` | Dashboard architecture |
| `VPS_Hostinger_setup.md` | VPS deployment guide |
| `DATA_SOURCES.md` | FRED series + CSV data map |
| `docs/BACKTEST_GUIDE.md` | Backtesting methodology |
| `docs/ES_DATA_SOURCES.md` | ES data pipeline docs |

---

## Active Constraints & Bottlenecks

1. **War period data ends Apr 2 2026** — strategy collapsed; needs forward data
2. **Commission drag**: $4.50 round-trip × min 5 trades = ~$30 floor on $100K
3. **Min trades constraint**: Score formula requires ≥5 trades; pure quality plays (2-3 trades, 100% WR) get penalized
4. **MR scalper integration friction**: Standalone +4.25%, integrated with shared state -0.30; v2 with independent state -0.03

---

## Next Priority Actions

1. **Forward data collection**: Update ES data Apr 3 → present to capture Phase 3 recovery
2. **Live MR scalper paper trading**: Standalone +4.25% has actionable edge
3. **Regime-switching capital allocator**: Dynamic % allocation based on ATR/VIX
4. **Reduce commission floor**: IBKR Pro tier or relax min-trade constraint to 3
