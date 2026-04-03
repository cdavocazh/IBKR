"""
Scoring formula for ES autoresearch.

Score = total_return_pct * (1 - max_drawdown_pct / 100) if constraints satisfied, else 0.

This risk-adjusted score penalizes drawdown:
- 10% return with 20% DD -> score = 10 * 0.80 = 8.0
- 10% return with 50% DD -> score = 10 * 0.50 = 5.0
- 6.25% return with 34% DD -> score = 6.25 * 0.66 = 4.12

Constraints:
- max_drawdown_pct <= 60%
- win_rate >= 30%
"""

import math


def compute_robustness_score(
    total_return_pct: float,
    max_drawdown_pct: float,
    total_trades: int,
    win_rate: float,
    max_dd_cap: float = 60.0,
    min_win_rate: float = 30.0,
) -> dict:
    """Compute score with hard constraints on DD and win rate.

    Args:
        total_return_pct: Total return percentage.
        max_drawdown_pct: Maximum drawdown percentage (positive number).
        total_trades: Number of trades.
        win_rate: Win rate percentage (0-100).
        max_dd_cap: Maximum allowed drawdown (hard cutoff).
        min_win_rate: Minimum required win rate.

    Returns:
        Dict with score and component metrics.
    """
    dd = abs(max_drawdown_pct)
    dd_violated = dd > max_dd_cap
    wr_violated = win_rate < min_win_rate
    too_few_trades = total_trades < 5

    if dd_violated or wr_violated or too_few_trades:
        score = 0.0
    else:
        score = total_return_pct * (1 - dd / 100)

    return {
        "score": round(score, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(dd, 2),
        "dd_violated": dd_violated,
        "dd_cap": max_dd_cap,
        "win_rate": round(win_rate, 2),
        "wr_violated": wr_violated,
        "min_win_rate": min_win_rate,
        "total_trades": total_trades,
        "too_few_trades": too_few_trades,
    }


def minimum_improvement_threshold(n_iterations: int, base_threshold: float = 0.05) -> float:
    """Near-zero rising threshold — adopt ANY improvement.

    Reduced from 0.2 to 0.05 to allow incremental hill-climbing.

    Examples (base=0.05):
        iter 1:   0.03
        iter 10:  0.12
        iter 50:  0.20
        iter 100: 0.23
        iter 500: 0.31
        iter 1000: 0.35
    """
    return base_threshold * math.log(1 + n_iterations)
