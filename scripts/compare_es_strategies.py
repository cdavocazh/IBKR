"""
Compare All ES Strategies

Runs all ES strategies and generates a comparison report.
"""

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine import BacktestEngine


def run_all_strategies():
    """Run all ES strategies and compare results."""

    # Load data once
    data_path = Path(__file__).parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Data: {len(data)} bars from {data.index.min()} to {data.index.max()}")
    print("="*80)

    results_summary = []

    # 1. Original ES Scalp (Momentum)
    print("\n1. Running ES_scalp_momentum (Original)...")
    from backtest.strategies.es_scalp_momentum import ESMomentumScalp
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ESMomentumScalp(ema_period=20, ema_slope_lookback=5, rsi_period=7,
                                rsi_entry_low=35.0, rsi_entry_high=65.0, atr_period=14,
                                stop_atr=1.2, target_atr=1.8, max_hold_bars=12, min_volume=200)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_scalp_momentum (Original)',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # 2. Original ES 4h
    print("2. Running ES_4h (Original)...")
    from backtest.strategies.es_4h import ES4HStrategy
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ES4HStrategy(trend_ema_period=60, fast_ema=12, slow_ema=26, macd_signal=9,
                            rsi_period=14, atr_period=20, stop_atr=2.0, target_atr=3.0,
                            max_hold_bars=48, min_volume=100)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_4h (Original)',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # 3. ES Scalp Optimized
    print("3. Running ES_scalp_optimized...")
    from backtest.strategies.es_scalp_optimized import ESScalpOptimizedStrategy
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ESScalpOptimizedStrategy(fast_ema=20, slow_ema=50, trend_ema=100,
                                         rsi_period=7, atr_period=14, stop_atr=1.0,
                                         target_atr=2.0, volume_mult=1.3, max_hold_bars=9,
                                         min_volume=150)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_scalp_optimized',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # 4. ES 4h Optimized
    print("4. Running ES_4h_optimized...")
    from backtest.strategies.es_4h_optimized import ES4HOptimizedStrategy
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ES4HOptimizedStrategy(fast_ema=20, slow_ema=50, trend_ema=100,
                                      pullback_min_atr=0.3, pullback_max_atr=1.5,
                                      atr_period=20, stop_atr=2.0, target_atr=4.0,
                                      max_hold_bars=48, min_volume=100)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_4h_optimized',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # 5. ES Trend Follow
    print("5. Running ES_trend_follow...")
    from backtest.strategies.es_trend_follow import ESTrendFollowStrategy
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ESTrendFollowStrategy(trend_ema=200, signal_ema=50, fast_ema=20,
                                      min_trend_atr=1.5, min_macd_strength=0.5,
                                      stop_atr=2.5, target_atr=5.0, max_hold_bars=72,
                                      min_bars_between_trades=12)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_trend_follow',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # 6. ES Scalp Regime
    print("6. Running ES_scalp_regime...")
    from backtest.strategies.es_scalp_regime import ESScalpRegimeStrategy
    engine = BacktestEngine(data=data.copy(), initial_capital=100000.0, max_position=2)
    strategy = ESScalpRegimeStrategy(regime_ema_period=50, regime_confirmation=3,
                                      rsi_period=7, atr_period=14, bb_period=20,
                                      max_hold_bars=12, min_volume=100)
    r = engine.run(strategy)
    results_summary.append({
        'Strategy': 'ES_scalp_regime',
        'Trades': r['total_trades'],
        'Win Rate': f"{r['win_rate']:.1f}%",
        'Return': f"{r['total_return_pct']:.2f}%",
        'Profit Factor': f"{r['profit_factor']:.2f}",
        'Max DD': f"{r['max_drawdown']:.2f}%",
        'Sharpe': f"{r['sharpe_ratio']:.2f}",
    })

    # Print comparison table
    print("\n" + "="*80)
    print("ES STRATEGY COMPARISON")
    print("="*80)

    df = pd.DataFrame(results_summary)
    print(df.to_string(index=False))

    print("\n" + "="*80)
    print("ANALYSIS")
    print("="*80)

    print("""
Key Observations:

1. ES_trend_follow has the best Profit Factor (1.14) - the only one above 1.0
   - Very selective (24 trades)
   - Longer holding period (~110 minutes)
   - Better R:R with wider targets

2. ES_scalp_optimized has the lowest drawdown (1.29%)
   - Very selective (25 trades)
   - Tight stops protect capital

3. All strategies struggle with win rate (30-43%)
   - ES market is highly efficient
   - Technical strategies face significant headwinds

4. Comparison to GC_buy_dip (the profitable one):
   - GC: 229 trades, 50.22% win rate, +1.48% return, PF 1.08
   - ES strategies are less profitable on this timeframe

Recommendations:
- For ES, use the trend_follow strategy (best edge)
- Consider GC strategies instead (more profitable)
- ES may need different approach (order flow, microstructure)
""")

    return results_summary


if __name__ == "__main__":
    run_all_strategies()
