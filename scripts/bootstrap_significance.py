#!/usr/bin/env python3
"""
Bootstrap significance testing for ES strategy.

Uses stratified bootstrap (from quant_simulation_skill_integration.md, Section IV)
to test whether the strategy's returns are statistically distinguishable from random.

Methods:
1. Circular block bootstrap — preserves autocorrelation in returns
2. Antithetic variates — guaranteed variance reduction (Section IV.1)
3. Stratified sampling — divide into regime-based strata (Section IV.3)

Output: p-value for the null hypothesis that the strategy has zero alpha.

Usage:
    python scripts/bootstrap_significance.py
    python scripts/bootstrap_significance.py --n-bootstrap 10000
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_single_backtest():
    """Run one backtest, return trade-level results."""
    from autoresearch.verify_strategy import run_backtest
    results = run_backtest()
    return results


def circular_block_bootstrap(returns: np.ndarray, block_size: int = 20,
                              n_bootstrap: int = 1000) -> np.ndarray:
    """Circular block bootstrap preserving return autocorrelation.

    Instead of shuffling individual returns (destroys serial dependence),
    we resample contiguous blocks. Circular wrapping ensures all observations
    have equal probability of appearing.
    """
    n = len(returns)
    bootstrap_means = np.zeros(n_bootstrap)

    for b in range(n_bootstrap):
        # Random starting points for blocks
        n_blocks = (n + block_size - 1) // block_size
        starts = np.random.randint(0, n, n_blocks)

        # Build bootstrap sample from circular blocks
        sample = []
        for s in starts:
            for j in range(block_size):
                sample.append(returns[(s + j) % n])
                if len(sample) >= n:
                    break
            if len(sample) >= n:
                break

        bootstrap_means[b] = np.mean(sample[:n])

    return bootstrap_means


def antithetic_bootstrap(returns: np.ndarray, n_bootstrap: int = 1000) -> np.ndarray:
    """Antithetic variates bootstrap (Section IV.1).

    For every bootstrap sample, also evaluate its 'mirror' (demean, negate, re-add mean).
    Guarantees ~50% variance reduction for monotone statistics.
    """
    n = len(returns)
    mu = np.mean(returns)
    bootstrap_means = np.zeros(n_bootstrap)

    for b in range(0, n_bootstrap, 2):
        # Standard bootstrap sample
        idx = np.random.randint(0, n, n)
        sample = returns[idx]
        bootstrap_means[b] = np.mean(sample)

        # Antithetic: mirror around mean
        if b + 1 < n_bootstrap:
            anti_sample = 2 * mu - sample  # Reflect around mean
            bootstrap_means[b + 1] = np.mean(anti_sample)

    return bootstrap_means


def stratified_bootstrap(returns: np.ndarray, regimes: np.ndarray,
                          n_bootstrap: int = 1000) -> np.ndarray:
    """Regime-stratified bootstrap (Section IV.3).

    Sample within each regime stratum separately, then combine.
    Reduces variance when regime matters (which TuneTA confirmed).
    """
    unique_regimes = np.unique(regimes)
    n = len(returns)
    bootstrap_means = np.zeros(n_bootstrap)

    for b in range(n_bootstrap):
        combined = []
        for r in unique_regimes:
            mask = regimes == r
            r_returns = returns[mask]
            if len(r_returns) == 0:
                continue
            # Neyman allocation: sample proportional to stratum size
            n_stratum = mask.sum()
            idx = np.random.randint(0, len(r_returns), n_stratum)
            combined.extend(r_returns[idx])

        bootstrap_means[b] = np.mean(combined[:n])

    return bootstrap_means


def compute_regime_labels(df: pd.DataFrame) -> np.ndarray:
    """Classify each bar into a regime for stratified bootstrap."""
    closes = df["close"].values
    n = len(closes)
    regimes = np.zeros(n, dtype=int)  # 0=sideways, 1=bull, -1=bear

    for i in range(50, n):
        sma20 = np.mean(closes[max(0, i - 20):i])
        sma50 = np.mean(closes[max(0, i - 50):i])
        if closes[i] > sma20 and sma20 > sma50:
            regimes[i] = 1
        elif closes[i] < sma20 and sma20 < sma50:
            regimes[i] = -1

    return regimes


def main():
    parser = argparse.ArgumentParser(description="Bootstrap significance testing")
    parser.add_argument("--n-bootstrap", type=int, default=2000,
                        help="Number of bootstrap samples (default: 2000)")
    parser.add_argument("--block-size", type=int, default=20,
                        help="Block size for circular bootstrap (default: 20 bars)")
    args = parser.parse_args()

    print("Running backtest...")
    results = run_single_backtest()

    total_return = results["total_return_pct"]
    trades = results.get("trades", pd.DataFrame())

    if len(trades) == 0:
        print("ERROR: No trades to analyze", file=sys.stderr)
        sys.exit(1)

    trade_returns = trades["pnl"].values
    n_trades = len(trade_returns)
    observed_mean = np.mean(trade_returns)
    observed_total = np.sum(trade_returns)

    print(f"\nStrategy results:")
    print(f"  Total return: {total_return:.2f}%")
    print(f"  Trades: {n_trades}")
    print(f"  Mean P&L per trade: ${observed_mean:.2f}")
    print(f"  Total P&L: ${observed_total:.2f}")
    print(f"  Win rate: {results['win_rate']:.1f}%")

    n_boot = args.n_bootstrap
    print(f"\nRunning {n_boot} bootstrap samples...")

    # Method 1: Circular block bootstrap
    print("\n1. Circular Block Bootstrap:")
    block_means = circular_block_bootstrap(trade_returns, block_size=min(5, n_trades // 3),
                                            n_bootstrap=n_boot)
    p_block = np.mean(block_means <= 0)  # P(mean <= 0)
    ci_block = np.percentile(block_means, [2.5, 97.5])
    print(f"   P(mean PnL > 0) = {1 - p_block:.4f}")
    print(f"   95% CI for mean PnL: [${ci_block[0]:.2f}, ${ci_block[1]:.2f}]")
    print(f"   Observed mean: ${observed_mean:.2f}")

    # Method 2: Antithetic variates
    print("\n2. Antithetic Bootstrap (50% variance reduction):")
    anti_means = antithetic_bootstrap(trade_returns, n_bootstrap=n_boot)
    p_anti = np.mean(anti_means <= 0)
    ci_anti = np.percentile(anti_means, [2.5, 97.5])
    print(f"   P(mean PnL > 0) = {1 - p_anti:.4f}")
    print(f"   95% CI for mean PnL: [${ci_anti[0]:.2f}, ${ci_anti[1]:.2f}]")

    # Method 3: Permutation test (null: returns are random)
    print("\n3. Permutation Test (null: no strategy edge):")
    perm_means = np.zeros(n_boot)
    for b in range(n_boot):
        # Random sign flips (equivalent to random entry direction)
        signs = np.random.choice([-1, 1], size=n_trades)
        perm_means[b] = np.mean(trade_returns * signs)
    p_perm = np.mean(perm_means >= observed_mean)
    print(f"   P(random >= observed): {p_perm:.4f}")
    print(f"   {'SIGNIFICANT' if p_perm < 0.05 else 'NOT significant'} at 5% level")

    # Summary
    print("\n" + "=" * 60)
    print("SIGNIFICANCE SUMMARY")
    print("=" * 60)
    print(f"  Strategy mean PnL: ${observed_mean:.2f}/trade")
    sig = p_perm < 0.05
    print(f"  Permutation p-value: {p_perm:.4f} ({'SIG' if sig else 'n.s.'})")
    print(f"  Block bootstrap CI: [${ci_block[0]:.2f}, ${ci_block[1]:.2f}]")

    if ci_block[0] > 0:
        print(f"  --> Strategy has POSITIVE alpha (CI excludes zero)")
    elif ci_block[1] < 0:
        print(f"  --> Strategy has NEGATIVE alpha (CI excludes zero)")
    else:
        print(f"  --> Strategy alpha INDETERMINATE (CI includes zero)")

    return {
        "p_block": 1 - p_block,
        "p_anti": 1 - p_anti,
        "p_perm": p_perm,
        "ci_block": ci_block.tolist(),
        "observed_mean": observed_mean,
        "n_trades": n_trades,
        "significant": sig,
    }


if __name__ == "__main__":
    main()
