#!/usr/bin/env python3
"""
Autoresearch orchestrator for ES strategy optimization.

Commands:
  init      - Establish baseline score
  evaluate  - Run verification and decide KEEP/DISCARD
  status    - Show progress summary
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from iteration_state import (
    load_state, save_state, record_iteration, record_crash,
    generate_progress_summary,
)
from scoring.robustness import minimum_improvement_threshold

AUTORESEARCH_DIR = Path(__file__).parent
CONFIG_FILE = AUTORESEARCH_DIR / "es_strategy_config.py"
BACKUP_FILE = AUTORESEARCH_DIR / "es_strategy_config.py.backup"
VERSIONS_DIR = AUTORESEARCH_DIR / "versions"


def run_verification():
    """Run verify_strategy.py and parse results."""
    try:
        result = subprocess.run(
            [sys.executable, str(AUTORESEARCH_DIR / "verify_strategy.py")],
            capture_output=True, text=True, timeout=600,
            cwd=str(AUTORESEARCH_DIR.parent),
        )

        # Parse SCORE from stdout
        score = 0.0
        for line in result.stdout.strip().split("\n"):
            if line.startswith("SCORE:"):
                score = float(line.split(":")[1].strip())

        # Parse metrics from stderr
        metrics = {}
        for line in result.stderr.strip().split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    metrics = json.loads(line)
                except json.JSONDecodeError:
                    pass

        return score, metrics

    except subprocess.TimeoutExpired:
        return 0.0, {"error": "Backtest timed out (600s)"}
    except Exception as e:
        return 0.0, {"error": str(e)}


def backup_config():
    """Save current config as backup."""
    shutil.copy2(CONFIG_FILE, BACKUP_FILE)


def revert_config():
    """Restore config from backup."""
    if BACKUP_FILE.exists():
        shutil.copy2(BACKUP_FILE, CONFIG_FILE)


def create_version_snapshot(version, description, score_result):
    """Save versioned snapshot of config."""
    VERSIONS_DIR.mkdir(exist_ok=True)
    ver_dir = VERSIONS_DIR / f"v{version:04d}"
    ver_dir.mkdir(exist_ok=True)

    # Copy config
    shutil.copy2(CONFIG_FILE, ver_dir / "es_strategy_config.py")

    # Write version metadata
    metadata = {
        "version": version,
        "timestamp": datetime.now().isoformat(),
        "description": description,
        "score": score_result.get("score", 0),
        "total_return_pct": score_result.get("total_return_pct", 0),
        "max_drawdown_pct": score_result.get("max_drawdown_pct", 0),
        "win_rate": score_result.get("win_rate", 0),
        "total_trades": score_result.get("total_trades", 0),
    }
    with open(ver_dir / "VERSION.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Write LATEST pointer
    with open(VERSIONS_DIR / "LATEST", "w") as f:
        f.write(str(version))


def write_next_steps(state, last_result, last_status, last_description):
    """Generate NEXT_STEPS.md handoff file."""
    cfg_path = CONFIG_FILE
    cfg_content = cfg_path.read_text() if cfg_path.exists() else ""

    threshold = minimum_improvement_threshold(state["iteration"])

    lines = [
        "# NEXT_STEPS.md — Autoresearch Handoff",
        "",
        f"## Current State (Iteration {state['iteration']})",
        f"- **Best Score:** {state['best_score']:.2f}% return",
        f"- **Baseline:** {state['baseline_score']:.2f}%",
        f"- **Min Improvement Needed:** {threshold:.2f}%",
        f"- **KEEPs/DISCARDs/CRASHes:** {state['total_keeps']}/{state['total_discards']}/{state['total_crashes']}",
        "",
        f"## Last Iteration: {last_status}",
        f"- Description: {last_description}",
        f"- Score: {last_result.get('score', 0)}",
        f"- Return: {last_result.get('total_return_pct', 0)}%",
        f"- Max DD: {last_result.get('max_drawdown_pct', 0)}%",
        f"- Win Rate: {last_result.get('win_rate', 0)}%",
        f"- Trades: {last_result.get('total_trades', 0)}",
        "",
        "## Constraints (HARD)",
        "- Win rate >= 30%",
        "- Max drawdown <= 60%",
        "- Min hold: 1 hour (12 bars)",
        "- Stop loss required",
        "- Entries during GMT+8 8am-midnight only",
        "- One position at a time",
        "- Risk $10,000 per trade",
        "",
        "## What to Try Next",
        "Pick ONE parameter change from es_strategy_config.py.",
        "Small increments (10-20% of parameter range).",
        "",
        "### Tunable Parameters",
        "- RSI_PERIOD, RSI_FAST_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT",
        "- RSI_FAST_OVERSOLD, RSI_FAST_OVERBOUGHT",
        "- ATR_PERIOD, SMA_FAST, SMA_SLOW",
        "- MACD_FAST, MACD_SLOW, MACD_SIGNAL",
        "- BB_PERIOD, BB_STD, ADX_PERIOD, ADX_TRENDING_MIN",
        "- COMPOSITE_THRESHOLD (0.2-0.7)",
        "- WEIGHT_RSI, WEIGHT_TREND, WEIGHT_MOMENTUM, WEIGHT_BB, WEIGHT_REGIME",
        "- STOP_ATR_MULT (1.0-4.0), TP_ATR_MULT (2.0-8.0)",
        "- TRAILING_START_R (0.5-3.0), TRAILING_ATR_MULT (0.5-3.0)",
        "- MAX_HOLD_BARS (72-1152), MIN_HOLD_BARS (12-48)",
        "- COOLDOWN_BARS (6-96), MIN_ATR_THRESHOLD (0.5-5.0)",
        "- VIX_LOW, VIX_HIGH, VIX_EXTREME",
        "- VIX_LOW_LONG_BOOST, VIX_HIGH_SHORT_BOOST, VIX_EXTREME_LONG_BOOST",
        "- USE_LIMIT_ORDERS (True/False), LIMIT_OFFSET_ATR (0.1-1.0)",
        "- PULLBACK_MIN_PCT (0.1-1.0), PULLBACK_LOOKBACK (12-96)",
        "- BREAKEVEN_R (0.5-2.0)",
        "- STOP_TIGHTEN_ON_RSI_EXTREME (True/False), STOP_TIGHTEN_ATR_MULT (0.5-2.0)",
        "",
    ]

    next_steps_path = AUTORESEARCH_DIR / "NEXT_STEPS.md"
    next_steps_path.write_text("\n".join(lines))


def cmd_init():
    """Establish baseline."""
    print("Initializing autoresearch baseline...")
    backup_config()

    score, metrics = run_verification()

    state = load_state()
    state["iteration"] = 0
    state["best_score"] = score
    state["baseline_score"] = score
    state["best_return"] = metrics.get("total_return_pct", -999)
    state["best_dd"] = metrics.get("max_drawdown_pct", 999)
    state["total_keeps"] = 0
    state["total_discards"] = 0
    state["total_crashes"] = 0
    state["started_at"] = datetime.now().isoformat()
    save_state(state)

    print(f"\nBaseline established:")
    print(f"  Score: {score}")
    print(f"  Return: {metrics.get('total_return_pct', 'N/A')}%")
    print(f"  Max DD: {metrics.get('max_drawdown_pct', 'N/A')}%")
    print(f"  Win Rate: {metrics.get('win_rate', 'N/A')}%")
    print(f"  Trades: {metrics.get('total_trades', 'N/A')}")

    write_next_steps(state, metrics, "BASELINE", "Initial baseline")

    # Create initial version
    create_version_snapshot(0, "Baseline", metrics)


def cmd_evaluate(description: str):
    """Evaluate current config vs best.

    NOTE: backup_config() is NOT called here because batch_iterate
    applies changes before calling evaluate. The backup should contain
    the PREVIOUS good config (set on init or after KEEP), not the trial.
    """
    state = load_state()
    # Do NOT backup here — batch_iterate already modified the config.
    # The backup file should contain the last KEEPed (or baseline) config.

    print(f"Evaluating: {description}")
    score, metrics = run_verification()

    if metrics.get("error"):
        print(f"CRASH: {metrics['error']}")
        state = record_crash(state, metrics.get("error", "unknown"))
        revert_config()
        write_next_steps(state, metrics, "CRASH", description)
        print("CRASH — config reverted")
        return

    # Decision
    threshold = minimum_improvement_threshold(state["iteration"])
    delta = score - state["best_score"]

    # Bootstrap mode: when best_score is 0 (constraints violated),
    # use return+DD as secondary metric to track progress toward feasibility.
    # Any config that achieves score > 0 is an automatic KEEP.
    # When both are 0, use less-negative return or lower DD as progress signal.
    best_return = state.get("best_return", -999)
    best_dd = state.get("best_dd", 999)
    curr_return = metrics.get("total_return_pct", -999)
    curr_dd = metrics.get("max_drawdown_pct", 999)

    # Score=0 means constraints violated (DD>60% or WR<30%).
    # A negative score means constraints pass but return is negative.
    # Negative score is BETTER than zero score (constraints satisfied > not satisfied).
    best_score = state["best_score"]

    # Effective comparison: treat score=0 (infeasible) as -9999 for comparison
    effective_score = score if score != 0 else -9999
    effective_best = best_score if best_score != 0 else -9999

    if effective_score > effective_best + threshold:
        status = "KEEP"
    elif effective_score == -9999 and effective_best == -9999:
        # Both infeasible: track progress toward feasibility
        better_dd = curr_dd < best_dd - 1.0
        better_return = curr_return > best_return + 2.0
        if better_dd or better_return:
            status = "KEEP"
        else:
            status = "DISCARD"
    elif effective_score > effective_best:
        status = "BELOW_THRESHOLD"
    else:
        status = "DISCARD"

    if status == "KEEP":
        version = state["total_keeps"] + 1
        state = record_iteration(state, metrics, status, description)
        state["best_return"] = curr_return
        state["best_dd"] = curr_dd
        create_version_snapshot(version, description, metrics)
        backup_config()  # New backup is this config
        save_state(state)
        print(f"KEEP — score {score:.2f} return {curr_return:.2f}% dd {curr_dd:.2f}% (delta +{delta:.2f})")
    elif status == "BELOW_THRESHOLD":
        state = record_iteration(state, metrics, status, description)
        revert_config()
        print(f"BELOW_THRESHOLD — score {score:.2f} (delta +{delta:.2f} < threshold {threshold:.2f})")
    else:
        state = record_iteration(state, metrics, status, description)
        revert_config()
        print(f"DISCARD — score {score:.2f} return {curr_return:.2f}% dd {curr_dd:.2f}%")

    write_next_steps(state, metrics, status, description)

    # Print key metrics
    print(f"  Return: {metrics.get('total_return_pct', 0):.2f}%")
    print(f"  Max DD: {metrics.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Win Rate: {metrics.get('win_rate', 0):.2f}%")
    print(f"  Trades: {metrics.get('total_trades', 0)}")


def cmd_status():
    """Show progress summary."""
    state = load_state()
    print(generate_progress_summary(state))


def main():
    parser = argparse.ArgumentParser(description="ES Autoresearch Orchestrator")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Establish baseline")

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate parameter change")
    eval_parser.add_argument("--description", "-d", required=True)

    subparsers.add_parser("status", help="Show progress")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init()
    elif args.command == "evaluate":
        cmd_evaluate(args.description)
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
