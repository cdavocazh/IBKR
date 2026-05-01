#!/usr/bin/env python3
"""Run all structural experiments sequentially — v2 with proper config management."""
import json, os, sys, subprocess, time, re

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(DIR, "es_strategy_config.py")
BASELINE = os.path.join(DIR, "es_strategy_config_baseline_exp.py")
PYTHON = os.environ.get("PYTHON_INTERPRETER", sys.executable)
VERIFY = os.path.join(DIR, "verify_strategy.py")
AUTORESEARCH = os.path.join(DIR, "autoresearch.py")
BATCH = os.path.join(DIR, "batch_iterate.py")
ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 500

EXPERIMENTS = [
    ("exp1", "Volatility Regime Gate", "VOL_REGIME_GATE_ENABLED"),
    ("exp2", "Max Trades Per Day", "MAX_TRADES_PER_DAY_ENABLED"),
    ("exp4", "Crisis Short Disabling", "CRISIS_SHORT_DISABLE_ENABLED"),
    ("exp5", "High-Vol Hold Reduction", "HIGH_VOL_HOLD_REDUCTION_ENABLED"),
    ("exp6", "Intraday Trend Filter", "INTRADAY_TREND_FILTER_ENABLED"),
    ("exp7", "Dual-Mode Strategy", "DUAL_MODE_ENABLED"),
]

def toggle_flag(flag, enable):
    with open(CONFIG) as f:
        txt = f.read()
    old = f"{flag} = {'False' if enable else 'True'}"
    new = f"{flag} = {'True' if enable else 'False'}"
    txt = txt.replace(old, new)
    with open(CONFIG, "w") as f:
        f.write(txt)

def reset():
    """Copy baseline back, preserving all flags as False."""
    import shutil
    shutil.copy(BASELINE, CONFIG)

def run_verify():
    r = subprocess.run([PYTHON, VERIFY], capture_output=True, text=True, cwd=DIR)
    line = r.stdout.strip().split("\n")[0]
    try:
        return json.loads(line)
    except:
        return {"score": "ERR", "error": line[:200] + " | " + r.stderr[:200]}

def run_sweep(n):
    subprocess.run([PYTHON, AUTORESEARCH, "init"], capture_output=True, text=True, cwd=DIR)
    subprocess.run([PYTHON, BATCH, str(n), "--report-every", "100"], capture_output=True, text=True, cwd=DIR)
    with open(os.path.join(DIR, "autoresearch-state.json")) as f:
        return json.load(f)

results = []

# First verify baseline
reset()
bl = run_verify()
print(f"BASELINE: score={bl.get('score')}, return={bl.get('total_return_pct')}%, "
      f"DD={bl.get('max_drawdown_pct')}%, trades={bl.get('total_trades')}, "
      f"WR={bl.get('win_rate')}%, sharpe={bl.get('sharpe_ratio')}, PF={bl.get('profit_factor')}")
print()

for exp_id, name, flag in EXPERIMENTS:
    print(f"{'='*60}")
    print(f"  {exp_id}: {name} ({flag})")
    print(f"{'='*60}")

    # Reset to clean baseline
    reset()
    # Enable this experiment's flag
    toggle_flag(flag, True)

    # Verify flag is set
    with open(CONFIG) as f:
        if f"{flag} = True" not in f.read():
            print(f"  ERROR: Flag {flag} not set!")
            continue

    # Get baseline WITH this flag
    base = run_verify()
    print(f"  With flag ON: score={base.get('score')}, return={base.get('total_return_pct')}%, "
          f"DD={base.get('max_drawdown_pct')}%, trades={base.get('total_trades')}")

    # Run sweep
    t0 = time.time()
    state = run_sweep(ITERS)
    elapsed = time.time() - t0

    # Get final metrics
    final = run_verify()
    print(f"  After {ITERS} iters: score={state.get('best_score')}, "
          f"return={state.get('best_return')}%, DD={state.get('best_dd')}%, "
          f"keeps={state.get('total_keeps')}, time={elapsed:.0f}s")
    print(f"  Final verify: trades={final.get('total_trades')}, "
          f"WR={final.get('win_rate')}%, sharpe={final.get('sharpe_ratio')}, "
          f"PF={final.get('profit_factor')}")

    results.append({
        "id": exp_id, "name": name, "flag": flag,
        "bl_score": base.get("score", 0),
        "bl_return": base.get("total_return_pct", 0),
        "bl_dd": base.get("max_drawdown_pct", 0),
        "bl_trades": base.get("total_trades", 0),
        "bl_wr": base.get("win_rate", 0),
        "final_score": state.get("best_score", 0),
        "final_return": state.get("best_return", 0),
        "final_dd": state.get("best_dd", 0),
        "keeps": state.get("total_keeps", 0),
        "final_trades": final.get("total_trades", 0),
        "final_wr": final.get("win_rate", 0),
        "final_sharpe": final.get("sharpe_ratio", 0),
        "final_pf": final.get("profit_factor", 0),
        "elapsed": elapsed,
    })

    # Reset for next experiment
    reset()

# Summary
print(f"\n{'='*90}")
print(f"  EXPERIMENT COMPARISON (baseline: score={bl.get('score')}, return={bl.get('total_return_pct')}%)")
print(f"{'='*90}")
print(f"{'Experiment':<30} {'BL Score':>9} {'Final':>9} {'Return%':>9} {'DD%':>8} {'Trades':>7} {'WR%':>6} {'KEEPs':>6}")
print(f"{'-'*90}")
for r in results:
    print(f"{r['name'][:29]:<30} {r['bl_score']:>9.2f} {r['final_score']:>9.2f} "
          f"{r['final_return']:>8.2f}% {r['final_dd']:>7.2f}% {r['final_trades']:>7} "
          f"{r['final_wr']:>5.1f}% {r['keeps']:>6}")

# Save
with open(os.path.join(DIR, "experiment_results_v2.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to experiment_results_v2.json")
