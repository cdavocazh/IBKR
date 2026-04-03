# Scoring Formula

## Formula
```
score = total_return_pct   if max_dd <= 60% AND win_rate >= 30% AND trades >= 5
score = 0                  otherwise
```

## Hard Constraints
| Constraint | Threshold | Violation |
|------------|-----------|-----------|
| Max Drawdown | <= 60% | score = 0 |
| Win Rate | >= 30% | score = 0 |
| Min Trades | >= 5 | score = 0 |

## Rising Improvement Threshold
```
min_improvement = 0.5 × log(1 + iteration_count)

Iteration 1:    0.35%
Iteration 10:   1.20%
Iteration 50:   1.96%
Iteration 100:  2.31%
Iteration 500:  3.11%
Iteration 1000: 3.45%
```

## Diagnostic Flowchart
```
IF dd_violated (DD > 60%):
  → Reduce STOP_ATR_MULT, TP_ATR_MULT
  → Tighten COMPOSITE_THRESHOLD
  → Reduce MAX_HOLD_BARS
  → Increase COOLDOWN_BARS

IF wr_violated (WR < 30%):
  → Increase COMPOSITE_THRESHOLD
  → Adjust RSI thresholds (wider oversold/overbought)
  → Increase COOLDOWN_BARS

IF too_few_trades (< 5):
  → Lower COMPOSITE_THRESHOLD
  → Reduce COOLDOWN_BARS
  → Reduce MIN_ATR_THRESHOLD
  → Reduce MIN_VOLUME_THRESHOLD

IF low return:
  → Increase TP_ATR_MULT
  → Increase MAX_HOLD_BARS
  → Reduce COOLDOWN_BARS
  → Adjust VIX boosts
```
