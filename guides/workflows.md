# Workflow Orchestration Guide

## Full Report (8-Analysis Chain)
The `/full_report` command runs these in sequence:
1. `scan_all_indicators("short")` → identify macro flags + follow-up triggers
2. `analyze_macro_regime()` → classify 6-dimension environment (inflation/employment/growth/rates/credit/housing with ISM decomposition, labor breadth, housing data)
3. `analyze_financial_stress()` → composite stress score (0-10)
4. `detect_late_cycle_signals()` → 13-signal framework
5. `analyze_equity_drivers()` → ERP, real yields, credit-equity, DXY, VIX
6. `analyze_bond_market()` → yield curve, credit spreads, real yields, term premium
7. `analyze_consumer_health()` → savings, credit, delinquencies, lending
8. `analyze_housing_market()` → starts, permits, sales, affordability, Case-Shiller

Synthesize into: Executive Summary, Macro Regime, Risk Dashboard, Equity Outlook, Fixed Income Outlook, Consumer & Housing, Key Levels & Thresholds, Actionable Recommendations

## Macro Synthesis (synthesize_macro_view)
Automated multi-analysis orchestration:
- Runs macro regime + equity drivers + bond market + financial stress + late-cycle + consumer health
- Produces: contradiction detection (5 cross-tool checks), historical analogue matching (5 reference periods), cause-effect reasoning chains, actionable recommendations with conviction scoring

The 5 contradiction checks:
1. Credit-equity: credit spreads say risk-off but equities rising?
2. Consumer-regime: consumer health stable but macro recessionary?
3. VIX-credit: VIX calm but credit stressed?
4. Late-cycle-growth: late-cycle signals but growth indicators strong?
5. Bonds-equity: bond market pricing recession but equity market not?

## Standard Comprehensive Workflow (7 Steps)
1. Progress updates → Always tell user what you're doing
2. Macro sweep → `scan_all_indicators` + analyze flags
3. Deep dives → `analyze_indicator_changes` for flagged indicators
4. Commodity dives → `analyze_commodity_outlook` for full supply/demand + technical + positioning
5. Equity review → Analyze specific companies or run comparisons
6. Web verification → Search for supporting context on key findings
7. Synthesis → Produce structured report with all sections

## Commodity Analysis (10-Step Workflow)
1. Pull price data → compute technicals (daily/WoW/MoM, z-scores)
2. Check COT positioning for crowding signals (if available)
3. Check inventory data for supply/demand (crude via FRED/EIA)
4. Check WTI-Brent spread for market structure (crude only)
5. Check cross-commodity correlations (DXY inverse, yield correlation)
6. Seasonal patterns from historical data
7. Support/resistance from recent price action
8. Web search for news/catalysts (OPEC, sanctions, weather)
9. Suggest Twitter searches (AFTER analysis, with user approval)
10. Synthesize with upside/downside scenarios and key levels

## Equity Analysis Workflow
1. `analyze_company(ticker)` → valuation, margins, growth, returns, cash flow
2. `peer_comparison(ticker)` → GICS sector matching with medians
3. `analyze_capital_allocation(ticker)` → buybacks, dividends, SBC
4. `analyze_balance_sheet(ticker)` → DSO, DPO, CCC, efficiency
5. Optional: `fundamental_ta_synthesis(ticker)` → combine valuation with technicals
6. Web search for recent earnings, guidance, catalysts

## Twitter Search Workflow (Human-in-the-Loop)
CRITICAL: ALL Twitter API calls require explicit user approval.
1. Complete ALL analysis FIRST (macro, equity, commodity)
2. Identify key themes from analysis
3. Suggest specific searches: "I recommend searching Twitter for: [topics]. Approve?"
4. Only execute AFTER explicit user approval

## BTC Analysis Workflow
1. `btc_trend_analysis()` → multi-timeframe OHLCV, EMA 9/21/50, RSI, trend
2. `btc_positioning_analysis()` → OI, funding rate, L/S ratios, z-scores
3. `btc_full_analysis()` → combines both + trade idea (entry/SL/TP/R:R)

## Technical Analysis Workflow
1. `murphy_full_analysis(asset)` → 13 frameworks with weighted composite
2. For specific needs: `calculate_rsi`, `find_support_resistance`, `analyze_breakout`
3. `quick_ta_snapshot(asset)` → RSI + S/R + breakout in one call
4. `fundamental_ta_synthesis(ticker)` → combines equity valuation with technicals

## Risk Assessment Workflow
1. `analyze_financial_stress()` → 8-component composite
2. `detect_late_cycle_signals()` → 13-signal framework
3. `analyze_risk_premium()` → VIX regime, vanna/charm, CTA proxy
4. `analyze_vix_opportunity()` → 7-tier framework with underVIX detection
5. `analyze_term_premium()` → global rate signals

## Cross-Asset Workflow
1. `analyze_cross_asset_momentum()` → BTC/SPX/gold/silver/DXY relative strength
2. `get_macro_market_correlations()` → rolling correlation matrix
3. `analyze_precious_metals_regime()` → gold/silver classification
4. `analyze_usd_regime()` → DXY structural regime, exodus basket

## Email Digest Workflow
The `/digest` command processes financial newsletters from Gmail to build qualitative market context:
1. `gmail_list_labels()` → resolve label names with special characters (pipes, spaces)
2. 6x `gmail_search_messages()` → one per source (Daily Rip, WSJ PM, Bloomberg/WSJ, Bloomberg/WSJ Markets, Eliant Capital, Macro newsletters), last 2 days default
3. `gmail_read_message()` for each result → get email body
4. Extract themes in agent's own words (copyright compliance — no verbatim reproduction)
5. Read existing `guides/market_context.md` if it exists
6. Write updated context file with rolling 7-day window, pruning older entries
7. Report summary to user (emails processed per source, top 3 themes)

The context file is consumed by all other workflows — read `guides/market_context.md` at session start for qualitative market backdrop before running quantitative tools. Sits at priority #4 in the data hierarchy (after local CSVs, FRED, yfinance; before web/Twitter search).

## Structured Report Format
Always output in this structure:
- Executive Summary (3-7 bullet points)
- Macro Environment (risk assessment, key movers, cross-asset signals)
- Commodity Outlook (if applicable)
- Equity Highlights (if applicable)
- Upside/Downside Scenarios with key levels
- Actionable Insights
- Risk Factors
- Key Levels & Thresholds (specific numbers)
