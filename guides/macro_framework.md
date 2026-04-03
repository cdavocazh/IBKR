# Macro Analytical Frameworks

## Macro Regime Classification (6 Dimensions)
The `analyze_macro_regime()` function classifies the current environment across:
1. **Inflation**: CPI/PCE/PPI trajectory, core vs headline, breadth of increases
2. **Employment**: NFP, unemployment rate, initial claims, JOLTS, Sahm Rule
3. **Growth**: ISM PMI, GDP, new orders, manufacturing hours
4. **Rates**: Fed funds, SOFR, 2Y/10Y trajectory, real yields
5. **Credit**: HY/IG/BBB OAS spreads, bank lending standards
6. **Housing**: Starts, permits, sales, mortgage rates, Case-Shiller

Each dimension uses ISM decomposition (DGORDER/MANEMP/ISRATIO), labor breadth (JOLTS + claims), and housing data as sub-indicators.

## Financial Stress Score (0-10 Composite)

### 8 Weighted Components
| Component | What it measures | Stress direction |
|-----------|-----------------|-----------------|
| NFCI | Financial conditions breadth | Higher = tighter |
| HY OAS | Corporate credit risk | Wider = more stress |
| VIX | Equity volatility | Higher = more fear |
| 2s10s spread | Yield curve shape | Inverted = recession signal |
| Initial claims | Labor market health | Rising = weakening |
| Sahm Rule | Unemployment acceleration | Triggered = recession |
| Consumer sentiment | Household confidence | Lower = more stress |
| Consumer credit | Credit quality | Delinquencies rising = stress |

### Scoring Mechanics
- Each component scored 0-10 independently
- Weighted average computed
- **Breadth floor**: When >=3 of 8 components score >=5, composite floors at 4.0 ("elevated")
- This prevents broad-based stress being masked by weighted averaging
- Output includes `weighted_average`, `breadth_floor_applied`, `scoring_method` fields

### Regime-Aware HY OAS Classification
- Uses 1-year percentile rank (not hardcoded thresholds)
- Absolute guardrails: 600bps = severe, 800bps = crisis
- Auto-calibrates: what's "tight" vs "wide" shifts with the rate environment
- All 5 instances across codebase use `classify_hy_oas()` (v2.7.1-v2.7.3 fixes)

## Late-Cycle Detection (13-Signal Framework)

### Signal Counting
| Active Signals | Classification |
|---------------|---------------|
| 0-2 | Early/mid cycle |
| 3-4 | Transitioning to late cycle |
| 5-6 | Late cycle |
| 7-8 | Pre-recessionary |
| 8+ | Severe recession risk |

### The 13 Signals
1. ISM manufacturing < 50 (contraction territory)
2. New orders declining (ISM sub-component)
3. NFP deceleration (3-month momentum slowing)
4. Rising initial claims (labor softening)
5. Credit spreads widening (HY OAS stress via regime-aware classifier)
6. Term premium rising (discount rate adjustment)
7. Quits rate declining (workers less confident)
8. Yield curve inversion (2s10s or 3m10s)
9. Labor share near record lows (wage pressure building)
10. Manufacturing recession (DGORDER/AWHMAN/OPHNFB/ULCNFB decomposition)
11. ISM employment breadth weakness
12. Housing permits declining 3+ months (leading indicator)
13. Delinquency rates rising (credit quality deteriorating)

## VIX 7-Tier Opportunity Framework

| Tier | VIX Range | Interpretation |
|------|----------|---------------|
| 1 | <14 | Complacency — extreme apathy, precedes sharp moves |
| 2 | 14-20 | Normal — healthy conditions |
| 3 | 20-25 | Elevated — moderate stress |
| 4 | 25-30 | Risk-off — active selling |
| 5 | 30-40 | Opportunity — vol control forced buying |
| 6 | 40-50 | Career P&L — extreme dislocation |
| 7 | 50+ | Home run — panic, forced liquidation |

### UnderVIX Detection
VIX appears low but credit spreads or curve stress present. Indicates complacency masking risks. Contrarian bearish signal.

## Term Premium Dynamics
**Proxy**: 10Y nominal - 10Y real (TIPS) - 10Y breakeven inflation

| Condition | Signal |
|-----------|--------|
| Positive + breakevens rising | Reflation / global discount rate adjustment |
| Negative | Flight to safety / risk-off |
| Rising | Investors demand more duration compensation |
| Falling | Safety bid for long bonds |

Includes global rate signal detection (e.g., Japan yield policy shifts affecting US term premium).

## Yardeni Frameworks

### Boom-Bust Barometer
- Formula: Copper price / Initial claims
- Peaks at boom end, troughs at recession end
- Minimal lag — useful leading indicator
- Note: Claims must be in thousands (not raw FRED value)

### FSMI (Fundamental Stock Market Indicator)
- Formula: Average z-score of CRB industrials + consumer sentiment
- Highly correlated with S&P 500
- Divergence = market may correct to fundamentals
- Needs >= 6 observations for z-score (reduced from 12 in v2.7.8)

### Bond Vigilantes Model
- Comparison: 10Y yield vs nominal GDP growth
- Yield > GDP growth: Bond market demanding fiscal discipline
- Yield < GDP growth: Central bank suppression active
- GDP window: 730 days (quarterly data needs wide window)

### Yardeni Valuation
- **Rule of 20**: P/E + CPI YoY = 20 → fair value P/E = 20 - CPI
- **Rule of 24**: P/E + Misery Index average = 23.9
- **Real Earnings Yield**: 1/PE - CPI
- CPI data comes from local CSV (pre-computed YoY percentages, not raw index)

### Market Decline Classification
- <10%: Panic attack (short-lived, 66 events 2009-2020)
- 10-20%: Correction
- >20%: Bear market
- Key insight: Forward EPS keeps rising during drawdown → correction not bear

## Energy-Inflation Passthrough Model
- Gas: CPI weight 2.91% × gas price change
- BofA oil model for broader energy impact
- Used by `market_regime_enhanced.py` for CPI forecasting

## Macro Synthesis Contradiction Detection
5 cross-tool consistency checks:
1. **Credit-equity**: Credit spreads risk-off but equities rising? Flag divergence
2. **Consumer-regime**: Consumer health stable but macro recessionary? Flag inconsistency
3. **VIX-credit**: VIX calm but credit stressed? Flag underVIX
4. **Late-cycle-growth**: Late-cycle signals active but growth strong? Flag mixed signals
5. **Bonds-equity**: Bond market pricing recession but equity ignoring? Flag divergence

Historical analogue matching uses fuzzy comparison on VIX level, HY OAS level, and curve shape against 5 reference periods.

## FRED Data Architecture
- 56 FRED series mapped to local CSVs via `FRED_TO_LOCAL_MAP`
- Local-first: reads local CSV with 2-year default window (v2.7.8: extended from 1 year)
- Falls back to FRED API when local data unavailable
- Key fix: CPI/core CPI/core PCE/PPI CSVs store pre-computed YoY percentages — `is_yoy_pct` flag prevents computing YoY of YoY
- Claims data: normalize raw FRED value to thousands (213000 → 213)
- ETF data: yfinance on-demand for XLE, XOP, KBE (30-min cache TTL)
