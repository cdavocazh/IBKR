"""
ES Kris Regime-Switching Strategy

Uses the ES_stance_history.xlsx to automatically switch between:
- Bullish: Long-only trades
- Bearish: Short-only trades
- Neutral: Both directions (but with caution on shorts)

This version reads your actual stance changes and applies them to the backtest.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


def load_stance_history() -> pd.DataFrame:
    """Load stance history from Excel file."""
    xlsx_path = Path(__file__).parent.parent.parent / "ES_stance_history.xlsx"
    df = pd.read_excel(xlsx_path)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')
    return df


class ESKrisRegimeStrategy(Strategy):
    """ES Strategy with automatic regime switching based on stance history."""

    def __init__(
        self,
        stance_history: pd.DataFrame,

        # Stop loss (percentage-based)
        stop_pct: float = 0.6,

        # Target (R-multiple based)
        target_r_multiple: float = 2.5,

        # Trailing stop
        breakeven_r: float = 1.0,
        trail_r_ratio: float = 0.8,

        # Multi-timeframe RSI
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_neutral_low: float = 35.0,
        rsi_neutral_high: float = 65.0,

        # Entry
        lookback_for_pattern: int = 60,
        min_pullback_pct: float = 0.4,

        # Position management
        max_hold_bars: int = 1152,
        min_hold_bars: int = 96,
        min_volume: int = 20,
        min_bars_between_trades: int = 120,
    ):
        super().__init__(name="ES_kris_regime")

        self.stance_history = stance_history
        self.stop_pct = stop_pct / 100
        self.target_r_multiple = target_r_multiple
        self.breakeven_r = breakeven_r
        self.trail_r_ratio = trail_r_ratio

        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_neutral_low = rsi_neutral_low
        self.rsi_neutral_high = rsi_neutral_high

        self.lookback_for_pattern = lookback_for_pattern
        self.min_pullback_pct = min_pullback_pct / 100
        self.max_hold_bars = max_hold_bars
        self.min_hold_bars = min_hold_bars
        self.min_volume = min_volume
        self.min_bars_between_trades = min_bars_between_trades

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.opens = []
        self.volumes = []

        # Resampled for multi-timeframe
        self.closes_30m = []
        self.highs_30m = []
        self.lows_30m = []
        self.closes_4h = []
        self.highs_4h = []
        self.lows_4h = []

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.initial_stop = None
        self.target_price = None
        self.trade_direction = None
        self.at_breakeven = False
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.last_trade_bar = -300

        # Current regime
        self.current_regime = "neutral"

    def _get_regime_for_date(self, timestamp) -> str:
        """Get the regime (stance) for a given date."""
        # Convert timestamp to date for comparison
        if hasattr(timestamp, 'date'):
            check_date = timestamp.date()
        else:
            check_date = pd.Timestamp(timestamp).date()

        # Find the most recent stance before this date
        stance_df = self.stance_history.copy()
        stance_df['check_date'] = stance_df['Date'].dt.date

        applicable = stance_df[stance_df['check_date'] <= check_date]

        if len(applicable) == 0:
            # Before any stance recorded - use bullish as ES generally trends up
            return "bullish"

        return applicable.iloc[-1]['Stance'].lower()

    def _resample_to_30m(self):
        """Resample 5-min to 30-min."""
        if len(self.closes) < 6:
            return
        if len(self.closes) % 6 == 0:
            self.closes_30m.append(self.closes[-1])
            self.highs_30m.append(max(self.highs[-6:]))
            self.lows_30m.append(min(self.lows[-6:]))

    def _resample_to_4h(self):
        """Resample 5-min to 4-hour."""
        if len(self.closes) < 48:
            return
        if len(self.closes) % 48 == 0:
            self.closes_4h.append(self.closes[-1])
            self.highs_4h.append(max(self.highs[-48:]))
            self.lows_4h.append(min(self.lows[-48:]))

    def _calculate_rsi(self, prices: list, period: int) -> Optional[float]:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None
        return Indicator.rsi(prices, period)

    def _get_multi_tf_rsi(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Get RSI on multiple timeframes."""
        rsi_30m = self._calculate_rsi(self.closes_30m, 14) if len(self.closes_30m) > 15 else None
        rsi_4h = self._calculate_rsi(self.closes_4h, 14) if len(self.closes_4h) > 15 else None
        rsi_daily = self._calculate_rsi(self.closes_4h, 28) if len(self.closes_4h) > 30 else None
        return rsi_30m, rsi_4h, rsi_daily

    def _is_double_bottom(self, lows: list, closes: list, threshold_pct: float = 0.003) -> bool:
        """Detect double bottom pattern."""
        if len(lows) < self.lookback_for_pattern:
            return False

        recent_lows = list(lows[-self.lookback_for_pattern:])
        recent_closes = list(closes[-self.lookback_for_pattern:])

        if len(recent_lows) < 10:
            return False

        min_idx1 = int(np.argmin(recent_lows))
        min_val1 = recent_lows[min_idx1]

        temp_lows = recent_lows.copy()
        for i in range(max(0, min_idx1-3), min(len(temp_lows), min_idx1+4)):
            temp_lows[i] = float('inf')

        if all(v == float('inf') for v in temp_lows):
            return False

        min_idx2 = int(np.argmin(temp_lows))
        if min_idx2 >= len(recent_lows):
            return False
        min_val2 = recent_lows[min_idx2]

        if min_val1 == 0 or abs(min_val1 - min_val2) / min_val1 > threshold_pct:
            return False

        start_idx, end_idx = min(min_idx1, min_idx2), max(min_idx1, min_idx2)
        if end_idx - start_idx < 3:
            return False

        between_high = max(recent_closes[start_idx:end_idx])
        if between_high <= max(min_val1, min_val2) * 1.005:
            return False

        if recent_closes[-1] < max(min_val1, min_val2) * 1.002:
            return False

        return True

    def _is_double_top(self, highs: list, closes: list, threshold_pct: float = 0.003) -> bool:
        """Detect double top pattern."""
        if len(highs) < self.lookback_for_pattern:
            return False

        recent_highs = list(highs[-self.lookback_for_pattern:])
        recent_closes = list(closes[-self.lookback_for_pattern:])

        if len(recent_highs) < 10:
            return False

        max_idx1 = int(np.argmax(recent_highs))
        max_val1 = recent_highs[max_idx1]

        temp_highs = recent_highs.copy()
        for i in range(max(0, max_idx1-3), min(len(temp_highs), max_idx1+4)):
            temp_highs[i] = float('-inf')

        if all(v == float('-inf') for v in temp_highs):
            return False

        max_idx2 = int(np.argmax(temp_highs))
        if max_idx2 >= len(recent_highs):
            return False
        max_val2 = recent_highs[max_idx2]

        if max_val1 == 0 or abs(max_val1 - max_val2) / max_val1 > threshold_pct:
            return False

        start_idx, end_idx = min(max_idx1, max_idx2), max(max_idx1, max_idx2)
        if end_idx - start_idx < 3:
            return False

        between_low = min(recent_closes[start_idx:end_idx])
        if between_low >= min(max_val1, max_val2) * 0.995:
            return False

        if recent_closes[-1] > min(max_val1, max_val2) * 0.998:
            return False

        return True

    def _has_pullback(self, direction: str) -> bool:
        """Check for adequate pullback."""
        if len(self.closes) < self.lookback_for_pattern:
            return False

        recent_highs = self.highs[-self.lookback_for_pattern:]
        recent_lows = self.lows[-self.lookback_for_pattern:]
        current_close = self.closes[-1]

        if direction == 'long':
            recent_high = max(recent_highs)
            pullback = (recent_high - current_close) / recent_high
            return pullback >= self.min_pullback_pct
        else:
            recent_low = min(recent_lows)
            if recent_low == 0:
                return False
            pullback = (current_close - recent_low) / recent_low
            return pullback >= self.min_pullback_pct

    def _is_bullish_candle(self, bar) -> bool:
        """Check for bullish candle."""
        if bar.close <= bar.open:
            return False
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False
        return (bar.close - bar.open) / range_size > 0.4

    def _is_bearish_candle(self, bar) -> bool:
        """Check for bearish candle."""
        if bar.close >= bar.open:
            return False
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False
        return (bar.open - bar.close) / range_size > 0.4

    def _check_long_entry(self, bar, rsi_30m, rsi_4h, rsi_daily) -> bool:
        """Check for long entry."""
        # Regime filter - no longs in bearish
        if self.current_regime == "bearish":
            return False

        # Don't buy when 4H RSI overbought
        if rsi_4h is not None and rsi_4h > self.rsi_overbought:
            return False
        if rsi_4h is not None and rsi_4h > self.rsi_neutral_high:
            return False

        # Patterns
        has_pattern = self._is_double_bottom(list(self.lows), list(self.closes))
        has_pullback = (
            self._has_pullback('long') and
            rsi_30m is not None and rsi_30m < self.rsi_neutral_low
        )

        if not (has_pattern or has_pullback):
            return False

        return self._is_bullish_candle(bar)

    def _check_short_entry(self, bar, rsi_30m, rsi_4h, rsi_daily) -> bool:
        """Check for short entry."""
        # Regime filter - no shorts in bullish
        if self.current_regime == "bullish":
            return False

        # Be more selective with shorts in neutral (since market has upward bias)
        if self.current_regime == "neutral":
            # Require stronger overbought signal
            if rsi_4h is None or rsi_4h < 68:  # Higher threshold
                return False

        # Don't short when 4H RSI oversold
        if rsi_4h is not None and rsi_4h < self.rsi_oversold:
            return False
        if rsi_4h is not None and rsi_4h < self.rsi_neutral_low:
            return False

        # Patterns
        has_pattern = self._is_double_top(list(self.highs), list(self.closes))
        has_pullback = (
            self._has_pullback('short') and
            rsi_30m is not None and rsi_30m > self.rsi_neutral_high
        )

        if not (has_pattern or has_pullback):
            return False

        return self._is_bearish_candle(bar)

    def _manage_position(self, engine, bar) -> bool:
        """Manage position with trailing stop."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        if self.trade_direction == 'long':
            self.highest_since_entry = max(self.highest_since_entry, bar.high)
        else:
            self.lowest_since_entry = min(self.lowest_since_entry, bar.low)

        risk = abs(self.entry_price - self.initial_stop)

        if self.trade_direction == 'long':
            current_profit = bar.close - self.entry_price
            current_r = current_profit / risk if risk > 0 else 0

            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

            if not self.at_breakeven and current_r >= self.breakeven_r:
                self.stop_price = self.entry_price + (risk * 0.1)
                self.at_breakeven = True

            if self.at_breakeven:
                profit_from_entry = self.highest_since_entry - self.entry_price
                new_stop = self.entry_price + (profit_from_entry * self.trail_r_ratio) - risk
                if new_stop > self.stop_price:
                    self.stop_price = new_stop

        else:  # Short
            current_profit = self.entry_price - bar.close
            current_r = current_profit / risk if risk > 0 else 0

            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            if bar.low <= self.target_price:
                engine.close_position()
                self._reset()
                return True

            if not self.at_breakeven and current_r >= self.breakeven_r:
                self.stop_price = self.entry_price - (risk * 0.1)
                self.at_breakeven = True

            if self.at_breakeven:
                profit_from_entry = self.entry_price - self.lowest_since_entry
                new_stop = self.entry_price - (profit_from_entry * self.trail_r_ratio) + risk
                if new_stop < self.stop_price:
                    self.stop_price = new_stop

        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset()
            return True

        return False

    def _reset(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.initial_stop = None
        self.target_price = None
        self.trade_direction = None
        self.at_breakeven = False
        self.highest_since_entry = None
        self.lowest_since_entry = None

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'
        self.initial_stop = price * (1 - self.stop_pct)
        self.stop_price = self.initial_stop
        risk = price - self.initial_stop
        self.target_price = price + (risk * self.target_r_multiple)
        self.at_breakeven = False
        self.highest_since_entry = price
        self.lowest_since_entry = price
        self.last_trade_bar = engine.current_index
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'short'
        self.initial_stop = price * (1 + self.stop_pct)
        self.stop_price = self.initial_stop
        risk = self.initial_stop - price
        self.target_price = price - (risk * self.target_r_multiple)
        self.at_breakeven = False
        self.highest_since_entry = price
        self.lowest_since_entry = price
        self.last_trade_bar = engine.current_index
        engine.sell(1)

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.opens.append(bar.open)
        self.volumes.append(bar.volume)

        self._resample_to_30m()
        self._resample_to_4h()

        # Update regime based on current bar's date
        self.current_regime = self._get_regime_for_date(bar.timestamp)

        if bar.volume < self.min_volume:
            return

        min_bars = max(self.lookback_for_pattern * 2, 50)
        if len(self.closes) < min_bars:
            return

        rsi_30m, rsi_4h, rsi_daily = self._get_multi_tf_rsi()

        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        if engine.current_index - self.last_trade_bar < self.min_bars_between_trades:
            return

        if self._check_long_entry(bar, rsi_30m, rsi_4h, rsi_daily):
            self._enter_long(engine, bar.close)
        elif self._check_short_entry(bar, rsi_30m, rsi_4h, rsi_daily):
            self._enter_short(engine, bar.close)


def run_backtest():
    """Run the ES Kris regime-switching backtest."""
    from backtest.engine import BacktestEngine

    # Load stance history
    stance_history = load_stance_history()
    print("Stance History:")
    print(stance_history.to_string())
    print()

    data_path = Path(__file__).parent.parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars")
    print(f"Date range: {data.index.min()} to {data.index.max()}")

    engine = BacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=2,
    )

    strategy = ESKrisRegimeStrategy(
        stance_history=stance_history,
        stop_pct=0.6,
        target_r_multiple=2.5,
        breakeven_r=1.0,
        trail_r_ratio=0.8,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        rsi_neutral_low=35.0,
        rsi_neutral_high=65.0,
        lookback_for_pattern=60,
        min_pullback_pct=0.4,
        max_hold_bars=1152,
        min_hold_bars=96,
        min_volume=20,
        min_bars_between_trades=120,
    )

    results = engine.run(strategy)
    return results, engine, strategy


if __name__ == "__main__":
    results, engine, strategy = run_backtest()

    print("\n" + "="*60)
    print("ES KRIS REGIME-SWITCHING Strategy Results")
    print("="*60)
    print(f"Initial Capital:  ${results['initial_capital']:,.2f}")
    print(f"Final Equity:     ${results['final_equity']:,.2f}")
    print(f"Total P&L:        ${results['total_pnl']:,.2f}")
    print(f"Total Return:     {results['total_return_pct']:.2f}%")
    print(f"Total Trades:     {results['total_trades']}")
    print(f"Win Rate:         {results['win_rate']:.2f}%")
    print(f"Avg Win:          ${results['avg_win']:,.2f}")
    print(f"Avg Loss:         ${results['avg_loss']:,.2f}")
    print(f"Profit Factor:    {results['profit_factor']:.2f}")
    print(f"Max Drawdown:     {results['max_drawdown']:.2f}%")
    print(f"Sharpe Ratio:     {results['sharpe_ratio']:.2f}")

    if len(results['trades']) > 0:
        avg_bars = results['trades']['bars_held'].mean()
        print(f"\nAvg Bars Held:    {avg_bars:.1f} bars")
        print(f"                  {avg_bars * 5 / 60:.1f} hours")
        print(f"                  {avg_bars * 5 / 60 / 24:.1f} days")

        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            long_wr = (long_trades['pnl'] > 0).mean() * 100
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {long_wr:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            short_wr = (short_trades['pnl'] > 0).mean() * 100
            print(f"Short trades: {len(short_trades)} | Win rate: {short_wr:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
