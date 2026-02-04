"""
ES 4-Hour Swing Strategy (ES_4h)

Holding period: 1-4 hours (12-48 bars on 5-min data)

Strategy Philosophy:
- Trade intraday trends that develop over hours
- Use multiple timeframe analysis (simulate hourly with 5-min data)
- Combine trend + momentum + volume for high-probability entries

Entry Logic:
1. Trend filter: Price above/below 60-bar EMA (5 hours of data)
2. Momentum: MACD histogram positive/negative and increasing
3. Pullback entry: RSI comes back from overbought/oversold
4. Volume confirmation: Above-average volume

Exit Logic:
1. Stop: 2 ATR from entry
2. Target: 3 ATR from entry
3. Trail: After 2 ATR profit, trail at 1 ATR
4. Time: Max 48 bars (4 hours)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ES4HStrategy(Strategy):
    """ES 4-Hour Swing Trading Strategy."""

    def __init__(
        self,
        trend_ema_period: int = 60,
        fast_ema: int = 12,
        slow_ema: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_entry_band: float = 15.0,
        atr_period: int = 20,
        stop_atr: float = 2.0,
        target_atr: float = 3.0,
        trail_trigger_atr: float = 2.0,
        trail_distance_atr: float = 1.0,
        max_hold_bars: int = 48,
        min_volume: int = 100,
        volume_lookback: int = 20,
    ):
        super().__init__(name="ES_4h")

        self.trend_ema_period = trend_ema_period
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.rsi_entry_band = rsi_entry_band
        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_distance_atr = trail_distance_atr
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume
        self.volume_lookback = volume_lookback

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # MACD tracking
        self.prev_macd_hist = None

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None

    def _get_trend(self, close: float, trend_ema: float) -> str:
        """Determine trend based on price vs EMA."""
        if close > trend_ema * 1.001:  # 0.1% buffer
            return 'up'
        elif close < trend_ema * 0.999:
            return 'down'
        return 'sideways'

    def _is_volume_confirmed(self) -> bool:
        """Check if current volume is above average."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * 1.2 if avg_vol > 0 else False

    def _check_entry(self, bar, trend: str, rsi: float, macd_hist: float) -> Optional[str]:
        """Check for entry signal."""
        if trend == 'sideways':
            return None

        # Check MACD momentum (don't require previous value for first signal)
        macd_positive = macd_hist > 0
        macd_negative = macd_hist < 0

        macd_increasing = (self.prev_macd_hist is not None and macd_hist > self.prev_macd_hist)
        macd_decreasing = (self.prev_macd_hist is not None and macd_hist < self.prev_macd_hist)

        # Long entry: uptrend + MACD positive/increasing + RSI not overbought
        if trend == 'up':
            # RSI in favorable range (not overbought, ideally recovering from dip)
            if rsi < 65:  # Not overbought
                # MACD positive, or turning positive and increasing
                if macd_positive or (macd_increasing and macd_hist > -0.5):
                    if self._is_volume_confirmed():
                        return 'long'

        # Short entry: downtrend + MACD negative/decreasing + RSI not oversold
        elif trend == 'down':
            if rsi > 35:  # Not oversold
                if macd_negative or (macd_decreasing and macd_hist < 0.5):
                    if self._is_volume_confirmed():
                        return 'short'

        return None

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position."""
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

            # Trailing stop management
            if self.trailing_stop is not None:
                self.trailing_stop = max(self.trailing_stop,
                                        bar.close - self.current_atr * self.trail_distance_atr)
                if bar.low <= self.trailing_stop:
                    engine.close_position()
                    self._reset()
                    return True
            else:
                # Activate trailing after trigger profit
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

            # Trailing stop management
            if self.trailing_stop is not None:
                self.trailing_stop = min(self.trailing_stop,
                                        bar.close + self.current_atr * self.trail_distance_atr)
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

    def _enter(self, engine, direction: str, price: float):
        """Enter new trade."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = direction
        self.trailing_stop = None

        if direction == 'long':
            self.stop_price = price - self.current_atr * self.stop_atr
            self.target_price = price + self.current_atr * self.target_atr
            engine.buy(1)
        else:
            self.stop_price = price + self.current_atr * self.stop_atr
            self.target_price = price - self.current_atr * self.target_atr
            engine.sell(1)

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
            self.trend_ema_period,
            self.slow_ema + self.macd_signal,
            self.rsi_period + 1,
            self.atr_period + 1,
            self.volume_lookback + 1
        )
        if len(self.closes) < min_bars:
            return

        # Calculate indicators
        trend_ema = Indicator.ema(self.closes, self.trend_ema_period)
        macd_data = Indicator.macd(self.closes, self.fast_ema, self.slow_ema, self.macd_signal)
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)

        if trend_ema is None or macd_data is None or rsi is None or atr is None:
            return

        macd_line, signal_line, macd_hist = macd_data
        self.current_atr = atr

        # Determine trend
        trend = self._get_trend(bar.close, trend_ema)

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            self.prev_macd_hist = macd_hist
            return

        # Look for entry
        signal = self._check_entry(bar, trend, rsi, macd_hist)
        if signal:
            self._enter(engine, signal, bar.close)

        self.prev_macd_hist = macd_hist


def run_backtest():
    """Run the backtest."""
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

    strategy = ES4HStrategy(
        trend_ema_period=60,
        fast_ema=12,
        slow_ema=26,
        macd_signal=9,
        rsi_period=14,
        atr_period=20,
        stop_atr=2.0,
        target_atr=3.0,
        trail_trigger_atr=2.0,
        trail_distance_atr=1.0,
        max_hold_bars=48,
        min_volume=100,
        volume_lookback=20,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES_4h Backtest Results")
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
