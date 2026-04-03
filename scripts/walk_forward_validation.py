#!/usr/bin/env python3
"""
Walk-Forward Validation for ES Futures Backtest Strategy.

Detects overfitting by splitting data into train/test periods and comparing
in-sample (IS) vs out-of-sample (OOS) performance.

Methods:
  1. Anchored walk-forward: expanding training window, fixed test window
  2. Simple 70/30 split

Usage:
    python scripts/walk_forward_validation.py
"""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "autoresearch"))

from backtest.engine import BacktestEngine

# Import verify_strategy helpers without running main()
_vs_path = PROJECT_ROOT / "autoresearch" / "verify_strategy.py"
_vs_spec = importlib.util.spec_from_file_location("verify_strategy", _vs_path)
_vs = importlib.util.module_from_spec(_vs_spec)
_vs_spec.loader.exec_module(_vs)

load_config = _vs.load_config
load_macro_data = _vs.load_macro_data
load_nlp_regime = _vs.load_nlp_regime
load_digest_context = _vs.load_digest_context
load_daily_es_trend = _vs.load_daily_es_trend
load_daily_sentiment = _vs.load_daily_sentiment
load_garch_forecast = _vs.load_garch_forecast
load_particle_regime = _vs.load_particle_regime
load_cusum_events = _vs.load_cusum_events
ESAutoResearchStrategy = _vs.ESAutoResearchStrategy


def load_es_1min():
    """Load raw 1-min ES data."""
    path = PROJECT_ROOT / "data" / "es" / "ES_1min.parquet"
    return pd.read_parquet(path)


def resample_to_5min(df):
    """Resample 1-min bars to 5-min, matching verify_strategy.py logic."""
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    has_range = (df_5m["high"] - df_5m["low"]) > 0
    has_volume = df_5m["volume"] > 0
    df_5m = df_5m[has_range | has_volume].copy()
    return df_5m


def slice_data(df_1min, start_date, end_date):
    """Slice 1-min data by date range and resample to 5-min."""
    tz = df_1min.index.tz
    start_ts = pd.Timestamp(start_date, tz=tz)
    end_ts = pd.Timestamp(end_date, tz=tz)
    mask = (df_1min.index >= start_ts) & (df_1min.index < end_ts)
    sliced = df_1min[mask].copy()
    if len(sliced) == 0:
        return sliced
    return resample_to_5min(sliced)


def run_backtest_on_data(df_5m, cfg, macro_data, nlp_regime, digest_ctx,
                          daily_trend, daily_sentiment, garch_forecast,
                          particle_regime, cusum_events, cusum_directions):
    """Run the backtest on a specific 5-min DataFrame."""
    if len(df_5m) < 100:
        return None

    engine = BacktestEngine(
        data=df_5m,
        initial_capital=cfg.INITIAL_CAPITAL,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=50,
    )
    strategy = ESAutoResearchStrategy(
        cfg, macro_data, nlp_regime, digest_ctx, daily_trend,
        daily_sentiment, garch_forecast, particle_regime,
        cusum_events, cusum_directions
    )
    engine.set_strategy(strategy.on_bar)

    # Suppress engine prints
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        results = engine.run()

    return results


def extract_metrics(results):
    """Extract key metrics from backtest results dict."""
    if results is None:
        return {
            "return_pct": 0.0, "max_dd": 0.0, "win_rate": 0.0,
            "trades": 0, "sharpe": 0.0, "profit_factor": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
        }
    return {
        "return_pct": round(results["total_return_pct"], 2),
        "max_dd": round(results["max_drawdown"], 2),
        "win_rate": round(results["win_rate"], 1),
        "trades": results["total_trades"],
        "sharpe": round(results["sharpe_ratio"], 3),
        "profit_factor": round(results["profit_factor"], 2),
        "avg_win": round(results["avg_win"], 2),
        "avg_loss": round(results["avg_loss"], 2),
    }


def print_separator(char="=", width=100):
    print(char * width)


def print_metrics_table(rows, headers):
    """Print a formatted table of metrics."""
    col_widths = [max(len(str(row[i])) for row in [headers] + rows) + 2 for i in range(len(headers))]

    # Header
    header_line = ""
    for i, h in enumerate(headers):
        header_line += str(h).ljust(col_widths[i])
    print(header_line)
    print("-" * sum(col_widths))

    # Rows
    for row in rows:
        line = ""
        for i, val in enumerate(row):
            line += str(val).ljust(col_widths[i])
        print(line)


def main():
    print_separator()
    print("  WALK-FORWARD VALIDATION — ES Futures Strategy")
    print("  Detecting overfitting from ~500 optimization iterations")
    print_separator()
    print()

    # Load shared data
    print("Loading data...")
    df_1min = load_es_1min()
    print(f"  1-min bars: {len(df_1min):,} ({df_1min.index.min()} to {df_1min.index.max()})")

    cfg = load_config()
    macro_data = load_macro_data()
    nlp_regime = load_nlp_regime()
    digest_ctx = load_digest_context()
    daily_trend = load_daily_es_trend()
    daily_sentiment = load_daily_sentiment()
    garch_forecast = load_garch_forecast()
    particle_regime = load_particle_regime()
    cusum_events, cusum_directions = load_cusum_events()
    print("  Config, macro, sentiment, overlays loaded.")
    print()

    # ──────────────────────────────────────────────────────────
    # Step 1: Full-period baseline (in-sample)
    # ──────────────────────────────────────────────────────────
    print_separator("-")
    print("STEP 1: Full-period baseline (In-Sample)")
    print_separator("-")

    df_full_5m = resample_to_5min(df_1min)
    print(f"  5-min bars: {len(df_full_5m):,}")

    results_full = run_backtest_on_data(
        df_full_5m, cfg, macro_data, nlp_regime, digest_ctx,
        daily_trend, daily_sentiment, garch_forecast,
        particle_regime, cusum_events, cusum_directions
    )
    m_full = extract_metrics(results_full)
    print(f"  Return: {m_full['return_pct']:+.2f}%  |  DD: {m_full['max_dd']:.2f}%  |  "
          f"WR: {m_full['win_rate']:.1f}%  |  Trades: {m_full['trades']}  |  "
          f"Sharpe: {m_full['sharpe']:.3f}  |  PF: {m_full['profit_factor']:.2f}")
    print()

    # ──────────────────────────────────────────────────────────
    # Step 2: Anchored Walk-Forward
    # ──────────────────────────────────────────────────────────
    print_separator("-")
    print("STEP 2: Anchored Walk-Forward (expanding train, fixed test)")
    print_separator("-")

    # Check data density to set appropriate splits
    monthly = df_1min.resample("ME").size()
    print("  Monthly bar distribution:")
    for dt, cnt in monthly.items():
        print(f"    {dt.strftime('%Y-%m')}: {cnt:>6} bars")
    print()

    # Define walk-forward splits based on actual data density
    # Data is dense from Jul 2025 onward (~15K-31K bars/month)
    # Sparse before Jul 2025 (~400-4400 bars/month)
    wf_splits = [
        {
            "name": "Fold 1",
            "train": ("2025-07-01", "2025-11-01"),
            "test":  ("2025-11-01", "2026-01-01"),
            "desc":  "Train Jul-Oct 2025, Test Nov-Dec 2025",
        },
        {
            "name": "Fold 2",
            "train": ("2025-07-01", "2026-01-01"),
            "test":  ("2026-01-01", "2026-03-01"),
            "desc":  "Train Jul 2025-Dec 2025, Test Jan-Feb 2026",
        },
        {
            "name": "Fold 3",
            "train": ("2025-07-01", "2026-02-01"),
            "test":  ("2026-02-01", "2026-04-01"),
            "desc":  "Train Jul 2025-Jan 2026, Test Feb-Mar 2026",
        },
    ]

    wf_results = []
    for split in wf_splits:
        name = split["name"]
        train_start, train_end = split["train"]
        test_start, test_end = split["test"]

        print(f"\n  {name}:")
        print(f"    Train: {train_start} to {train_end}")
        print(f"    Test:  {test_start} to {test_end}")

        # Run on train period
        df_train = slice_data(df_1min, train_start, train_end)
        r_train = run_backtest_on_data(
            df_train, cfg, macro_data, nlp_regime, digest_ctx,
            daily_trend, daily_sentiment, garch_forecast,
            particle_regime, cusum_events, cusum_directions
        )
        m_train = extract_metrics(r_train)

        # Run on test period
        df_test = slice_data(df_1min, test_start, test_end)
        r_test = run_backtest_on_data(
            df_test, cfg, macro_data, nlp_regime, digest_ctx,
            daily_trend, daily_sentiment, garch_forecast,
            particle_regime, cusum_events, cusum_directions
        )
        m_test = extract_metrics(r_test)

        print(f"    Train 5m bars: {len(df_train):,}  |  Test 5m bars: {len(df_test):,}")
        print(f"    Train: Ret={m_train['return_pct']:+.2f}%  DD={m_train['max_dd']:.2f}%  "
              f"WR={m_train['win_rate']:.1f}%  Trades={m_train['trades']}  Sharpe={m_train['sharpe']:.3f}")
        print(f"    Test:  Ret={m_test['return_pct']:+.2f}%  DD={m_test['max_dd']:.2f}%  "
              f"WR={m_test['win_rate']:.1f}%  Trades={m_test['trades']}  Sharpe={m_test['sharpe']:.3f}")

        wf_results.append({
            "name": name,
            "train": m_train,
            "test": m_test,
            "train_period": f"{train_start} to {train_end}",
            "test_period": f"{test_start} to {test_end}",
        })

    # ──────────────────────────────────────────────────────────
    # Step 3: Simple 70/30 Split
    # ──────────────────────────────────────────────────────────
    print()
    print_separator("-")
    print("STEP 3: Simple 70/30 Split")
    print_separator("-")

    total_days = (df_1min.index.max() - df_1min.index.min()).days
    split_date = df_1min.index.min() + pd.Timedelta(days=int(total_days * 0.7))
    split_date_str = split_date.strftime("%Y-%m-%d")

    print(f"  Split date: {split_date_str}")
    print(f"  Train: {df_1min.index.min().strftime('%Y-%m-%d')} to {split_date_str}")
    print(f"  Test:  {split_date_str} to {df_1min.index.max().strftime('%Y-%m-%d')}")

    train_start_str = df_1min.index.min().strftime("%Y-%m-%d")
    test_end_str = (df_1min.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df_train_70 = slice_data(df_1min, train_start_str, split_date_str)
    df_test_30 = slice_data(df_1min, split_date_str, test_end_str)

    print(f"  Train 5m bars: {len(df_train_70):,}  |  Test 5m bars: {len(df_test_30):,}")

    r_train_70 = run_backtest_on_data(
        df_train_70, cfg, macro_data, nlp_regime, digest_ctx,
        daily_trend, daily_sentiment, garch_forecast,
        particle_regime, cusum_events, cusum_directions
    )
    r_test_30 = run_backtest_on_data(
        df_test_30, cfg, macro_data, nlp_regime, digest_ctx,
        daily_trend, daily_sentiment, garch_forecast,
        particle_regime, cusum_events, cusum_directions
    )
    m_train_70 = extract_metrics(r_train_70)
    m_test_30 = extract_metrics(r_test_30)

    print(f"  Train: Ret={m_train_70['return_pct']:+.2f}%  DD={m_train_70['max_dd']:.2f}%  "
          f"WR={m_train_70['win_rate']:.1f}%  Trades={m_train_70['trades']}  Sharpe={m_train_70['sharpe']:.3f}")
    print(f"  Test:  Ret={m_test_30['return_pct']:+.2f}%  DD={m_test_30['max_dd']:.2f}%  "
          f"WR={m_test_30['win_rate']:.1f}%  Trades={m_test_30['trades']}  Sharpe={m_test_30['sharpe']:.3f}")

    # ──────────────────────────────────────────────────────────
    # Step 3b: Non-overlapping sequential folds (dense data only)
    # ──────────────────────────────────────────────────────────
    print()
    print_separator("-")
    print("STEP 3b: Non-Overlapping Sequential Folds (Jul 2025 onward, dense data)")
    print_separator("-")

    seq_folds = [
        ("Jul-Sep 2025", "2025-07-01", "2025-10-01"),
        ("Oct-Dec 2025", "2025-10-01", "2026-01-01"),
        ("Jan-Mar 2026", "2026-01-01", "2026-04-01"),
    ]

    seq_results = []
    for name, start, end in seq_folds:
        df_fold = slice_data(df_1min, start, end)
        r = run_backtest_on_data(
            df_fold, cfg, macro_data, nlp_regime, digest_ctx,
            daily_trend, daily_sentiment, garch_forecast,
            particle_regime, cusum_events, cusum_directions
        )
        m = extract_metrics(r)
        seq_results.append((name, m))
        print(f"  {name}: Ret={m['return_pct']:+.2f}%  DD={m['max_dd']:.2f}%  "
              f"WR={m['win_rate']:.1f}%  Trades={m['trades']}  Sharpe={m['sharpe']:.3f}  PF={m['profit_factor']:.2f}")

    # ──────────────────────────────────────────────────────────
    # Step 4: Summary Table
    # ──────────────────────────────────────────────────────────
    print()
    print_separator("=")
    print("  WALK-FORWARD VALIDATION SUMMARY")
    print_separator("=")
    print()

    headers = ["Period", "Type", "Return%", "MaxDD%", "WinRate%", "Trades", "Sharpe", "PF"]
    rows = [
        ["Full Period", "IS", m_full["return_pct"], m_full["max_dd"],
         m_full["win_rate"], m_full["trades"], m_full["sharpe"], m_full["profit_factor"]],
    ]

    for wf in wf_results:
        rows.append([
            f"{wf['name']} Train", "IS",
            wf["train"]["return_pct"], wf["train"]["max_dd"],
            wf["train"]["win_rate"], wf["train"]["trades"],
            wf["train"]["sharpe"], wf["train"]["profit_factor"],
        ])
        rows.append([
            f"{wf['name']} Test", "OOS",
            wf["test"]["return_pct"], wf["test"]["max_dd"],
            wf["test"]["win_rate"], wf["test"]["trades"],
            wf["test"]["sharpe"], wf["test"]["profit_factor"],
        ])

    for name, m in seq_results:
        rows.append([
            f"Seq: {name}", "SEQ",
            m["return_pct"], m["max_dd"],
            m["win_rate"], m["trades"],
            m["sharpe"], m["profit_factor"],
        ])

    rows.append([
        "70/30 Train", "IS",
        m_train_70["return_pct"], m_train_70["max_dd"],
        m_train_70["win_rate"], m_train_70["trades"],
        m_train_70["sharpe"], m_train_70["profit_factor"],
    ])
    rows.append([
        "70/30 Test", "OOS",
        m_test_30["return_pct"], m_test_30["max_dd"],
        m_test_30["win_rate"], m_test_30["trades"],
        m_test_30["sharpe"], m_test_30["profit_factor"],
    ])

    print_metrics_table(rows, headers)

    # ──────────────────────────────────────────────────────────
    # Step 5: Overfit Diagnostics
    # ──────────────────────────────────────────────────────────
    print()
    print_separator("=")
    print("  OVERFIT DIAGNOSTICS")
    print_separator("=")
    print()

    # Collect OOS metrics
    oos_returns = [wf["test"]["return_pct"] for wf in wf_results]
    oos_sharpes = [wf["test"]["sharpe"] for wf in wf_results]
    oos_win_rates = [wf["test"]["win_rate"] for wf in wf_results]
    oos_trades = [wf["test"]["trades"] for wf in wf_results]

    is_return = m_full["return_pct"]
    is_sharpe = m_full["sharpe"]

    # OOS aggregates
    avg_oos_return = np.mean(oos_returns) if oos_returns else 0
    avg_oos_sharpe = np.mean(oos_sharpes) if oos_sharpes else 0
    avg_oos_wr = np.mean(oos_win_rates) if oos_win_rates else 0

    # Ratios
    return_ratio = avg_oos_return / is_return if is_return != 0 else float("inf")
    sharpe_ratio_cmp = avg_oos_sharpe / is_sharpe if is_sharpe != 0 else float("inf")

    print(f"  1. OOS/IS Return Ratio:  {return_ratio:.2f}")
    print(f"     (Avg OOS return: {avg_oos_return:+.2f}%  vs  IS return: {is_return:+.2f}%)")
    if return_ratio < 0:
        print("     >>> WARNING: OOS returns are negative — strong overfitting signal")
    elif return_ratio < 0.3:
        print("     >>> WARNING: OOS < 30% of IS — likely overfit")
    elif return_ratio < 0.5:
        print("     >>> CAUTION: OOS < 50% of IS — possible overfitting")
    elif return_ratio < 0.75:
        print("     >>> MODERATE: OOS 50-75% of IS — some degradation, typical for optimized strategies")
    else:
        print("     >>> GOOD: OOS >= 75% of IS — strategy appears robust")
    print()

    print(f"  2. OOS/IS Sharpe Ratio:  {sharpe_ratio_cmp:.2f}")
    print(f"     (Avg OOS Sharpe: {avg_oos_sharpe:.3f}  vs  IS Sharpe: {is_sharpe:.3f})")
    print()

    print(f"  3. OOS Win Rate Stability:")
    print(f"     IS Win Rate:   {m_full['win_rate']:.1f}%")
    for i, wf in enumerate(wf_results):
        wr_delta = wf["test"]["win_rate"] - m_full["win_rate"]
        print(f"     {wf['name']} OOS:   {wf['test']['win_rate']:.1f}%  (delta: {wr_delta:+.1f}%)")
    print(f"     70/30 OOS:     {m_test_30['win_rate']:.1f}%  (delta: {m_test_30['win_rate'] - m_full['win_rate']:+.1f}%)")
    wr_std = np.std(oos_win_rates + [m_test_30["win_rate"]]) if oos_win_rates else 0
    print(f"     OOS WR Std Dev: {wr_std:.1f}%")
    print()

    print(f"  4. Fold Consistency:")
    positive_folds = sum(1 for r in oos_returns if r > 0)
    total_folds = len(oos_returns)
    print(f"     Positive OOS folds: {positive_folds}/{total_folds}")
    print(f"     70/30 OOS positive: {'Yes' if m_test_30['return_pct'] > 0 else 'No'}")
    print()

    print(f"  5. Trade Activity (OOS):")
    total_oos_trades = sum(oos_trades) + m_test_30["trades"]
    print(f"     Total OOS trades across all folds: {total_oos_trades}")
    if total_oos_trades < 10:
        print("     >>> WARNING: Very few OOS trades — results not statistically significant")
    elif total_oos_trades < 30:
        print("     >>> CAUTION: Limited OOS trades — interpret with care")
    else:
        print("     >>> OK: Sufficient trades for basic statistical inference")
    print()

    # Overall verdict
    print_separator("=")
    print("  VERDICT")
    print_separator("=")

    red_flags = 0
    if return_ratio < 0:
        red_flags += 3
    elif return_ratio < 0.3:
        red_flags += 2
    elif return_ratio < 0.5:
        red_flags += 1
    if sharpe_ratio_cmp < 0:
        red_flags += 2
    elif sharpe_ratio_cmp < 0.3:
        red_flags += 1
    if positive_folds < total_folds / 2:
        red_flags += 2
    if total_oos_trades < 10:
        red_flags += 1
    if wr_std > 20:
        red_flags += 1

    if red_flags >= 4:
        verdict = "LIKELY OVERFIT — strategy performance degrades significantly out-of-sample"
    elif red_flags >= 2:
        verdict = "POSSIBLE OVERFITTING — some degradation observed, consider reducing parameter count"
    elif red_flags >= 1:
        verdict = "MILD CONCERNS — minor degradation, strategy may be partially overfit"
    else:
        verdict = "APPEARS ROBUST — OOS performance consistent with IS"

    print(f"  Red flags: {red_flags}")
    print(f"  {verdict}")
    print_separator("=")


if __name__ == "__main__":
    main()
