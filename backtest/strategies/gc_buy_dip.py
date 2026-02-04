"""
GC (Gold) Buy-the-Dip Strategy

Gold tends to be a safe-haven asset that trends upward over time.
This strategy buys dips in gold futures during pullbacks in the overall uptrend.

Strategy Logic:
1. Identify long-term trend (100-bar EMA)
2. Wait for pullbacks (RSI oversold + price below short-term MA)
3. Enter on signs of reversal (price reclaiming short MA)
4. Use ATR-based stops and targets

Holding Period: 2-8 hours (24-96 bars on 5-min)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class GCBuyDipStrategy(Strategy):
    """Gold Buy-the-Dip Strategy - long only."""

    def __init__(
        self,
        long_ema_period: int = 100,
        short_ma_period: int = 20,
        rsi_period: int = 14,
        rsi_oversold: float = 35.0,
        rsi_recovery: float = 45.0,
        atr_period: int = 20,
        stop_atr: float = 2.5,
        target_atr: float = 4.0,
        trail_trigger_atr: float = 2.0,
        trail_distance_atr: float = 1.5,
        max_hold_bars: int = 96,
        min_volume: int = 20,
        volume_lookback: int = 20,
        pullback_depth_atr: float = 1.5,
    ):
        super().__init__(name="GC_buy_dip")

        self.long_ema_period = long_ema_period
        self.short_ma_period = short_ma_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_recovery = rsi_recovery
        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_distance_atr = trail_distance_atr
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume
        self.volume_lookback = volume_lookback
        self.pullback_depth_atr = pullback_depth_atr

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # State tracking
        self.was_oversold = False
        self.lowest_rsi = 100.0
        self.prev_close = None
        self.prev_short_ma = None

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.current_atr = None

    def _is_uptrend(self, close: float, long_ema: float) -> bool:
        """Check if in overall uptrend."""
        return close > long_ema * 0.995  # 0.5% buffer below still considered uptrend

    def _is_pullback(self, close: float, short_ma: float, atr: float) -> bool:
        """Check if price has pulled back enough."""
        return close < short_ma - atr * 0.5  # Price at least 0.5 ATR below short MA

    def _is_recovery_signal(self, bar, rsi: float, short_ma: float) -> bool:
        """Check for recovery signal to enter."""
        if not self.was_oversold:
            return False

        # RSI recovering from oversold
        if rsi < self.rsi_recovery:
            return False

        # Price reclaiming short MA (or close to it)
        if bar.close < short_ma * 0.998:  # Need to be within 0.2% of short MA
            return False

        # Previous close was below short MA (crossover)
        if self.prev_close is not None and self.prev_short_ma is not None:
            if self.prev_close < self.prev_short_ma:
                return True

        return False

    def _is_volume_confirmed(self) -> bool:
        """Check if volume is sufficient."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * 1.0 if avg_vol > 0 else False  # At least average

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

        return False

    def _reset(self):
        """Reset trade and state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.was_oversold = False
        self.lowest_rsi = 100.0

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.stop_price = price - self.current_atr * self.stop_atr
        self.target_price = price + self.current_atr * self.target_atr
        self.trailing_stop = None
        engine.buy(1)

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Skip very low volume
        if bar.volume < self.min_volume:
            self.prev_close = bar.close
            return

        # Need enough data
        min_bars = max(
            self.long_ema_period,
            self.short_ma_period,
            self.rsi_period + 1,
            self.atr_period + 1,
            self.volume_lookback + 1
        )
        if len(self.closes) < min_bars:
            self.prev_close = bar.close
            return

        # Calculate indicators
        long_ema = Indicator.ema(self.closes, self.long_ema_period)
        short_ma = Indicator.sma(self.closes, self.short_ma_period)
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)

        if long_ema is None or short_ma is None or rsi is None or atr is None:
            self.prev_close = bar.close
            self.prev_short_ma = short_ma
            return

        self.current_atr = atr

        # Track if we've been oversold
        if rsi < self.rsi_oversold:
            self.was_oversold = True
            self.lowest_rsi = min(self.lowest_rsi, rsi)

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            self.prev_close = bar.close
            self.prev_short_ma = short_ma
            return

        # Check for entry (long only strategy)
        if self._is_uptrend(bar.close, long_ema):
            if self._is_recovery_signal(bar, rsi, short_ma):
                if self._is_volume_confirmed():
                    self._enter_long(engine, bar.close)

        # Reset oversold tracking if RSI gets too high without entry
        if rsi > 60:
            self.was_oversold = False
            self.lowest_rsi = 100.0

        self.prev_close = bar.close
        self.prev_short_ma = short_ma


# GC-specific backtest engine
class GCBacktestEngine:
    """Backtest engine configured for Gold futures."""

    # GC Contract Specifications
    TICK_SIZE = 0.10  # $0.10 per troy ounce
    POINT_VALUE = 100.0  # $100 per point (100 troy oz contract)
    TICK_VALUE = TICK_SIZE * POINT_VALUE  # $10 per tick

    def __init__(
        self,
        data: pd.DataFrame,
        initial_capital: float = 100000.0,
        commission_per_contract: float = 2.25,
        slippage_ticks: int = 1,
        max_position: int = 5,
    ):
        # Import here to avoid circular
        from backtest.engine import BacktestEngine
        self.engine = BacktestEngine(
            data=data,
            initial_capital=initial_capital,
            commission_per_contract=commission_per_contract,
            slippage_ticks=slippage_ticks,
            max_position=max_position,
        )
        # Override ES specs with GC specs
        self.engine.TICK_SIZE = self.TICK_SIZE
        self.engine.POINT_VALUE = self.POINT_VALUE
        self.engine.TICK_VALUE = self.TICK_VALUE
        self.engine.slippage_points = slippage_ticks * self.TICK_SIZE

    def run(self, strategy):
        return self.engine.run(strategy)


def run_backtest():
    """Run the GC buy-the-dip backtest."""
    data_path = Path(__file__).parent.parent.parent / "data" / "gc" / "GC_combined_5mins.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars for GC")
    print(f"Date range: {data.index.min()} to {data.index.max()}")

    engine = GCBacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=3,
    )

    strategy = GCBuyDipStrategy(
        long_ema_period=80,
        short_ma_period=15,
        rsi_period=10,
        rsi_oversold=30.0,
        rsi_recovery=40.0,
        atr_period=14,
        stop_atr=2.0,
        target_atr=3.5,
        trail_trigger_atr=1.5,
        trail_distance_atr=1.0,
        max_hold_bars=72,
        min_volume=20,
        volume_lookback=15,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("GC Buy-the-Dip Backtest Results")
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
