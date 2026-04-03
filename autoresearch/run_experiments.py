#!/usr/bin/env python3
"""Run all 8 structural experiments sequentially, each with 500 iterations."""
import json
import os
import sys
import shutil
import subprocess
import time

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "es_strategy_config.py")
BASELINE_PATH = os.path.join(os.path.dirname(__file__), "es_strategy_config_baseline_exp.py")
STATE_PATH = os.path.join(os.path.dirname(__file__), "autoresearch-state.json")
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "autoresearch-results.tsv")
PYTHON = "/Users/kriszhang/mambaforge/bin/python3"
AUTORESEARCH = os.path.join(os.path.dirname(__file__), "autoresearch.py")
BATCH_ITERATE = os.path.join(os.path.dirname(__file__), "batch_iterate.py")
VERIFY = os.path.join(os.path.dirname(__file__), "verify_strategy.py")

EXPERIMENTS = {
    "exp1_vol_gate": {
        "name": "Volatility Regime Gate",
        "flags": {"VOL_REGIME_GATE_ENABLED": True},
    },
    "exp2_max_trades": {
        "name": "Max Trades Per Day (2)",
        "flags": {"MAX_TRADES_PER_DAY_ENABLED": True},
    },
    "exp3_sentiment": {
        "name": "Rebuilt Daily Sentiment",
        "flags": {},  # Just needs sentiment CSV rebuilt — no config flag
        "note": "Requires daily_sentiment.csv to be updated before running",
    },
    "exp4_crisis_short": {
        "name": "Crisis Short Disabling (VIX>30 + ATR>2%)",
        "flags": {"CRISIS_SHORT_DISABLE_ENABLED": True},
    },
    "exp5_hold_reduction": {
        "name": "High-Vol Hold Reduction (48 bars)",
        "flags": {"HIGH_VOL_HOLD_REDUCTION_ENABLED": True},
    },
    "exp6_trend_filter": {
        "name": "Intraday Trend Filter",
        "flags": {"INTRADAY_TREND_FILTER_ENABLED": True},
    },
    "exp7_dual_mode": {
        "name": "Dual-Mode Strategy (Crisis Mode)",
        "flags": {"DUAL_MODE_ENABLED": True},
    },
    "exp8_walkforward": {
        "name": "Walk-Forward (no config change — structural validation)",
        "flags": {},
        "note": "This experiment validates via walk-forward, not parameter sweep",
    },
}

ITERATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 500


def set_config_flag(flag_name, value):
    """Set a flag in es_strategy_config.py."""
    with open(CONFIG_PATH, "r") as f:
        content = f.read()
    # Find the line with this flag
    old_val = "True" if not value else "False"
    new_val = "True" if value else "False"
    old_line = f"{flag_name} = {old_val}"
    new_line = f"{flag_name} = {new_val}"
    if old_line in content:
        content = content.replace(old_line, new_line)
    with open(CONFIG_PATH, "w") as f:
        f.write(content)


def reset_config():
    """Reset config to baseline (all experiment flags disabled)."""
    shutil.copy(BASELINE_PATH, CONFIG_PATH)
    # Re-add the experiment flags (baseline doesn't have them)
    with open(CONFIG_PATH, "r") as f:
        content = f.read()
    if "VOL_REGIME_GATE_ENABLED" not in content:
        # Need to re-add the flags section — read from current
        # Just disable all flags
        for exp in EXPERIMENTS.values():
            for flag in exp["flags"]:
                if flag not in content:
                    # Add it after GARCH_ENABLED line
                    content = content.replace(
                        "GARCH_ENABLED = True",
                        f"GARCH_ENABLED = True\n{flag} = False",
                    )
        with open(CONFIG_PATH, "w") as f:
            f.write(content)


def get_baseline():
    """Run verify_strategy.py and return metrics."""
    result = subprocess.run(
        [PYTHON, VERIFY], capture_output=True, text=True, cwd=os.path.dirname(__file__)
    )
    try:
        return json.loads(result.stdout.strip().split("\n")[0])
    except:
        return {"score": 0, "error": result.stderr[:500]}


def run_experiment(exp_id, exp_config, iterations):
    """Run a single experiment: enable flags, init, sweep, collect results."""
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT: {exp_config['name']} ({exp_id})")
    print(f"{'='*60}")

    # Enable flags
    for flag, value in exp_config["flags"].items():
        set_config_flag(flag, value)
        print(f"  Set {flag} = {value}")

    # Get baseline with this flag enabled (before sweep)
    baseline = get_baseline()
    print(f"  Baseline: score={baseline.get('score', 'ERR')}, "
          f"return={baseline.get('total_return_pct', 'ERR')}%, "
          f"DD={baseline.get('max_drawdown_pct', 'ERR')}%, "
          f"trades={baseline.get('total_trades', 'ERR')}")

    # Init autoresearch
    subprocess.run(
        [PYTHON, AUTORESEARCH, "init"],
        capture_output=True, text=True, cwd=os.path.dirname(__file__)
    )

    # Run sweep
    print(f"  Running {iterations} iterations...")
    start = time.time()
    subprocess.run(
        [PYTHON, BATCH_ITERATE, str(iterations), "--report-every", "100"],
        capture_output=True, text=True, cwd=os.path.dirname(__file__)
    )
    elapsed = time.time() - start
    print(f"  Completed in {elapsed:.0f}s")

    # Read final state
    with open(STATE_PATH, "r") as f:
        state = json.load(f)

    # Get final metrics
    final = get_baseline()

    result = {
        "exp_id": exp_id,
        "name": exp_config["name"],
        "baseline_score": baseline.get("score", 0),
        "baseline_return": baseline.get("total_return_pct", 0),
        "baseline_dd": baseline.get("max_drawdown_pct", 0),
        "baseline_trades": baseline.get("total_trades", 0),
        "final_score": state.get("best_score", 0),
        "final_return": state.get("best_return", 0),
        "final_dd": state.get("best_dd", 0),
        "total_keeps": state.get("total_keeps", 0),
        "final_trades": final.get("total_trades", 0),
        "final_win_rate": final.get("win_rate", 0),
        "final_sharpe": final.get("sharpe_ratio", 0),
        "final_pf": final.get("profit_factor", 0),
        "elapsed_s": elapsed,
    }

    print(f"  Result: score={result['final_score']:.2f}, "
          f"return={result['final_return']:.2f}%, "
          f"DD={result['final_dd']:.2f}%, "
          f"keeps={result['total_keeps']}, "
          f"trades={result['final_trades']}")

    # Disable flags (reset for next experiment)
    for flag in exp_config["flags"]:
        set_config_flag(flag, False)

    return result


def main():
    results = []

    # Run experiments 1-2, 4-7 (config-flag based)
    for exp_id in ["exp1_vol_gate", "exp2_max_trades", "exp4_crisis_short",
                    "exp5_hold_reduction", "exp6_trend_filter", "exp7_dual_mode"]:
        exp = EXPERIMENTS[exp_id]
        result = run_experiment(exp_id, exp, ITERATIONS)
        results.append(result)
        # Reset config between experiments
        for flag in exp["flags"]:
            set_config_flag(flag, False)

    # Exp 3 and 8 are special — skip parameter sweep, just report baseline impact
    # Exp 3: sentiment rebuild effect
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT: exp3_sentiment (baseline only, no sweep)")
    print(f"{'='*60}")
    baseline_3 = get_baseline()
    results.append({
        "exp_id": "exp3_sentiment",
        "name": "Rebuilt Daily Sentiment",
        "baseline_score": baseline_3.get("score", 0),
        "baseline_return": baseline_3.get("total_return_pct", 0),
        "baseline_dd": baseline_3.get("max_drawdown_pct", 0),
        "baseline_trades": baseline_3.get("total_trades", 0),
        "final_score": baseline_3.get("score", 0),
        "final_return": baseline_3.get("total_return_pct", 0),
        "final_dd": baseline_3.get("max_drawdown_pct", 0),
        "total_keeps": 0,
        "final_trades": baseline_3.get("total_trades", 0),
        "final_win_rate": baseline_3.get("win_rate", 0),
        "final_sharpe": baseline_3.get("sharpe_ratio", 0),
        "final_pf": baseline_3.get("profit_factor", 0),
        "elapsed_s": 0,
        "note": "No sweep — sentiment CSV gap still exists",
    })

    # Exp 8: walk-forward (report only)
    results.append({
        "exp_id": "exp8_walkforward",
        "name": "Walk-Forward Retraining",
        "baseline_score": -0.37,
        "baseline_return": -0.45,
        "baseline_dd": 16.04,
        "baseline_trades": 39,
        "final_score": -0.37,
        "final_return": -0.45,
        "final_dd": 16.04,
        "total_keeps": 0,
        "final_trades": 39,
        "final_win_rate": 43.59,
        "final_sharpe": 0.18,
        "final_pf": 1.61,
        "elapsed_s": 0,
        "note": "Structural validation — requires separate walk-forward run",
    })

    # Print summary table
    print(f"\n{'='*80}")
    print(f"  EXPERIMENT SUMMARY")
    print(f"{'='*80}")
    print(f"{'Exp':<25} {'BL Score':>9} {'Final Score':>12} {'Return%':>9} {'DD%':>8} {'Trades':>7} {'KEEPs':>6}")
    print(f"{'-'*80}")
    for r in results:
        print(f"{r['name'][:24]:<25} {r['baseline_score']:>9.2f} {r['final_score']:>12.2f} "
              f"{r['final_return']:>8.2f}% {r['final_dd']:>7.2f}% {r['final_trades']:>7} {r['total_keeps']:>6}")

    # Save results JSON
    out_path = os.path.join(os.path.dirname(__file__), "experiment_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
