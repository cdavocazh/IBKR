"""
Trend Analysis for ES Futures

Analyzes historical data to identify:
1. Trend change indicators
2. Bull/Bear/Neutral regime detection
3. Optimal indicators for each regime

This analysis will inform strategy optimization.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Tuple, Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.strategy import Indicator


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate a comprehensive set of indicators for analysis."""
    df = df.copy()

    closes = df['close'].tolist()
    highs = df['high'].tolist()
    lows = df['low'].tolist()

    # Moving Averages
    for period in [10, 20, 50, 100, 200]:
        df[f'sma_{period}'] = df['close'].rolling(period).mean()
        df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    # RSI
    for period in [7, 14, 21]:
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        df[f'rsi_{period}'] = 100 - (100 / (1 + rs))

    # ATR
    for period in [14, 20]:
        tr = pd.DataFrame({
            'hl': df['high'] - df['low'],
            'hc': abs(df['high'] - df['close'].shift(1)),
            'lc': abs(df['low'] - df['close'].shift(1))
        }).max(axis=1)
        df[f'atr_{period}'] = tr.rolling(period).mean()

    # Bollinger Bands
    for period in [20]:
        sma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        df[f'bb_upper_{period}'] = sma + 2 * std
        df[f'bb_lower_{period}'] = sma - 2 * std
        df[f'bb_width_{period}'] = (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}']) / sma
        df[f'bb_pct_{period}'] = (df['close'] - df[f'bb_lower_{period}']) / (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}'])

    # MACD
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # Momentum indicators
    for period in [10, 20]:
        df[f'roc_{period}'] = df['close'].pct_change(period) * 100
        df[f'momentum_{period}'] = df['close'] - df['close'].shift(period)

    # Volatility
    df['volatility_20'] = df['close'].pct_change().rolling(20).std() * np.sqrt(252 * 78)  # Annualized for 5-min bars

    # Volume indicators
    df['volume_sma_20'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_sma_20']

    # Price position relative to MAs
    df['price_above_sma20'] = (df['close'] > df['sma_20']).astype(int)
    df['price_above_sma50'] = (df['close'] > df['sma_50']).astype(int)
    df['price_above_sma100'] = (df['close'] > df['sma_100']).astype(int)

    # MA slopes (rate of change)
    for period in [20, 50]:
        df[f'sma_{period}_slope'] = df[f'sma_{period}'].diff(5) / df[f'sma_{period}'].shift(5) * 100

    # Higher timeframe trend (using rolling window)
    df['trend_strength'] = (df['close'] - df['sma_50']) / df['atr_14']

    return df


def classify_regime(df: pd.DataFrame, lookforward: int = 60) -> pd.DataFrame:
    """
    Classify market regime based on forward returns.

    lookforward: Number of bars to look ahead (60 bars = 5 hours on 5-min data)
    """
    df = df.copy()

    # Calculate forward returns
    df['forward_return'] = df['close'].shift(-lookforward) / df['close'] - 1
    df['forward_return_pct'] = df['forward_return'] * 100

    # Define regime thresholds (based on ATR)
    atr_pct = df['atr_14'] / df['close'] * 100
    threshold = atr_pct * 1.5  # 1.5 ATR move

    # Classify regime
    conditions = [
        df['forward_return_pct'] > threshold,
        df['forward_return_pct'] < -threshold,
    ]
    choices = ['bull', 'bear']
    df['regime'] = np.select(conditions, choices, default='neutral')

    return df


def analyze_indicator_predictiveness(df: pd.DataFrame) -> dict:
    """Analyze which indicators best predict regime changes."""

    results = {}

    # Indicators to analyze
    indicators = [
        'rsi_7', 'rsi_14', 'rsi_21',
        'macd_hist',
        'bb_pct_20',
        'roc_10', 'roc_20',
        'momentum_10', 'momentum_20',
        'trend_strength',
        'volatility_20',
        'volume_ratio',
        'sma_20_slope', 'sma_50_slope',
    ]

    for regime in ['bull', 'bear', 'neutral']:
        regime_df = df[df['regime'] == regime].copy()
        if len(regime_df) < 100:
            continue

        results[regime] = {
            'count': len(regime_df),
            'pct': len(regime_df) / len(df) * 100,
            'indicators': {}
        }

        for ind in indicators:
            if ind not in df.columns:
                continue

            valid = regime_df[ind].dropna()
            if len(valid) > 0:
                results[regime]['indicators'][ind] = {
                    'mean': valid.mean(),
                    'median': valid.median(),
                    'std': valid.std(),
                    'p25': valid.quantile(0.25),
                    'p75': valid.quantile(0.75),
                }

    return results


def find_trend_change_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Identify bars where regime changes occur and analyze preceding indicators."""

    df = df.copy()

    # Identify regime changes
    df['prev_regime'] = df['regime'].shift(1)
    df['regime_change'] = df['regime'] != df['prev_regime']

    # Type of change
    df['change_type'] = None
    df.loc[(df['prev_regime'] == 'bear') & (df['regime'] == 'bull'), 'change_type'] = 'bear_to_bull'
    df.loc[(df['prev_regime'] == 'bull') & (df['regime'] == 'bear'), 'change_type'] = 'bull_to_bear'
    df.loc[(df['prev_regime'] == 'neutral') & (df['regime'] == 'bull'), 'change_type'] = 'neutral_to_bull'
    df.loc[(df['prev_regime'] == 'neutral') & (df['regime'] == 'bear'), 'change_type'] = 'neutral_to_bear'
    df.loc[(df['prev_regime'] == 'bull') & (df['regime'] == 'neutral'), 'change_type'] = 'bull_to_neutral'
    df.loc[(df['prev_regime'] == 'bear') & (df['regime'] == 'neutral'), 'change_type'] = 'bear_to_neutral'

    return df


def generate_regime_rules(analysis_results: dict) -> dict:
    """Generate trading rules based on regime analysis."""

    rules = {}

    for regime, data in analysis_results.items():
        if 'indicators' not in data:
            continue

        ind = data['indicators']

        if regime == 'bull':
            rules['bull'] = {
                'description': 'Bullish regime - favor long positions',
                'entry_conditions': [],
                'exit_conditions': [],
            }

            # RSI conditions
            if 'rsi_14' in ind:
                rules['bull']['entry_conditions'].append(
                    f"RSI(14) between {ind['rsi_14']['p25']:.1f} and {ind['rsi_14']['p75']:.1f}"
                )

            # MACD conditions
            if 'macd_hist' in ind:
                rules['bull']['entry_conditions'].append(
                    f"MACD histogram > {ind['macd_hist']['p25']:.2f}"
                )

            # Trend strength
            if 'trend_strength' in ind:
                rules['bull']['entry_conditions'].append(
                    f"Trend strength > {ind['trend_strength']['p25']:.2f}"
                )

        elif regime == 'bear':
            rules['bear'] = {
                'description': 'Bearish regime - favor short positions',
                'entry_conditions': [],
                'exit_conditions': [],
            }

            if 'rsi_14' in ind:
                rules['bear']['entry_conditions'].append(
                    f"RSI(14) between {ind['rsi_14']['p25']:.1f} and {ind['rsi_14']['p75']:.1f}"
                )

            if 'macd_hist' in ind:
                rules['bear']['entry_conditions'].append(
                    f"MACD histogram < {ind['macd_hist']['p75']:.2f}"
                )

            if 'trend_strength' in ind:
                rules['bear']['entry_conditions'].append(
                    f"Trend strength < {ind['trend_strength']['p75']:.2f}"
                )

        elif regime == 'neutral':
            rules['neutral'] = {
                'description': 'Neutral/Ranging - mean reversion strategies',
                'entry_conditions': [],
                'exit_conditions': [],
            }

            if 'bb_pct_20' in ind:
                rules['neutral']['entry_conditions'].append(
                    f"BB% near extremes (< 0.2 for long, > 0.8 for short)"
                )

            if 'volatility_20' in ind:
                rules['neutral']['entry_conditions'].append(
                    f"Volatility around {ind['volatility_20']['mean']:.2f}"
                )

    return rules


def run_analysis():
    """Run the full trend analysis."""

    # Load ES 5-minute data
    data_path = Path(__file__).parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    df = pd.read_parquet(data_path)
    df = df[df['volume'] > 0].copy()

    print(f"Loaded {len(df)} bars")
    print(f"Date range: {df.index.min()} to {df.index.max()}")

    # Calculate indicators
    print("\nCalculating indicators...")
    df = calculate_all_indicators(df)

    # Classify regimes
    print("Classifying regimes...")
    df = classify_regime(df, lookforward=60)  # 5 hours ahead

    # Analyze indicator predictiveness
    print("Analyzing indicator predictiveness...")
    analysis = analyze_indicator_predictiveness(df)

    # Find trend change signals
    print("Finding trend change signals...")
    df = find_trend_change_signals(df)

    # Print results
    print("\n" + "="*70)
    print("REGIME ANALYSIS RESULTS")
    print("="*70)

    for regime, data in analysis.items():
        print(f"\n{regime.upper()} REGIME")
        print(f"  Count: {data['count']} bars ({data['pct']:.1f}%)")
        print(f"  Key indicator values:")

        for ind_name, stats in data['indicators'].items():
            print(f"    {ind_name}: mean={stats['mean']:.2f}, median={stats['median']:.2f}")

    # Generate rules
    rules = generate_regime_rules(analysis)

    print("\n" + "="*70)
    print("SUGGESTED TRADING RULES")
    print("="*70)

    for regime, rule_data in rules.items():
        print(f"\n{regime.upper()}: {rule_data['description']}")
        print("  Entry conditions:")
        for cond in rule_data['entry_conditions']:
            print(f"    - {cond}")

    # Analyze regime changes
    changes = df[df['regime_change'] == True]
    print("\n" + "="*70)
    print("REGIME CHANGE ANALYSIS")
    print("="*70)

    change_counts = changes['change_type'].value_counts()
    print("\nRegime transition frequencies:")
    for change_type, count in change_counts.items():
        if change_type:
            print(f"  {change_type}: {count}")

    # Key indicators at regime changes
    print("\nIndicator values at bull-to-bear transitions:")
    bull_to_bear = df[df['change_type'] == 'bull_to_bear']
    if len(bull_to_bear) > 0:
        for ind in ['rsi_14', 'macd_hist', 'trend_strength', 'volatility_20']:
            if ind in bull_to_bear.columns:
                val = bull_to_bear[ind].mean()
                print(f"  {ind}: {val:.2f}")

    print("\nIndicator values at bear-to-bull transitions:")
    bear_to_bull = df[df['change_type'] == 'bear_to_bull']
    if len(bear_to_bull) > 0:
        for ind in ['rsi_14', 'macd_hist', 'trend_strength', 'volatility_20']:
            if ind in bear_to_bull.columns:
                val = bear_to_bull[ind].mean()
                print(f"  {ind}: {val:.2f}")

    return df, analysis, rules


if __name__ == "__main__":
    df, analysis, rules = run_analysis()
