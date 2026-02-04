"""
ES Scalping Strategy - Momentum with Trend Filter

Simple but effective momentum scalping:
1. Trade in direction of short-term trend (20 EMA slope)
2. Enter on pullbacks (RSI oversold in uptrend, overbought in downtrend)
3. Use ATR-based stops and targets
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESMomentumScalp(Strategy):
    """Trend-following scalping strategy."""

    def __init__(
        self,
        ema_period: int = 20,
        ema_slope_lookback: int = 5,
        rsi_period: int = 7,
        rsi_entry_low: float = 40.0,
        rsi_entry_high: float = 60.0,
        atr_period: int = 14,
        stop_atr: float = 1.5,
        target_atr: float = 2.0,
        max_hold_bars: int = 20,
        min_volume: int = 100,
    ):
        super().__init__(name="ES_momentum_scalp")

        self.ema_period = ema_period
        self.ema_slope_lookback = ema_slope_lookback
        self.rsi_period = rsi_period
        self.rsi_entry_low = rsi_entry_low
        self.rsi_entry_high = rsi_entry_high
        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume

        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []
        self.emas = []

        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trade_direction = None
        self.current_atr = None

    def _get_trend(self) -> Optional[str]:
        """Determine trend based on EMA slope."""
        if len(self.emas) < self.ema_slope_lookback:
            return None

        current_ema = self.emas[-1]
        past_ema = self.emas[-self.ema_slope_lookback]

        slope = (current_ema - past_ema) / past_ema * 100

        if slope > 0.05:  # 0.05% slope threshold
            return 'up'
        elif slope < -0.05:
            return 'down'
        return 'sideways'

    def _check_entry(self, bar, rsi: float, trend: str) -> Optional[str]:
        """Check for entry signal."""
        if trend == 'up':
            # In uptrend, buy on RSI pullback
            if rsi < self.rsi_entry_low:
                return 'long'
        elif trend == 'down':
            # In downtrend, sell on RSI bounce
            if rsi > self.rsi_entry_high:
                return 'short'
        return None

    def _manage_position(self, engine, bar) -> bool:
        """Manage position."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset()
            return True

        if self.trade_direction == 'long':
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

        elif self.trade_direction == 'short':
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True
            if bar.low <= self.target_price:
                engine.close_position()
                self._reset()
                return True

        return False

    def _reset(self):
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trade_direction = None

    def _enter(self, engine, direction: str, price: float):
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = direction

        if direction == 'long':
            self.stop_price = price - self.current_atr * self.stop_atr
            self.target_price = price + self.current_atr * self.target_atr
            engine.buy(1)
        else:
            self.stop_price = price + self.current_atr * self.stop_atr
            self.target_price = price - self.current_atr * self.target_atr
            engine.sell(1)

    def on_bar(self, engine, bar):
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        if bar.volume < self.min_volume:
            return

        min_bars = max(self.ema_period, self.rsi_period + 1, self.atr_period + 1) + self.ema_slope_lookback
        if len(self.closes) < min_bars:
            ema = Indicator.ema(self.closes, self.ema_period)
            if ema is not None:
                self.emas.append(ema)
            return

        ema = Indicator.ema(self.closes, self.ema_period)
        if ema is not None:
            self.emas.append(ema)

        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        trend = self._get_trend()

        if rsi is None or atr is None or trend is None:
            return

        self.current_atr = atr

        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        signal = self._check_entry(bar, rsi, trend)
        if signal:
            self._enter(engine, signal, bar.close)


def run_backtest():
    from backtest.engine import BacktestEngine

    data_path = Path(__file__).parent.parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars")

    engine = BacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=2,
    )

    strategy = ESMomentumScalp(
        ema_period=20,
        ema_slope_lookback=5,
        rsi_period=7,
        rsi_entry_low=35.0,
        rsi_entry_high=65.0,
        atr_period=14,
        stop_atr=1.2,
        target_atr=1.8,
        max_hold_bars=12,
        min_volume=200,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES Momentum Scalp Results")
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
