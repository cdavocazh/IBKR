"""
ES Futures Strategy Configuration — ONLY MUTABLE FILE

Multi-parameter jump: combining top near-miss signals + structural improvements.
Key changes from previous baseline (-5.84% return):
- Faster SMA (50 vs 80) for quicker trend detection
- Confidence-weighted sizing enabled (scale up/down by signal strength)
- Adaptive TP enabled (let winners run via trailing instead of fixed TP)
- Bull defensive mode enabled (short during corrections within bull regime)
- Tighter trailing in bull (lock profits), wider in bear (let shorts run)
- Lower thresholds for all regimes (more entries with better sizing control)
"""

# ─── CAPITAL & RISK ───────────────────────────────────────────
INITIAL_CAPITAL = 100_000
RISK_PER_TRADE = 5_000             # Lower risk = lower DD penalty in scoring
ES_POINT_VALUE = 50

# ─── ENTRY HOURS (GMT+8) ─────────────────────────────────────
ENTRY_UTC_START = 0
ENTRY_UTC_END = 16

# ─── US OPEN AVOIDANCE ───────────────────────────────────────
AVOID_US_OPEN = True
AVOID_US_OPEN_START_H = 14
AVOID_US_OPEN_START_M = 30
AVOID_US_OPEN_END_H = 16
AVOID_US_OPEN_END_M = 0

# ─── INDICATOR PERIODS ────────────────────────────────────────
RSI_PERIOD = 7
RSI_FAST_PERIOD = 3
ATR_PERIOD = 28
SMA_FAST = 30
SMA_SLOW = 30          # CHANGED: 80->50 (faster trend detection)
SMA_200 = 200
BB_PERIOD = 25
BB_STD = 2.2

# ─── DIP/RIP FILTER (regime-specific entry philosophy) ──────
# Bullish: only buy when RSI < DIP threshold (buying the dip)
# Bearish: only sell when RSI > RIP threshold (selling the rip)
# Sideways: mean reversion at BB/RSI extremes (no filter needed)
DIP_RIP_FILTER_ENABLED = False     # Disabled for 40+ trade research mode
DIP_BUY_RSI_THRESHOLD = 40
RIP_SELL_RSI_THRESHOLD = 65

# ─── REGIME CLASSIFICATION ───────────────────────────────────
REGIME_SMA_CROSS_WEIGHT = 0.3
REGIME_PRICE_VS_200_WEIGHT = 0.5  # Near-miss: -0.90
REGIME_VIX_WEIGHT = 0.0           # Near-miss: -0.92 (reduce VIX noise in regime)
REGIME_NLP_WEIGHT = 0.25
REGIME_DIGEST_WEIGHT = 0.05
REGIME_DAILY_TREND_WEIGHT = 0.2   # CHANGED: 0.2->0.25 (more daily weight)

# ─── NLP SENTIMENT & DIGEST INTEGRATION ──────────────────────
NLP_SENTIMENT_BOOST = 0.15
DIGEST_CONTEXT_BOOST = 0.05

# ─── DAILY TREND OVERLAY ─────────────────────────────────────
DAILY_TREND_BOOST = 0.05          # CHANGED: 0.05->0.08
DAILY_COUNTER_TREND_PENALTY = 0.15 # CHANGED: 0.05->0.08

# ─── DAILY RSI / ATR AS ENTRY SIGNALS ────────────────────────
DAILY_RSI_WEIGHT = 0.0
DAILY_RSI_OVERSOLD = 35
DAILY_RSI_OVERBOUGHT = 70
DAILY_ATR_VOL_ADJUST = 0.05

# ─── VOLUME SIGNAL ───────────────────────────────────────────
VOLUME_SIGNAL_WEIGHT = 0.05         # Multi-param jump: near-miss -0.05
VOLUME_AVG_LOOKBACK = 10
VOLUME_SURGE_THRESHOLD = 3.0       # CHANGED: 1.2->3.0 (near-miss +11.01%)
VOLUME_DRY_THRESHOLD = 0.7

# ─── WSJ + DJ-N SENTIMENT SIGNAL ────────────────────────────
SENTIMENT_SIGNAL_WEIGHT = 0.15
BULL_WEIGHT_SENTIMENT = 0.15
BEAR_WEIGHT_SENTIMENT = 0.0        # Near-miss: +11.0%
SIDE_WEIGHT_SENTIMENT = 0.10
SENTIMENT_THRESHOLD_BOOST = 0.05  # Lower threshold when sentiment agrees

# ─── DAILY TREND GATE ────────────────────────────────────────
DAILY_TREND_GATE = False

# ─── SEQUENTIAL DECISION PIPELINE ────────────────────────────
SEQUENTIAL_DECISION_ENABLED = True
SEQ_MACRO_REJECT_THRESHOLD = -0.4
SEQ_VOLUME_GATE_ENABLED = True
SEQ_VOLUME_MIN_RATIO = 0.3
SEQ_MACRO_ADVERSE_SIZE_SCALE = 1.0
SEQ_MACRO_FAVORABLE_SIZE_SCALE = 1.2  # No upscaling initially

# ─── ADAPTIVE STOP-LOSS (macro + TA scaled) ─────────────────
ADAPTIVE_STOP_LOW_VOL_SCALE = 1.0
ADAPTIVE_STOP_HIGH_VOL_SCALE = 1.5
ADAPTIVE_STOP_VIX_RISKOFF_SCALE = 1.3
ADAPTIVE_STOP_VIX_PANIC_SCALE = 1.8
ADAPTIVE_STOP_VIX_LOW_SCALE = 0.8
ADAPTIVE_STOP_CREDIT_STRESS_SCALE = 1.2
ADAPTIVE_STOP_DXY_STRONG_SCALE = 0.7

# ─── ADAPTIVE TAKE-PROFIT (macro + TA scaled) ───────────────
ADAPTIVE_TP_TREND_ALIGNED_SCALE = 1.8
ADAPTIVE_TP_COUNTER_TREND_SCALE = 1.0
ADAPTIVE_TP_RSI_EXTENDED_SCALE = 0.9
ADAPTIVE_TP_RSI_REVERSAL_SCALE = 1.3
ADAPTIVE_TP_VIX_HIGH_SCALE = 1.3  # CHANGED: 2.0->1.3 (less extreme TP widening)
ADAPTIVE_TP_VIX_ELEVATED_SCALE = 1.3
ADAPTIVE_TP_VOLUME_SURGE_SCALE = 1.0

# ─── IN-TRADE MACRO ADJUSTMENTS ─────────────────────────────
INTRADE_VIX_SPIKE_THRESHOLD = 3.0
INTRADE_VIX_SPIKE_TIGHTEN = 0.4
INTRADE_CREDIT_STRESS_TIGHTEN = 0.5
INTRADE_TRAILING_VIX_TIGHTEN = 0.5
INTRADE_RSI_EXTREME_TIGHTEN_ATR = 0.3

# ─── CONFIDENCE-WEIGHTED POSITION SIZING ─────────────────────
CONFIDENCE_SIZING_ENABLED = True
CONFIDENCE_HIGH_THRESHOLD = 0.65    # Multi-param jump: near-miss -0.05
CONFIDENCE_HIGH_MULT = 2.5
CONFIDENCE_LOW_MULT = 0.3

# ─── ADAPTIVE TP (momentum-based trailing) ───────────────────
ADAPTIVE_TP_ENABLED = False
ADAPTIVE_TP_FLOOR_ATR = 3.0

# ─── ASYMMETRIC RISK/REWARD FLOOR ────────────────────────────
MIN_RR_RATIO = 1.0                # Allow 1:1 R:R to maximize WR

# ─── ADAPTIVE COOLDOWN (win/loss streak) ─────────────────────
ADAPTIVE_COOLDOWN_ENABLED = True
STREAK_LOOKBACK = 5
COOLDOWN_WIN_STREAK_MULT = 0.5     # 50% cooldown after winning streak
COOLDOWN_LOSS_STREAK_MULT = 2.0    # 200% cooldown after losing streak

# ─── BREAKOUT ENTRY MODE ────────────────────────────────────
BREAKOUT_ENTRY_ENABLED = True
BREAKOUT_LOOKBACK = 48             # 4 hours of 5-min bars
BREAKOUT_VOL_MULT = 2.0            # Require 2x avg volume for breakout

# ─── DAILY LOSS CIRCUIT BREAKER ──────────────────────────────
DAILY_LOSS_CIRCUIT_PCT = -1.0
MAX_CONSECUTIVE_LOSSES = 3          # Pause trading for 1 day after N consecutive losses
CONSECUTIVE_LOSS_COOLDOWN_BARS = 78 # ~6.5 hours (1 trading day of 5-min bars)

# ─── VOLATILITY REGIME POSITION SCALING ──────────────────────
VOL_REGIME_SCALING_ENABLED = False
VOL_EXTREME_THRESHOLD_PCT = 3.0
VOL_EXTREME_SIZE_SCALE = 0.5
VOL_HIGH_THRESHOLD_PCT = 1.5
VOL_HIGH_SIZE_SCALE = 0.5

# ─── MOMENTUM-BASED EXIT ─────────────────────────────────────
MOMENTUM_EXIT_ENABLED = False
MOMENTUM_EXIT_MIN_BARS = 48       # CHANGED: 36->24 (exit sooner on reversal)
MOMENTUM_RSI_EXIT_ENABLED = False   # CHANGED: False->True
MOMENTUM_RSI_EXTREME = 75         # CHANGED: 65->75

# ─── BULLISH REGIME CONFIG (multi-day trend following) ────────
BULL_SIDE = "LONG"
BULL_RSI_OVERSOLD = 30
BULL_RSI_OVERBOUGHT = 80          # CHANGED: 75->70 (take profit on RSI earlier)
BULL_COMPOSITE_THRESHOLD = 0.99
BULL_STOP_ATR_MULT = 3.0            # Multi-param jump: near-miss -0.05
BULL_TP_ATR_MULT = 2.0            # 1:1 R:R — maximize WR
BULL_TRAILING_START_R = 1.5
BULL_TRAILING_ATR_MULT = 0.5
BULL_MAX_HOLD_BARS = 288
BULL_RISK_MULT = 0.4
BULL_WEIGHT_RSI = 0.12             # TuneTA: dcor=0.15, nudge up from 0.10
BULL_WEIGHT_TREND = 0.30           # TuneTA: dcor=0.27, reduce from 0.35
BULL_WEIGHT_MOMENTUM = 0.05        # TuneTA: dcor=0.16, nudge up from 0.10
BULL_WEIGHT_BB = 0.05              # TuneTA: dcor=0.04, confirmed low
BULL_WEIGHT_VIX = 0.10
BULL_WEIGHT_MACRO = 0.05

# ─── BULL DEFENSIVE MODE ─────────────────────────────────────
BULL_DEFENSIVE_ENABLED = True
BULL_DEFENSIVE_RISK_MULT = 0.3
BULL_DEFENSIVE_STOP_ATR = 3.0
BULL_DEFENSIVE_TP_ATR = 3.0
BULL_DEFENSIVE_THRESHOLD = 0.50

# ─── BEARISH REGIME CONFIG ───────────────────────────────────
BEAR_SIDE = "SHORT"
BEAR_RSI_OVERSOLD = 40            # CHANGED: 25->30
BEAR_RSI_OVERBOUGHT = 75
BEAR_COMPOSITE_THRESHOLD = 0.99
BEAR_STOP_ATR_MULT = 1.8
BEAR_TP_ATR_MULT = 2.0
BEAR_TRAILING_START_R = 0.8
BEAR_TRAILING_ATR_MULT = 0.8
BEAR_MAX_HOLD_BARS = 432
BEAR_RISK_MULT = 0.4              # Conservative — crisis short disable handles bear protection
BEAR_WEIGHT_RSI = 0.15             # TuneTA Phase1: dcor=0.12 (reduced from 0.20)
BEAR_WEIGHT_TREND = 0.15          # TuneTA Phase1: dcor=0.29 (increased from 0.10)
BEAR_WEIGHT_MOMENTUM = 0.10       # TuneTA Phase1: dcor=0.18 (increased from 0.05)
BEAR_WEIGHT_BB = 0.10             # TuneTA Phase1: dcor=0.06 (reduced from 0.20 — key DD reduction)
BEAR_WEIGHT_VIX = 0.05
BEAR_WEIGHT_MACRO = 0.2

# ─── SIDEWAYS REGIME CONFIG ──────────────────────────────────
SIDE_SIDE = "BOTH"
SIDE_RSI_OVERSOLD = 20            # CHANGED: 40->35
SIDE_RSI_OVERBOUGHT = 60          # CHANGED: 80->70
SIDE_COMPOSITE_THRESHOLD = 0.99
SIDE_STOP_ATR_MULT = 2.0
SIDE_TP_ATR_MULT = 2.0
SIDE_TRAILING_START_R = 0.5
SIDE_TRAILING_ATR_MULT = 0.5
SIDE_MAX_HOLD_BARS = 72
SIDE_RISK_MULT = 0.5              # Conservative sizing
SIDE_WEIGHT_RSI = 0.15
SIDE_WEIGHT_TREND = 0.15          # TuneTA: dcor=0.17 (increase from 0.10)
SIDE_WEIGHT_MOMENTUM = 0.20       # TuneTA: dcor=0.19 (slight reduce from 0.25)
SIDE_WEIGHT_BB = 0.15             # TuneTA: dcor=0.07 (reduce from 0.25)
SIDE_WEIGHT_VIX = 0.2
SIDE_WEIGHT_MACRO = 0.2

# ─── GLOBAL ENTRY FILTERS ────────────────────────────────────
RSI_FAST_OVERSOLD = 30
RSI_FAST_OVERBOUGHT = 80          # CHANGED: 85->80 (best near-miss)
COOLDOWN_BARS = 96                # High cooldown reduces composite overtrading
MIN_ATR_THRESHOLD = 5.0           # Risk-adj KEEP: 4.0->5.0
MIN_VOLUME_THRESHOLD = 50
MIN_HOLD_BARS = 24
BREAKEVEN_R = 1.5                  # Near-miss: scored -2.9 (was 1.5)
STOP_TIGHTEN_ON_RSI_EXTREME = False # Multi-param jump: near-miss -0.03, PF 2.05
STOP_TIGHTEN_ATR_MULT = 1.2       # CHANGED: 2.0->1.5 (tighter on RSI extreme)

# ─── VIX 7-TIER OPPORTUNITY FRAMEWORK ────────────────────────
# VIX natural state is below 20. Spikes above are temporary.
# VIX > 30: ALWAYS looking at dip-buying setups (mean reversion)
# VIX < 16: No room for charm/vanna compression → no more dealer buying pressure
VIX_TIER_1 = 16.0                 # Complacency: vanna/charm exhausted, short alert
VIX_TIER_2 = 20.0                 # CHANGED: 18->20 (near-miss +10.99%)
VIX_TIER_3 = 28.0                 # Elevated: caution, reduced position
VIX_TIER_4 = 35.0                 # Riskoff: ALMOST ALWAYS buy dips here
VIX_TIER_5 = 40.0                 # Opportunity: strong dip-buy conviction
VIX_TIER_6 = 50.0                 # Career/homerun: max dip-buy aggression

VIX_COMPLACENCY_SHORT_BOOST = 0.05  # VIX<16: charm/vanna exhausted, short bias
VIX_NORMAL_LONG_BOOST = 0.1       # VIX 16-20: normal, slight long support
VIX_ELEVATED_SHORT_BOOST = 0.05    # VIX 20-25: cautious, slight short bias
VIX_RISKOFF_SHORT_BOOST = 0.0      # VIX 25-30: DON'T short — about to buy dips
VIX_OPPORTUNITY_LONG_BOOST = 0.3  # VIX 30-40: dip-buy (but size conservatively)
VIX_CAREER_LONG_BOOST = 0.20       # VIX 40-50: career dip-buy
VIX_HOMERUN_LONG_BOOST = 0.25      # VIX 50+: max conviction dip-buy

# ─── CTA PROXY ───────────────────────────────────────────────
# ES >5% above 200 SMA = fully deployed CTAs, short boost
CTA_FULL_DEPLOY_PCT = 10.0          # >5% above 200 SMA: CTAs fully long → crowded
CTA_DELEVERAGE_PCT = 0.0
CTA_BUY_POTENTIAL_PCT = -7.0       # >5% below 200 SMA: CTAs underweight → buying potential
CTA_FULL_DEPLOY_SHORT_BOOST = 0.05 # Strong short signal when CTAs maxed out
CTA_BUY_POTENTIAL_LONG_BOOST = 0.0 # Long signal when CTAs have room to buy

# ─── CREDIT CONDITIONS (HY OAS) ──────────────────────────────
# HY OAS widening = credit stress → short bias
HY_OAS_NORMAL = 350
HY_OAS_ELEVATED = 450
HY_OAS_STRESSED = 500
HY_OAS_SEVERE = 600
CREDIT_TIGHTENING_LONG_BOOST = 0.0  # Tight credit = risk-on support
CREDIT_WIDENING_SHORT_BOOST = 0.0   # Widening = stress → short bias

# ─── YIELD CURVE ─────────────────────────────────────────────
YIELD_CURVE_INVERTED_SHORT_BOOST = 0.10
YIELD_CURVE_STEEP_LONG_BOOST = 0.05

# ─── DXY ─────────────────────────────────────────────────────
# Strong dollar → negative for ES (capital outflows from risk assets)
DXY_STRONG_THRESHOLD = 110.0
DXY_WEAK_THRESHOLD = 102.0
DXY_STRONG_SHORT_BOOST = 0.15     # Strong DXY → short ES bias
DXY_WEAK_LONG_BOOST = 0.0        # Weak DXY → supportive for ES

# ─── DR. COPPER ──────────────────────────────────────────────
# Copper = growth barometer. Falling copper → short bias
COPPER_MOMENTUM_LOOKBACK = 20
COPPER_RISING_LONG_BOOST = 0.05
COPPER_FALLING_SHORT_BOOST = 0.05 # Multi-param jump: near-miss -0.03

# ─── LIMIT ORDERS ────────────────────────────────────────────
USE_LIMIT_ORDERS = True
LIMIT_OFFSET_ATR = 0.7

# ─── GARCH VOLATILITY FORECAST ─────────────────────────────────
# Forward-looking conditional variance from GARCH(1,1) on daily ES returns.
# Replaces backward-looking ATR regime scaling with predictive vol forecast.
GARCH_ENABLED = True               # Re-enabled: blocks entries during extreme vol

# ─── STRUCTURAL EXPERIMENT FLAGS ─────────────────────────────
# Exp 1: Volatility regime gate (dormant insurance — activates when ATR > 2.5%)
VOL_REGIME_GATE_ENABLED = True
VOL_GATE_REDUCE_ATR_PCT = 1.5
VOL_GATE_HALT_ATR_PCT = 3.0         # ATR% threshold: stop trading entirely
VOL_GATE_REDUCE_SIZE_SCALE = 0.25   # Position size multiplier in high-vol
VOL_GATE_REDUCE_COOLDOWN = 150      # Cooldown bars in high-vol

# Exp 2: Max trades per day
MAX_TRADES_PER_DAY_ENABLED = False
MAX_TRADES_PER_DAY = 2

# Exp 4: Regime-dependent short disabling (dormant insurance — VIX>30 + ATR>2%)
CRISIS_SHORT_DISABLE_ENABLED = True
CRISIS_SHORT_DISABLE_VIX = 24.0     # VIX threshold (lowered: Apr 2026 VIX was ~24)
CRISIS_SHORT_DISABLE_ATR_PCT = 1.5

# Exp 5: High-vol hold reduction (dormant insurance — activates when ATR > 2%)
HIGH_VOL_HOLD_REDUCTION_ENABLED = True
HIGH_VOL_MAX_HOLD_BARS = 24         # Reduced max hold in high-vol (~2 hours)
HIGH_VOL_HOLD_ATR_PCT = 1.5

# Exp 6: Intraday trend filter (ACTIVE — best structural improvement)
INTRADAY_TREND_FILTER_ENABLED = True
INTRADAY_TREND_LOOKBACK = 12        # 1 hour of 5-min bars
INTRADAY_TREND_STRENGTH = 0.3       # Min net directional move as % of ATR

# Exp 7: Dual-mode strategy (dormant insurance — activates when ATR > 2%)
DUAL_MODE_ENABLED = True
CRISIS_MODE_ATR_PCT = 1.5
CRISIS_MODE_ONLY_LONGS = True       # Only take long entries in crisis mode
CRISIS_MODE_RSI_EXTREME = 20        # Only enter on extreme oversold in crisis
CRISIS_MODE_SIZE_SCALE = 0.3        # Very small positions in crisis
# ─── VIX MODEL SWITCHING ─────────────────────────────────────────
VIX_MODEL_SWITCH_ENABLED = False
VIX_MODEL_LOW_THRESHOLD = 20.0      # VIX < this = LOW regime
VIX_MODEL_HIGH_THRESHOLD = 30.0     # VIX > this = HIGH regime

# LOW VIX MODEL (trend-following, tight stops, high confidence)
VLOW_COMPOSITE_THRESHOLD = 0.45
VLOW_STOP_ATR_MULT = 1.5
VLOW_TP_ATR_MULT = 3.0
VLOW_MAX_HOLD_BARS = 432
VLOW_RISK_MULT = 0.5
VLOW_ALLOWED_SIDE = "BOTH"
VLOW_COOLDOWN_BARS = 72
VLOW_WEIGHT_RSI = 0.10
VLOW_WEIGHT_TREND = 0.30
VLOW_WEIGHT_MOMENTUM = 0.15
VLOW_WEIGHT_BB = 0.10
VLOW_WEIGHT_VIX = 0.05
VLOW_WEIGHT_MACRO = 0.05

# MED VIX MODEL (balanced, current approach)
VMED_COMPOSITE_THRESHOLD = 0.35
VMED_STOP_ATR_MULT = 2.0
VMED_TP_ATR_MULT = 2.0
VMED_MAX_HOLD_BARS = 288
VMED_RISK_MULT = 0.4
VMED_ALLOWED_SIDE = "BOTH"
VMED_COOLDOWN_BARS = 96
VMED_WEIGHT_RSI = 0.15
VMED_WEIGHT_TREND = 0.20
VMED_WEIGHT_MOMENTUM = 0.13
VMED_WEIGHT_BB = 0.10
VMED_WEIGHT_VIX = 0.10
VMED_WEIGHT_MACRO = 0.10

# HIGH VIX MODEL (crisis: longs only, wide stops, tiny size)
VHIGH_COMPOSITE_THRESHOLD = 0.55
VHIGH_STOP_ATR_MULT = 3.5
VHIGH_TP_ATR_MULT = 5.0
VHIGH_MAX_HOLD_BARS = 96
VHIGH_RISK_MULT = 0.2
VHIGH_ALLOWED_SIDE = "LONG"
VHIGH_COOLDOWN_BARS = 150
VHIGH_WEIGHT_RSI = 0.25
VHIGH_WEIGHT_TREND = 0.05
VHIGH_WEIGHT_MOMENTUM = 0.05
VHIGH_WEIGHT_BB = 0.15
VHIGH_WEIGHT_VIX = 0.20
VHIGH_WEIGHT_MACRO = 0.15

# ─── ML ENTRY CLASSIFIER ────────────────────────────────────────
ML_ENTRY_SIGNAL_WEIGHT = 0.0       # Start at 0, sweep via autoresearch
ML_ENTRY_CONFIDENCE_GATE = 0.1     # Min ML confidence to use signal

# ─── ADAPTIVE HOLD PERIOD ───────────────────────────────────────
ADAPTIVE_HOLD_ENABLED = False
ADAPTIVE_HOLD_LOW_ATR_PCT = 1.0
ADAPTIVE_HOLD_HIGH_ATR_PCT = 2.0
ADAPTIVE_HOLD_LOW_ATR_MULT = 1.5
ADAPTIVE_HOLD_HIGH_ATR_MULT = 0.3
ADAPTIVE_HOLD_VIX_LOW_MAX = 576
ADAPTIVE_HOLD_VIX_MED_MAX = 288
ADAPTIVE_HOLD_VIX_HIGH_MAX = 48
ADAPTIVE_HOLD_SWING_ATR_PCT = 1.0
ADAPTIVE_HOLD_SWING_MAX = 864
ADAPTIVE_HOLD_SCALP_ATR_PCT = 2.0
ADAPTIVE_HOLD_SCALP_MAX = 48

# ─── MULTI-TIMEFRAME STRATEGY ───────────────────────────────────
# Switches bar resolution based on volatility regime:
# - Normal (ATR% < threshold): 5-min bars, current strategy
# - High vol (ATR% >= threshold): 4-hour bars, wider stops, fewer trades
MULTI_TF_ENABLED = False
MULTI_TF_VOL_THRESHOLD = 1.5         # Daily ATR% to switch to 4h bars
MULTI_TF_4H_STOP_MULT = 3.5         # Wide stops on 4h bars
MULTI_TF_4H_TP_MULT = 5.0           # Wide TP on 4h bars
MULTI_TF_4H_MAX_HOLD = 18           # Max hold in 4h bars (~3 trading days)
MULTI_TF_4H_MIN_HOLD = 2            # Min hold in 4h bars (~8 hours)
MULTI_TF_4H_COOLDOWN = 9            # Cooldown in 4h bars (~1.5 days)
MULTI_TF_4H_RISK_MULT = 0.15        # Very small positions on 4h
MULTI_TF_4H_COMPOSITE_THRESH = 0.50 # High threshold for 4h entries
MULTI_TF_4H_ALLOWED_SIDE = "LONG"   # Only longs in high-vol 4h mode

# ─── MEAN REVERSION MODE (high-vol days) ────────────────────────
# Instead of trend-following on high-vol days, switch to intraday
# mean reversion: buy oversold bounces, quick exits.
# Tested: +$5,262 on 18 trades (55.6% WR) during war period.
MR_MODE_ENABLED = False              # Legacy flag — use COMBINED_STRATEGY_ENABLED instead
MR_MODE_ATR_PCT = 1.5               # Daily ATR% threshold to activate
MR_MODE_RSI_PERIOD = 12             # Short RSI for mean reversion
MR_MODE_RSI_ENTRY = 25              # RSI below this = oversold, buy (optimal from sweep)
MR_MODE_RSI_EXIT = 55               # RSI above this = recovered, exit
MR_MODE_MAX_HOLD = 12               # Max hold bars (~1 hour — avg hold is 23 min)
MR_MODE_SIDE = "LONG"               # "LONG" only — shorts don't work in high-vol wars
MR_MODE_RISK_MULT = 0.4             # Position size multiplier
MR_MODE_STOP_ATR = 3.0              # Stop at 1.5x ATR below entry
MR_MODE_MAX_TRADES_DAY = 1          # 1 best trade/day — 70% WR, PF 2.43
MR_MODE_RSI_SHORT_ENTRY = 80        # RSI above this = overbought, short
MR_MODE_RSI_SHORT_EXIT = 45         # RSI below this = recovered, cover

# ─── PHASE 4 MULTI-INPUT SIGNALS (intraday sentiment / MAG7 / Polymarket / blackout) ───
# Each weight is 0 by default — sweepable. Composite signal expects values in [-1, +1]
# from each feed, multiplies by the weight, sums into the per-side score.

# Intraday sentiment (15-min rolling) — from data/news/sentiment_intraday.csv
# Produced by tools/sentiment_intraday.py reading headlines.db.
INTRADAY_SENTIMENT_ENABLED = False
INTRADAY_SENTIMENT_WEIGHT = 0.10        # composite score weight (sweep 0.05–0.25)
INTRADAY_SENTIMENT_WINDOW = "15m"       # which window column to use (15m/30m/1h/4h/1d)
INTRADAY_SENTIMENT_THRESHOLD = 0.10     # min |sentiment| to act on; below = neutral

# MAG7 mega-cap breadth — from data/es/mag7_breadth.csv
# Produced by tools/mag7_breadth.py
MAG7_BREADTH_ENABLED = False
MAG7_BREADTH_WEIGHT = 0.10              # composite score weight
MAG7_BREADTH_THRESHOLD = 0.50           # pct_above_5d_ma threshold to flip bullish/bearish
MAG7_BREADTH_MOMENTUM_WEIGHT = 0.05     # weight on the 15-min change (separate from level)

# Polymarket prediction-market signals — from data/es/polymarket_signals.csv
# Produced by tools/polymarket_signal.py reading market-tracker cache.
POLYMARKET_ENABLED = False
POLYMARKET_FED_WEIGHT = 0.05            # weight on Fed rate path delta
POLYMARKET_RECESSION_WEIGHT = 0.05      # weight on recession probability
POLYMARKET_GEOPOLITICS_WEIGHT = 0.05    # weight on geopolitics escalation
POLYMARKET_FISCAL_WEIGHT = 0.05         # weight on fiscal expansion / shutdown
POLYMARKET_COMPOSITE_WEIGHT = 0.10      # weight on composite_es_signal column

# Macro release blackout — from tools/macro_calendar.py
# Blocks entries in a window around CPI/NFP/FOMC/PCE and mega-cap earnings.
MACRO_BLACKOUT_ENABLED = False
MACRO_BLACKOUT_LOOKBACK_MIN = 30        # block N min after release
MACRO_BLACKOUT_LOOKAHEAD_MIN = 60       # block N min before release
MACRO_BLACKOUT_MIN_IMPACT = "HIGH"      # HIGH / MEDIUM / LOW

# ─── COMBINED STRATEGY (MR + Composite routing) ────────────────
# Routes by daily ATR%: high-vol days → MR scalper, normal days → composite.
# MR has fully independent state (cooldown, trade counter, circuit breaker).
# Previous integration failed because shared state killed MR edge.
COMBINED_STRATEGY_ENABLED = True    # Master switch for combined routing
COMBINED_MR_ATR_THRESHOLD = 1.6     # ATR% cutoff: above = MR, below = composite
COMBINED_MR_COOLDOWN_BARS = 6       # MR's own cooldown (30 min, independent of composite)
COMBINED_MR_ENTRY_UTC_START = 14    # 9 AM ET — MR trades US hours
COMBINED_MR_ENTRY_UTC_END = 20      # 3 PM ET — avoid close
COMBINED_MR_TP_ATR = 2.0            # MR take-profit (ATR multiplier)
COMBINED_MR_MAX_CONSECUTIVE_LOSSES = 5  # MR's own circuit breaker (more lenient)

# ─── OIL SHOCK GATE ─────────────────────────────────────────────
OIL_SHOCK_GATE_ENABLED = False
OIL_SHOCK_THRESHOLD_PCT = 3.0       # |CL daily %change| > this = oil shock
OIL_SHOCK_HALT_ALL = False           # If True, halt all trading; if False, just block shorts

# ─── CBOE SKEW GATE ─────────────────────────────────────────────
SKEW_GATE_ENABLED = False
SKEW_PANIC_THRESHOLD = 140.0         # Skew > this = institutional panic hedging
SKEW_PANIC_RISK_SCALE = 0.5          # Reduce position size during skew panic

# ─── GOLD RISK-OFF GATE ─────────────────────────────────────────
GOLD_RISKOFF_GATE_ENABLED = False
GOLD_SURGE_THRESHOLD_PCT = 2.0       # Gold daily %change > this = risk-off flight

GARCH_BLEND_WEIGHT = 0.7            # Phase1: 0.7 optimal for 40+ trade regime
GARCH_VOL_INCREASE_SCALE = 1.2      # Widen stops when GARCH predicts higher vol
GARCH_VOL_DECREASE_SCALE = 0.85     # Tighten stops when GARCH predicts lower vol
GARCH_EXTREME_VOL_THRESHOLD = 2.5   # Skip entries when vol_ratio > this
GARCH_FALLBACK_LOOKBACK = 5         # Days to look back for nearest GARCH forecast

# ─── PARTICLE FILTER REGIME (Bayesian SMC) ─────────────────────
# Adds particle filter regime probabilities as an additional regime signal.
# Smoother regime transitions than static SMA/VIX thresholds.
PARTICLE_REGIME_ENABLED = True
REGIME_PARTICLE_WEIGHT = 0.10       # Phase2: PF regime weight (0.10 optimal for 50-trade regime)

# ─── CUSUM EVENT FILTER (mlfinlab-style) ───────────────────────
# Instead of fixed cooldown, only enter when CUSUM detects a structural break.
# Naturally adaptive: more entries in trending markets, fewer in chop.
CUSUM_ENTRY_ENABLED = True         # Disabled: only 6 trades — too few for optimization
CUSUM_WINDOW_BARS = 96              # Wide window: look back 8 hours for CUSUM event

# ─── TSFRESH DATA-DRIVEN FEATURES ─────────────────────────────
TSFRESH_SIGNAL_WEIGHT = 0.0         # Start at 0, sweep via autoresearch

# ─── HOURLY REGIME OVERLAY (3yr hourly features) ──────────────
# Pre-computed from ES_combined_hourly_extended.parquet (Apr 2023 - Mar 2026)
# Uses previous-day values only — no lookahead bias.
REGIME_HOURLY_WEIGHT = 0.0            # Regime signal weight (sweep 0.05-0.25)
HOURLY_VOL_REGIME_ADJUST = 0.0        # Composite boost in low vol / penalty in high vol
HOURLY_MOMENTUM_ENTRY_BOOST = 0.0     # Boost when hourly momentum aligns with trade

# ─── RISK-OFF STOP TIGHTENING ────────────────────────────────
RISKOFF_STOP_TIGHTEN_MULT = 0.8
