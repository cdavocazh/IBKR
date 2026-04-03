# ES Strategy Architecture

## Overview
Multi-signal composite strategy for E-mini S&P 500 futures (ES).
Entries during Asia hours (GMT+8 8am-midnight), exits any time.
VIX regime-aware position management.

## Signal Components

### 1. RSI (Weight: 25%)
- Dual-period RSI (14 + 7)
- Long: RSI < oversold, Short: RSI > overbought
- Fast RSI provides early signal boost

### 2. Trend (Weight: 25%)
- SMA crossover (fast/slow)
- Long: fast SMA > slow SMA, Short: opposite
- Normalized by price level

### 3. Momentum (Weight: 20%)
- 1-hour price change (12 bars on 5-min)
- Long: positive momentum, Short: negative
- Capped at 0.5% normalization

### 4. Bollinger Bands (Weight: 15%)
- Mean reversion at band extremes
- Long: price below lower band, Short: above upper
- Gradual score between band and SMA

### 5. VIX Regime (Weight: 15%)
- VIX < 16: favor longs (low vol environment)
- VIX 16-25: neutral
- VIX 25-35: favor shorts
- VIX > 35: buy dips aggressively (extreme fear)

## Entry Rules
1. Composite score >= threshold (default 0.45)
2. Within Asia hours (GMT+8 8:00 AM to 11:59 PM)
3. Cooldown expired (default 24 bars = 2 hours)
4. ATR above minimum (avoid dead markets)
5. Volume above minimum
6. No existing position

## Position Sizing
```
contracts = floor($10,000 / (stop_distance × $50))
stop_distance = ATR × STOP_ATR_MULT
```

## Exit Rules
1. **Stop Loss**: Entry ± ATR × STOP_ATR_MULT (always active)
2. **Take Profit**: Entry ± ATR × TP_ATR_MULT
3. **Breakeven**: Move stop to entry + 0.25 at BREAKEVEN_R × risk
4. **Trailing**: After TRAILING_START_R × risk, trail at ATR × TRAILING_ATR_MULT
5. **RSI Tightening**: Tighten stop when RSI hits extreme
6. **Time Exit**: Close after MAX_HOLD_BARS (respect MIN_HOLD_BARS)

## Tunable Parameter Ranges

| Parameter | Range | Default |
|-----------|-------|---------|
| RSI_PERIOD | 7-21 | 14 |
| RSI_OVERSOLD | 20-40 | 30 |
| RSI_OVERBOUGHT | 60-80 | 70 |
| COMPOSITE_THRESHOLD | 0.25-0.65 | 0.45 |
| STOP_ATR_MULT | 1.0-3.5 | 2.0 |
| TP_ATR_MULT | 2.0-8.0 | 4.0 |
| MAX_HOLD_BARS | 72-1152 | 288 |
| COOLDOWN_BARS | 6-96 | 24 |
| VIX_LOW | 12-20 | 16 |
| VIX_HIGH | 20-30 | 25 |

## Data Sources
- **Price**: ES 1-min → 5-min resample (data/es/ES_1min.parquet)
- **VIX**: Daily from macro_2 (forward-filled)
- **Period**: Jan 2025 - Jan 2026 (~13 months)
