# Self-Evaluation Guide — Output Quality Assurance

This guide contains the **complete evaluation criteria** from all 9 taste evaluation approaches (Approach #2 through #10) in `/Testing_Agent/taste/`. The agent uses this to self-evaluate outputs before delivery and to log evaluation records for continuous improvement.

Read alongside `guides/interpretation.md` and `guides/thresholds.md`. Log findings to `taste_evaluation_report.md` under Evaluation Records.

---

## Pre-Delivery Checklist

Before presenting any analysis, verify these 6 items:

1. **Label-to-value grounding** (Approach #3, #9) — Every qualitative label matches the threshold dictionary below
2. **Cross-tool consistency** (Approach #6) — Same metric has same value across all tool outputs used
3. **Coherence rules** (Approach #2) — No contradictions across tools per the 11 coherence rules
4. **Composite decomposition** (Approach #6) — Weighted averages recompute correctly from components
5. **Conflict reconciliation** (Approach #10) — When composite signal disagrees with individual indicators, explicitly explain why
6. **Narrative quality** (Approach #4) — Cause-effect chains, data provenance, risk-to-thesis, actionable levels

---

## Approach #2: Internal Coherence (11 Rules)

Source: `taste/approach_2_coherence/coherence_checker.py`

Cross-checks whether different tools' conclusions are logically compatible. Pure domain-logic, no LLM.

### All 11 Rules

| Rule | Condition | Required Outcome | Severity |
|------|-----------|-----------------|----------|
| **C-01** | Regime = Reflationary or Goldilocks | Stress score < 6.0 | HIGH |
| **C-01b** | Regime = Recessionary, Stagflation, or Crisis | Stress score > 4.0 | HIGH |
| **C-02** | HY OAS > 250 bps | Narrative must NOT say "tight", "supportive", or "benign" | CRITICAL |
| **C-02b** | HY OAS <= 250 bps | Narrative must NOT say "wide", "stress", or "distress" | CRITICAL |
| **C-03** | Yield curve inverted | Late-cycle count >= 3 | HIGH |
| **C-03b** | Yield curve normal | Late-cycle count <= 8 | MEDIUM |
| **C-04** | Housing signals include PLUNGING/COLLAPSING/CRISIS | Consumer health must NOT be "healthy" | HIGH |
| **C-05** | VIX > 25 | Stress level must NOT be "low" | HIGH |
| **C-05b** | VIX < 15 | Stress level must NOT be "high" or "extreme" | MEDIUM |
| **C-06** | Growth regime = "expansion" | Must NOT have ISM_CONTRACTION signal | HIGH |
| **C-07** | Any signal pair across all tools | No mutually exclusive pairs: CREDIT_LOOSE+CREDIT_TIGHT, INFLATION_HOT+INFLATION_COOLING, GROWTH_EXPANSION+GROWTH_CONTRACTION, FED_TIGHTENING+FED_EASING, STRESS_LOW+STRESS_ELEVATED/HIGH | CRITICAL |
| **C-08** | BANK_SYSTEMIC_STRESS signal present | Consumer credit must NOT be "healthy", "strong", or "robust" | HIGH |
| **C-09** | Real yield > 2.0% AND trend = "rising" | Equity summary must mention "headwind", "pressure", "compress", "drag", "negative", or "challenge" | MEDIUM |
| **C-10** | Rate regime contains "easing" | Must NOT have FED_TIGHTENING signal | HIGH |
| **C-10b** | Rate regime contains "tightening" | Must NOT have FED_EASING signal | HIGH |
| **C-11** | flagged_count / total_indicators > 70% | Stress level must NOT be "low" | MEDIUM |

---

## Approach #3: Narrative-vs-Data Grounding (9 Threshold Dictionaries)

Source: `taste/approach_3_grounding/grounding_evaluator.py`

Checks whether qualitative labels in narratives match the numeric values. When the tool's regime-aware classifier produces a different label, **present both framings**.

### Complete Threshold Dictionary

```
hy_oas_bps:
  tight:      (0, 150)
  normal:     (150, 300)
  wide:       (300, 500)
  stressed:   (500, 800)
  distressed: (800, 5000)

vix:
  complacent: (0, 12)
  calm:       (12, 16)
  normal:     (16, 20)
  elevated:   (20, 25)
  fearful:    (25, 35)
  panic:      (35, 100)

stress_score:
  low:      (0, 2.5)
  moderate: (2.5, 5)
  elevated: (5, 7)
  high:     (7, 9)
  extreme:  (9, 10)

consumer_health_score:
  critical: (0, 3)
  stressed: (3, 5)
  stable:   (5, 7)
  healthy:  (7, 10)

cpi_yoy_pct:
  deflationary: (-5, 0)
  low:          (0, 2)
  target:       (2, 2.5)
  above_target: (2.5, 3.5)
  hot:          (3.5, 5)
  very_hot:     (5, 20)

unemployment_pct:
  very_tight: (0, 3.5)
  tight:      (3.5, 4.5)
  normal:     (4.5, 5.5)
  loose:      (5.5, 7)
  weak:       (7, 20)

real_yield_10y_pct:
  deeply_negative: (-5, -0.5)
  negative:        (-0.5, 0)
  low:             (0, 1)
  moderate:        (1, 2)
  high:            (2, 3)
  very_high:       (3, 10)

fed_funds_pct:
  near_zero:        (0, 0.5)
  accommodative:    (0.5, 2)
  neutral:          (2, 3.5)
  restrictive:      (3.5, 5.5)
  very_restrictive: (5.5, 10)

late_cycle_count:
  early_cycle:   (0, 3)
  mid_cycle:     (3, 6)
  late_cycle:    (6, 10)
  pre_recession: (10, 14)
```

### 7 Claim Categories Checked

1. **Credit spread interpretation** — Does "tight"/"supportive"/"wide" in narratives match HY OAS level?
2. **Stress level vs composite score** — Does stress_level label match the numeric stress_score?
3. **VIX characterization** — Do VIX descriptions match the actual VIX value?
4. **Inflation characterization** — Does inflation regime ("hot"/"cooling") match CPI YoY?
5. **Late-cycle confidence** — Does confidence_level label match the late_cycle_count?
6. **Real yield characterization** — Do real yield descriptions ("moderate"/"high") match actual 10Y real yield?
7. **Consumer health level vs score** — Does "stable"/"stressed"/"healthy" match the composite_score?

---

## Approach #4: Comparative Benchmark (7-Dimension LLM Judge)

Source: `taste/approach_4_comparative/comparative_benchmark.py`

Evaluates overall analytical quality on a CFA Research Challenge-inspired rubric. Each dimension scored 1-10.

### 7 Rubric Dimensions

| # | Dimension | Weight | Scoring Guide |
|---|-----------|--------|---------------|
| 1 | **Data Accuracy & Traceability** | 15% | 1-2: Missing/wrong. 3-4: Numbers present, no sources. 5-6: Some sources. 7-8: Specific data cited with FRED/BLS refs. 9-10: Comprehensive sourcing, fully verifiable |
| 2 | **Analytical Depth (Why, Not Just What)** | 20% | 1-2: No analysis. 3-4: Describes conditions. 5-6: Some cause-effect. 7-8: Cause-effect chains, second-order thinking, historical analogies. 9-10: Novel insights, explains mechanisms |
| 3 | **Internal Coherence** | 15% | 1-2: Major contradictions. 3-4: Contradictions present, unacknowledged. 5-6: Mostly consistent. 7-8: Coherent, contradictions reconciled. 9-10: Airtight logic |
| 4 | **Actionability & Investment Implications** | 20% | 1-2: No recommendations. 3-4: Generic direction only. 5-6: Some tilts mentioned. 7-8: Specific sector tilts, duration calls, risk mgmt, entry/stop levels. 9-10: Complete portfolio action plan |
| 5 | **Completeness & Risk Assessment** | 10% | 1-2: Single scenario, no risks. 3-4: Basic scenario. 5-6: Some risks noted. 7-8: Base/bull/bear cases, key risks identified. 9-10: Comprehensive with blind spots acknowledged |
| 6 | **Professional Quality & Communication** | 10% | 1-2: Unparseable. 3-4: Readable but rough. 5-6: Adequate with gaps. 7-8: Professional language, proper caveats. 9-10: Publication-grade |
| 7 | **Signal Specificity & Originality** | 10% | 1-2: Generic. 3-4: Restates data as signals. 5-6: Some insights. 7-8: Cross-dimensional, connecting dots. 9-10: Novel insights beyond Bloomberg terminal |

**Weighted score** = sum(score_i x weight_i). Tiers: Excellent (>=8), Good (>=6), Acceptable (>=4), Poor (<4).

---

## Approach #5: Forward-Looking Signal Backtesting (22 Signal Definitions)

Source: `taste/approach_5_backtesting/signal_tracker.py`

Captures directional signals and verifies them after 1/4/12 weeks.

### All Signal Definitions

**Inflation:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| INFLATION_HOT | up | CPI YoY next print > current OR stays above 3% | 4-12w |
| INFLATION_COOLING | down | CPI YoY next print < current OR moves toward 2% | 4-12w |
| INFLATION_STABLE | neutral | CPI YoY stays 1.5-2.5% | 4-12w |

**Growth:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| GROWTH_EXPANSION | up | ISM > 50 | 4w |
| GROWTH_SLOWING | down | ISM moves toward/below 50 | 4-12w |
| GROWTH_CONTRACTION | down | ISM < 50 OR GDP negative | 4-12w |
| ISM_CONTRACTION | down | ISM remains < 50 | 4w |

**Labor:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| LABOR_TIGHT | strong | Unemployment < 4.5% | 4-12w |
| LABOR_LOOSENING | weakening | Unemployment rises OR claims increase | 4-12w |

**Fed Policy:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| FED_TIGHTENING | hawkish | Rates stay elevated or increase | 4-12w |
| FED_EASING | dovish | Rates decrease or cuts announced | 4-12w |
| FED_NEUTRAL | neutral | Rates unchanged | 4w |
| FED_RESTRICTIVE | hawkish | Real policy rate positive and above neutral | 4-12w |

**Credit:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| CREDIT_LOOSE | easy | HY OAS < 300 bps | 4w |
| CREDIT_TIGHT | tight | HY OAS > 400 bps or widens further | 4-12w |
| CREDIT_STRESS | stress | HY OAS elevated OR default rates rise | 4-12w |

**Volatility:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| VIX_HOME_RUN | elevated | VIX 20-25 (buying opportunity) | 1-4w |
| VIX_CAREER_PNL | high | VIX 25-35 (major buying opportunity) | 1-4w |
| VIX_COMPLACENCY | low | VIX < 12 | 4-12w |

**Breakeven Inflation:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| BREAKEVEN_RISING | up | Breakevens stay elevated or rise | 4-12w |
| BREAKEVEN_FALLING | down | Breakevens continue to decline | 4-12w |
| BREAKEVEN_MIXED | neutral | Breakevens range-bound | 4w |

**Yield Curve:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| CURVE_INVERSION_WARNING | inverted | Recession within 6-18 months OR curve un-inverts | 12-52w |
| CURVE_STEEPENING | steepening | Spread continues to widen | 4-12w |

**Regime:**
| Signal | Direction | Verification | Horizon |
|--------|-----------|-------------|---------|
| RISK_OFF_REGIME | risk_off | SPX flat/negative, bonds rally, gold up | 1-4w |
| FLIGHT_TO_SAFETY | risk_off | Yields decline OR gold rises | 1-4w |

---

## Approach #6: Data Accuracy Verification (7 Check Categories)

Source: `taste/approach_6_data_accuracy/data_accuracy_checker.py`

Arithmetic correctness, cross-tool consistency, range plausibility, and contradiction detection.

### Category 1: Arithmetic Consistency

| Check | Formula | Tolerance |
|-------|---------|-----------|
| A-01 | 2s10s = 10Y_nominal - 2Y_nominal | ±2 bp |
| A-02 | Term premium = nominal_10Y - real_10Y - breakeven_10Y | ±10 bp |
| A-03 | HY-IG differential = HY_OAS_bps - IG_OAS_bps | exact |
| A-04 | OAS_pct x 100 = OAS_bps (for HY, IG, BBB) | ±1 bp |
| A-05 | Permits/starts ratio = permits / starts | ±2% |
| A-06 | Monthly payment approx= price x rate / 12 | ±$10 |
| A-07 | 10Y breakeven approx= nominal_10Y - real_10Y | ±15 bp |
| A-07b | 5Y breakeven approx= nominal_5Y - real_5Y | ±15 bp |

### Category 2: Cross-Tool Value Consistency

| Check | Metric | Tools Compared | Tolerance |
|-------|--------|---------------|-----------|
| X-01 | VIX | stress vs equity_drivers vs scan | ±0.5 |
| X-02 | HY OAS (pct) | bond_market vs equity_drivers vs stress | ±0.05 |
| X-03 | Real yield 10Y | equity_drivers vs bond_market | ±0.05 |
| X-04 | Fed funds rate | macro_regime vs bond_market | exact |
| X-05 | Nominal 10Y | yield_curve vs term_premium (within bond) | exact |
| X-06 | Credit spread direction | bond signals vs equity signals | consistent |
| X-07 | Mortgage rate | macro_regime vs housing_market | exact |
| X-08 | Credit classification | consistent label across all tools | exact |

### Category 3: Composite Score Decomposition

| Check | Score | Verification Method | Tolerance |
|-------|-------|-------------------|-----------|
| S-01 | Financial stress | Recompute: sum(component_score x weight) / sum(weights) | ±0.15 |
| S-02 | Consumer health | Same weighted-average decomposition | ±0.15 |
| S-03 | Late-cycle count | Count of actually firing signals in output | exact |
| S-04 | Scan flagged_count | Length of flagged_indicators list | exact |

### Category 4: Flag Alignment (~23 checks)

- **F-01** (8 checks): Threshold flags match actual values (e.g., OIL_ELEVATED only if crude > threshold)
- **F-02** (13 checks): 52-week proximity flags — current value within 5% of stated 52W high/low
- **F-03/F-03b**: Plausibility caps — daily move > ±50% or monthly move > ±100% = suspicious

### Category 5: Range Plausibility (16 checks)

```
Plausible ranges:
  vix:                   (8, 90)
  fed_funds_rate:        (0, 7)
  cpi_yoy_pct:           (-3, 15)
  unemployment_pct:      (2, 15)
  hy_oas_bps:            (200, 2500)
  ig_oas_bps:            (40, 600)
  real_yield_10y:        (-2, 5)
  stress_score:          (0, 10)
  consumer_health_score: (0, 10)
  late_cycle_count:      (0, 13)
  mortgage_rate:         (2, 10)
  housing_starts_k:      (400, 2500)
  existing_sales:        (1e6, 8e6)
  ism_pmi:               (30, 70)
  savings_rate:          (0, 35)
  breakeven_inflation:   (0, 5)
```

### Category 6: Internal Contradictions (7 checks)

| Check | Contradiction | Why Impossible |
|-------|--------------|----------------|
| I-01 | BREAKEVEN_RISING + BREAKEVEN_FALLING simultaneously | Mutually exclusive directions |
| I-02 | CREDIT_LOOSE signal + credit regime "tight" | Same tool says opposite |
| I-03 | CREDIT_TAILWIND signal + HY OAS > 300 bps | Tailwind implies tightening; 300+ is wide |
| I-04 | SALES_PLUNGING + leading indicator NO_WARNING | Plunging sales IS a warning |
| I-05 | Consumer health label vs numeric score mismatch | "stable" requires 5-7; if actual < 5, label wrong |
| I-06 | Stress level label vs numeric score mismatch | Same pattern as I-05 |
| I-07 | Housing phase "mixed" + multiple distress signals | Should be "declining"/"distressed" |

### Category 7: Temporal Consistency (2 checks)

- **T-01**: All tools report the same date/timestamp
- **T-02**: Fewer than 3 "data_unavailable" or null fields

---

## Approach #7: TA Internal Coherence (15 Checks per Asset)

Source: `taste/approach_7_ta_evaluation/ta_coherence_checker.py`

Cross-tool consistency for TA outputs. Run for each asset analyzed.

### Signal Direction Consistency (TC-01 to TC-05)

| Check | Test | Logic |
|-------|------|-------|
| TC-01 | Composite signal vs trend direction | Allow mild divergence if score < ±0.5 |
| TC-02 | MACD crossover vs histogram sign | histogram > 0 = bullish, < 0 = bearish |
| TC-03 | RSI vs Stochastic alignment | Must NOT have opposing extremes (RSI overbought + %K oversold) |
| TC-04 | Bollinger %B vs RSI coherence | %B > 90 + RSI < 30 is contradictory |
| TC-05 | Trend direction vs MA structure | Price below SMA50 AND SMA200 should NOT be "uptrend" |

### S/R Consistency (TC-06 to TC-08)

| Check | Test | Tolerance |
|-------|------|-----------|
| TC-06 | All supports < price < all resistances | 1% tolerance |
| TC-07 | Murphy S/R vs standalone S/R nearest levels match | < 2% difference |
| TC-08 | S/R level spacing (no duplicate/near-duplicate levels) | > 0.3% apart |

### Cross-Tool Consistency (TC-09 to TC-12)

| Check | Test | Tolerance |
|-------|------|-----------|
| TC-09 | Murphy RSI vs standalone RSI | < 0.1 difference (exact) |
| TC-10 | Breakout type vs trend direction | Bullish breakout in uptrend, bearish in downtrend |
| TC-11 | Breakout nearest_res matches S/R nearest_res | < 1% difference |
| TC-12 | Quick snapshot RSI vs individual tools RSI | < 0.1 difference (exact) |

### Stop-Loss Coherence (TC-13 to TC-15)

| Check | Test | Severity |
|-------|------|----------|
| TC-13 | Long stop-loss < entry price | CRITICAL |
| TC-14 | Short stop-loss > entry price | CRITICAL |
| TC-15 | (entry - stop) / entry = risk_pct in position_sizing | ±1% tolerance |

---

## Approach #8: TA Data Accuracy (25 Checks per Asset)

Source: `taste/approach_8_ta_accuracy/ta_accuracy_checker.py`

Recomputes indicators from raw OHLCV and compares to tool output.

### RSI Verification (TA-01 to TA-04)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-01 | RSI(14) vs recomputed (Wilder's formula) | ±1.5 points |
| TA-02 | RSI(7) vs recomputed | ±2.0 points |
| TA-03 | RSI(21) vs recomputed | ±2.0 points |
| TA-04 | RSI zone label matches value range | exact |

### MACD Verification (TA-05 to TA-09)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-05 | MACD line vs recomputed (EMA-based) | 1% of price |
| TA-06 | Signal line vs recomputed | 1% of price |
| TA-07 | Histogram vs recomputed | 1% of price |
| TA-08 | Histogram sign matches crossover label | exact |
| TA-09 | Centerline label correct (above/below zero) | exact |

### Bollinger Bands Verification (TA-10 to TA-14)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-10 | Upper band vs recomputed (SMA20 + 2x std) | 0.5% of price |
| TA-11 | Lower band vs recomputed | 0.5% of price |
| TA-12 | Middle band vs recomputed (SMA20) | 0.5% of price |
| TA-13 | Bandwidth% vs recomputed ((upper-lower)/middle*100) | ±1.0% |
| TA-14 | %B vs recomputed ((price-lower)/(upper-lower)*100) | ±3.0% |

### Fibonacci Verification (TA-15 to TA-17)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-15 | Fib 38.2% vs recomputed (swing_high - diff*0.382) | 0.5% of price |
| TA-16 | Fib 61.8% vs recomputed | 0.5% of price |
| TA-17 | Fibonacci zone description plausible | non-empty |

### Stochastic Verification (TA-18 to TA-20)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-18 | %K vs recomputed (14-period) | ±2.0 points |
| TA-19 | %D vs recomputed (3-period SMA of %K) | ±2.0 points |
| TA-20 | Zone label matches %K range | exact |

### Composite Signal Verification (TA-21 to TA-23)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-21 | Composite score within [-1.0, 1.0] | exact |
| TA-22 | Signal label matches score (BULLISH >0.3, BEARISH <-0.3) | exact |
| TA-23 | Confidence label matches magnitude (high: 0.6-1.0, medium: 0.3-0.6, low: 0-0.3) | exact |

### Stop-Loss Arithmetic (TA-24 to TA-25)

| Check | Indicator | Tolerance |
|-------|-----------|-----------|
| TA-24 | Risk% = (entry - stop) / entry * 100 = position_sizing.risk_pct | exact |
| TA-25 | R:R ratio = reward_pct / risk_pct (must be >= 1.0) | exact |

---

## Approach #9: TA Grounding (12 Label-to-Value Checks per Asset)

Source: `taste/approach_9_ta_grounding/ta_grounding_evaluator.py`

Verifies TA labels match their underlying indicator values.

### TA Threshold Dictionary

```
rsi:
  oversold:          (0, 30)
  bearish_momentum:  (30, 50)
  bullish_momentum:  (50, 70)
  overbought:        (70, 100)

stochastic:
  oversold:   (0, 20)
  neutral:    (20, 80)
  overbought: (80, 100)

bollinger_pct_b:
  below_lower_band: (-999, 0)
  near_lower_band:  (0, 20)
  within_bands:     (20, 80)
  near_upper_band:  (80, 100)
  above_upper_band: (100, 999)

composite_signal:
  BEARISH: (-1.0, -0.3)
  NEUTRAL: (-0.3, 0.3)
  BULLISH: (0.3, 1.0)

confidence:
  high:   (0.6, 1.0)
  medium: (0.3, 0.6)
  low:    (0.0, 0.3)
```

### All 12 Checks

| Check | Test | Logic |
|-------|------|-------|
| TG-01 | RSI zone label matches RSI value | Value must be within threshold range for stated zone |
| TG-02 | RSI divergence label valid | Must be BEARISH_DIVERGENCE, BULLISH_DIVERGENCE, or null |
| TG-03 | Stochastic zone label matches %K value | Value must be within threshold range |
| TG-04 | Stochastic crossover label correct | BULLISH_CROSS = %K >= %D; BEARISH_CROSS = %K <= %D |
| TG-05 | Bollinger squeeze label matches bandwidth | squeeze=true only if bandwidth < 10% |
| TG-06 | Bollinger position label matches %B value | Position must be within threshold range for %B |
| TG-07 | MACD crossover label matches histogram sign | BULLISH = histogram >= 0; BEARISH = histogram <= 0 |
| TG-08 | Trend direction label matches price vs swing structure | Uptrend: price closer to recent highs |
| TG-09 | MA crossover label matches SMA relationship | Bullish alignment = SMA50 >= SMA200 |
| TG-10 | Composite signal label matches score | Must be within signal threshold range |
| TG-11 | Confidence label matches score magnitude | Must be within confidence threshold range |
| TG-12 | Breakout type matches breakout direction detected | Bullish breakout = upward breach |

---

## Approach #10: TA Quality Benchmark (7-Dimension LLM Judge)

Source: `taste/approach_10_ta_benchmark/ta_benchmark.py`

Evaluates TA output quality on a 7-dimension rubric. Each dimension scored 0-10.

### 7 Rubric Dimensions

| # | Dimension | Weight | 10 (Best) | 6 (Adequate) | 2 (Poor) | 0 (Missing) |
|---|-----------|--------|-----------|--------------|----------|-------------|
| 1 | **S/R Quality** | 20% | Meaningful pivots, proper spacing, multi-timeframe | Reasonable but may miss key pivots | Few/wrong levels, supports above price | No S/R analysis |
| 2 | **Entry/Exit Clarity** | 20% | Clear entries, stop-loss, R:R ratio, position sizing | Mentioned but lacks specificity | Only direction, no levels | No entry/exit guidance |
| 3 | **Indicator Interpretation** | 15% | Contextual (divergences, multi-TF RSI, histogram expansion rate) | Correct labels with basic context | Just labels without context | No indicator analysis |
| 4 | **Signal Synthesis** | 15% | All indicators synthesized, conflicts explicitly reconciled, weighting logic clear | Composite present, doesn't address conflicts | Individual results listed, not synthesized | No synthesis |
| 5 | **Risk Management** | 15% | Multiple stop methods (swing/ATR/%), position sizing, trailing stops, Fidenza rules | Single stop-loss method with risk % | Stop mentioned, no specific level | No risk management |
| 6 | **Pattern Detection** | 5% | Patterns with targets, confirmation criteria, and failure conditions | Patterns identified with targets | Generic labels only | No pattern detection |
| 7 | **Professional Presentation** | 10% | Well-organized, correct terminology, follow-ups, suitable for professional trader | Good organization, proper terminology | Basic but missing structure | Unparseable output |

**Weighted score** = sum(score_i x weight_i). Tiers: Excellent (>=8), Good (>=6), Acceptable (>=4), Poor (<4).

---

## Command-to-Approach Mapping

Which checks to run for each `/fin` command:

| Command Type | Approaches to Check |
|---|---|
| `/fin scan`, `/fin macro`, `/fin synthesize` | #2 (all 11 rules), #3 (labels), #5 (signal definitions), #6 (cross-tool, flags) |
| `/fin stress` | #3 (stress_score label), #6 (S-01 composite decomposition, range) |
| `/fin bonds` | #3 (credit labels), #6 (A-01/A-02/A-07 arithmetic, I-01 breakeven) |
| `/fin drivers` | #3 (ERP, real yield), #6 (X-01 to X-04 cross-tool) |
| `/fin consumer`, `/fin housing`, `/fin labor` | #2 (C-04, C-08), #3 (consumer_health label), #6 (I-05, I-07) |
| `/fin latecycle` | #2 (C-03), #3 (late_cycle_count label), #6 (S-03 count) |
| `/fin vixanalysis` | #2 (C-05), #3 (VIX label) |
| `/fin ta ASSET` | #7 (TC-01 to TC-15), #8 (TA-01 to TA-25), #9 (TG-01 to TG-12), #10 (7 dims) |
| `/fin btc` | #9 (TA grounding), #7 (TC-13 to TC-15 stop coherence) |
| `/fin analyze TICKER` | #6 (arithmetic, data staleness) |
| `/fin commodity ASSET` | #3 (labels), #6 (plausibility) |
| `/fin sl ASSET PRICE DIR` | #7 (TC-13 to TC-15), #8 (TA-24 to TA-25) |
| `/fin full_report` | ALL approaches — comprehensive check |

---

## Known False Positives

Don't flag these as issues:

1. **"Accommodative" in bond summary** — Describes Fed policy stance, not credit conditions. Approach #3 may incorrectly flag as credit label.
2. **GLD vs gold futures price divergence** — ETF discount due to session timing and ETF mechanics. Not a data error.
3. **Regime-aware vs static threshold labels** — When tool uses percentile (e.g., HY OAS "stressed" at 82nd pctile) and static dict says "wide" (300-500 bps), both correct. Present both.
4. **Leading vs lagging indicator divergence** — Bank equity stress (leading) can coexist with healthy consumer credit (lagging). Explicitly label time dimension.
5. **TA-01 to TA-03 RSI mismatches (±1-2 points)** — Wilder's RSI is initialization-dependent on lookback period. Tool uses 252-504 bars vs verifier's 250. Not a bug.

---

## Narrative Quality Rules

### Conflict Reconciliation (Approach #10, Signal Synthesis dimension)
When composite signal disagrees with key individual indicators:
> "Composite reads BULLISH (6/8 indicators) but RSI at 72.3 is overbought and volume is declining (ratio 0.46). The bullish count reflects structural strength (golden cross, above all MAs) while the overbought/volume signals warn of near-term exhaustion. Weight: structural trumps momentum for swing trades, but day traders should wait for RSI mean-reversion."

### Data Provenance (Approach #4, Traceability dimension)
For key claims:
> "HY OAS at 320 bps (FRED: BAMLH0A0HYM2, 82nd percentile 1Y)"
> "Gold at $4,574.90 (local: gold_ohlcv.csv, z-score -2.59)"

### Risk-to-Thesis (Approach #4, Completeness dimension)
Every directional call:
> "**Risk to thesis:** If [trigger event], [asset] could reach [level]. Probability: [low/medium/high]. Hedge: [instrument/action]."

### Executive Summary (Approach #4, Professional Quality dimension)
Lead every analysis with a 3-line summary:
> **[ASSET] at $[PRICE] — [BUY/SELL/HOLD/WAIT]**
> [One sentence on why]
> [Key level to watch]

---

## Evaluation Records Format

After significant analyses (multi-tool or `/full_report`), log to `taste_evaluation_report.md`:

```markdown
### Record: YYYY-MM-DD — [Session Description]
**Prompts**: [Prompt 1 summary] | [Prompt 2 summary] | ...
**Commands Run**: [list of /fin subcommands used]
**Scores**:
| Approach | Score | Issues |
|----------|-------|--------|
| #2 Coherence | X/Y (Z%) | [rule failures] |
| #3 Grounding | X/Y (Z%) | [label mismatches] |
| #4 Benchmark | X.X/10 | [weakest dimensions] |
| #5 Backtesting | N signals captured | [signal list] |
| #6 Accuracy | X/Y (Z%) | [math errors] |
| #7 TA Coherence | X/Y (Z%) | [TA issues] |
| #8 TA Accuracy | X/Y (Z%) | [computation mismatches] |
| #9 TA Grounding | X/Y (Z%) | [label issues] |
| #10 TA Quality | X.X/10 | [weakest dimensions] |

**Issues Found**:
1. [Issue description] — Severity: [critical/high/medium] — Approach: [#N]

**Improvements Needed**:
1. [Specific improvement] — Priority: [P1-P6]

**Status**: [open / partially-addressed / resolved]
```
