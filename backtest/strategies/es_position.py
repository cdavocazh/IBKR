"""
ES Position Strategy (1-5 day holding period)

Designed for multi-day position trades that capture weekly trends.
Very selective entries with wide stops and profit targets.

Key principles:
1. Only trade clear weekly trends
2. Use daily-level indicators (approximated on 5-min data)
3. Enter on significant corrections within the trend
4. Very wide stops (5+ ATR) to survive intraday noise
5. Large targets (4:1+ R:R) for outsized gains
6. Max 2-3 trades per month

Holding Period: 1-5 days (288-1440 bars on 5-min data)
Target: 4:1 R:R minimum
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESPositionStrategy(Strategy):
    """ES Position Strategy for 1-5 day holds."""

    def __init__(
        self,
        # Trend indicators (very long periods for weekly trend)
        trend_ema: int = 960,           # ~80 hours / ~1 week of RTH
        medium_ema: int = 480,          # ~40 hours
        fast_ema: int = 120,            # ~10 hours

        # Pullback detection (deeper pullbacks for position trades)
        min_pullback_atr: float = 3.0,  # Minimum pullback depth
        max_pullback_atr: float = 8.0,  # Maximum pullback

        # Entry confirmation
        rsi_period: int = 28,           # Longer RSI
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_recovery: float = 42.0,

        # MACD for weekly trend confirmation
        macd_fast: int = 48,            # ~4 hours
        macd_slow: int = 104,           # ~8.5 hours
        macd_signal: int = 36,

        # Volume confirmation
        volume_lookback: int = 60,      # 5 hours for volume avg
        volume_multiplier: float = 1.2, # Need 20% above average

        # Risk management (very wide for multi-day)
        atr_period: int = 60,
        stop_atr: float = 5.0,          # Very wide stop
        target_atr: float = 20.0,       # 4:1 R:R
        trail_trigger_atr: float = 10.0,
        trail_distance_atr: float = 4.0,

        # Position management
        max_hold_bars: int = 1440,      # 5 days max
        min_hold_bars: int = 96,        # 8 hours minimum
        min_volume: int = 30,

        # Trade cooldown
        min_bars_between_trades: int = 288,  # 24 hours between trades
    ):
        super().__init__(name="ES_position")

        self.trend_ema = trend_ema
        self.medium_ema = medium_ema
        self.fast_ema = fast_ema

        self.min_pullback_atr = min_pullback_atr
        self.max_pullback_atr = max_pullback_atr

        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_recovery = rsi_recovery

        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

        self.volume_lookback = volume_lookback
        self.volume_multiplier = volume_multiplier

        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_distance_atr = trail_distance_atr

        self.max_hold_bars = max_hold_bars
        self.min_hold_bars = min_hold_bars
        self.min_volume = min_volume
        self.min_bars_between_trades = min_bars_between_trades

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # State tracking - track swing highs/lows over longer period
        self.swing_high = float('-inf')
        self.swing_low = float('inf')
        self.swing_high_bar = 0
        self.swing_low_bar = 0
        self.was_oversold = False
        self.was_overbought = False

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None
        self.last_trade_bar = -500

    def _calculate_ema(self, prices: list, period: int) -> Optional[float]:
        """Calculate EMA."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _is_weekly_uptrend(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        macd_hist: float
    ) -> bool:
        """
        Check for weekly uptrend:
        1. Medium EMA above trend EMA (weekly trend up)
        2. MACD positive on weekly scale
        """
        # Medium EMA above trend EMA indicates weekly uptrend
        if medium_ema <= trend_ema:
            return False

        # MACD should be positive
        if macd_hist <= 0:
            return False

        # Price should be in reasonable range (not too far below trend)
        if close < trend_ema * 0.97:  # Not more than 3% below trend
            return False

        return True

    def _is_weekly_downtrend(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        macd_hist: float
    ) -> bool:
        """Check for weekly downtrend."""
        # Medium EMA below trend EMA
        if medium_ema >= trend_ema:
            return False

        # MACD negative
        if macd_hist >= 0:
            return False

        # Price not too far above trend
        if close > trend_ema * 1.03:
            return False

        return True

    def _update_swing_points(self, bar, engine, lookback: int = 48):
        """
        Update swing high/low points.
        A swing point is invalidated after 4 hours (48 bars).
        """
        # Update swing high
        if bar.high > self.swing_high:
            self.swing_high = bar.high
            self.swing_high_bar = engine.current_index

        # Update swing low
        if bar.low < self.swing_low:
            self.swing_low = bar.low
            self.swing_low_bar = engine.current_index

        # Reset swing high if too old
        if engine.current_index - self.swing_high_bar > lookback * 2:
            recent_highs = self.highs[-lookback:] if len(self.highs) >= lookback else self.highs
            self.swing_high = max(recent_highs)
            self.swing_high_bar = engine.current_index

        # Reset swing low if too old
        if engine.current_index - self.swing_low_bar > lookback * 2:
            recent_lows = self.lows[-lookback:] if len(self.lows) >= lookback else self.lows
            self.swing_low = min(recent_lows)
            self.swing_low_bar = engine.current_index

    def _is_significant_pullback_long(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        atr: float,
        engine
    ) -> bool:
        """
        Check for significant pullback for long entry:
        - Price has dropped 3+ ATR from recent swing high
        - Price near or below medium EMA
        - But still above critical support (trend EMA)
        """
        pullback_from_high = (self.swing_high - close) / atr

        # Need significant pullback
        if pullback_from_high < self.min_pullback_atr:
            return False

        # But not too much (trend might be broken)
        if pullback_from_high > self.max_pullback_atr:
            return False

        # Price should be testing medium EMA or below
        if close > medium_ema + atr * 0.3:
            return False

        # Should still be above trend EMA (key support)
        if close < trend_ema - atr * 1.0:
            return False

        return True

    def _is_significant_pullback_short(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        atr: float,
        engine
    ) -> bool:
        """Check for significant pullback for short entry."""
        pullback_from_low = (close - self.swing_low) / atr

        if pullback_from_low < self.min_pullback_atr:
            return False

        if pullback_from_low > self.max_pullback_atr:
            return False

        # Price should be testing medium EMA or above
        if close < medium_ema - atr * 0.3:
            return False

        # Should still be below trend EMA (key resistance)
        if close > trend_ema + atr * 1.0:
            return False

        return True

    def _is_volume_confirmed(self) -> bool:
        """Check for volume spike confirming reversal."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False

        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        if avg_vol <= 0:
            return False

        return self.volumes[-1] >= avg_vol * self.volume_multiplier

    def _is_reversal_entry_long(
        self,
        bar,
        rsi: float,
        fast_ema: float,
        atr: float
    ) -> bool:
        """
        Check for reversal entry after significant pullback:
        - RSI recovered from oversold
        - Strong bullish candle
        - Price reclaiming fast EMA
        - Volume confirmation
        """
        if not self.was_oversold:
            return False

        # RSI must have recovered
        if rsi < self.rsi_recovery:
            return False

        # Strong bullish candle (body > 50% of range)
        body = bar.close - bar.open
        range_size = bar.high - bar.low
        if body <= 0 or range_size <= 0:
            return False
        if body / range_size < 0.5:
            return False

        # Close near high (upper 30% of range)
        if (bar.close - bar.low) / range_size < 0.7:
            return False

        # Price reclaiming fast EMA
        if bar.close < fast_ema - atr * 0.3:
            return False

        # Volume confirmation
        if not self._is_volume_confirmed():
            return False

        return True

    def _is_reversal_entry_short(
        self,
        bar,
        rsi: float,
        fast_ema: float,
        atr: float
    ) -> bool:
        """Check for reversal entry for short."""
        if not self.was_overbought:
            return False

        # RSI must have dropped from overbought
        if rsi > 100 - self.rsi_recovery:
            return False

        # Strong bearish candle
        body = bar.open - bar.close
        range_size = bar.high - bar.low
        if body <= 0 or range_size <= 0:
            return False
        if body / range_size < 0.5:
            return False

        # Close near low
        if (bar.high - bar.close) / range_size < 0.7:
            return False

        # Price below fast EMA
        if bar.close > fast_ema + atr * 0.3:
            return False

        # Volume confirmation
        if not self._is_volume_confirmed():
            return False

        return True

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position with trailing stops."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Don't exit before minimum hold time (but respect stop)
        if bars_held < self.min_hold_bars:
            if self.trade_direction == 'long' and bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True
            elif self.trade_direction == 'short' and bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True
            return False

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
        self.was_oversold = False
        self.was_overbought = False
        # Don't reset swing points - they're rolling

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

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Skip low volume
        if bar.volume < self.min_volume:
            return

        # Need enough data for longest indicator
        min_bars = max(
            self.trend_ema + 10,
            self.macd_slow + self.macd_signal,
            self.rsi_period + 1,
            self.atr_period + 1,
            self.volume_lookback + 1,
        )
        if len(self.closes) < min_bars:
            return

        # Calculate indicators
        fast_ema = self._calculate_ema(self.closes, self.fast_ema)
        medium_ema = self._calculate_ema(self.closes, self.medium_ema)
        trend_ema = self._calculate_ema(self.closes, self.trend_ema)

        if fast_ema is None or medium_ema is None or trend_ema is None:
            return

        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        macd_data = Indicator.macd(self.closes, self.macd_fast, self.macd_slow, self.macd_signal)

        if rsi is None or atr is None or macd_data is None:
            return

        macd_hist = macd_data[2]
        self.current_atr = atr

        # Update swing points
        self._update_swing_points(bar, engine)

        # Track oversold/overbought
        if rsi < self.rsi_oversold:
            self.was_oversold = True
        if rsi > self.rsi_overbought:
            self.was_overbought = True

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Check cooldown
        if engine.current_index - self.last_trade_bar < self.min_bars_between_trades:
            return

        # Check for entry signals
        if self._is_weekly_uptrend(bar.close, fast_ema, medium_ema, trend_ema, macd_hist):
            if self._is_significant_pullback_long(bar.close, fast_ema, medium_ema, trend_ema, atr, engine):
                if self._is_reversal_entry_long(bar, rsi, fast_ema, atr):
                    self._enter_long(engine, bar.close)

        elif self._is_weekly_downtrend(bar.close, fast_ema, medium_ema, trend_ema, macd_hist):
            if self._is_significant_pullback_short(bar.close, fast_ema, medium_ema, trend_ema, atr, engine):
                if self._is_reversal_entry_short(bar, rsi, fast_ema, atr):
                    self._enter_short(engine, bar.close)

        # Reset oversold/overbought on strong moves
        if rsi > 55:
            self.was_oversold = False
        if rsi < 45:
            self.was_overbought = False


def run_backtest():
    """Run the ES position backtest."""
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

    strategy = ESPositionStrategy(
        trend_ema=600,           # Reduced from 960 (more responsive)
        medium_ema=300,          # Reduced from 480
        fast_ema=80,             # Reduced from 120
        min_pullback_atr=2.0,    # Lower from 3.0
        max_pullback_atr=10.0,   # Higher tolerance
        rsi_period=21,           # Reduced from 28
        rsi_oversold=35.0,       # More generous
        rsi_overbought=65.0,
        rsi_recovery=45.0,
        macd_fast=36,            # Faster MACD
        macd_slow=78,
        macd_signal=27,
        volume_lookback=40,
        volume_multiplier=1.0,   # No volume requirement
        atr_period=50,
        stop_atr=4.5,
        target_atr=18.0,         # 4:1 R:R
        trail_trigger_atr=9.0,
        trail_distance_atr=3.5,
        max_hold_bars=1440,
        min_hold_bars=192,       # 16 hours minimum (was 96)
        min_volume=20,
        min_bars_between_trades=192,  # 16 hours between trades
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES POSITION Strategy Results (1-5 day holds)")
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
        print(f"                  {results['trades']['bars_held'].mean() * 5 / 60:.1f} hours")
        print(f"                  {results['trades']['bars_held'].mean() * 5 / 60 / 24:.1f} days")

        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
