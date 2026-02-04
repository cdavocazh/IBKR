"""
ES Strategy Based on Kris's Trading Approach

Key principles from "ES trading approach.md":
1. Time horizon: 1-4 days
2. Tight stops: 0.4-0.8% (30-60 pts) from entry
3. Targets: 60-150 pts (2-5R profit)
4. Trailing: Move stop to breakeven at 1R, then trail 1:1
5. Multi-timeframe RSI confirmation (daily, 4H, 30min)
6. Don't buy when 4H RSI overbought, don't short when oversold
7. Look for patterns: double bottoms, failed breakouts, exhaustion

Regime from ES_stance_history:
- Bullish: Long-only, buy dips
- Bearish: Short-only, sell rallies
- Neutral: Both directions allowed

On 5-min data:
- Daily ~= 1560 bars (13 hours RTH * 12 bars/hour * 10 days)
- 4H ~= 48 bars
- 30min ~= 6 bars
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESKrisApproachStrategy(Strategy):
    """ES Strategy implementing Kris's trading approach."""

    def __init__(
        self,
        # Regime (from stance history)
        regime: str = "neutral",  # "bullish", "bearish", "neutral"

        # Stop loss (percentage-based as per your approach)
        stop_pct: float = 0.5,          # 0.4-0.8%, default 0.5% (~30-40 pts on ES ~6000)

        # Target (R-multiple based)
        target_r_multiple: float = 3.0,  # Target 2-5R, default 3R

        # Trailing stop
        breakeven_r: float = 1.0,        # Move to breakeven at 1R
        trail_r_ratio: float = 1.0,      # Trail 1:1 after breakeven

        # Multi-timeframe RSI periods (converted to 5-min bars)
        rsi_daily_period: int = 14,      # Daily RSI (calculated on resampled data)
        rsi_4h_period: int = 14,         # 4H RSI
        rsi_30m_period: int = 14,        # 30min RSI

        # RSI thresholds
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_neutral_low: float = 40.0,   # Avoid buying above this on 4H
        rsi_neutral_high: float = 60.0,  # Avoid shorting below this on 4H

        # Entry confirmation
        lookback_for_pattern: int = 48,  # 4 hours to detect patterns
        min_pullback_pct: float = 0.3,   # Minimum pullback for entry

        # Position management
        max_hold_bars: int = 1152,       # 4 days max (4 * 24 * 12 * 0.67 RTH ratio)
        min_hold_bars: int = 72,         # 6 hours minimum
        min_volume: int = 20,

        # Trade frequency
        min_bars_between_trades: int = 144,  # 12 hours cooldown
    ):
        super().__init__(name="ES_kris_approach")

        self.regime = regime.lower()
        self.stop_pct = stop_pct / 100
        self.target_r_multiple = target_r_multiple
        self.breakeven_r = breakeven_r
        self.trail_r_ratio = trail_r_ratio

        self.rsi_daily_period = rsi_daily_period
        self.rsi_4h_period = rsi_4h_period
        self.rsi_30m_period = rsi_30m_period
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

        # Resampled data for multi-timeframe
        self.closes_30m = []  # 6-bar resampled
        self.highs_30m = []
        self.lows_30m = []
        self.closes_4h = []   # 48-bar resampled
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

    def _resample_to_30m(self):
        """Resample 5-min data to 30-min (6 bars)."""
        if len(self.closes) < 6:
            return

        # Take last 6 bars
        chunk_closes = self.closes[-6:]
        chunk_highs = self.highs[-6:]
        chunk_lows = self.lows[-6:]

        # Only add if we're at a 30-min boundary (every 6 bars)
        if len(self.closes) % 6 == 0:
            self.closes_30m.append(chunk_closes[-1])
            self.highs_30m.append(max(chunk_highs))
            self.lows_30m.append(min(chunk_lows))

    def _resample_to_4h(self):
        """Resample 5-min data to 4-hour (48 bars)."""
        if len(self.closes) < 48:
            return

        # Take last 48 bars
        chunk_closes = self.closes[-48:]
        chunk_highs = self.highs[-48:]
        chunk_lows = self.lows[-48:]

        # Only add if we're at a 4H boundary (every 48 bars)
        if len(self.closes) % 48 == 0:
            self.closes_4h.append(chunk_closes[-1])
            self.highs_4h.append(max(chunk_highs))
            self.lows_4h.append(min(chunk_lows))

    def _calculate_rsi(self, prices: list, period: int) -> Optional[float]:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None
        return Indicator.rsi(prices, period)

    def _get_multi_tf_rsi(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Get RSI on multiple timeframes: (30m, 4h, daily_proxy)."""
        rsi_30m = None
        rsi_4h = None
        rsi_daily = None

        if len(self.closes_30m) > self.rsi_30m_period:
            rsi_30m = self._calculate_rsi(self.closes_30m, self.rsi_30m_period)

        if len(self.closes_4h) > self.rsi_4h_period:
            rsi_4h = self._calculate_rsi(self.closes_4h, self.rsi_4h_period)

        # Daily proxy: use 4H RSI with longer period as approximation
        # (True daily would need daily data)
        if len(self.closes_4h) > self.rsi_daily_period * 2:
            rsi_daily = self._calculate_rsi(self.closes_4h, self.rsi_daily_period * 2)

        return rsi_30m, rsi_4h, rsi_daily

    def _is_double_bottom(self, lows: list, closes: list, threshold_pct: float = 0.003) -> bool:
        """
        Detect double bottom pattern.
        Two lows within threshold% of each other with a higher high between.
        """
        if len(lows) < self.lookback_for_pattern:
            return False

        recent_lows = list(lows[-self.lookback_for_pattern:])
        recent_closes = list(closes[-self.lookback_for_pattern:])

        if len(recent_lows) < 10:
            return False

        # Find two lowest points
        min_idx1 = int(np.argmin(recent_lows))
        min_val1 = recent_lows[min_idx1]

        # Temporarily remove first minimum to find second
        temp_lows = recent_lows.copy()
        start_mask = max(0, min_idx1-3)
        end_mask = min(len(temp_lows), min_idx1+4)
        for i in range(start_mask, end_mask):
            temp_lows[i] = float('inf')

        if all(v == float('inf') for v in temp_lows):
            return False

        min_idx2 = int(np.argmin(temp_lows))
        if min_idx2 >= len(recent_lows):
            return False
        min_val2 = recent_lows[min_idx2]

        # Check if lows are within threshold
        if min_val1 == 0:
            return False
        if abs(min_val1 - min_val2) / min_val1 > threshold_pct:
            return False

        # Check if there's a higher point between them
        start_idx = min(min_idx1, min_idx2)
        end_idx = max(min_idx1, min_idx2)
        if end_idx - start_idx < 3:
            return False

        between_high = max(recent_closes[start_idx:end_idx])
        if between_high <= max(min_val1, min_val2) * 1.005:
            return False

        # Current price should be recovering (above the lows)
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
        start_mask = max(0, max_idx1-3)
        end_mask = min(len(temp_highs), max_idx1+4)
        for i in range(start_mask, end_mask):
            temp_highs[i] = float('-inf')

        if all(v == float('-inf') for v in temp_highs):
            return False

        max_idx2 = int(np.argmax(temp_highs))
        if max_idx2 >= len(recent_highs):
            return False
        max_val2 = recent_highs[max_idx2]

        if max_val1 == 0:
            return False
        if abs(max_val1 - max_val2) / max_val1 > threshold_pct:
            return False

        start_idx = min(max_idx1, max_idx2)
        end_idx = max(max_idx1, max_idx2)
        if end_idx - start_idx < 3:
            return False

        between_low = min(recent_closes[start_idx:end_idx])
        if between_low >= min(max_val1, max_val2) * 0.995:
            return False

        if recent_closes[-1] > min(max_val1, max_val2) * 0.998:
            return False

        return True

    def _is_failed_breakout_down(self, highs: list, lows: list, closes: list) -> bool:
        """
        Detect failed breakdown (bullish signal).
        Price breaks below support but immediately reverses.
        """
        if len(closes) < self.lookback_for_pattern:
            return False

        recent_lows = lows[-self.lookback_for_pattern:]
        recent_closes = closes[-self.lookback_for_pattern:]

        # Find support level (cluster of lows in first half)
        first_half_lows = recent_lows[:len(recent_lows)//2]
        support = np.percentile(first_half_lows, 10)

        # Check if we broke below support recently (last 6 bars)
        broke_support = any(l < support * 0.998 for l in recent_lows[-6:])

        # But now we're back above
        recovered = recent_closes[-1] > support * 1.002

        return broke_support and recovered

    def _is_failed_breakout_up(self, highs: list, lows: list, closes: list) -> bool:
        """Detect failed breakout (bearish signal)."""
        if len(closes) < self.lookback_for_pattern:
            return False

        recent_highs = highs[-self.lookback_for_pattern:]
        recent_closes = closes[-self.lookback_for_pattern:]

        first_half_highs = recent_highs[:len(recent_highs)//2]
        resistance = np.percentile(first_half_highs, 90)

        broke_resistance = any(h > resistance * 1.002 for h in recent_highs[-6:])
        rejected = recent_closes[-1] < resistance * 0.998

        return broke_resistance and rejected

    def _has_pullback(self, direction: str) -> bool:
        """Check if there's been adequate pullback for entry."""
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
            pullback = (current_close - recent_low) / recent_low
            return pullback >= self.min_pullback_pct

    def _is_bullish_candle(self, bar) -> bool:
        """Check for bullish confirmation candle."""
        if bar.close <= bar.open:
            return False
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False
        body = bar.close - bar.open
        return body / range_size > 0.4

    def _is_bearish_candle(self, bar) -> bool:
        """Check for bearish confirmation candle."""
        if bar.close >= bar.open:
            return False
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False
        body = bar.open - bar.close
        return body / range_size > 0.4

    def _check_long_entry(self, bar, rsi_30m, rsi_4h, rsi_daily) -> bool:
        """
        Check for long entry signal.
        Per your approach:
        - Don't buy when 4H RSI is overbought
        - Look for double bottoms, failed breakdowns
        - Confirm with multi-TF RSI
        """
        # Regime filter
        if self.regime == "bearish":
            return False

        # Don't buy when 4H RSI overbought
        if rsi_4h is not None and rsi_4h > self.rsi_overbought:
            return False

        # Prefer buying when oversold or neutral
        if rsi_4h is not None and rsi_4h > self.rsi_neutral_high:
            return False  # Avoid buying in overbought territory

        # Check for patterns
        has_pattern = (
            self._is_double_bottom(list(self.lows), list(self.closes)) or
            self._is_failed_breakout_down(list(self.highs), list(self.lows), list(self.closes))
        )

        # Or just a good pullback with oversold RSI
        has_pullback_setup = (
            self._has_pullback('long') and
            rsi_30m is not None and rsi_30m < self.rsi_neutral_low
        )

        if not (has_pattern or has_pullback_setup):
            return False

        # Confirmation candle
        if not self._is_bullish_candle(bar):
            return False

        return True

    def _check_short_entry(self, bar, rsi_30m, rsi_4h, rsi_daily) -> bool:
        """Check for short entry signal."""
        # Regime filter
        if self.regime == "bullish":
            return False

        # Don't short when 4H RSI oversold
        if rsi_4h is not None and rsi_4h < self.rsi_oversold:
            return False

        if rsi_4h is not None and rsi_4h < self.rsi_neutral_low:
            return False

        # Check for patterns
        has_pattern = (
            self._is_double_top(list(self.highs), list(self.closes)) or
            self._is_failed_breakout_up(list(self.highs), list(self.lows), list(self.closes))
        )

        has_pullback_setup = (
            self._has_pullback('short') and
            rsi_30m is not None and rsi_30m > self.rsi_neutral_high
        )

        if not (has_pattern or has_pullback_setup):
            return False

        if not self._is_bearish_candle(bar):
            return False

        return True

    def _manage_position(self, engine, bar) -> bool:
        """
        Manage position per your approach:
        1. Initial stop at entry - stop_pct
        2. Move to breakeven at 1R
        3. Trail 1:1 after that
        """
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Update high/low tracking
        if self.trade_direction == 'long':
            self.highest_since_entry = max(self.highest_since_entry, bar.high)
        else:
            self.lowest_since_entry = min(self.lowest_since_entry, bar.low)

        # Calculate current R
        risk = abs(self.entry_price - self.initial_stop)

        if self.trade_direction == 'long':
            current_profit = bar.close - self.entry_price
            current_r = current_profit / risk if risk > 0 else 0

            # Check stop
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Check target
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Move to breakeven at 1R
            if not self.at_breakeven and current_r >= self.breakeven_r:
                self.stop_price = self.entry_price + (risk * 0.1)  # Slightly above breakeven
                self.at_breakeven = True

            # Trail 1:1 after breakeven
            if self.at_breakeven:
                # Trail: for every point gained, move stop up by 1 point
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

        # Time exit
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
        """Enter long with percentage-based stop."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'

        # Stop at stop_pct below entry
        self.initial_stop = price * (1 - self.stop_pct)
        self.stop_price = self.initial_stop

        # Target at R-multiple
        risk = price - self.initial_stop
        self.target_price = price + (risk * self.target_r_multiple)

        self.at_breakeven = False
        self.highest_since_entry = price
        self.lowest_since_entry = price
        self.last_trade_bar = engine.current_index
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short with percentage-based stop."""
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

        # Resample for multi-timeframe
        self._resample_to_30m()
        self._resample_to_4h()

        # Skip low volume
        if bar.volume < self.min_volume:
            return

        # Need enough data
        min_bars = max(
            self.lookback_for_pattern * 2,
            50  # Minimum for indicators
        )
        if len(self.closes) < min_bars:
            return

        # Get multi-timeframe RSI
        rsi_30m, rsi_4h, rsi_daily = self._get_multi_tf_rsi()

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Check cooldown
        if engine.current_index - self.last_trade_bar < self.min_bars_between_trades:
            return

        # Check entry signals
        if self._check_long_entry(bar, rsi_30m, rsi_4h, rsi_daily):
            self._enter_long(engine, bar.close)
        elif self._check_short_entry(bar, rsi_30m, rsi_4h, rsi_daily):
            self._enter_short(engine, bar.close)


def run_backtest(regime: str = "neutral"):
    """Run the ES Kris approach backtest."""
    from backtest.engine import BacktestEngine

    data_path = Path(__file__).parent.parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars")
    print(f"Date range: {data.index.min()} to {data.index.max()}")
    print(f"Regime: {regime}")

    engine = BacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=2,
    )

    strategy = ESKrisApproachStrategy(
        regime=regime,
        stop_pct=0.6,              # 0.6% stop (~36 pts on ES 6000) - slightly wider
        target_r_multiple=2.5,     # 2.5R target - more achievable
        breakeven_r=1.0,           # Move to BE at 1R
        trail_r_ratio=0.8,         # Trail 0.8:1 - tighter trail to lock profits
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        rsi_neutral_low=35.0,      # More permissive for entries
        rsi_neutral_high=65.0,
        lookback_for_pattern=60,   # 5 hours for better pattern detection
        min_pullback_pct=0.4,      # 0.4% minimum pullback - need more pullback
        max_hold_bars=1152,        # ~4 days
        min_hold_bars=96,          # 8 hours min
        min_volume=20,
        min_bars_between_trades=120,  # 10 hours between trades
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    import sys

    regime = sys.argv[1] if len(sys.argv) > 1 else "neutral"
    results, engine = run_backtest(regime)

    print("\n" + "="*60)
    print(f"ES KRIS APPROACH Strategy Results (Regime: {regime.upper()})")
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
