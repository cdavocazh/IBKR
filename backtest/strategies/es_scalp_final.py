"""
ES Scalping Strategy - Final Version

A Bollinger Band mean-reversion strategy with strict filters.

Key insight: ES tends to mean-revert on short timeframes, especially
during periods of high volatility when price temporarily overshoots.

Entry Logic:
1. Price touches or exceeds outer Bollinger Band
2. RSI confirms extreme (oversold for longs, overbought for shorts)
3. Volume spike indicates capitulation/exhaustion
4. Price starting to reverse (confirmation candle)

Exit Logic:
1. Fixed stop at 1 ATR
2. Target at middle Bollinger Band
3. Time-based exit at 15 bars
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESScalpFinalStrategy(Strategy):
    """Bollinger Band Mean Reversion Scalping."""

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_period: int = 14,
        volume_lookback: int = 20,
        volume_spike_mult: float = 2.0,
        stop_atr: float = 1.2,
        max_hold_bars: int = 15,
        min_volume: int = 100,
    ):
        super().__init__(name="ES_scalp_final")

        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.volume_lookback = volume_lookback
        self.volume_spike_mult = volume_spike_mult
        self.stop_atr = stop_atr
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume

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
        self.trade_direction = None
        self.current_atr = None
        self.bb_middle = None

        # Previous bar for reversal confirmation
        self.prev_close = None
        self.prev_low = None
        self.prev_high = None

    def _is_volume_spike(self) -> bool:
        """Check if current volume is a spike."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * self.volume_spike_mult if avg_vol > 0 else False

    def _check_long_entry(self, bar, rsi: float, bb_lower: float, bb_middle: float) -> bool:
        """Check for long entry conditions."""
        # Price at or near lower band (within 0.5 ATR)
        band_distance = bar.close - bb_lower
        if band_distance > 0.5 * self.current_atr:
            return False

        # RSI oversold
        if rsi > self.rsi_oversold:
            return False

        # Volume confirmation (not necessarily spike, but above average)
        if not self._is_volume_above_avg():
            return False

        # Reversal confirmation OR price touching band
        if bar.close <= bb_lower:
            return True  # Touching band is enough
        if self.prev_close is not None and self.prev_low is not None:
            if bar.close > self.prev_close:  # Any upward close
                return True

        return False

    def _check_short_entry(self, bar, rsi: float, bb_upper: float, bb_middle: float) -> bool:
        """Check for short entry conditions."""
        # Price at or near upper band
        band_distance = bb_upper - bar.close
        if band_distance > 0.5 * self.current_atr:
            return False

        # RSI overbought
        if rsi < self.rsi_overbought:
            return False

        # Volume confirmation
        if not self._is_volume_above_avg():
            return False

        # Reversal confirmation OR price touching band
        if bar.close >= bb_upper:
            return True
        if self.prev_close is not None and self.prev_high is not None:
            if bar.close < self.prev_close:
                return True

        return False

    def _is_volume_above_avg(self) -> bool:
        """Check if volume is above average (less strict than spike)."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * 1.2 if avg_vol > 0 else False

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position."""
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

            # Target: middle band
            if bar.high >= self.bb_middle:
                engine.close_position()
                self._reset_trade()
                return True

        elif self.trade_direction == 'short':
            # Stop loss
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset_trade()
                return True

            # Target: middle band
            if bar.low <= self.bb_middle:
                engine.close_position()
                self._reset_trade()
                return True

        return False

    def _reset_trade(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trade_direction = None

    def _enter_trade(self, engine, direction: str, price: float, bb_middle: float):
        """Enter new trade."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = direction
        self.bb_middle = bb_middle

        if direction == 'long':
            self.stop_price = price - self.current_atr * self.stop_atr
            self.target_price = bb_middle
            engine.buy(1)
        else:
            self.stop_price = price + self.current_atr * self.stop_atr
            self.target_price = bb_middle
            engine.sell(1)

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Skip low volume
        if bar.volume < self.min_volume:
            self.prev_close = bar.close
            self.prev_low = bar.low
            self.prev_high = bar.high
            return

        # Calculate indicators
        min_bars = max(self.bb_period, self.rsi_period + 1, self.atr_period + 1, self.volume_lookback + 1)
        if len(self.closes) < min_bars:
            self.prev_close = bar.close
            self.prev_low = bar.low
            self.prev_high = bar.high
            return

        bb_data = Indicator.bollinger_bands(self.closes, self.bb_period, self.bb_std)
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)

        if bb_data is None or rsi is None or atr is None:
            self.prev_close = bar.close
            self.prev_low = bar.low
            self.prev_high = bar.high
            return

        bb_middle, bb_upper, bb_lower = bb_data
        self.current_atr = atr

        # Update target if in position
        if not engine.position.is_flat:
            self.bb_middle = bb_middle  # Dynamic target

        # Manage position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            self.prev_close = bar.close
            self.prev_low = bar.low
            self.prev_high = bar.high
            return

        # Look for entry
        if self._check_long_entry(bar, rsi, bb_lower, bb_middle):
            self._enter_trade(engine, 'long', bar.close, bb_middle)
        elif self._check_short_entry(bar, rsi, bb_upper, bb_middle):
            self._enter_trade(engine, 'short', bar.close, bb_middle)

        self.prev_close = bar.close
        self.prev_low = bar.low
        self.prev_high = bar.high


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

    strategy = ESScalpFinalStrategy(
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        atr_period=14,
        volume_lookback=20,
        volume_spike_mult=1.8,
        stop_atr=1.2,
        max_hold_bars=15,
        min_volume=100,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES_scalp Final Backtest Results")
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
        print(f"Max Bars Held:    {results['trades']['bars_held'].max()}")
