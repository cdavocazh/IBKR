"""
ES Pure Trend Following Strategy

Simplify approach: Only trade the strongest, clearest trends.
Inspired by the GC buy-the-dip success (the only profitable strategy).

Key principles:
1. LESS IS MORE - very selective entries
2. Only trade when trend is undeniable (multiple confirmations)
3. Let winners run with trailing stops
4. Cut losers quickly

Differences from previous strategies:
- Much longer trend EMA (200 bars = ~16 hours of data)
- Require price to be significantly above/below trend EMA
- MACD must be clearly positive/negative (not just turning)
- RSI used as FILTER not signal (avoid extremes)
- Wider targets (3:1 R:R minimum)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESTrendFollowStrategy(Strategy):
    """ES Pure Trend Following Strategy."""

    def __init__(
        self,
        # Trend EMAs
        trend_ema: int = 200,        # Long-term trend (16+ hours)
        signal_ema: int = 50,        # Entry timing
        fast_ema: int = 20,          # Short-term

        # Trend strength filter
        min_trend_atr: float = 1.5,  # Price must be 1.5 ATR away from trend EMA

        # MACD filter (stricter)
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        min_macd_strength: float = 0.5,  # MACD histogram must be significant

        # RSI filter (avoid extremes)
        rsi_period: int = 14,
        rsi_long_min: float = 35.0,   # Don't buy oversold (trend might be ending)
        rsi_long_max: float = 70.0,   # Don't buy overbought
        rsi_short_min: float = 30.0,
        rsi_short_max: float = 65.0,

        # ATR settings (conservative)
        atr_period: int = 20,
        stop_atr: float = 2.5,       # Wider stop to avoid noise
        target_atr: float = 5.0,     # 2:1 R:R minimum
        trail_trigger_atr: float = 3.0,
        trail_distance_atr: float = 1.5,

        # Position management
        max_hold_bars: int = 72,     # 6 hours max
        min_volume: int = 100,

        # Entry cooldown
        min_bars_between_trades: int = 12,  # Wait 1 hour between trades
    ):
        super().__init__(name="ES_trend_follow")

        self.trend_ema = trend_ema
        self.signal_ema = signal_ema
        self.fast_ema = fast_ema
        self.min_trend_atr = min_trend_atr

        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.min_macd_strength = min_macd_strength

        self.rsi_period = rsi_period
        self.rsi_long_min = rsi_long_min
        self.rsi_long_max = rsi_long_max
        self.rsi_short_min = rsi_short_min
        self.rsi_short_max = rsi_short_max

        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_distance_atr = trail_distance_atr

        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume
        self.min_bars_between_trades = min_bars_between_trades

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None
        self.last_trade_bar = -100

    def _calculate_ema(self, prices: list, period: int) -> Optional[float]:
        """Calculate EMA."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _is_strong_uptrend(
        self,
        close: float,
        fast_ema: float,
        signal_ema: float,
        trend_ema: float,
        atr: float,
        macd_hist: float,
        rsi: float,
    ) -> bool:
        """
        Check for strong uptrend conditions:
        1. Price significantly above trend EMA
        2. EMAs properly stacked (fast > signal > trend)
        3. MACD histogram strongly positive
        4. RSI in favorable range
        """
        # Price must be well above trend EMA
        trend_distance = (close - trend_ema) / atr
        if trend_distance < self.min_trend_atr:
            return False

        # EMAs must be bullishly stacked
        if not (fast_ema > signal_ema > trend_ema):
            return False

        # MACD must be strongly positive
        if macd_hist < self.min_macd_strength:
            return False

        # RSI in favorable range (not at extremes)
        if rsi < self.rsi_long_min or rsi > self.rsi_long_max:
            return False

        return True

    def _is_strong_downtrend(
        self,
        close: float,
        fast_ema: float,
        signal_ema: float,
        trend_ema: float,
        atr: float,
        macd_hist: float,
        rsi: float,
    ) -> bool:
        """
        Check for strong downtrend conditions.
        """
        # Price must be well below trend EMA
        trend_distance = (trend_ema - close) / atr
        if trend_distance < self.min_trend_atr:
            return False

        # EMAs must be bearishly stacked
        if not (fast_ema < signal_ema < trend_ema):
            return False

        # MACD must be strongly negative
        if macd_hist > -self.min_macd_strength:
            return False

        # RSI in favorable range
        if rsi < self.rsi_short_min or rsi > self.rsi_short_max:
            return False

        return True

    def _is_pullback_entry(
        self,
        bar,
        direction: str,
        fast_ema: float,
        signal_ema: float,
        atr: float,
    ) -> bool:
        """
        Check for pullback entry opportunity:
        - Price has retraced to signal EMA but not below
        - Or price has touched fast EMA
        """
        if direction == 'long':
            # Price near signal EMA but above it
            if bar.low <= signal_ema + atr * 0.3:
                if bar.close > signal_ema:
                    return True
            # Or price touched fast EMA with bullish close
            if bar.low <= fast_ema and bar.close > bar.open:
                return True

        elif direction == 'short':
            # Price near signal EMA but below it
            if bar.high >= signal_ema - atr * 0.3:
                if bar.close < signal_ema:
                    return True
            # Or price touched fast EMA with bearish close
            if bar.high >= fast_ema and bar.close < bar.open:
                return True

        return False

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'
        self.stop_price = price - self.current_atr * self.stop_atr
        self.target_price = price + self.current_atr * self.target_atr
        self.trailing_stop = None
        self.last_trade_bar = engine.current_index
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'short'
        self.stop_price = price + self.current_atr * self.stop_atr
        self.target_price = price - self.current_atr * self.target_atr
        self.trailing_stop = None
        self.last_trade_bar = engine.current_index
        engine.sell(1)

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position with trailing stops."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Time exit
        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset()
            return True

        if self.trade_direction == 'long':
            # Stop loss
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Take profit
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop
            if self.trailing_stop is not None:
                self.trailing_stop = max(
                    self.trailing_stop,
                    bar.close - self.current_atr * self.trail_distance_atr
                )
                if bar.low <= self.trailing_stop:
                    engine.close_position()
                    self._reset()
                    return True
            else:
                profit = bar.close - self.entry_price
                if profit >= self.current_atr * self.trail_trigger_atr:
                    self.trailing_stop = bar.close - self.current_atr * self.trail_distance_atr

        elif self.trade_direction == 'short':
            # Stop loss
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Take profit
            if bar.low <= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop
            if self.trailing_stop is not None:
                self.trailing_stop = min(
                    self.trailing_stop,
                    bar.close + self.current_atr * self.trail_distance_atr
                )
                if bar.high >= self.trailing_stop:
                    engine.close_position()
                    self._reset()
                    return True
            else:
                profit = self.entry_price - bar.close
                if profit >= self.current_atr * self.trail_trigger_atr:
                    self.trailing_stop = bar.close + self.current_atr * self.trail_distance_atr

        return False

    def _reset(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Skip low volume
        if bar.volume < self.min_volume:
            return

        # Need enough data
        min_bars = max(
            self.trend_ema + 5,
            self.macd_slow + self.macd_signal,
            self.rsi_period + 1,
            self.atr_period + 1,
        )
        if len(self.closes) < min_bars:
            return

        # Calculate indicators
        fast_ema = self._calculate_ema(self.closes, self.fast_ema)
        signal_ema = self._calculate_ema(self.closes, self.signal_ema)
        trend_ema = self._calculate_ema(self.closes, self.trend_ema)

        if fast_ema is None or signal_ema is None or trend_ema is None:
            return

        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        macd_data = Indicator.macd(self.closes, self.macd_fast, self.macd_slow, self.macd_signal)

        if rsi is None or atr is None or macd_data is None:
            return

        macd_hist = macd_data[2]
        self.current_atr = atr

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Check cooldown
        if engine.current_index - self.last_trade_bar < self.min_bars_between_trades:
            return

        # Check for strong trends and pullback entries
        if self._is_strong_uptrend(bar.close, fast_ema, signal_ema, trend_ema, atr, macd_hist, rsi):
            if self._is_pullback_entry(bar, 'long', fast_ema, signal_ema, atr):
                self._enter_long(engine, bar.close)

        elif self._is_strong_downtrend(bar.close, fast_ema, signal_ema, trend_ema, atr, macd_hist, rsi):
            if self._is_pullback_entry(bar, 'short', fast_ema, signal_ema, atr):
                self._enter_short(engine, bar.close)


def run_backtest():
    """Run the trend follow backtest."""
    from backtest.engine import BacktestEngine

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

    strategy = ESTrendFollowStrategy(
        trend_ema=200,
        signal_ema=50,
        fast_ema=20,
        min_trend_atr=1.5,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        min_macd_strength=0.5,
        rsi_period=14,
        rsi_long_min=35.0,
        rsi_long_max=70.0,
        rsi_short_min=30.0,
        rsi_short_max=65.0,
        atr_period=20,
        stop_atr=2.5,
        target_atr=5.0,
        trail_trigger_atr=3.0,
        trail_distance_atr=1.5,
        max_hold_bars=72,
        min_volume=100,
        min_bars_between_trades=12,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES TREND FOLLOW Strategy Results")
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
        print(f"\nAvg Bars Held:    {results['trades']['bars_held'].mean():.1f} bars")
        print(f"                  {results['trades']['bars_held'].mean() * 5:.1f} minutes")

        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
