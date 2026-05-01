#!/usr/bin/env python3
"""
Dual-System Backtest: Composite Strategy + MR Scalper running independently.

The composite strategy handles normal/trend days.
The MR scalper handles high-volatility mean-reversion days.
Each system gets its own capital allocation and they never interfere.

Combined equity = sum of both equity curves.
"""
import sys
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_mr_scalper import ScalperConfig, run_scalper_backtest


def run_composite_backtest():
    """Run the composite strategy via verify_strategy.py and capture results."""
    # Use env override or current Python interpreter; never hardcode user-specific paths.
    import os as _os
    PYTHON = _os.environ.get("PYTHON_INTERPRETER", sys.executable)
    result = subprocess.run(
        [PYTHON, str(PROJECT_ROOT / "autoresearch" / "verify_strategy.py")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT / "autoresearch")
    )

    # Parse the JSON output line (may be in stdout or stderr)
    metrics = {}
    all_output = (result.stderr or "") + "\n" + (result.stdout or "")
    for line in all_output.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") and "score" in line:
            try:
                data = json.loads(line)
                metrics["return_pct"] = data.get("total_return_pct", 0)
                metrics["max_dd_pct"] = data.get("max_drawdown_pct", 0)
                metrics["trades"] = data.get("total_trades", 0)
                metrics["win_rate"] = data.get("win_rate", 0)
                metrics["score"] = data.get("score", 0)
                metrics["sharpe"] = data.get("sharpe_ratio", 0)
                metrics["profit_factor"] = data.get("profit_factor", 0)
                metrics["long_trades"] = data.get("long_trades", 0)
                metrics["short_trades"] = data.get("short_trades", 0)
                metrics["long_pnl"] = data.get("long_pnl", 0)
                metrics["short_pnl"] = data.get("short_pnl", 0)
                break
            except json.JSONDecodeError:
                pass

    return metrics, result.stdout


def run_mr_scalper(capital=100_000):
    """Run the MR scalper with best known config."""
    cfg = ScalperConfig(
        # Best config from sweep: RSI(12) < 25, LONG only
        use_rsi=True,
        rsi_period=12,
        rsi_long_entry=25,
        rsi_short_entry=80,
        use_bb=False,
        use_vwap=False,
        use_dist_from_open=False,
        use_volume_climax=False,
        min_signals=1,
        side="LONG",
        rsi_long_exit=55,
        max_hold_bars=24,
        stop_atr_mult=1.5,
        tp_atr_mult=2.0,
        capital=capital,
        risk_per_trade=2_000,
        max_trades_per_day=3,
        cooldown_bars=6,
        min_daily_atr_pct=1.5,
        max_daily_atr_pct=5.0,
        entry_utc_start=14,
        entry_utc_end=20,
    )
    return run_scalper_backtest(cfg)


def main():
    print("=" * 70)
    print("  DUAL-SYSTEM BACKTEST")
    print("  System A: Composite (trend/regime) — full config")
    print("  System B: MR Scalper (high-vol days) — RSI(12) < 25, LONG only")
    print("=" * 70)

    # --- System A: Composite ---
    print("\n▶ Running composite strategy...")
    composite_metrics, composite_raw = run_composite_backtest()

    comp_return = composite_metrics.get("return_pct", 0)
    comp_dd = composite_metrics.get("max_dd_pct", 0)
    comp_trades = composite_metrics.get("trades", 0)
    comp_wr = composite_metrics.get("win_rate", 0)

    print(f"  Composite: {comp_return:+.2f}% return | {comp_dd:.1f}% DD | {comp_trades} trades | {comp_wr:.0f}% WR")

    # --- System B: MR Scalper ---
    print("\n▶ Running MR scalper...")
    mr_result = run_mr_scalper(capital=100_000)

    mr_return = mr_result["return_pct"]
    mr_dd = mr_result["max_dd_pct"]
    mr_trades = mr_result["total_trades"]
    mr_wr = mr_result["win_rate"]

    print(f"  MR Scalp:  {mr_return:+.2f}% return | {mr_dd:.1f}% DD | {mr_trades} trades | {mr_wr:.0f}% WR")

    # --- Combined (each system with $100K, total $200K capital) ---
    # Combined return = weighted average (equal allocation)
    combined_pnl_pct = (comp_return + mr_return) / 2  # On $200K total
    # Or: on $100K each, total PnL = comp_pnl + mr_pnl
    comp_pnl = comp_return / 100 * 100_000
    mr_pnl = mr_return / 100 * 100_000
    total_pnl = comp_pnl + mr_pnl
    total_capital = 200_000
    combined_return_200k = total_pnl / total_capital * 100
    combined_return_100k = total_pnl / 100_000 * 100  # If viewing as single $100K account

    # Conservative DD estimate: max of individual DDs (they trade different days)
    # Since MR only trades high-vol days and composite trades all days,
    # DDs are largely non-overlapping, but worst case is additive
    combined_dd_conservative = max(comp_dd, mr_dd)
    combined_dd_worst = (comp_dd + mr_dd) / 2  # Weighted

    total_trades = comp_trades + mr_trades
    combined_wr = "N/A"

    print("\n" + "=" * 70)
    print("  COMBINED RESULTS")
    print("=" * 70)
    print(f"\n  Allocation: $100K composite + $100K MR scalper = $200K total")
    print(f"  Combined return (on $200K): {combined_return_200k:+.2f}%")
    print(f"  Combined return (on $100K): {combined_return_100k:+.2f}%")
    print(f"  Combined PnL: ${total_pnl:+,.0f}")
    print(f"  Max DD (conservative): {combined_dd_conservative:.1f}%")
    print(f"  Max DD (worst case avg): {combined_dd_worst:.1f}%")
    print(f"  Total trades: {total_trades}")

    # Risk-adjusted score (using $200K base)
    score_200k = combined_return_200k * (1 - combined_dd_conservative / 100)
    score_100k = combined_return_100k * (1 - combined_dd_conservative / 100)
    print(f"\n  Score (on $200K): {score_200k:+.2f}")
    print(f"  Score (on $100K): {score_100k:+.2f}")

    print("\n" + "-" * 70)
    print("  CAPITAL ALLOCATION SCENARIOS")
    print("-" * 70)

    for alloc_mr in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        alloc_comp = 1 - alloc_mr
        cap = 100_000
        pnl = (comp_return / 100 * cap * alloc_comp) + (mr_return / 100 * cap * alloc_mr)
        ret = pnl / cap * 100
        dd_est = comp_dd * alloc_comp + mr_dd * alloc_mr
        score = ret * (1 - dd_est / 100) if dd_est < 60 else 0
        print(f"  {alloc_comp:.0%} Comp + {alloc_mr:.0%} MR: {ret:+.2f}% return | ~{dd_est:.1f}% DD | score {score:+.2f}")

    print()


if __name__ == "__main__":
    main()
