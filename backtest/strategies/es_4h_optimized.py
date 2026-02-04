"""
ES 4-Hour Swing Strategy - OPTIMIZED

Key optimizations based on regime analysis:
1. Only trade in CONFIRMED trending regimes (strong_bull or strong_bear)
2. Wait for pullback to key moving average
3. Use momentum confirmation (MACD slope, not just crossover)
4. Better risk:reward with trailing stops
5. Wider targets in strong trends

From analysis:
- 44% of time in bull regime, 35.5% in bear, 20.5% neutral
- Bull regime: trend_strength mean 0.56, RSI ~52
- Bear regime: trend_strength mean 0.85 (ironically higher - price above MA but falling)

Holding Period: 1-4 hours (12-48 bars on 5-min data)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ES4HOptimizedStrategy(Strategy):
    """ES 4-Hour Swing Strategy - Optimized."""

    def __init__(
        self,
        # Trend detection EMAs
        fast_ema: int = 20,
        slow_ema: int = 50,
        trend_ema: int = 100,

        # Entry filter - pullback depth
        pullback_min_atr: float = 0.5,  # Minimum pullback
        pullback_max_atr: float = 2.0,  # Maximum pullback

        # MACD
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,

        # RSI filter
        rsi_period: int = 14,
        rsi_long_max: float = 65.0,   # Not overbought for longs
        rsi_short_min: float = 35.0,  # Not oversold for shorts

        # ATR settings
        atr_period: int = 20,
        stop_atr: float = 2.0,
        target_atr: float = 4.0,      # 2:1 R:R

        # Trailing stop
        trail_trigger_atr: float = 2.0,
        trail_distance_atr: float = 1.0,

        # Position management
        max_hold_bars: int = 48,
        min_volume: int = 100,
        volume_lookback: int = 20,

        # Regime filter
        require_trend_confirmation: bool = True,
        trend_confirmation_bars: int = 5,  # Bars trend must persist
    ):
        super().__init__(name="ES_4h_opt")

        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trend_ema = trend_ema

        self.pullback_min_atr = pullback_min_atr
        self.pullback_max_atr = pullback_max_atr

        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

        self.rsi_period = rsi_period
        self.rsi_long_max = rsi_long_max
        self.rsi_short_min = rsi_short_min

        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr

        self.trail_trigger_atr = trail_trigger_atr
        self.trail_distance_atr = trail_distance_atr

        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume
        self.volume_lookback = volume_lookback

        self.require_trend_confirmation = require_trend_confirmation
        self.trend_confirmation_bars = trend_confirmation_bars

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # Trend tracking
        self.trend_history = []
        self.prev_macd_hist = None

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None

    def _calculate_ema(self, prices: list, period: int) -> Optional[float]:
        """Calculate EMA."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _get_trend(self, fast_ema: float, slow_ema: float, trend_ema: float, close: float) -> str:
        """
        Determine trend strength.
        """
        # Strong bull: perfect bullish alignment
        if close > fast_ema > slow_ema > trend_ema:
            return 'strong_bull'

        # Bull: price above trend, MAs bullish
        if close > trend_ema and fast_ema > slow_ema:
            return 'bull'

        # Strong bear: perfect bearish alignment
        if close < fast_ema < slow_ema < trend_ema:
            return 'strong_bear'

        # Bear: price below trend, MAs bearish
        if close < trend_ema and fast_ema < slow_ema:
            return 'bear'

        return 'neutral'

    def _is_trend_confirmed(self, current_trend: str) -> bool:
        """Check if trend has persisted for confirmation period."""
        if not self.require_trend_confirmation:
            return True

        if len(self.trend_history) < self.trend_confirmation_bars:
            return False

        # Check if all recent trends match (or are similar direction)
        bullish_trends = ['bull', 'strong_bull']
        bearish_trends = ['bear', 'strong_bear']

        recent = self.trend_history[-self.trend_confirmation_bars:]

        if current_trend in bullish_trends:
            return all(t in bullish_trends for t in recent)
        elif current_trend in bearish_trends:
            return all(t in bearish_trends for t in recent)

        return False

    def _is_pullback(self, bar, trend: str, fast_ema: float, atr: float) -> bool:
        """Check if price has pulled back to a good entry level."""
        if trend in ['bull', 'strong_bull']:
            # Price should be near fast EMA from above
            distance = bar.close - fast_ema
            if distance < 0:  # Below EMA
                return abs(distance) <= atr * self.pullback_max_atr
            elif distance < atr * self.pullback_min_atr:
                return True  # Near but above

        elif trend in ['bear', 'strong_bear']:
            # Price should be near fast EMA from below
            distance = fast_ema - bar.close
            if distance < 0:  # Above EMA
                return abs(distance) <= atr * self.pullback_max_atr
            elif distance < atr * self.pullback_min_atr:
                return True

        return False

    def _is_volume_ok(self) -> bool:
        """Check if volume is adequate."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * 0.8 if avg_vol > 0 else False

    def _check_long_entry(
        self,
        bar,
        trend: str,
        fast_ema: float,
        rsi: float,
        macd_hist: float,
        atr: float,
    ) -> bool:
        """
        Long entry conditions:
        1. Trend is bull or strong_bull AND confirmed
        2. Price has pulled back to fast EMA
        3. RSI not overbought
        4. MACD histogram positive or improving
        5. Volume adequate
        """
        if trend not in ['bull', 'strong_bull']:
            return False

        if not self._is_trend_confirmed(trend):
            return False

        if not self._is_pullback(bar, trend, fast_ema, atr):
            return False

        if rsi > self.rsi_long_max:
            return False

        # MACD: positive or turning positive
        if macd_hist <= 0:
            if self.prev_macd_hist is None or macd_hist <= self.prev_macd_hist:
                return False  # Not improving

        if not self._is_volume_ok():
            return False

        return True

    def _check_short_entry(
        self,
        bar,
        trend: str,
        fast_ema: float,
        rsi: float,
        macd_hist: float,
        atr: float,
    ) -> bool:
        """
        Short entry conditions:
        1. Trend is bear or strong_bear AND confirmed
        2. Price has pulled back to fast EMA
        3. RSI not oversold
        4. MACD histogram negative or declining
        5. Volume adequate
        """
        if trend not in ['bear', 'strong_bear']:
            return False

        if not self._is_trend_confirmed(trend):
            return False

        if not self._is_pullback(bar, trend, fast_ema, atr):
            return False

        if rsi < self.rsi_short_min:
            return False

        # MACD: negative or getting more negative
        if macd_hist >= 0:
            if self.prev_macd_hist is None or macd_hist >= self.prev_macd_hist:
                return False

        if not self._is_volume_ok():
            return False

        return True

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'
        self.stop_price = price - self.current_atr * self.stop_atr
        self.target_price = price + self.current_atr * self.target_atr
        self.trailing_stop = None
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'short'
        self.stop_price = price + self.current_atr * self.stop_atr
        self.target_price = price - self.current_atr * self.target_atr
        self.trailing_stop = None
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
            self.volume_lookback + 1
        )
        if len(self.closes) < min_bars:
            return

        # Calculate indicators
        fast_ema = self._calculate_ema(self.closes, self.fast_ema)
        slow_ema = self._calculate_ema(self.closes, self.slow_ema)
        trend_ema = self._calculate_ema(self.closes, self.trend_ema)

        if fast_ema is None or slow_ema is None or trend_ema is None:
            return

        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        macd_data = Indicator.macd(self.closes, self.macd_fast, self.macd_slow, self.macd_signal)

        if rsi is None or atr is None or macd_data is None:
            return

        macd_hist = macd_data[2]
        self.current_atr = atr

        # Determine and track trend
        trend = self._get_trend(fast_ema, slow_ema, trend_ema, bar.close)
        self.trend_history.append(trend)
        if len(self.trend_history) > self.trend_confirmation_bars + 5:
            self.trend_history.pop(0)

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            self.prev_macd_hist = macd_hist
            return

        # Check for entries
        if self._check_long_entry(bar, trend, fast_ema, rsi, macd_hist, atr):
            self._enter_long(engine, bar.close)
        elif self._check_short_entry(bar, trend, fast_ema, rsi, macd_hist, atr):
            self._enter_short(engine, bar.close)

        self.prev_macd_hist = macd_hist


def run_backtest():
    """Run the optimized 4h backtest."""
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

    strategy = ES4HOptimizedStrategy(
        fast_ema=20,
        slow_ema=50,
        trend_ema=100,
        pullback_min_atr=0.3,
        pullback_max_atr=1.5,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        rsi_period=14,
        rsi_long_max=65.0,
        rsi_short_min=35.0,
        atr_period=20,
        stop_atr=2.0,
        target_atr=4.0,
        trail_trigger_atr=2.0,
        trail_distance_atr=1.0,
        max_hold_bars=48,
        min_volume=100,
        volume_lookback=20,
        require_trend_confirmation=True,
        trend_confirmation_bars=5,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES 4-Hour OPTIMIZED Strategy Results")
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

        # Breakdown by direction
        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
