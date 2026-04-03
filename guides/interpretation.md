# Interpretation Guide — Financial Data

This is the canonical reference for interpreting all financial data produced by the agent's tools. When generating analysis, follow these rules and thresholds exactly. Do not invent thresholds or override these with general knowledge.

---

## Data Sourcing Priority

**Always use local data first. Internet research is a last resort.**

1. **Run the appropriate tool** (`python tools/run.py <command>`) — tools read local `/macro_2` CSVs automatically
2. **Read local CSVs directly** if a tool doesn't cover the specific data point — 120+ CSVs in `/macro_2/historical_data/`
3. **FRED API fallback** — only for series with no local CSV (weekly EIA inventories: WCESTUS1, WGTSTUS1, WDISTUS1)
4. **yfinance** — only for ETF prices and stock TA not covered by local CSVs
5. **Web search** — ONLY for qualitative context (news, Fed commentary, analyst opinions, geopolitical events) that cannot be answered from data

**Do NOT use web search when:** the user asks about macro regime, yields, credit spreads, equity valuations, commodity prices, BTC positioning, inflation, employment, housing, consumer health, or any quantitative question. The answer is in the local data — run the tool.

---

## Macro Indicator Interpretation

### Anomaly Detection Thresholds
- z-score > 2.0 = flagged as anomaly
- Daily moves > 3% = flagged as anomaly
- Proximity to 52-week extremes = flagged

### Comparison Dimensions
Always report changes across three timeframes:
- Daily changes
- Week-over-week (WoW) changes
- Month-over-month (MoM) changes

### 27+ Indicators Tracked

Group by category when presenting:

**Volatility:** VIX, MOVE Index, CBOE SKEW, VIX/MOVE ratio

**Currency:** DXY, USD/JPY

**Rates:** 10Y Treasury yield, 2Y Treasury yield, SOFR, Japan 2Y, US-JP spread

**Commodities:** Gold, Silver, Crude Oil, Copper + CFTC COT positioning

**Equity Indices:** ES Futures, RTY Futures, Russell 2000, S&P 500/200MA ratio

**Valuation:** Shiller CAPE, S&P 500 P/E, P/B, Market Cap/GDP (Buffett Indicator)

**Liquidity:** Fed Net Liquidity, TGA Balance

**Economic:** GDP, ISM PMI

---

## Equity Analysis Interpretation

### Data Sources & Smart Source Selection (v2.7.9)
- Three sources: SEC EDGAR (53 columns, ~503 tickers), Yahoo Finance (~504 tickers), Legacy (20 tickers, 11 columns)
- Sort by financial quarter end date, NOT scrape timestamp
- Negative share counts are discarded (set to None)
- Emit `data_warning` if the latest quarter is more than 2 years old

### Key Metrics

**Quarterly financials:** revenue, gross profit, EBITDA, operating income, net income, EPS

**Margins:** gross, operating, net, EBITDA, R&D%, SBC%

**Cash flow:** OCF, FCF, capex-to-OCF, FCF margin

**OCF/NI interpretation (three tiers):**
- Strong: >= 0.8
- Adequate: >= 0.5
- Weak: < 0.5

**Balance sheet:** current ratio, debt-to-equity, total/net debt, leverage

**Returns:** ROE, ROIC, ROA (quarterly + annualized)

**Capital allocation:** buybacks, dividends, SBC dilution

**Peer comparison:** automatic GICS sector/industry matching with medians

**Balance sheet efficiency:** DSO, DPO, inventory turnover, cash conversion cycle (CCC)

**Margin trends:** multi-quarter direction detection

---

## Financial Stress Score (0-10 Composite)

### 8 Components (weighted average)
1. NFCI (Chicago Fed National Financial Conditions Index)
2. HY OAS (High Yield option-adjusted spread)
3. VIX
4. 2s10s spread (yield curve)
5. Initial claims (employment)
6. Sahm Rule (unemployment rate acceleration)
7. Consumer sentiment (UMich)
8. Consumer credit stress

### Scoring Rules
- Each component scores 0-10 independently; higher = more stress
- Breadth floor rule: when >= 3 of 8 components score >= 5, the composite floors at 4.0 ("elevated"). Broad-based stress must not be masked by weighted averaging.
- Report `weighted_average`, `breadth_floor_applied`, and `scoring_method` in output.

### Composite Thresholds
| Range | Classification |
|-------|---------------|
| 0-2   | Low           |
| 2-4   | Moderate      |
| 4-6   | Elevated      |
| 6-8   | High          |
| 8-10  | Critical      |

### Regime-Aware HY OAS Classification
- Uses 1-year percentile rank with absolute guardrails
- 600 bps = severe stress (regardless of percentile)
- 800 bps = crisis (regardless of percentile)
- Auto-calibrates as the rate environment changes
- Always use `classify_hy_oas()` — never hardcode HY OAS thresholds

---

## Late-Cycle Detection (13 Signals)

### Signal Count Interpretation
| Count | Phase            |
|-------|-----------------|
| 0-2   | Early/mid cycle  |
| 3-4   | Transitioning    |
| 5-6   | Late cycle       |
| 7-8   | Pre-recessionary  |
| 8+    | Severe           |

### The 13 Signals
1. ISM < 50
2. New orders declining
3. NFP deceleration
4. Rising initial claims
5. Credit spreads widening
6. Term premium rising
7. Quits rate declining
8. Yield curve inversion
9. Labor share near record lows
10. Manufacturing recession (DGORDER / AWHMAN / OPHNFB / ULCNFB — labor hoarding detection)
11. ISM employment breadth weakness
12. Housing permits declining 3+ months
13. Delinquency rates rising

---

## VIX 7-Tier Framework

| Tier | VIX Range | Label         | Interpretation                                    |
|------|-----------|---------------|---------------------------------------------------|
| 1    | < 14      | Complacency   | Extreme apathy; precedes sharp moves              |
| 2    | 14-20     | Normal        | Healthy market conditions                         |
| 3    | 20-25     | Elevated      | Moderate stress                                   |
| 4    | 25-30     | Risk-off      | Active selling pressure                           |
| 5    | 30-40     | Opportunity   | Vol-control funds forced to buy; opportunity zone  |
| 6    | 40-50     | Career P&L    | Extreme dislocation                               |
| 7    | 50+       | Home run      | Panic, forced liquidation                         |

**UnderVIX detection:** VIX appears low (tier 1-2) but credit spreads widening or curve stress present. This signals complacency masking underlying risk. Flag explicitly when detected.

---

## Term Premium Interpretation

Proxy calculation: 10Y nominal yield - 10Y real yield (TIPS) - 10Y breakeven inflation

| Condition                          | Signal                              |
|------------------------------------|-------------------------------------|
| Positive + breakevens rising       | Reflation signal                    |
| Negative                           | Flight to safety                    |
| Rising                             | Investors demand duration compensation |
| Falling                            | Safety bid for long bonds           |

---

## Consumer Health (0-10 health score)

The score is inverted from the underlying stress calculation: `health = 10 - stress`. Report both `weighted_stress_average` and final `consumer_health_score`.

### Component Warning Levels
- Savings rate < 3%: consumers running out of buffer
- Credit growth > 10% YoY: overleveraging risk
- Delinquencies > 2.5%: credit quality deteriorating
- Banks tightening > 10% (Senior Loan Officer survey): restricting credit access

### Health Score Thresholds
| Score  | Classification |
|--------|---------------|
| > 7    | Healthy       |
| 5-7    | Stable        |
| 3-5    | Stressed      |
| < 3    | Critical      |

---

## Housing Market

Housing is a leading economic indicator by 4-6 quarters.

### Key Rules
- Permits declining 3+ consecutive months: confirmed leading recession signal
- 2-of-3 trigger (starts + permits + sales declining): classify as downturn
- Cycle phases: boom, cooling, contraction, recovery

### Downstream Cycle Phase Overrides
- "mixed" becomes "declining" when >= 2 distress signals present
- "declining" becomes "distressed" when >= 3 distress signals present

---

## Productivity & Stagflation

**CRITICAL:** Stagflation requires ALL THREE conditions simultaneously:
1. Unit labor costs (ULC) outpacing output per hour (productivity)
2. Core inflation elevated (> 3%)
3. Growth slowing (ISM declining)

A negative ULC-productivity gap alone is NOT sufficient to classify as stagflation. Do not use the term unless all three conditions are met.

---

## Commodity Analysis (10-Step Workflow)

Execute in this order:
1. Pull price data and compute technicals
2. Check COT positioning (CFTC data)
3. Check inventories (crude oil via FRED/EIA)
4. Check WTI-Brent spread (crude oil only)
5. Cross-commodity correlations (DXY inverse, yield correlations)
6. Seasonal patterns
7. Support/resistance levels
8. Web search for news and catalysts
9. Suggest Twitter searches (AFTER completing analysis, with user approval)
10. Synthesize with upside/downside scenarios

---

## Macro-to-Market Signal Table

| Signal                        | Interpretation                                      |
|-------------------------------|-----------------------------------------------------|
| ERP < 2%                      | Market expensive relative to bonds                  |
| Rising TIPS yields            | Headwind for growth/tech equities                   |
| HY OAS > 500 bps             | Risk-off regime, credit tightening                  |
| 2s10s or 3m10s inverted       | Recession warning (historically leads by 12-18 mo)  |
| Hot CPI print                 | Value/energy rotation favored                       |
| Cooling CPI print             | Growth/tech rotation favored                        |
| DXY rising WoW               | Interpret as dollar strengthening (incorporate direction, not just level) |

---

## Bitcoin Interpretation

### Open Interest + Price Combos
| OI       | Price    | Signal                                |
|----------|----------|---------------------------------------|
| Rising   | Rising   | Strong trend confirmation             |
| Rising   | Falling  | Short buildup (bearish)               |
| Falling  | Rising   | Short squeeze / weak rally            |
| Falling  | Falling  | Long capitulation                     |

### Funding Rate
- Funding > 0.05%: crowded longs — contrarian bearish signal
- Funding < -0.02%: crowded shorts — contrarian bullish signal

### L/S Ratio
- Z-score > 2 on long/short ratio: expect mean reversion

### Macro Context
BTC functions as a global liquidity barometer. BTC underperformance often leads broader risk asset decline.

---

## Yardeni Frameworks

**Boom-Bust Barometer:** copper price / initial claims ratio. Peaks at the end of boom phases. Declining ratio = economic deceleration.

**FSMI (Financial Stress Market Indicator):** average z-score of CRB industrials + consumer sentiment. Divergence from S&P 500 = correction signal.

**Bond Vigilantes Model:** 10Y yield vs nominal GDP growth. When yield > GDP growth = markets demanding fiscal discipline.

**Rule of 20:** P/E + CPI YoY = 20 is fair value. Above 20 = overvalued, below = undervalued.

**Rule of 24:** P/E + Misery Index average = 23.9 historical midpoint.

**Drawdown Classification:**
| Drawdown  | Type          | Key Distinction                                     |
|-----------|---------------|-----------------------------------------------------|
| < 10%     | Panic attack  | Brief, sharp, recovers quickly                      |
| 10-20%    | Correction    | Healthy in bull markets                             |
| > 20%     | Bear market   | Sustained, fundamental deterioration                |

Forward EPS rising during a drawdown = correction, not bear market.

---

## Graham Value Investing

**Graham Number:** sqrt(22.5 * EPS * BVPS)

**Margin of Safety:** (Graham Number - Price) / Price
- Negative MoS = stock is overvalued relative to Graham Number
- Use Price as denominator, not Graham Number

**7 Defensive Investor Criteria:**
1. Adequate size (revenue)
2. Strong financial condition (current ratio > 2, debt < net current assets)
3. Earnings stability (positive EPS every year for 10 years)
4. Dividend record (uninterrupted for 20 years)
5. Earnings growth (minimum 33% over 10 years)
6. Moderate P/E (< 15x trailing)
7. Moderate P/E * P/B (< 22.5)

**Graham Score:** X / 7 (count of criteria met)

**Net-Net:** Price < 2/3 * NCAV (net current asset value). Very few large caps qualify.

---

## Murphy Technical Analysis

### Trend Rules
- Higher highs + higher lows = uptrend
- Lower highs + lower lows = downtrend
- Golden cross (50 SMA > 200 SMA) = bullish
- Death cross (50 SMA < 200 SMA) = bearish

### Support/Resistance
- Supports must be below current price, resistances above
- Generate synthetic round-number levels when no relevant historical levels exist

### Oscillators
- RSI: < 30 oversold, > 70 overbought
- Bollinger %B: < 0 near lower band (oversold), > 1 near upper band (overbought)
- Bollinger Band width compression precedes explosive moves

### Fibonacci Retracements
- 38.2% = shallow pullback (strong trend)
- 50.0% = moderate pullback
- 61.8% = aggressive pullback (trend weakening)

### Composite Signal
Weighted composite across 13 frameworks produces: BULLISH / BEARISH / NEUTRAL with confidence level.

---

## Pro Macro Playbook (Qualitative Rules)

These are pattern-based rules derived from institutional macro trader behavior. Apply when relevant:

- **Regime transitions:** Watch for disinflation-to-reflation shifts. When yields rally and dollar strengthens simultaneously, a regime change is underway.
- **Tariffs:** Do not buy the first dip on tariff announcements. Wait for the retaliation-to-retaliation cycle to play out.
- **Oil gaps:** Oil gaps close within days. Check floating storage data for confirmation.
- **Headline vs breadth:** CPI headline "soft" but broad-based increases underneath = opposite market reaction from headline suggests.
- **Fed speakers:** A hawk turning dovish is far more significant than a dove staying dovish.
- **TGA refill:** Treasury General Account refill = liquidity drain + USD tailwind.
- **4H RSI rule:** Do not buy when 4-hour RSI is overbought. Do not chase extended Monday moves.
- **Vol compression:** Volatility compression (Bollinger Band squeeze) precedes explosive directional moves.
- **Contrarian positioning:** Bearish positioning extreme + price refuses to decline = contrarian long setup.
- **Price-insensitive demand:** Asset rallying against adverse macro = market-specific driver present, worth investigating as a trade.
- **Silver vulnerability:** Silver = speculative short-dollar + long-risk play. More vulnerable to hawkish Fed surprises than gold.

---

## Pro Trader Stop-Loss Framework

### Three Stop Methods
1. **Swing-based:** Below recent swing low (longs) or above recent swing high (shorts)
2. **ATR-based:** Entry +/- ATR multiplier
3. **Percent-based:** Fixed percentage from entry

### Position Sizing
- Risk 0.75% to 2.0% of total capital per trade
- Never exceed 2% risk on a single position

### Trailing Stop Rules
- Move stop to breakeven after 1R profit
- Trail 1:1 after that (for every 1R of additional profit, trail stop by 1R)

### Asset Class Profiles
| Asset    | Typical Stop Width      |
|----------|------------------------|
| FX       | 50-100 pips            |
| Gold     | 30-160 points          |
| Silver   | 3-5 points (half size) |
| Copper   | 10-30 cents            |
| Oil      | $1.50-$3.50            |
| BTC      | $3,000-$8,000 (wide)   |
| ES       | 30-60 points           |
| Rates    | 5-10 basis points (tight) |
| ETFs     | 5-10%                  |

When swing or ATR data is unavailable, emit a `warnings` list noting the missing inputs and guiding the user to supply them.

---

## USD Structural Regime

### Classification Rules
| Condition | Classification |
|-----------|---------------|
| DXY < both 50 and 200 SMA with death cross | Structural bear |
| Price above both SMAs but death cross still true (SMAs haven't crossed back) | Recovering |
| DXY > both 50 and 200 SMA with golden cross | Structural bull |
| Mixed signals | Neutral or weakening |

### American Exodus Basket
Simultaneous: long gold + short USD + short treasuries (gold up, DXY down, 30Y yields up)

This pattern works when three conditions converge:
1. Fiscal indiscipline
2. Geopolitical trust loss
3. US asset overvaluation

### Regime Labels
exodus, structural_bear, weakening, neutral, recovering, structural_bull

### Key Levels
- 30Y yield near 5% ceiling: bond shorts get squeezed
- MOVE Index elevated: bond market volatility reduces positioning confidence

---

## Precious Metals Regime

| Regime          | Characteristics                                      |
|-----------------|------------------------------------------------------|
| Structural bid  | Gold decoupled from dollar/yields (central bank buying driving) |
| Macro-driven    | Normal inverse correlations with DXY and real yields intact |
| Risk-asset mode | Gold selling off during equity rallies (liquidation behavior) |

### Silver
Silver's speculative beta makes it more vulnerable to hawkish Fed surprises than gold. Silver outperformance signals risk-on sentiment; underperformance signals caution.

### Parabolic Advance Detection
Rate-of-change acceleration in gold/silver = correction risk rising. Report correction risk score (0-10).

---

## Output Style Rules

When generating analysis output, follow these rules:

1. Write like a morning briefing for a portfolio manager
2. Be concise and data-driven — no filler language
3. Cite specific data points: values, percentages, z-scores, dates
4. Highlight cross-asset signals and contradictions explicitly
5. Differentiate noise from signal — flag which moves are statistically significant
6. Provide progress updates at each step of multi-step analysis
7. When tools disagree (e.g., credit vs equity signals), call out the contradiction and state which signal typically leads
8. Always include actionable implications: what does this mean for positioning?
