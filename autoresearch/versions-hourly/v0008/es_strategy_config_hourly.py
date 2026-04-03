"""
ES Futures Strategy Configuration — HOURLY TIMEFRAME

Dual-strategy variant: hourly bars using extended SPY+ES dataset (Apr 2023 - Mar 2026).
Uses USE_EXTENDED_DATA=True and BAR_SCALE_FACTOR=12 to adapt 5-min bar counts to hourly.
Half capital allocation for dual-strategy mode.
"""

# ─── DATA MODE ────────────────────────────────────────────────
USE_EXTENDED_DATA = True           # Use extended hourly dataset (SPY gap + real ES)
BAR_SCALE_FACTOR = 12              # 12 x 5-min bars = 1 hourly bar

# ─── CAPITAL & RISK ───────────────────────────────────────────
INITIAL_CAPITAL = 50_000           # Half capital for dual strategy
RISK_PER_TRADE = 5_000             # Same per-trade risk
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
RSI_PERIOD = 10
RSI_FAST_PERIOD = 3
ATR_PERIOD = 28
SMA_FAST = 30
SMA_SLOW = 30          # CHANGED: 80->50 (faster trend detection)
SMA_200 = 200
BB_PERIOD = 25
BB_STD = 1.5

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
VOLUME_SIGNAL_WEIGHT = 0.05
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
SEQ_VOLUME_MIN_RATIO = 0.7
SEQ_MACRO_ADVERSE_SIZE_SCALE = 1.0
SEQ_MACRO_FAVORABLE_SIZE_SCALE = 1.2  # No upscaling initially

# ─── ADAPTIVE STOP-LOSS (macro + TA scaled) ─────────────────
ADAPTIVE_STOP_LOW_VOL_SCALE = 1.0
ADAPTIVE_STOP_HIGH_VOL_SCALE = 1.2
ADAPTIVE_STOP_VIX_RISKOFF_SCALE = 1.0
ADAPTIVE_STOP_VIX_PANIC_SCALE = 0.7
ADAPTIVE_STOP_VIX_LOW_SCALE = 0.8
ADAPTIVE_STOP_CREDIT_STRESS_SCALE = 0.9
ADAPTIVE_STOP_DXY_STRONG_SCALE = 0.7

# ─── ADAPTIVE TAKE-PROFIT (macro + TA scaled) ───────────────
ADAPTIVE_TP_TREND_ALIGNED_SCALE = 1.8
ADAPTIVE_TP_COUNTER_TREND_SCALE = 1.0
ADAPTIVE_TP_RSI_EXTENDED_SCALE = 0.9
ADAPTIVE_TP_RSI_REVERSAL_SCALE = 1.3
ADAPTIVE_TP_VIX_HIGH_SCALE = 1.3  # CHANGED: 2.0->1.3 (less extreme TP widening)
ADAPTIVE_TP_VIX_ELEVATED_SCALE = 1.0
ADAPTIVE_TP_VOLUME_SURGE_SCALE = 1.0

# ─── IN-TRADE MACRO ADJUSTMENTS ─────────────────────────────
INTRADE_VIX_SPIKE_THRESHOLD = 3.0
INTRADE_VIX_SPIKE_TIGHTEN = 0.4
INTRADE_CREDIT_STRESS_TIGHTEN = 0.5
INTRADE_TRAILING_VIX_TIGHTEN = 0.5
INTRADE_RSI_EXTREME_TIGHTEN_ATR = 0.3

# ─── CONFIDENCE-WEIGHTED POSITION SIZING ─────────────────────
CONFIDENCE_SIZING_ENABLED = True
CONFIDENCE_HIGH_THRESHOLD = 0.5
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
BULL_COMPOSITE_THRESHOLD = 0.35
BULL_STOP_ATR_MULT = 3.5
BULL_TP_ATR_MULT = 2.0            # 1:1 R:R — maximize WR
BULL_TRAILING_START_R = 1.5
BULL_TRAILING_ATR_MULT = 0.5
BULL_MAX_HOLD_BARS = 288
BULL_RISK_MULT = 0.4
BULL_WEIGHT_RSI = 0.12             # TuneTA: dcor=0.15, nudge up from 0.10
BULL_WEIGHT_TREND = 0.30           # TuneTA: dcor=0.27, reduce from 0.35
BULL_WEIGHT_MOMENTUM = 0.13        # TuneTA: dcor=0.16, nudge up from 0.10
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
BEAR_COMPOSITE_THRESHOLD = 0.40
BEAR_STOP_ATR_MULT = 3.5
BEAR_TP_ATR_MULT = 2.0
BEAR_TRAILING_START_R = 0.8
BEAR_TRAILING_ATR_MULT = 0.8
BEAR_MAX_HOLD_BARS = 432
BEAR_RISK_MULT = 0.6              # Very conservative short sizing
BEAR_WEIGHT_RSI = 0.1             # TuneTA Phase1: dcor=0.12 (reduced from 0.20)
BEAR_WEIGHT_TREND = 0.15          # TuneTA Phase1: dcor=0.29 (increased from 0.10)
BEAR_WEIGHT_MOMENTUM = 0.10       # TuneTA Phase1: dcor=0.18 (increased from 0.05)
BEAR_WEIGHT_BB = 0.10             # TuneTA Phase1: dcor=0.06 (reduced from 0.20 — key DD reduction)
BEAR_WEIGHT_VIX = 0.1
BEAR_WEIGHT_MACRO = 0.2

# ─── SIDEWAYS REGIME CONFIG ──────────────────────────────────
SIDE_SIDE = "BOTH"
SIDE_RSI_OVERSOLD = 20            # CHANGED: 40->35
SIDE_RSI_OVERBOUGHT = 60          # CHANGED: 80->70
SIDE_COMPOSITE_THRESHOLD = 0.35
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
COOLDOWN_BARS = 6                # Reduced for 40+ trade research mode
MIN_ATR_THRESHOLD = 5.0           # Risk-adj KEEP: 4.0->5.0
MIN_VOLUME_THRESHOLD = 50
MIN_HOLD_BARS = 24
BREAKEVEN_R = 1.5                  # Near-miss: scored -2.9 (was 1.5)
STOP_TIGHTEN_ON_RSI_EXTREME = True # CHANGED: False->True
STOP_TIGHTEN_ATR_MULT = 1.2       # CHANGED: 2.0->1.5 (tighter on RSI extreme)

# ─── VIX 7-TIER OPPORTUNITY FRAMEWORK ────────────────────────
# VIX natural state is below 20. Spikes above are temporary.
# VIX > 30: ALWAYS looking at dip-buying setups (mean reversion)
# VIX < 16: No room for charm/vanna compression → no more dealer buying pressure
VIX_TIER_1 = 16.0                 # Complacency: vanna/charm exhausted, short alert
VIX_TIER_2 = 20.0                 # CHANGED: 18->20 (near-miss +10.99%)
VIX_TIER_3 = 22.0                 # Elevated: caution, reduced position
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
COPPER_FALLING_SHORT_BOOST = 0.1  # Falling copper → economic slowdown signal

# ─── LIMIT ORDERS ────────────────────────────────────────────
USE_LIMIT_ORDERS = True
LIMIT_OFFSET_ATR = 0.7

# ─── GARCH VOLATILITY FORECAST ─────────────────────────────────
# Forward-looking conditional variance from GARCH(1,1) on daily ES returns.
# Replaces backward-looking ATR regime scaling with predictive vol forecast.
GARCH_ENABLED = False              # Ablation: zero impact on current config
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
CUSUM_ENTRY_ENABLED = False         # Phase3: disabled until tuned
CUSUM_WINDOW_BARS = 6               # Look back N bars for recent CUSUM event

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
