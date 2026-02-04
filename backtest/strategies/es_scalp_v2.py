"""
ES Scalping Strategy V2 (ES_scalp)

A volatility-breakout based scalping strategy with strict risk management.

Holding period: 15-60 minutes (3-12 bars on 5-min data)

Key Principles:
1. Trade only during high-volume periods
2. Enter on volatility expansion (ATR breakout)
3. Use tight stops (1 ATR) and wider targets (2.5 ATR)
4. Filter using multiple timeframe momentum
"""

import pandas as pd
import numpy as np
from collections import deque
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESScalpV2Strategy(Strategy):
    """
    ES Volatility Breakout Scalping Strategy.

    Entry:
    - Price breaks above/below N-bar high/low (Donchian breakout)
    - ATR expansion (current ATR > average ATR)
    - Volume confirmation
    - RSI not overbought/oversold (avoid exhaustion)

    Exit:
    - Stop: 1 ATR from entry
    - Target: 2.5 ATR from entry
    - Time: Max 12 bars
    - Trail after 1.5 ATR profit
    """

    def __init__(
        self,
        breakout_period: int = 10,
        atr_period: int = 14,
        atr_expansion_mult: float = 1.2,
        volume_lookback: int = 20,
        volume_threshold: float = 1.5,
        rsi_period: int = 14,
        rsi_neutral_low: float = 40.0,
        rsi_neutral_high: float = 60.0,
        stop_atr: float = 1.0,
        target_atr: float = 2.5,
        trail_trigger_atr: float = 1.5,
        max_hold_bars: int = 12,
        min_volume: int = 200,
    ):
        super().__init__(name="ES_scalp_v2")

        self.breakout_period = breakout_period
        self.atr_period = atr_period
        self.atr_expansion_mult = atr_expansion_mult
        self.volume_lookback = volume_lookback
        self.volume_threshold = volume_threshold
        self.rsi_period = rsi_period
        self.rsi_neutral_low = rsi_neutral_low
        self.rsi_neutral_high = rsi_neutral_high
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []
        self.atrs = []

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None

    def _get_avg_atr(self, lookback: int = 50) -> Optional[float]:
        """Get average ATR over lookback period."""
        if len(self.atrs) < lookback:
            return None
        return sum(self.atrs[-lookback:]) / lookback

    def _get_relative_volume(self) -> Optional[float]:
        """Get current volume relative to average."""
        if len(self.volumes) < self.volume_lookback + 1:
            return None
        avg = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] / avg if avg > 0 else None

    def _check_entry_signal(self, bar, rsi: float, atr: float) -> Optional[str]:
        """Check for entry signal. Returns 'long', 'short', or None."""

        if len(self.highs) < self.breakout_period + 1:
            return None

        # Get breakout levels (previous N bars, excluding current)
        prev_high = max(self.highs[-self.breakout_period-1:-1])
        prev_low = min(self.lows[-self.breakout_period-1:-1])

        # Check ATR expansion
        avg_atr = self._get_avg_atr()
        if avg_atr is None:
            return None

        atr_expanding = atr > avg_atr * self.atr_expansion_mult

        # Check volume
        rel_vol = self._get_relative_volume()
        if rel_vol is None:
            return None
        vol_confirmed = rel_vol >= self.volume_threshold

        # RSI filter - avoid overbought/oversold extremes
        # For longs, RSI should not be too high (room to grow)
        # For shorts, RSI should not be too low (room to fall)

        # Long entry: breakout above previous high
        if bar.close > prev_high:
            if atr_expanding and vol_confirmed:
                if rsi < 70:  # Not overbought
                    return 'long'

        # Short entry: breakdown below previous low
        if bar.close < prev_low:
            if atr_expanding and vol_confirmed:
                if rsi > 30:  # Not oversold
                    return 'short'

        return None

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position. Returns True if closed."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Time exit
        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset_trade()
            return True

        if self.trade_direction == 'long':
            # Stop loss
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset_trade()
                return True

            # Take profit
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset_trade()
                return True

            # Trailing stop
            if self.trailing_stop is not None:
                self.trailing_stop = max(self.trailing_stop, bar.close - self.current_atr * 0.8)
                if bar.low <= self.trailing_stop:
                    engine.close_position()
                    self._reset_trade()
                    return True
            else:
                # Activate trailing stop after trail_trigger profit
                if bar.close >= self.entry_price + self.current_atr * self.trail_trigger_atr:
                    self.trailing_stop = bar.close - self.current_atr * 0.8

        elif self.trade_direction == 'short':
            # Stop loss
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset_trade()
                return True

            # Take profit
            if bar.low <= self.target_price:
                engine.close_position()
                self._reset_trade()
                return True

            # Trailing stop
            if self.trailing_stop is not None:
                self.trailing_stop = min(self.trailing_stop, bar.close + self.current_atr * 0.8)
                if bar.high >= self.trailing_stop:
                    engine.close_position()
                    self._reset_trade()
                    return True
            else:
                if bar.close <= self.entry_price - self.current_atr * self.trail_trigger_atr:
                    self.trailing_stop = bar.close + self.current_atr * 0.8

        return False

    def _reset_trade(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None

    def _enter_trade(self, engine, direction: str, price: float):
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

        # Skip low volume bars
        if bar.volume < self.min_volume:
            return

        # Calculate ATR
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        if atr is not None:
            self.atrs.append(atr)
            self.current_atr = atr

        # Need enough data
        min_bars = max(self.breakout_period + 1, self.atr_period + 1, self.volume_lookback + 1, 50)
        if len(self.closes) < min_bars:
            return

        # Calculate RSI
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        if rsi is None or atr is None:
            return

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Look for entry
        signal = self._check_entry_signal(bar, rsi, atr)
        if signal:
            self._enter_trade(engine, signal, bar.close)


def run_backtest():
    """Run the backtest."""
    from backtest.engine import BacktestEngine

    # Load data
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

    strategy = ESScalpV2Strategy(
        breakout_period=10,
        atr_period=14,
        atr_expansion_mult=1.15,
        volume_lookback=20,
        volume_threshold=1.4,
        rsi_period=14,
        stop_atr=1.0,
        target_atr=2.5,
        trail_trigger_atr=1.5,
        max_hold_bars=12,
        min_volume=150,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES_scalp V2 Backtest Results")
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
        print(f"\nAvg Bars Held:    {results['trades']['bars_held'].mean():.1f}")
