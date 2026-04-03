#!/usr/bin/env python3
"""Run dual-strategy backtest: 5-min + hourly configs independently.

Runs verify_strategy.py with each config, then reports combined results.
Capital is split 50/50 between the two strategies.

Usage:
  python scripts/run_dual_backtest.py
  python scripts/run_dual_backtest.py --fivemin-config path/to/config.py
  python scripts/run_dual_backtest.py --hourly-config path/to/config.py
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_FIVEMIN_CONFIG = str(PROJECT_ROOT / "autoresearch" / "es_strategy_config.py")
DEFAULT_HOURLY_CONFIG = str(PROJECT_ROOT / "autoresearch" / "es_strategy_config_hourly.py")


def run_config(config_path, label):
    """Run verify_strategy.py with a specific config, return results dict."""
    print(f"\n{'='*60}")
    print(f"  Running {label}: {Path(config_path).name}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "autoresearch" / "verify_strategy.py"),
         "--config", config_path],
        capture_output=True, text=True, timeout=700,
        cwd=str(PROJECT_ROOT),
    )

    # Parse SCORE from stdout
    score = 0.0
    for line in result.stdout.strip().split("\n"):
        if line.startswith("SCORE:"):
            try:
                score = float(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass

    # Parse metrics JSON from stderr
    metrics = {}
    for line in result.stderr.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                metrics = json.loads(line)
            except json.JSONDecodeError:
                pass

    metrics["score"] = score
    return metrics


def print_strategy_summary(label, metrics):
    """Print a single strategy's results."""
    print(f"\n  {label}:")
    print(f"    Score:      {metrics.get('score', 0):.2f}")
    print(f"    Return:     {metrics.get('total_return_pct', 0):.2f}%")
    print(f"    Max DD:     {metrics.get('max_drawdown_pct', 0):.2f}%")
    print(f"    Win Rate:   {metrics.get('win_rate', 0):.2f}%")
    print(f"    Trades:     {metrics.get('total_trades', 0)}")
    print(f"    Sharpe:     {metrics.get('sharpe_ratio', 0):.4f}")
    print(f"    PF:         {metrics.get('profit_factor', 0):.4f}")
    if "long_trades" in metrics:
        print(f"    Long/Short: {metrics.get('long_trades', 0)}/{metrics.get('short_trades', 0)}")
        print(f"    Long PnL:   ${metrics.get('long_pnl', 0):,.2f}")
        print(f"    Short PnL:  ${metrics.get('short_pnl', 0):,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Run dual-strategy backtest")
    parser.add_argument("--fivemin-config", default=DEFAULT_FIVEMIN_CONFIG,
                        help="Path to 5-min strategy config")
    parser.add_argument("--hourly-config", default=DEFAULT_HOURLY_CONFIG,
                        help="Path to hourly strategy config")
    args = parser.parse_args()

    # Run both strategies
    fivemin = run_config(args.fivemin_config, "5-Min Strategy")
    hourly = run_config(args.hourly_config, "Hourly Strategy")

    # Combined metrics (50/50 capital split)
    fm_return = fivemin.get("total_return_pct", 0)
    hr_return = hourly.get("total_return_pct", 0)
    combined_return = fm_return / 2 + hr_return / 2  # weighted by capital allocation

    fm_dd = fivemin.get("max_drawdown_pct", 0)
    hr_dd = hourly.get("max_drawdown_pct", 0)
    combined_dd = max(fm_dd, hr_dd)  # conservative: worst of the two

    combined_trades = fivemin.get("total_trades", 0) + hourly.get("total_trades", 0)

    fm_wr = fivemin.get("win_rate", 0)
    hr_wr = hourly.get("win_rate", 0)
    fm_trades = fivemin.get("total_trades", 0)
    hr_trades = hourly.get("total_trades", 0)
    if combined_trades > 0:
        combined_wr = (fm_wr * fm_trades + hr_wr * hr_trades) / combined_trades
    else:
        combined_wr = 0

    # Print comparison table
    print(f"\n{'='*60}")
    print(f"  DUAL-STRATEGY BACKTEST RESULTS")
    print(f"{'='*60}")

    print_strategy_summary("5-Min Strategy (50% capital)", fivemin)
    print_strategy_summary("Hourly Strategy (50% capital)", hourly)

    print(f"\n  {'─'*56}")
    print(f"  COMBINED (50/50 capital split):")
    print(f"    Return:     {combined_return:.2f}%")
    print(f"    Max DD:     {combined_dd:.2f}% (conservative: max of both)")
    print(f"    Win Rate:   {combined_wr:.2f}% (trade-weighted)")
    print(f"    Trades:     {combined_trades}")

    # Diversification benefit
    if fm_dd > 0 and hr_dd > 0:
        naive_dd = (fm_dd + hr_dd) / 2
        div_benefit = naive_dd - combined_dd
        if div_benefit > 0:
            print(f"    Div Benefit: {div_benefit:.2f}% DD reduction vs naive avg")

    print(f"{'='*60}\n")

    # Output combined JSON for programmatic use
    combined = {
        "combined_return_pct": round(combined_return, 2),
        "combined_max_dd_pct": round(combined_dd, 2),
        "combined_trades": combined_trades,
        "combined_win_rate": round(combined_wr, 2),
        "fivemin": fivemin,
        "hourly": hourly,
    }
    print(json.dumps(combined), file=sys.stderr)


if __name__ == "__main__":
    main()
