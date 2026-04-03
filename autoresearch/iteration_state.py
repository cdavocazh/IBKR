"""
Iteration state management and result logging for ES autoresearch.
"""

import json
import os
from datetime import datetime
from pathlib import Path

STATE_FILE = "autoresearch-state.json"
RESULTS_TSV = "autoresearch-results.tsv"

TSV_HEADERS = [
    "iteration", "score", "total_return_pct", "max_dd_pct",
    "dd_violated", "wr_violated", "total_trades", "win_rate",
    "sharpe", "pf", "delta", "status", "description",
]


def load_state() -> dict:
    """Load or initialize autoresearch state."""
    state_path = Path(__file__).parent / STATE_FILE
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {
        "iteration": 0,
        "best_score": 0.0,
        "baseline_score": 0.0,
        "total_keeps": 0,
        "total_discards": 0,
        "total_crashes": 0,
        "started_at": None,
    }


def save_state(state: dict):
    """Persist state to JSON."""
    state_path = Path(__file__).parent / STATE_FILE
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def ensure_tsv_headers():
    """Create TSV file with headers if it doesn't exist."""
    tsv_path = Path(__file__).parent / RESULTS_TSV
    if not tsv_path.exists():
        with open(tsv_path, "w") as f:
            f.write("\t".join(TSV_HEADERS) + "\n")


def record_iteration(
    state: dict,
    score_result: dict,
    status: str,
    description: str,
) -> dict:
    """Record an iteration result and update state.

    Args:
        state: Current state dict.
        score_result: Dict from compute_robustness_score + backtest metrics.
        status: KEEP, DISCARD, BELOW_THRESHOLD, or CRASH.
        description: What was changed.

    Returns:
        Updated state dict.
    """
    state["iteration"] += 1
    iteration = state["iteration"]

    score = score_result.get("score", 0.0)
    delta = score - state["best_score"]

    if status == "KEEP":
        state["best_score"] = score
        state["total_keeps"] += 1
    elif status == "CRASH":
        state["total_crashes"] += 1
    else:
        state["total_discards"] += 1

    # Append TSV row
    ensure_tsv_headers()
    tsv_path = Path(__file__).parent / RESULTS_TSV
    row = {
        "iteration": iteration,
        "score": score_result.get("score", 0),
        "total_return_pct": score_result.get("total_return_pct", 0),
        "max_dd_pct": score_result.get("max_drawdown_pct", 0),
        "dd_violated": score_result.get("dd_violated", False),
        "wr_violated": score_result.get("wr_violated", False),
        "total_trades": score_result.get("total_trades", 0),
        "win_rate": score_result.get("win_rate", 0),
        "sharpe": score_result.get("sharpe_ratio", 0),
        "pf": score_result.get("profit_factor", 0),
        "delta": round(delta, 2),
        "status": status,
        "description": description,
    }
    with open(tsv_path, "a") as f:
        f.write("\t".join(str(row[h]) for h in TSV_HEADERS) + "\n")

    # Write iteration markdown
    iter_dir = Path(__file__).parent / "iterations"
    iter_dir.mkdir(exist_ok=True)
    iter_path = iter_dir / f"iteration_{iteration:04d}.md"
    with open(iter_path, "w") as f:
        f.write(f"# Iteration {iteration}\n\n")
        f.write(f"**Status:** {status}\n")
        f.write(f"**Description:** {description}\n")
        f.write(f"**Score:** {score_result.get('score', 0)}\n")
        f.write(f"**Delta:** {delta:+.2f}\n\n")
        f.write("## Metrics\n")
        for k, v in score_result.items():
            f.write(f"- {k}: {v}\n")

    save_state(state)
    return state


def record_crash(state: dict, error_msg: str) -> dict:
    """Record a crashed backtest."""
    state["iteration"] += 1
    state["total_crashes"] += 1

    ensure_tsv_headers()
    tsv_path = Path(__file__).parent / RESULTS_TSV
    row_vals = [
        str(state["iteration"]), "0", "0", "0",
        "False", "False", "0", "0",
        "0", "0", "0", "CRASH", error_msg[:100],
    ]
    with open(tsv_path, "a") as f:
        f.write("\t".join(row_vals) + "\n")

    save_state(state)
    return state


def generate_progress_summary(state: dict) -> str:
    """Format human-readable progress summary."""
    lines = [
        f"Iteration: {state['iteration']}",
        f"Best Score: {state['best_score']:.2f}% return",
        f"Baseline: {state['baseline_score']:.2f}%",
        f"KEEPs: {state['total_keeps']}",
        f"DISCARDs: {state['total_discards']}",
        f"CRASHes: {state['total_crashes']}",
    ]
    if state["baseline_score"] > 0:
        improvement = state["best_score"] - state["baseline_score"]
        lines.append(f"Improvement: {improvement:+.2f}%")
    return "\n".join(lines)
