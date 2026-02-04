"""
ES Scalping Strategy (ES_scalp)

Holding period: 15+ minutes (3+ bars on 5-min data)
Approach: Multi-factor momentum/mean-reversion hybrid with volatility filtering

Factors used:
1. Price Action: VWAP deviation, momentum, mean reversion zones
2. Volume: Relative volume, volume-price divergence
3. Volatility: HV/IV regime filtering, ATR-based stops
4. Custom Indicators: Volume-weighted momentum, price acceleration
"""

import pandas as pd
import numpy as np
from collections import deque
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESScalpStrategy(Strategy):
    """
    ES Scalping Strategy targeting 15-60 minute holds.

    Entry Logic:
    - Mean reversion: Enter on oversold/overbought RSI with volume confirmation
    - Momentum: Enter on breakouts with increasing volume
    - Filter: Only trade in favorable volatility regimes

    Exit Logic:
    - Take profit at 2 ATR
    - Stop loss at 1.5 ATR
    - Time-based exit after 60 bars (5 hours on 5-min)
    - Trail stop after 1 ATR profit
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        atr_period: int = 14,
        volume_lookback: int = 20,
        volume_threshold: float = 1.5,
        take_profit_atr: float = 2.0,
        stop_loss_atr: float = 1.5,
        trail_trigger_atr: float = 1.0,
        max_hold_bars: int = 60,
        momentum_period: int = 5,
        vwap_period: int = 20,
        min_volume_filter: int = 100,
    ):
        super().__init__(name="ES_scalp")

        # RSI parameters
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

        # ATR/volatility parameters
        self.atr_period = atr_period
        self.volume_lookback = volume_lookback
        self.volume_threshold = volume_threshold

        # Risk parameters
        self.take_profit_atr = take_profit_atr
        self.stop_loss_atr = stop_loss_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.max_hold_bars = max_hold_bars

        # Momentum/VWAP parameters
        self.momentum_period = momentum_period
        self.vwap_period = vwap_period
        self.min_volume_filter = min_volume_filter

        # Data storage
        self.prices = []
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []
        self.typical_prices = []  # For VWAP
        self.pv_sum = []  # Price * Volume cumulative
        self.v_sum = []   # Volume cumulative

        # Trade management
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None  # 'long' or 'short'
        self.current_atr = None

    def _calculate_vwap(self) -> Optional[float]:
        """Calculate VWAP over lookback period."""
        if len(self.typical_prices) < self.vwap_period:
            return None

        tp_slice = self.typical_prices[-self.vwap_period:]
        vol_slice = self.volumes[-self.vwap_period:]

        total_pv = sum(tp * v for tp, v in zip(tp_slice, vol_slice))
        total_v = sum(vol_slice)

        if total_v == 0:
            return None
        return total_pv / total_v

    def _calculate_relative_volume(self) -> Optional[float]:
        """Calculate relative volume (current vs average)."""
        if len(self.volumes) < self.volume_lookback + 1:
            return None

        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        if avg_vol == 0:
            return None
        return self.volumes[-1] / avg_vol

    def _calculate_momentum(self) -> Optional[float]:
        """Calculate price momentum (rate of change)."""
        if len(self.closes) < self.momentum_period + 1:
            return None

        return (self.closes[-1] - self.closes[-self.momentum_period-1]) / self.closes[-self.momentum_period-1] * 100

    def _calculate_price_acceleration(self) -> Optional[float]:
        """Calculate change in momentum (second derivative)."""
        if len(self.closes) < self.momentum_period * 2 + 1:
            return None

        current_mom = (self.closes[-1] - self.closes[-self.momentum_period-1]) / self.closes[-self.momentum_period-1]
        prev_mom = (self.closes[-self.momentum_period-1] - self.closes[-self.momentum_period*2-1]) / self.closes[-self.momentum_period*2-1]

        return current_mom - prev_mom

    def _is_volume_confirmed(self) -> bool:
        """Check if current bar has above-average volume."""
        rel_vol = self._calculate_relative_volume()
        if rel_vol is None:
            return False
        return rel_vol >= self.volume_threshold

    def _check_mean_reversion_entry(self, rsi: float, vwap: float, close: float, atr: float) -> Optional[str]:
        """
        Check for mean reversion entry signal.
        Returns 'long', 'short', or None.
        """
        # Calculate VWAP deviation in ATR units
        vwap_dev = (close - vwap) / atr if atr > 0 else 0

        # Oversold conditions for long entry
        # Require extreme RSI AND price significantly below VWAP
        if rsi < self.rsi_oversold:
            if vwap_dev < -1.5:  # Price more than 1.5 ATR below VWAP
                if self._is_volume_confirmed():
                    return 'long'

        # Overbought conditions for short entry
        if rsi > self.rsi_overbought:
            if vwap_dev > 1.5:  # Price more than 1.5 ATR above VWAP
                if self._is_volume_confirmed():
                    return 'short'

        return None

    def _check_momentum_entry(self, momentum: float, acceleration: float, vwap: float, close: float, atr: float) -> Optional[str]:
        """
        Check for momentum breakout entry.
        Returns 'long', 'short', or None.
        """
        if momentum is None or acceleration is None:
            return None

        # Calculate VWAP deviation
        vwap_dev = (close - vwap) / atr if atr > 0 else 0

        # Strong upward momentum with positive acceleration
        # And price breaking above VWAP
        if momentum > 0.20 and acceleration > 0.05:
            if vwap_dev > 0.5 and self._is_volume_confirmed():
                return 'long'

        # Strong downward momentum with negative acceleration
        if momentum < -0.20 and acceleration < -0.05:
            if vwap_dev < -0.5 and self._is_volume_confirmed():
                return 'short'

        return None

    def _manage_position(self, engine, bar) -> bool:
        """
        Manage existing position. Returns True if position was closed.
        """
        if engine.position.is_flat:
            return False

        current_bar_index = engine.current_index
        bars_held = current_bar_index - self.entry_bar

        # Time-based exit
        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset_trade_state()
            return True

        # Check stops and targets
        if self.trade_direction == 'long':
            # Check stop loss
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset_trade_state()
                return True

            # Check take profit
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset_trade_state()
                return True

            # Update trailing stop if triggered
            if self.trailing_stop is not None:
                self.trailing_stop = max(self.trailing_stop, bar.close - self.current_atr * self.stop_loss_atr)
                if bar.low <= self.trailing_stop:
                    engine.close_position()
                    self._reset_trade_state()
                    return True
            else:
                # Check if we should start trailing
                profit_atr = (bar.close - self.entry_price) / self.current_atr
                if profit_atr >= self.trail_trigger_atr:
                    self.trailing_stop = bar.close - self.current_atr * self.stop_loss_atr

        elif self.trade_direction == 'short':
            # Check stop loss
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset_trade_state()
                return True

            # Check take profit
            if bar.low <= self.target_price:
                engine.close_position()
                self._reset_trade_state()
                return True

            # Update trailing stop if triggered
            if self.trailing_stop is not None:
                self.trailing_stop = min(self.trailing_stop, bar.close + self.current_atr * self.stop_loss_atr)
                if bar.high >= self.trailing_stop:
                    engine.close_position()
                    self._reset_trade_state()
                    return True
            else:
                # Check if we should start trailing
                profit_atr = (self.entry_price - bar.close) / self.current_atr
                if profit_atr >= self.trail_trigger_atr:
                    self.trailing_stop = bar.close + self.current_atr * self.stop_loss_atr

        return False

    def _reset_trade_state(self):
        """Reset trade management variables."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None

    def _enter_trade(self, engine, direction: str, entry_price: float):
        """Enter a new trade with proper risk management."""
        self.entry_price = entry_price
        self.entry_bar = engine.current_index
        self.trade_direction = direction
        self.trailing_stop = None

        if direction == 'long':
            self.stop_price = entry_price - self.current_atr * self.stop_loss_atr
            self.target_price = entry_price + self.current_atr * self.take_profit_atr
            engine.buy(1)
        else:
            self.stop_price = entry_price + self.current_atr * self.stop_loss_atr
            self.target_price = entry_price - self.current_atr * self.take_profit_atr
            engine.sell(1)

    def on_bar(self, engine, bar):
        """Process each bar."""
        # Update data arrays
        self.prices.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Calculate typical price for VWAP
        typical_price = (bar.high + bar.low + bar.close) / 3
        self.typical_prices.append(typical_price)

        # Skip if volume is too low (likely outside regular trading hours)
        if bar.volume < self.min_volume_filter:
            return

        # Need enough data for indicators
        min_bars = max(self.rsi_period + 1, self.atr_period + 1, self.vwap_period, self.volume_lookback + 1)
        if len(self.prices) < min_bars:
            return

        # Calculate indicators
        rsi = Indicator.rsi(self.prices, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        vwap = self._calculate_vwap()
        momentum = self._calculate_momentum()
        acceleration = self._calculate_price_acceleration()

        if rsi is None or atr is None or vwap is None:
            return

        self.current_atr = atr

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Look for new entry signals (only when flat)
        # Priority 1: Mean reversion
        signal = self._check_mean_reversion_entry(rsi, vwap, bar.close, atr)

        # Priority 2: Momentum (if no mean reversion signal)
        if signal is None:
            signal = self._check_momentum_entry(momentum, acceleration, vwap, bar.close, atr)

        # Execute trade
        if signal is not None:
            self._enter_trade(engine, signal, bar.close)


def run_es_scalp_backtest():
    """Run ES_scalp backtest and return results."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from backtest.engine import BacktestEngine

    # Load ES 5-min data
    data_path = Path(__file__).parent.parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)

    # Filter for regular trading hours (higher volume bars)
    # Keep bars with volume > 0 to reduce noise
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars for ES_scalp backtest")
    print(f"Date range: {data.index.min()} to {data.index.max()}")

    # Initialize engine and strategy
    engine = BacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=2,
    )

    strategy = ESScalpStrategy(
        rsi_period=10,
        rsi_oversold=20.0,
        rsi_overbought=80.0,
        atr_period=14,
        volume_lookback=20,
        volume_threshold=1.8,
        take_profit_atr=2.5,
        stop_loss_atr=1.0,
        trail_trigger_atr=1.2,
        max_hold_bars=40,
        momentum_period=3,
        vwap_period=15,
        min_volume_filter=100,
    )

    # Run backtest
    results = engine.run(strategy)

    return results, engine


if __name__ == "__main__":
    results, engine = run_es_scalp_backtest()

    print("\n" + "="*60)
    print("ES_scalp Backtest Results")
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
