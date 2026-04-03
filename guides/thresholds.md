# Anomaly Detection & Scoring Thresholds

## Macro Indicator Anomaly Detection

### Z-Score Thresholds
- z-score > 2.0 (or < -2.0): Flagged as anomaly
- Rolling window: 20-day for z-score computation

### Percentage Change Thresholds
- Daily move > 3%: Flagged
- Proximity to 52-week high/low: Flagged

### Plausibility Caps (v2.7.2 — BUG-3 fix)
Reject impossible moves computed by `_safe_pct()`:
- |daily| > 50% → None
- |weekly| > 80% → None
- |monthly| > 100% → None

## Financial Stress Score Thresholds

### Component Scoring (each 0-10)
| Component | Low (0-2) | Moderate (3-4) | Elevated (5-6) | High (7-8) | Critical (9-10) |
|-----------|-----------|---------------|----------------|-----------|----------------|
| VIX | <14 | 14-20 | 20-25 | 25-35 | >35 |
| HY OAS | Regime-aware (percentile rank) | | | 600bps severe | 800bps crisis |
| 2s10s | Positive, steep | Flat | Inverted | Deeply inverted | |
| Claims | <220K | 220-250K | 250-300K | 300-400K | >400K (in thousands) |
| NFCI | <-0.5 | -0.5 to 0 | 0 to 0.5 | 0.5 to 1.0 | >1.0 |
| Sahm Rule | <0.3 | 0.3-0.5 | 0.5+ (triggered) | | |

### Composite Thresholds
- 0-2: Low stress
- 2-4: Moderate stress
- 4-6: Elevated stress
- 6-8: High stress
- 8-10: Critical stress

### Breadth Floor Rule (v2.7.2 — BUG-6 fix)
When >=3 of 8 components score >=5, composite floors at 4.0 ("elevated").
Prevents weighted averaging from masking broad-based stress.

## HY OAS Regime-Aware Classification

### Method
- Compute 1-year percentile rank of current HY OAS level
- Classification by percentile:
  - <25th percentile: Tight
  - 25-50th: Normal
  - 50-75th: Widening
  - 75-90th: Wide
  - >90th: Very wide

### Absolute Guardrails
- 600bps: Severe (regardless of percentile)
- 800bps: Crisis (regardless of percentile)

### Cross-Tool Consistency (v2.7.7 — BUG-RE-2 fix)
- Macro tool exposes value in bps (e.g., 306)
- Stress tool exposes raw value (e.g., 3.06) PLUS `value_bps` field

## Consumer Health Score Thresholds

### Component Stress Scoring (each 0-10, higher = more stress)
| Component | Low Stress | High Stress |
|-----------|-----------|-------------|
| Savings rate | >7% | <3% |
| Credit growth (YoY) | <5% | >10% |
| Delinquency rate | <1.5% | >2.5% |
| Bank lending standards | Net easing | Net tightening >10% |

### Health Score (inverted from stress)
- Formula: health = 10 - weighted_stress_average
- >7: Healthy
- 5-7: Stable
- 3-5: Stressed
- <3: Critical

### Output Fields (v2.7.8)
- `consumer_health_score`: The health score (inverted)
- `weighted_stress_average`: Pre-inversion stress value
- `consumer_health_level` and `consumer_health`: Both point to same classification
- `scoring_method`: Explains formula breakdown

## Housing Market Thresholds

### Leading Indicator Logic (v2.7.2 — BUG-5 fix)
- Leading indicator checks: permits + starts + sales
- 2-of-3 declining triggers downturn classification
- Downstream cycle phase override: "mixed" → "declining" (>=2 distress) or "distressed" (>=3)

### Cycle Phase Classification
- Boom: Rising permits, low affordability pressure
- Cooling: Permits stabilizing, affordability tightening
- Contraction: Permits declining, sales falling
- Recovery: Permits rising, prices stabilizing

## Equity Analysis Thresholds

### OCF/NI Interpretation (v2.7.4 — BUG-CMD-2 fix)
- Strong: >= 0.8
- Adequate: >= 0.5
- Weak: < 0.5

### Data Staleness Warning
- data_warning field emitted when latest quarter > 2 years old

### Negative Shares Validation (v2.7.6 — BUG-B3-5 fix)
- Negative diluted share counts discarded (set to None)

## VIX 7-Tier Opportunity Thresholds

| Tier | VIX Range | Classification |
|------|----------|---------------|
| 1 | <14 | Complacency |
| 2 | 14-20 | Normal |
| 3 | 20-25 | Elevated |
| 4 | 25-30 | Risk-off |
| 5 | 30-40 | Opportunity |
| 6 | 40-50 | Career P&L |
| 7 | 50+ | Home run |

## Late-Cycle Signal Counting

| Active Signals | Classification |
|---------------|---------------|
| 0-2 | Early/mid cycle |
| 3-4 | Transitioning |
| 5-6 | Late cycle |
| 7-8 | Pre-recessionary |
| 8+ | Severe recession risk |

## Inflation Interpretation Thresholds

### Contradiction Handling (v2.7.5 — BUG-B2-3 fix)
- Rising trend prevents "cooling" classification
- BREAKEVEN vote-based dedup: majority wins, mixed when series disagree (v2.7.1)

### CPI Data Source Note (v2.7.7 — BUG-RE-1 fix)
- Local CSVs store pre-computed YoY percentages (~2.7%), NOT raw index (~314)
- `is_yoy_pct` flag in FRED_TO_LOCAL_MAP prevents computing YoY of YoY

## Initial Claims Normalization

### Raw FRED Value vs Display (v2.7.5 — BUG-B2-7 fix)
- Raw FRED: 213000 (actual count)
- Display: 213K (in thousands)
- All scoring thresholds expect values in thousands
- Applied in: fred_data.py, market_regime_enhanced.py, yardeni_frameworks.py

## FRED Data Window Thresholds

### Default Windows (v2.7.8 — BUG-R2-1 fix)
- Default window: 2 years (730 days) — extended from 1 year
- Quarterly data needs 730 days to get 5+ observations for YoY
- Monthly data with 730 days gets ~20 observations for reliable z-scores

### FSMI Observation Threshold (v2.7.8 — BUG-R2-2 fix)
- Minimum observations for z-score: 6 (reduced from 12)

## Graham Analysis Thresholds

### Graham Number
- sqrt(22.5 × EPS × BVPS)

### Margin of Safety (v2.7.5 — BUG-B2-6 fix)
- Formula: (Graham Number - Price) / Price
- Positive: Trading below intrinsic value (buy zone)
- Negative: Trading above intrinsic value (overvalued)

### 7 Defensive Investor Criteria
Scored X/7. Higher = more defensive.

### Net-Net Screen
- Buy zone: Price < 2/3 × Net Current Asset Value

## Stop-Loss Asset Profiles

| Asset | Typical Stop Width |
|-------|-------------------|
| FX | 50-100 pips |
| Gold | 30-160 points |
| Silver | 3-5 points (half-size) |
| Copper | 10-30 cents |
| Oil | $1.50-3.50 |
| BTC | $3,000-8,000 |
| ES | 30-60 points |
| Rates | 5-10 bps |
| ETFs | 5-10% |

Position sizing: 0.75-2.0% of capital per trade.
