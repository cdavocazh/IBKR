# /autoresearch — ES Strategy Optimization Protocol

## Per-Iteration Flowchart

```
1. READ CURRENT STATE
   → Read NEXT_STEPS.md for context
   → Read es_strategy_config.py for current parameters
   ↓
2. DIAGNOSE
   ├─ dd_violated → Reduce risk (lower TP, tighter stop, fewer trades)
   ├─ wr_violated → Improve entry quality (higher threshold, better filters)
   ├─ too_few_trades → Relax filters (lower threshold, shorter cooldown)
   └─ Low return → Increase risk/reward (wider TP, longer holds)
   ↓
3. PICK ONE ATOMIC CHANGE
   → Only es_strategy_config.py, ONE parameter
   → Small increment (10-20% of range)
   ↓
4. APPLY CHANGE
   → Modify es_strategy_config.py
   ↓
5. VERIFY
   → python verify_strategy.py
   → Outputs: SCORE: <float> to stdout
   ↓
6. EVALUATE
   → python autoresearch.py evaluate -d "description"
   → Auto compares vs best + rising threshold
   → KEEP: saves version snapshot
   → DISCARD/BELOW_THRESHOLD: reverts config
   ↓
7. REPORT + NEXT_STEPS.md generated automatically
```

## Rules (Non-Negotiable)
- ONE change per iteration
- Small increments (10-20% of parameter range)
- Do NOT modify verify_strategy.py, scoring, engine, or data
- Max 3 crash retries
- KEEP or REVERT — never partial changes
- Config changes via batch_iterate.py (automated) or manual

## Batch Mode
```bash
python batch_iterate.py 1000 --report-every 50
```
Automatically sweeps all parameters, shuffled for diversity.
Stops after 5 consecutive dry passes (no KEEPs).
