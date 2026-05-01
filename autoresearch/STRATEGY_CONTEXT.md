# ES Strategy Architecture & Context

> Last updated: 2026-04-12
> **IMPORTANT**: Update this file after every structural strategy change.

---

## Overview

Three trading approaches for E-mini S&P 500 futures (ES):

1. **Composite Strategy** — Multi-signal trend/regime system for normal markets (verify_strategy.py)
2. **MR Scalper (standalone)** — Intraday mean-reversion for high-volatility days (backtest_mr_scalper.py)
3. **Combined Strategy v2** — Routes between MR and composite within single backtest using INDEPENDENT state (verify_strategy.py + `_handle_mr_entry_combined()`)

The Combined Strategy v2 is the current best on the war-extended dataset (-0.03 score, 83% WR, PF 16.9). The dual-system approach (running 1+2 separately and combining equity curves) achieves +3.39% return.

---

## System A: Composite Strategy

### Architecture
Sequential decision pipeline with regime-adaptive parameters (~120 params in `es_strategy_config.py`):

```
Bar arrives (5-min)
  → Daily loss circuit breaker check
  → Consecutive loss cooldown (max 3 losses → 78-bar pause)
  → Position management (if in trade): trailing stops, RSI exits, momentum exit, max hold
  → Cooldown check (adaptive: shorter after wins, longer after losses)
  → Volume + ATR filters
  → Entry hours check (UTC 0:00–16:00, avoid US open 14:30–16:00)
  → Structural gates:
      - Vol regime gate (ATR%>1.5% = 0.25x size, ATR%>3.0% = halt)
      - Crisis short disable (VIX>24 + ATR%>1.5% = no shorts)
      - Dual mode (crisis ATR%>1.5% = longs-only, tiny size)
  → Intraday trend filter (12-bar lookback, 0.3× ATR strength)
  → Regime classification (BULL / BEAR / SIDEWAYS)
  → Bull defensive mode check
  → Dip-buy / Rip-sell filter
  → Sequential macro gate
  → Daily trend gate
  → Composite scoring (8 signals)
  → Breakout entry fallback
  → Volume confirmation gate
  → Adaptive SL/TP (ATR-scaled, VIX-adjusted, credit-adjusted, DXY-adjusted)
  → Confidence-weighted sizing
  → Volatility regime scaling
  → Execute entry (limit order with 0.7× ATR offset)
```

### Regime Classification
Weighted vote system:
| Signal | Weight | Source |
|---|---|---|
| SMA crossover (fast vs slow) | 0.30 | 5-min SMA |
| Price vs 200 SMA | 0.50 | Daily 200 SMA |
| NLP sentiment | 0.25 | WSJ + DJ-N headlines |
| Digest context | 0.05 | Newsletter analysis |
| Daily trend | 0.20 | Daily RSI + momentum |
| Particle filter | 0.10 | Bayesian SMC regime |

### Composite Signal Components (per-regime weights)
| Signal | BULL | BEAR | SIDEWAYS | Source |
|---|---|---|---|---|
| RSI | 0.12 | 0.15 | 0.15 | RSI(7) on closes |
| Trend (SMA) | 0.30 | 0.15 | 0.15 | SMA(30) fast vs slow |
| Momentum | 0.13 | 0.10 | 0.20 | 12-bar price change |
| Bollinger Bands | 0.05 | 0.10 | 0.15 | BB(25, 2.2 std) |
| VIX | 0.10 | 0.10 | 0.20 | 7-tier framework |
| Macro | 0.05 | 0.05 | 0.20 | CTA + credit + yield + DXY + copper |
| Volume | 0.15 | 0.15 | 0.15 | Surge/dry ratio |
| Sentiment | 0.15 | 0.10 | 0.10 | Daily composite score |

### Macro Overlays
- **VIX 7-tier**: Complacency (<16) → Normal (16-20) → Elevated (20-28) → Riskoff (28-35) → Opportunity (35-40) → Career (40-50) → Homerun (>50)
- **CTA Proxy**: ES vs 200 SMA distance (>10% above = short pressure; >7% below = buy signal)
- **Credit (HY OAS)**: Normal (<350 bps) → Elevated (350-450) → Stressed (450-600) → Severe (>600)
- **Yield Curve**: 2s10s inverted = short bias; steep = long bias
- **DXY**: Strong (>110) = short ES; Weak (<102) = long ES
- **Dr. Copper**: 20-day momentum; falling = short bias, rising = long bias

### Position Sizing
```
contracts = floor($5,000 / (stop_distance × $50))
stop_distance = ATR(28) × STOP_ATR_MULT (regime-dependent: BULL=2.0, BEAR=2.5, SIDE=2.0)
confidence scaling: HIGH(>0.5) = 2.5×, LOW(<0.2) = 0.3×
```

### Exit Rules
1. **Stop Loss**: Entry ± ATR × STOP_ATR_MULT (always active, adjusted by VIX/credit/DXY)
2. **Take Profit**: Entry ± ATR × TP_ATR_MULT (adaptive: wider with trend, tighter against)
3. **Trailing Stop**: After 1× risk, trail at regime-dependent ATR multiple (BULL=0.5, BEAR=0.8)
4. **RSI Exit**: Tighten stop when RSI reaches overbought/oversold
5. **Momentum Exit**: Close when daily trend reverses (optional)
6. **Time Exit**: Close after MAX_HOLD_BARS (regime-dependent: BULL=288, BEAR=432)
7. **Circuit Breaker**: 3 consecutive losses → 78-bar mandatory cooldown

### Active Structural Features
| Feature | Config Flag | Setting |
|---|---|---|
| Vol Regime Gate | `VOL_REGIME_GATE_ENABLED=True` | ATR>1.5% = 0.25x size; ATR>3% = halt |
| Crisis Short Disable | `CRISIS_SHORT_DISABLE_ENABLED=True` | VIX>24 + ATR>1.5% = no shorts |
| High-Vol Hold Reduction | `HIGH_VOL_HOLD_REDUCTION_ENABLED=True` | Max 24 bars in high-vol |
| Intraday Trend Filter | `INTRADAY_TREND_FILTER_ENABLED=True` | 12-bar lookback, 0.3× ATR strength |
| Dual Mode (Crisis) | `DUAL_MODE_ENABLED=True` | ATR>1.5% = longs-only, 0.3× size |
| GARCH Vol Forecast | `GARCH_ENABLED=True` | Blocks extreme vol entries |
| Particle Filter | `PARTICLE_REGIME_ENABLED=True` | Regime weight 0.10 |
| CUSUM Events | `CUSUM_ENTRY_ENABLED=True` | 96-bar structural break window |

### Disabled Features (tested, no improvement)
| Feature | Reason Disabled |
|---|---|
| VIX Model Switching (3 regimes × 15 params) | No improvement over base config |
| ML Entry Classifier (LightGBM) | 47.9% accuracy = noise |
| Adaptive Hold Period | 12 params, no improvement |
| Multi-Timeframe (5min + 4h) | 0 trades on 4h bars |
| MR Mode (integrated) | Hurts composite (-0.30 vs -0.10) |
| Oil/Gold/Skew Gates | Binary gates too aggressive |
| tsfresh Signal Weight | 0.0 optimal |

### Current Performance (Extended Data: Jan 2025 – Apr 2 2026)
```
Return: -0.08% | Max DD: 6.95% | Win Rate: 33% | Trades: 6
Score: -0.07 (risk-adjusted)
```

---

## System B: MR Scalper

### Concept
Standalone intraday mean-reversion system that only trades on high-volatility days. Completely independent of the composite strategy — no shared state, indicators, or capital.

### Architecture
```
Daily check: ATR% ≥ 1.5% and ≤ 5.0%? → HIGH-VOL DAY → activate
  → Entry hours: 9 AM – 3 PM ET (UTC 14:00–20:00)
  → Cooldown: 6 bars (30 min) between trades
  → Max 3 trades/day
  → Compute RSI(12) on 5-min bars
  → RSI < 25 → LONG entry
  → Position sizing: $2,000 risk / (1.5× ATR × $50)
  → Stop: 1.5× ATR below entry
  → TP: 2.0× ATR above entry
  → RSI exit: close when RSI > 55
  → Max hold: 24 bars (2 hours)
```

### Key Parameters
| Parameter | Value | Rationale |
|---|---|---|
| RSI Period | 12 | Short period for fast mean-reversion |
| RSI Entry | < 25 | Deep oversold only |
| RSI Exit | > 55 | Don't wait for overbought — take the bounce |
| Side | LONG only | Shorts don't work in high-vol wars |
| Max Hold | 24 bars (2h) | Scalping — get in, get out |
| Stop | 1.5× ATR | Tight but not too tight |
| TP | 2.0× ATR | 1.33:1 R:R (compensated by 43% WR) |
| Daily ATR% filter | 1.5% – 5.0% | Only high-vol, not extreme crash |
| Risk/Trade | $2,000 | Conservative for scalping |

### Performance
```
Return: +4.25% | Max DD: 4.4% | Trades: 51 | Win Rate: 43%
Avg Hold: ~23 min | Profit Factor: ~1.3
```

### Signal Sweep Summary (47 configs tested)
| Rank | Config | Return | DD | Trades | WR |
|---|---|---|---|---|---|
| 1 | RSI(12)<20, LONG | +5.88% | 4.2% | 60 | 53% |
| 2 | RSI(12)<25, LONG | +4.25% | 4.4% | 51 | 43% |
| 3 | RSI+BB (2 signals), LONG | +3.91% | 3.8% | 38 | 47% |
| 4 | RSI(8)<25, LONG | +2.64% | 5.1% | 44 | 39% |
| 5 | VWAP only, LONG | +1.82% | 3.9% | 32 | 41% |

---

## Combined Strategy v2 (Independent State Routing)

### Concept
Same routing idea as previous attempts (high-vol → MR, normal → composite) but MR gets **fully independent state** within a single backtest run. Solves the integration problem that killed v1 (-0.30 vs standalone +4.25%).

### Independent State Variables (added to verify_strategy.py:`__init__`)
```python
self._mr_bars_since_trade = 999    # Own cooldown (vs composite's 36)
self._mr_trades_today = 0           # Own daily counter (vs composite's quota)
self._mr_trades_today_date = None
self._mr_consecutive_losses = 0     # Own loss streak
self._mr_loss_cooldown = 0          # Own circuit breaker
```

### Routing Logic (in `on_bar()`)
```
Position management → MR check BEFORE vol gate/cooldown:
  IF COMBINED_STRATEGY_ENABLED:
    daily_atr_pct = lookup from daily_trend cache
    IF daily_atr_pct >= COMBINED_MR_ATR_THRESHOLD (1.6):
      → _handle_mr_entry_combined() with INDEPENDENT state
      → Use US hours (UTC 14-20)
      → return  # bypass composite entirely
  ELSE:
    → composite gates (cooldown, vol gate, etc.)
```

### New Config Params (~10 lines in es_strategy_config.py)
| Param | Default | Purpose |
|---|---|---|
| `COMBINED_STRATEGY_ENABLED` | True | Master switch |
| `COMBINED_MR_ATR_THRESHOLD` | 1.6 | ATR% cutoff for MR routing |
| `COMBINED_MR_COOLDOWN_BARS` | 6 | MR's own cooldown (30 min) |
| `COMBINED_MR_ENTRY_UTC_START` | 14 | 9 AM ET |
| `COMBINED_MR_ENTRY_UTC_END` | 20 | 3 PM ET |
| `COMBINED_MR_TP_ATR` | 2.0 | MR take-profit (sweepable) |
| `COMBINED_MR_MAX_CONSECUTIVE_LOSSES` | 5 | MR's own circuit breaker |

### MR-Only Mode (Best Configuration)
Setting `BULL/BEAR/SIDE_COMPOSITE_THRESHOLD = 0.99` effectively disables composite entries while keeping the macro/regime infrastructure available. Best result on extended dataset:

```
Score: -0.03 | Return: -0.03% | DD: 1.99% | Trades: 6 | WR: 83% | PF: 16.9
$32 from breakeven on $100K (commission floor)
```

### Grid Search Results (ATR threshold sweep, MR-only)
| ATR | Trades | WR | PF | Score | Final Equity |
|---|---|---|---|---|---|
| 1.2 | 40 | 68% | 1.67 | -0.21 | $99,780 |
| 1.4 | 24 | 83% | 6.11 | -0.12 | $99,874 |
| 1.5 | 18 | 83% | 4.90 | -0.09 | $99,910 |
| **1.6** | **6** | **83%** | **16.9** | **-0.03** | **$99,968** |
| 1.7 | 2 | 100% | ∞ | 0.00 | $99,991 |

**Key insight**: Trade quality (WR, PF) increases monotonically with ATR threshold; trade count drops. ATR=1.6 is the sweet spot — minimum trades for statistical validity (≥5) with maximum quality.

---

## Dual-System Architecture

### Capital Allocation
Run both systems independently with separate capital allocations on $100K total:

| Comp % | MR % | Return | Est DD | Score |
|---|---|---|---|---|
| 80% | 20% | +0.79% | ~6.4% | +0.74 |
| 50% | 50% | +2.04% | ~5.7% | +1.91 |
| **20%** | **80%** | **+3.39%** | **~3.9%** | **+3.26** |

### Why Separate Systems vs Combined v2
- **Dual-system**: Truly independent backtests, equity curves combined post-hoc. Captures full +4.25% MR scalper edge.
- **Combined v2**: Single backtest with routing. MR has independent state but still shares equity tracking. Achieves better DD (1.99% vs 3.9%) but lower absolute return.
- **Use case**: Combined v2 for unified backtest score; dual-system for actual capital deployment with two accounts.

---

## Tunable Parameter Ranges

### Core Parameters (Composite)
| Parameter | Range | Current |
|---|---|---|
| RSI_PERIOD | 3-21 | 7 |
| ATR_PERIOD | 14-50 | 28 |
| SMA_FAST | 10-80 | 30 |
| SMA_SLOW | 30-200 | 30 |
| BB_PERIOD | 10-50 | 25 |
| BB_STD | 1.0-3.0 | 2.2 |
| COMPOSITE_THRESHOLD | 0.20-0.65 | BULL=0.35, BEAR=0.40, SIDE=0.35 |
| STOP_ATR_MULT | 1.0-4.0 | BULL=2.0, BEAR=2.5, SIDE=2.0 |
| TP_ATR_MULT | 1.5-8.0 | BULL=2.0, BEAR=2.0, SIDE=2.0 |
| MAX_HOLD_BARS | 24-1152 | BULL=288, BEAR=432, SIDE=288 |
| COOLDOWN_BARS | 6-150 | 36 |
| MIN_ATR_THRESHOLD | 0.5-5.0 | 5.0 |
| RISK_MULT | 0.1-2.0 | BULL=0.4, BEAR=1.5, SIDE=0.5 |
| VIX tiers | — | 16/20/28/35/40/50 |

### MR Scalper Parameters
| Parameter | Range | Current |
|---|---|---|
| RSI Period | 5-20 | 12 |
| RSI Entry | 15-35 | 25 |
| RSI Exit | 40-65 | 55 |
| Max Hold | 6-48 bars | 24 |
| Stop ATR Mult | 1.0-2.5 | 1.5 |
| TP ATR Mult | 1.5-3.0 | 2.0 |
| Min Daily ATR% | 1.0-2.5 | 1.5 |
| Max Trades/Day | 1-5 | 3 |
| Cooldown Bars | 3-12 | 6 |
| Risk/Trade | $1K-$5K | $2K |

---

## Data Sources
| File | Bars | Range | Notes |
|---|---|---|---|
| `ES_combined_5min.parquet` | 50,760 | Jan 31 2025 – Apr 2 2026 | Primary backtest |
| `ES_1min.parquet` | 241,009 | Jan 2025 – Mar 2026 | High-res data |
| `ES_daily.parquet` | 649 | Aug 2023 – Apr 2 2026 | Daily overlay |
| `ES_combined_hourly_extended.parquet` | 7,119 | Apr 2023 – Mar 2026 | SPY-converted + real |
| `ml_entry_signal.csv` | 330 | Dec 2024 – Apr 2026 | Walk-forward ML predictions |
| `daily_sentiment.csv` | 345 | — | WSJ + DJ-N composite |
| VIX, HY OAS, DXY, yields, copper | — | — | From macro_2 repo |

---

## Prior Strategy Versions

### Phase 15: Peak (Original Data, Mar 20 2026)
```
Return: +14.73% | DD: 28.88% | WR: 34% | Trades: 44 | Score: 10.47
```
- Data ended Mar 20 2026 (pre-war)
- Risk-adjusted scoring enabled
- 3,100 iterations to reach this peak

### Phase 13: Low-DD Peak (Original Data)
```
Return: +10.98% | DD: 19.64% | WR: 46% | Trades: 13 | Score: 8.82
```
- Very selective (13 trades), high WR
- Near-miss chains from 4,000 iterations

### Phase 1: Highest Raw Return
```
Return: +32.18% | DD: 56.6% | WR: 48% | Trades: 54 | Score: 13.97 (retroactive)
```
- Flat strategy (no regime classification)
- Near DD limit (56.6% vs 60% cap)

### Post-Extension Collapse
```
Return: -0.45% | DD: 16.04% | Trades: 39 | Score: -0.37
```
- Data extended to Apr 2 2026 (Iran war)
- War caused 3× volatility, destroyed short entries
- Led to structural experiments and MR scalper development

### See Also
- `AR_exp_log.md` (project root) — complete experiment history with all 28 sweep batches
- `autoresearch/NEXT_STEPS.md` — current roadmap and exhausted approaches
