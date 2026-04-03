# Technical Analysis Guide

## Murphy 13-Framework Analysis

### Supported Asset Types
- **BTC**: Full OHLCV with multi-timeframe (5min→30min/1H/4H/1D)
- **Commodities**: Close-only with synthesized OHLC (gold, silver, crude_oil, copper)
- **Indices**: Close-only with synthesized OHLC (es_futures, rty_futures, dxy)
- **Stocks/ETFs**: Any ticker via yfinance on-demand OHLCV (AAPL, NVDA, QQQ, etc.) with 30-min TTL cache

### The 13 Core Frameworks
1. **Trend**: Higher highs + higher lows = uptrend; lower highs + lower lows = downtrend
2. **Support/Resistance**: Key price levels from historical pivots. Supports < current price, resistances > current price. Synthetic round-number levels generated when no relevant historical levels exist.
3. **Volume**: Volume confirms trend. Rising volume + rising price = strong. Falling volume + rising price = weak.
4. **Moving Averages**: SMA 50/200. Golden cross (50>200) = bullish. Death cross (50<200) = bearish. EMA 9/21/50 for short-term.
5. **MACD**: Signal line crossovers, histogram momentum, zero-line position.
6. **RSI**: <30 oversold, 30-70 normal, >70 overbought. Multi-period (7/14/21 + custom). Zone classification. Divergence detection.
7. **Bollinger Bands**: %B <0 near lower (oversold), >1 near upper (overbought). Band width compression precedes explosive moves.
8. **Fibonacci**: 38.2% = shallow pullback, 50% = normal, 61.8% = aggressive pullback.
9. **Stochastic**: Fast/slow crossovers, overbought/oversold zones.
10. **Pattern Recognition**: Double tops/bottoms, triangles, continuation/reversal.
11. **Intermarket**: 4-market model (stocks, bonds, commodities, currencies).
12. **Relative Strength**: Ratio analysis between related assets.
13. **Dow Theory**: Primary/secondary/minor trends, confirmation between averages.

Note: Frameworks 11-13 (intermarket, relative strength, Dow Theory) are separate tools from the main 10 in `murphy_full_analysis`.

### Weighted Composite Signal
All frameworks contribute to BULLISH/BEARISH/NEUTRAL assessment.
Confidence levels: HIGH (strong consensus), MODERATE (majority agree), LOW (mixed signals), WEAK (conflicting).

### Error Handling (v2.7.6)
Each framework wrapped in try-except. Failed frameworks return `{"available": false, "error": "..."}` instead of crashing.

## Standalone TA Tools

### RSI Calculator (`calculate_rsi`)
- Multi-period: default runs 7/14/21 + any custom period
- Zone classification: oversold, normal, overbought
- Divergence detection: price vs RSI direction
- Actionable signal with follow-up suggestions
- Parameters: `asset`, `period` (default 14), `timeframe` (default "1D"), `extra_periods`

### Support/Resistance Finder (`find_support_resistance`)
- Key levels from historical pivots
- Proximity analysis: how close is current price to each level
- Position assessment: AT_SUPPORT, AT_RESISTANCE, BETWEEN_LEVELS, etc.
- Nearest actionable levels (closest support below, closest resistance above)
- MA trend context (50/200 SMA positions)
- Follow-up suggestions

### Breakout Analysis (`analyze_breakout`)
- Breakout detection through S/R levels
- Confirmation signals:
  - Stocks/ETFs: volume surge, Bollinger expansion, RSI room, MA alignment (scored on 4)
  - Close-only assets: Bollinger expansion, RSI room, MA alignment (scored on 3)
- Confidence: HIGH (all confirm), MODERATE (most), LOW (some), WEAK (few)
- Retest detection: price pulled back to broken level
- False breakout warnings: breakout failed or reversed
- Stop-loss integration suggestions

### Quick TA Snapshot (`quick_ta_snapshot`)
- Combines RSI + S/R + Breakout in one call
- Actionable summary with position assessment
- Good for fast triage before deeper analysis

### Fundamental + TA Synthesis (`fundamental_ta_synthesis`)
- Combines equity valuation data with technical signals
- Alignment assessment:
  - ALIGNED_BULLISH: both fundamental and technical bullish
  - ALIGNED_BEARISH: both bearish
  - DIVERGENT: fundamental and technical disagree
  - NEUTRAL: no strong signal either way
- Conviction level based on alignment strength

## Pro Trader Stop-Loss Framework

### Three Stop Methods
1. **Swing-based**: Below recent swing low (long) or above swing high (short)
2. **ATR-based**: Entry ± ATR × multiplier (1.5-2.5 typical)
3. **Percent-based**: Fixed percentage from entry

### Asset-Class Stop Profiles
| Asset | Typical Stop Width |
|-------|-------------------|
| FX pairs | 50-100 pips |
| Gold | 30-160 points |
| Silver | 3-5 points (half-size) |
| Copper | 10-30 cents |
| Oil | $1.50-3.50 |
| BTC | $3,000-8,000 (wide) |
| ES (S&P futures) | 30-60 points |
| Rates | 5-10 bps (tight) |
| ETFs/stocks | 5-10% |

### Position Sizing
- Risk 0.75-2.0% of capital per trade
- Tighter stop = larger position (inverse relationship)

### Trailing Stop Rules
- 1:1 trailing after 1R profit (move stop to breakeven when profit equals initial risk)
- Size relative to volatility regime (higher vol = smaller size, wider stops)

### 10-Rule Fidenza Risk Framework
Institutional risk management principles embedded in the stop-loss output.

## Pro Trader Frameworks

### Risk Premium Analysis
- VIX > 30 falling: stored buying energy (accumulation)
- VIX < 16: complacency (distribution)
- Volatility compression (BB width falling): precedes explosive moves
- Opportunity score 0-10

### Cross-Asset Momentum
- BTC/SPX, gold/SPX, BTC/gold, silver/gold relative strength
- 20-day rolling correlations
- Divergence detection and momentum failures
- BTC underperformance leads broader risk decline

### Precious Metals Regime
- Structural bid: decoupled from dollar/yields (central bank buying)
- Macro-driven: normal inverse correlations with dollar/yields
- Risk-asset mode: liquidation during equity rallies
- Parabolic advance detection via RoC acceleration
- Correction risk score 0-10
- China seasonal calendar

### USD Structural Regime
- DXY SMA 50/200 + death cross detection
- 30Y yield 5% ceiling analysis
- MOVE index (bond volatility)
- "American exodus" basket: gold up + DXY down + 30Y yields up
- Classifications: exodus, structural_bear, weakening, neutral, recovering, structural_bull, cyclical_strength
- "recovering" = price above both SMAs but death cross still true (SMAs haven't crossed back)

## Stock TA Cache
- yfinance data cached with 30-minute TTL
- Clear with `clear_stock_ta_cache()` for fresh data
- Cache stored in `_STOCK_OHLCV_CACHE` dict in murphy_ta.py
