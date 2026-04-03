# ES Autoresearch — Complete Backtest Record

> Last updated: 2026-03-27 | Total iterations: ~15,000+ across all phases
> Best result (raw return): +14.73% return, 28.88% DD, 34% WR, 44 trades
> Best result (risk-adjusted): Score 10.47 (+14.73% × (1 - 0.2888))

---

## Table of Contents
1. [Backtest Setup & Constraints](#backtest-setup--constraints)
2. [Strategy Architecture](#strategy-architecture)
3. [File Map](#file-map)
4. [Scoring Formulas](#scoring-formulas)
5. [Phase-by-Phase Results](#phase-by-phase-results)
6. [Current Config Parameters](#current-config-parameters)
7. [Key Learnings](#key-learnings)
8. [ML Tools Evaluation](#ml-tools-evaluation)

---

## Backtest Setup & Constraints

| Parameter | Value |
|---|---|
| **Instrument** | ES (E-mini S&P 500 Futures) |
| **Data (5-min)** | `data/es/ES_combined_5min.parquet` — 48,233 bars, Jan 31 2025 – Mar 20 2026 |
| **Data (1-min)** | `data/es/ES_1min.parquet` — 241,009 bars, Jan 2025 – Mar 2026 |
| **Data (daily)** | `data/es/ES_daily.parquet` — 638 bars, Aug 2023 – Mar 2026 |
| **Extended data** | `data/es/ES_combined_hourly_extended.parquet` — SPY-converted hourly (Apr 2023 – Jan 2025) + real ES |
| **Initial Capital** | $100,000 |
| **Risk per Trade** | $10,000 (reduced to $5,000 in later phases for 40+ trade regime) |
| **ES Multiplier** | $50/point |
| **Position Sizing** | `contracts = risk_dollars / (stop_distance × $50)` |
| **Entry Hours** | GMT+8 8:00 AM – 11:59 PM (UTC 0:00 – 16:00) |
| **Limit Orders** | Set during entry hours; can fill at any time |
| **Min Hold** | 1 hour (12 × 5-min bars, or 1 hourly bar in extended mode) |
| **Max Positions** | 1 at a time |
| **Stop Loss** | Required on every trade; can trigger any time |

### Hard Constraints
| Constraint | Threshold |
|---|---|
| Max Drawdown | ≤ 60% |
| Win Rate | ≥ 30% |
| Min Trades | ≥ 5 (structural); target ≥ 40 (operational) |

---

## Strategy Architecture

### Sequential Decision Pipeline
```
Bar arrives → Daily loss circuit breaker check → Position management (if in trade)
  → Cooldown check (adaptive: shorter after wins, longer after losses)
  → Volume + ATR filters → Entry hours check (GMT+8 8am-midnight)
  → Regime classification (BULL/BEAR/SIDEWAYS)
  → Bull defensive mode check → Dip-buy / Rip-sell filter
  → Sequential macro gate → Daily trend gate (optional)
  → Composite scoring (8 signals) → Breakout entry fallback
  → Volume confirmation gate → Adaptive SL/TP → Confidence sizing
  → Volatility regime scaling → Execute entry
```

### Regime Classification
Weighted vote: SMA crossover (0.30) + Price vs 200 SMA (0.50) + NLP sentiment (0.25) + Digest context (0.05) + Daily trend (0.20)

### Signal Components
| Signal | BULL Wt | BEAR Wt | SIDE Wt | Source |
|---|---|---|---|---|
| RSI | 0.12 | 0.15 | 0.15 | `compute_rsi()` on closes |
| Trend (SMA) | 0.30 | 0.15 | 0.15 | SMA fast vs slow |
| Momentum | 0.13 | 0.10 | 0.20 | 12-bar price change |
| Bollinger Bands | 0.05 | 0.10 | 0.15 | Price vs bands |
| VIX | 0.10 | 0.10 | 0.20 | 7-tier framework |
| Macro | 0.05 | 0.05 | 0.20 | CTA + credit + yield + DXY + copper |
| Volume | 0.15 | 0.15 | 0.15 | Surge/dry ratio |
| Sentiment | 0.15 | 0.10 | 0.10 | WSJ + DJ-N daily composite |

### Macro Overlays
- **VIX 7-tier**: Complacency (<16) → Normal → Elevated → Riskoff → Opportunity (>30) → Career (>40) → Homerun (>50)
- **CTA Proxy**: ES vs 200 SMA (>10% above = short; >7% below = buy)
- **Credit (HY OAS)**: Normal (<350) → Elevated → Stressed → Severe (>600)
- **Yield Curve**: 2s10s inverted = short; steep = long
- **DXY**: Strong (>110) = short ES; Weak (<102) = long ES
- **Dr. Copper**: 20-day momentum; falling = short, rising = long

---

## File Map

### Core Autoresearch
| File | Purpose |
|---|---|
| `autoresearch/es_strategy_config.py` | **ONLY MUTABLE FILE** — all tunable parameters |
| `autoresearch/verify_strategy.py` | Backtest runner, strategy logic, scoring |
| `autoresearch/autoresearch.py` | Orchestrator (init/evaluate/status) |
| `autoresearch/batch_iterate.py` | Automated parameter sweep |
| `autoresearch/iteration_state.py` | State + TSV logging |
| `autoresearch/scoring/robustness.py` | Scoring formula + rising threshold |
| `autoresearch/versions/v0000–v0010` | Versioned config snapshots |
| `autoresearch/SKILL.md` | /autoresearch skill protocol |
| `autoresearch/SCORING.md` | Scoring formula docs |
| `autoresearch/STRATEGY_CONTEXT.md` | Architecture + parameter ranges |

### Backtest Engine
| File | Purpose |
|---|---|
| `backtest/engine.py` | Core BacktestEngine |
| `backtest/analytics.py` | Performance analytics |
| `backtest/regime.py` | Regime detection |
| `backtest/strategy.py` | Base strategy + indicators |

### Data Files
| File | Content |
|---|---|
| `data/es/ES_combined_5min.parquet` | 48K bars (primary backtest) |
| `data/es/ES_daily.parquet` | 638 daily bars |
| `data/es/ES_combined_hourly_extended.parquet` | SPY-converted + real ES hourly |
| `data/es/garch_daily_forecast.csv` | GARCH conditional variance |
| `data/es/particle_regime_daily.csv` | Particle filter regime probs |
| `data/es/cusum_events.csv` | CUSUM structural breaks |
| `data/es/tsfresh_daily_features.csv` | Auto-extracted features |
| `data/es/tuneta_indicator_ranking.csv` | TuneTA distance-correlation |
| `data/news/daily_sentiment.csv` | WSJ + DJ-N sentiment (345 days) |
| `data/news/wsj_subjects.json` | 298 WSJ email subjects |
| `data/news/sample_headlines.json` | 291 IBKR DJ-N headlines |

### Scripts
| File | Purpose |
|---|---|
| `scripts/build_sentiment_csv.py` | Build daily sentiment CSV |
| `scripts/compute_garch_forecast.py` | GARCH volatility forecast |
| `scripts/compute_particle_regime.py` | Particle filter regime |
| `scripts/compute_cusum_events.py` | CUSUM structural breaks |
| `scripts/compute_tsfresh_features.py` | tsfresh feature extraction |
| `scripts/tuneta_analysis.py` | TuneTA indicator ranking |
| `scripts/bootstrap_significance.py` | Bootstrap significance test |
| `scripts/walk_forward_validation.py` | Walk-forward IS/OOS validation |
| `scripts/run_sentiment.py` | NLP on IBKR news |
| `scripts/update_es_data.py` | Update ES data via IBKR API |
| `scripts/run_streaming.py` | Real-time streaming dashboard |

### Skills
| Skill | Path |
|---|---|
| `/fin` | `.claude/skills/fin/SKILL.md` |
| `/digest` | `.claude/skills/digest/SKILL.md` |
| `/digest_ES` | `.claude/skills/digest_ES/SKILL.md` |

---

## Scoring Formulas

### Current: Risk-Adjusted
```
score = return% × (1 - DD%/100)    if DD ≤ 60% AND WR ≥ 30%
score = 0                           otherwise
```

### Previous: Raw Return
```
score = return%    if DD ≤ 60% AND WR ≥ 30%
```

### Rising Threshold: `0.05 × log(1 + iteration)`

---

## Phase-by-Phase Results

| Phase | Approach | Iters | Return | DD | WR | Trades | Score Type | Key Change |
|---|---|---|---|---|---|---|---|---|
| 1 | Flat (no regime) | 1,000 | **+32.18%** | 56.6% | 48% | 54 | Raw | High selectivity |
| 2 | 3-Regime | 500 | +13.56% | 54.3% | 46% | 159 | Raw | Per-regime params |
| 3 | +Bull Defensive | 500 | -5.86% | **21.9%** | 42% | 202 | Raw | Shorts in corrections |
| 4 | +VIX/RSI stops | 500 | -7.54% | 49.9% | 43% | 100 | Raw | Stop tightening |
| 5 | +Daily data | 500 | -8.59% | 47.8% | 42% | 154 | Raw | Daily RSI/ATR overlay |
| 6 | +Daily RSI direct | 1,000 | **+4.15%** | 40.0% | 47% | 53 | Raw | Daily RSI as primary |
| 7 | +NLP sentiment | 500 | -7.82% | 63.0% | 49% | 115 | Raw | DD violated |
| 8 | Multi-param jump | 200 | -10.49% | 56.4% | **50%** | 90 | Raw | Coordinated jump |
| 9 | Adaptive arch | 1,000 | -5.84% | 48.0% | 39% | 114 | Raw | Trend gate + sizing |
| 10 | Asym R:R + CB | 521 | -5.83% | 35.6% | 34% | 135 | Raw | 2:1 R:R floor |
| 11 | Volume fix + dip/rip | 1,000 | -3.09% | 25.0% | 38% | 96 | Raw | TRADES volume |
| 12 | VIX mean-reversion | ~2,000 | +5.61% | 21.2% | 35% | 36 | Raw | VIX dip-buy boost |
| 13 | Near-miss chains | ~4,000 | +10.98% | **19.6%** | 46% | 13 | Raw | Incremental jumps |
| 14 | +WSJ/DJ-N sentiment | 1,000 | +10.98% | 19.6% | 46% | 13 | Raw | Sentiment signal |
| 15 | Risk-adj scoring | ~2,600 | **+14.73%** | 28.9% | 34% | **44** | Risk-adj | Best balanced |

### Best Configs Summary
| Label | Return | DD | WR | Trades | Risk-Adj Score |
|---|---|---|---|---|---|
| **Highest return** | +32.18% | 56.6% | 48% | 54 | 13.97 |
| **Best DD** | -5.86% | 21.9% | 42% | 202 | — |
| **Best WR** | -10.49% | 56.4% | 50% | 90 | — |
| **Most trades** | -5.86% | 21.9% | 42% | 202 | — |
| **Best risk-adjusted** | +14.73% | 28.9% | 34% | 44 | **10.47** |
| **Best low-DD positive** | +10.98% | 19.6% | 46% | 13 | 8.82 |

---

## Current Config Parameters

Full config: `autoresearch/es_strategy_config.py` (324 lines, ~100 parameters)

### Key Current Values
| Category | Parameter | Value |
|---|---|---|
| Data | USE_EXTENDED_DATA | True |
| Capital | RISK_PER_TRADE | $5,000 |
| Indicators | RSI_PERIOD=21, ATR_PERIOD=28, SMA_FAST=30, SMA_SLOW=30 |
| | BB_PERIOD=25, BB_STD=1.5 |
| Entry | COOLDOWN_BARS=36, MIN_ATR_THRESHOLD=5.0 |
| | BULL_THRESHOLD=0.35, BEAR_THRESHOLD=0.40, SIDE_THRESHOLD=0.35 |
| Exit | BULL_STOP/TP=2.0/2.0, BEAR_STOP/TP=2.5/2.0, SIDE_STOP/TP=2.0/2.0 |
| Sizing | BULL_RISK_MULT=0.4, BEAR_RISK_MULT=1.5, SIDE_RISK_MULT=0.5 |
| | CONFIDENCE_HIGH_THRESHOLD=0.5, CONFIDENCE_HIGH_MULT=2.5 |
| VIX | Tiers: 16/20/28/35/40/50 |
| Execution | USE_LIMIT_ORDERS=True, LIMIT_OFFSET_ATR=0.7 |
| Advanced | GARCH_ENABLED=False, PARTICLE_REGIME_ENABLED=True |
| | CUSUM_ENTRY_ENABLED=False, TSFRESH_SIGNAL_WEIGHT=0.0 |

---

## Key Learnings

### What Works
1. **High selectivity** — fewer, higher-quality trades (ATR threshold + long cooldown)
2. **Daily RSI alignment** — intraday entries matching daily momentum
3. **VIX mean-reversion** — buy dips when VIX > 30 (career opportunity)
4. **Limit orders** — improved fills vs market orders
5. **Conservative bull sizing** (0.4×) — prevents bull trap losses
6. **Volume confirmation** — 3.0× avg volume surge filter
7. **WSJ sentiment** — daily narrative shifts from Markets A.M./P.M.
8. **Risk-adjusted scoring** — `return × (1 - DD/100)` finds balanced configs
9. **Near-zero rising threshold** (0.05) — enables incremental hill-climbing
10. **Particle filter regime** — smoother regime transitions than static thresholds

### What Doesn't Work
1. **Multi-param jumps** without testing — can regress
2. **NLP without guardrails** — overconfidence → DD violations
3. **Too many parameters** — search space noise
4. **Asymmetric R:R ≥ 2:1** — kills WR below 30%
5. **GARCH volatility** — ablation showed negative impact (7.41→7.65 without it)
6. **High rising threshold** (0.5) — blocks all improvements after 100 iters
7. **Deep RL** — insufficient data for single-instrument futures

### Structural Trade-offs
| Dimension | Inverse Relationship |
|---|---|
| Return ↔ Trade count | Fewer trades = higher return per trade |
| Win Rate ↔ R:R ratio | Wider TP = lower WR but bigger wins |
| DD control ↔ Return | Best DD (21.9%) had -5.86% return |
| Complexity ↔ Robustness | Simple Phase 1 outperformed complex Phase 9 |
| ATR threshold ↔ Trades | ATR 5.0 = 10 trades; ATR 2.0 = 38 trades |

---

## ML Tools Evaluation

Full evaluation: `guides/ml_quant_tools_evaluation.md`

| Priority | Tool | Status | Benefit |
|---|---|---|---|
| HIGH | TuneTA | Implemented | Statistical indicator selection |
| HIGH | ARCH | Implemented (disabled) | GARCH vol forecast |
| HIGH | vectorbt | Not implemented | Grid search optimization |
| MEDIUM | tsfresh | Implemented | Auto feature extraction |
| MEDIUM | mlfinlab (CUSUM) | Implemented (disabled) | Event-driven entries |
| MEDIUM | Particle filter | Implemented (active) | Bayesian regime detection |
| LOW | Qlib | Not implemented | Overkill for single instrument |
| LOW | FinRL | Not implemented | Data-starved |
