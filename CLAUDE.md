# IBKR ES Futures — Trading System + Financial Analysis Agent

## React Dashboard

```bash
bash dashboard/start.sh                # Auto-finds ports, starts backend + frontend
```

Opens at `http://localhost:5173` (or next available port). Shows:
- **Multi-Account Portfolio**: Account selector sidebar, per-account pages with positions table (symbol, cost basis, current price, prev close, market value, unrealized P&L, P&L%)
- **Open Orders**: Pending orders table (symbol, action, type, qty, limit price, status) — read-only via `ib.openOrders()`
- **ES Sentiment Panel**: Unified trading direction (BEARISH/BULLISH/SIDEWAYS), confidence, sentiment scores (unified/newsletter/NLP), key levels (Smashlevel pivot, support/resistance, VPOCs, MA200), positioning (JPM z-score, NAAIM, VIX tier), expandable themes & insights, signal history timeline
- **Price Charts**: Click any position symbol to open interactive OHLCV chart (1m/5m/15m/1h/1d/1w), live price updates when live mode enabled
- **News Feed**: Real-time IBKR news headlines from 7 providers (BRFG, BRFUPDN, DJ-N, DJ-RT, DJ-RTA, DJ-RTE, DJ-RTG)
- **Watchlists**: Custom instrument watchlists with real-time prices, rename/delete support
- **WebSocket**: Live updates every 10s (portfolio) + per-second in live mode + real-time (news)

Backend: FastAPI (`dashboard/server.py`) connects to IBKR TWS/Gateway via `ib_async` with auto-port detection (7496→7497→4001→4002).
Frontend: Vite + React + TypeScript + Tailwind CSS (`dashboard/frontend/`).

---

## Financial Analysis Agent

Use `/fin <command>` for macro, equity, commodity, technical, and pro-trader analysis.
Use `/digest` to read financial newsletter emails and update market context.
Use `/digest_ES` to read ES-focused newsletters (Smashelito, Geo Chen/Fidenza, etc.) and update ES trading context.

### Key Commands
```
/fin scan              # Quick macro scan (27 indicators)
/fin macro             # Macro regime classification
/fin stress            # Financial stress score (0-10)
/fin latecycle         # 13-signal late-cycle detection
/fin ta ES=F           # Technical analysis (Murphy 13-framework)
/fin riskpremium       # VIX regime + vanna/charm + CTA proxy
/fin crossasset        # Cross-asset momentum & divergences
/fin usdregime         # USD structural regime (DXY analysis)
/fin sl ES 6000 long   # Stop-loss framework (Fidenza 10-rule)
/fin full_report       # 8-step analysis chain
/digest                # Read newsletters -> guides/market_context.md
/digest_ES             # Read ES newsletters -> guides/market_context_ES.md
```

### ES Sentiment Pipeline (Standalone)
```bash
python scripts/run_sentiment.py              # Auto-detect IBKR port, fetch headlines, run NLP
python scripts/run_sentiment.py --port 7496  # Specify TWS port
python scripts/run_sentiment.py --dry-run    # Use cached headlines (skip IBKR)
python scripts/run_sentiment.py --days 14    # 2-week lookback
```

Fetches ~4000 headlines from 7 IBKR news providers, runs NLP sentiment analysis, merges with newsletter context from `/digest_ES` (40% NLP + 60% newsletters), outputs unified ES trading direction.

**Output files:**
- `data/news/sentiment_analysis.json` — Full analysis with regime signals, key themes, actionable insights, top 100 headlines
- `data/news/sentiment_timeseries.csv` — Appends one row per run (tracks signal history)

**Scheduled tasks** (run when Claude Code is active):
- `es-sentiment-11am` — 11:03 AM daily
- `es-sentiment-8pm` — 8:02 PM daily
- `es-sentiment-11pm` — 11:04 PM daily

Each task runs `/digest_ES` (email newsletters) then `run_sentiment.py` (IBKR headlines + NLP).

### News Streaming (IBKR API)
```bash
python scripts/ib_news_stream.py verify                  # Full API check
python scripts/ib_news_stream.py providers               # List news providers
python scripts/ib_news_stream.py headlines AAPL           # Fetch headlines
python scripts/ib_news_stream.py stream AAPL,NVDA         # Real-time stream
python scripts/ib_news_stream.py broadtape --duration 600 # All headlines
```

### File Map
```
tools/                          <- 20 Python analysis tools (macro, equity, TA, pro-trader)
tools/news_stream.py            <- Multi-provider news aggregation (IBKR, Finnhub, Benzinga, Finlight)
tools/news_sentiment_nlp.py     <- NLP sentiment engine (headline analysis, regime signals, newsletter merge)
guides/                         <- 8 interpretation/framework guides
guides/market_context_ES.md     <- ES-specific newsletter digest (Smashelito, Geo Chen, etc.)
scripts/run_sentiment.py        <- Standalone ES sentiment pipeline (IBKR news + NLP)
.claude/skills/fin/             <- /fin skill definition
.claude/skills/digest/          <- /digest skill definition
.claude/skills/digest_ES/       <- /digest_ES skill definition (ES-focused newsletters)
data/news/sentiment_analysis.json    <- Latest full sentiment analysis
data/news/sentiment_timeseries.csv   <- Historical sentiment signal log
DATA_SOURCES.md                 <- FRED series + CSV data map
.env                            <- API keys (FRED, Tavily, Finnhub, Benzinga, Finlight)
```

### Data Sources
- **Local CSVs**: `/Users/kriszhang/Github/macro_2/historical_data/` (120+ files)
- **FRED API**: 56 economic series (fallback when local CSV unavailable)
- **yfinance**: On-demand stock/ETF data with 30-min cache
- **Gmail**: Financial newsletters via /digest and /digest_ES skills (9 sources: Smashelito, Geo Chen/Fidenza, MarketEar, Macro Ops, SpotGamma, Daily Chartbook, Barchart, Market Ear, GS/JPM)
- **IBKR News**: 7 providers (BRFG, BRFUPDN, DJ-N, DJ-RT, DJ-RTA, DJ-RTE, DJ-RTG) — BRFG has years of history, DJ feeds ~2-5 weeks

---

## Autoresearch (ES Strategy Optimization)

### Quick Start
```bash
cd autoresearch
python autoresearch.py init                          # establish baseline
python batch_iterate.py 1000 --report-every 50       # run iterations
python autoresearch.py status                        # check progress
```

### How It Works
1. `batch_iterate.py` generates single-parameter variations from `es_strategy_config.py`
2. Each variation is applied, backtested via `verify_strategy.py`, and scored
3. If score > best + rising_threshold: **KEEP** (save version snapshot, update baseline)
4. Otherwise: **DISCARD** (revert config to last good state)
5. Repeat with fresh parameter sweep from new baseline

### Strategy Architecture
Sequential decision pipeline with regime-adaptive parameters:
1. **Classify regime** (BULLISH / BEARISH / SIDEWAYS) using SMA crossover + price vs 200 SMA + VIX tier + NLP sentiment + digest context + daily trend
2. **Sequential gates**: Macro filter → Regime filter → Daily trend gate → Dip-buy/Rip-sell filter → Technical composite → Volume confirmation
3. **Composite signal**: Weighted RSI + SMA trend + momentum + Bollinger Bands + VIX + macro + volume + WSJ/DJ-N sentiment (per-regime weights)
4. **Adaptive entry**: Confidence-weighted sizing, breakout mode fallback, adaptive cooldown (win/loss streak)
5. **Adaptive exits**: Stop-loss scaled by daily ATR regime + VIX + credit conditions + DXY; TP scaled by trend alignment + RSI extension; momentum-based exit on daily trend reversal
6. **Macro overlay**: VIX 7-tier framework, CTA proxy, HY OAS credit conditions, yield curve, DXY, Dr. Copper
7. **Sentiment integration**: WSJ Markets A.M./P.M. email sentiment + IBKR DJ-N headline sentiment → daily composite score

### Current Best Result
```
Return: +10.61% | Max DD: 22.46% | Win Rate: 36.0% | Trades: 25 | PF: ~2.0
Period: Jan 2025 - Mar 2026 (14 months, 5-min bars with daily overlay)
```

### Scoring
```
score = total_return_pct   if max_dd <= 60% AND win_rate >= 30%
score = 0                  otherwise
```

Rising threshold: `min_improvement = 0.05 * log(1 + iteration_count)` (near-zero for incremental hill-climbing)

### Constraints
- Initial capital: $100,000
- Risk per trade: $10,000 (contracts = $10K / (stop_distance * $50))
- Win rate >= 30%, max drawdown <= 60%
- Min holding period: 1 hour (12 × 5-min bars)
- Stop loss required on every trade (adjustable based on indicators)
- New entries: GMT+8 8am-11:59pm only (Asia hours); limit orders set during these hours
- One position at a time
- Daily loss circuit breaker (configurable % threshold)

### Key Files
```
autoresearch/
  es_strategy_config.py      <- ONLY MUTABLE FILE (per-regime parameters)
  verify_strategy.py         <- Runs backtest, outputs SCORE
  autoresearch.py            <- Orchestrator (init/evaluate/status)
  batch_iterate.py           <- Automated parameter sweep
  iteration_state.py         <- State + TSV logging
  scoring/robustness.py      <- Scoring formula
  autoresearch-state.json    <- Persistent state (iteration count, best score)
  autoresearch-results.tsv   <- Full iteration log
  iterations/                <- Per-iteration markdown reports
  versions/                  <- Versioned config snapshots (KEEPs only)
  SKILL.md                   <- Full iteration protocol
  SCORING.md                 <- Scoring formula + diagnostic flowchart
  STRATEGY_CONTEXT.md        <- Strategy architecture + tunable parameter ranges
```

### Autoresearch Rules
1. **ONE change per iteration** - atomic for clear attribution
2. **Only modify `es_strategy_config.py`** - never touch verify, scoring, or engine
3. **Small increments** - 10-20% of parameter range per change
4. **Rising threshold** - `0.05 * log(1 + iteration)` allows incremental hill-climbing
5. **KEEP or REVERT** - no partial changes
6. **Multi-param jumps** between batches — apply top 3 near-misses simultaneously

### Data
- **ES 5-min**: `data/es/ES_combined_5min.parquet` (48K bars, Jan 2025 - Mar 2026, TRADES volume)
- **ES 1-min**: `data/es/ES_1min.parquet` (241K bars, Jan 2025 - Mar 2026)
- **ES daily**: `data/es/ES_daily.parquet` (638 bars, Aug 2023 - Mar 2026)
- **Macro**: VIX, HY OAS, DXY, 10Y/2Y yields, copper from macro_2 repo
- **Sentiment**: `data/news/daily_sentiment.csv` (345 days, WSJ + DJ-N composite)
- **WSJ subjects**: `data/news/wsj_subjects.json` (298 email subjects)
- **DJ-N headlines**: `data/news/sample_headlines.json` (291 IBKR headlines)

### Sentiment Pipeline
```bash
python scripts/build_sentiment_csv.py     # Build daily_sentiment.csv from WSJ + DJ-N
python scripts/run_sentiment.py           # Run NLP on IBKR news headlines
```

---

## IBKR Market Data Framework

### Core Library (`ibkr/`)
- `connection.py` - TWS/Gateway connection management (ib_async/ib_insync)
- `contracts.py` - Contract factory for futures (ES, GC, SI, NQ, CL, etc.)
- `market_data.py` - Quote fetching and streaming
- `streaming.py` - Real-time streaming engine + portfolio monitoring
- `futures_data.py` / `es_data.py` - Historical data download
- `data_store.py` - Parquet/CSV storage and resampling

### Scripts
- `scripts/run_streaming.py` - Console streaming dashboard
- `scripts/run_backtest.py` - Run backtests with built-in strategies
- `scripts/update_es_data.py` - Update ES data to latest via IBKR API
- `scripts/ib_news_stream.py` - News streaming harness (ib_async)
- `scripts/run_sentiment.py` - Standalone ES sentiment pipeline (IBKR news + NLP + newsletter merge)
- `scripts/get_realtime_snapshot.py` - Market snapshots

### ES Data Files (`data/es/`)
| File | Bars | Range |
|------|------|-------|
| ES_1min.parquet | 241K | Jan 2025 - Mar 2026 |
| ES_combined_5min.parquet | 48K | Jan 2025 - Mar 2026 |
| ES_daily.parquet | 638 | Aug 2023 - Mar 2026 |
| ES_implied_volatility_daily | 401 | Aug 2024 - Mar 2026 |
| ES_historical_volatility_daily | 265 | Mar 2025 - Mar 2026 |
