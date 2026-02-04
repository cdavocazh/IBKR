"""
ES Swing Strategy (8-24 hour holding period)

Designed for longer-term trades that capture multi-hour moves.
Based on learnings from ES_trend_follow (PF 1.14) and GC_buy_dip (profitable).

Key principles:
1. Trade only with the daily trend (very selective)
2. Use longer-period indicators for noise reduction
3. Wait for significant pullbacks before entry
4. Wider stops and targets for larger moves
5. Trail profits to maximize gains

Holding Period: 8-24 hours (96-288 bars on 5-min data)
Target: 3:1 R:R minimum
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESSwingStrategy(Strategy):
    """ES Swing Strategy for 8-24 hour holds."""

    def __init__(
        self,
        # Trend indicators (longer periods for daily trend)
        trend_ema: int = 480,           # 40 hours of data (captures daily trend)
        medium_ema: int = 120,          # 10 hours
        fast_ema: int = 40,             # ~3.3 hours

        # Pullback detection
        min_pullback_atr: float = 2.0,  # Minimum pullback depth
        max_pullback_atr: float = 5.0,  # Maximum pullback (trend might be broken)

        # Entry confirmation
        rsi_period: int = 21,           # Longer RSI for swing
        rsi_oversold: float = 35.0,     # For longs
        rsi_overbought: float = 65.0,   # For shorts
        rsi_recovery: float = 45.0,     # Recovery threshold

        # MACD for trend confirmation
        macd_fast: int = 24,            # Doubled for swing
        macd_slow: int = 52,
        macd_signal: int = 18,

        # Risk management (wider for swing)
        atr_period: int = 40,           # Longer ATR
        stop_atr: float = 3.5,          # Wider stop
        target_atr: float = 10.5,       # 3:1 R:R
        trail_trigger_atr: float = 5.0,
        trail_distance_atr: float = 2.5,

        # Position management
        max_hold_bars: int = 288,       # 24 hours max
        min_hold_bars: int = 24,        # 2 hours minimum
        min_volume: int = 50,

        # Trade cooldown
        min_bars_between_trades: int = 48,  # 4 hours between trades
    ):
        super().__init__(name="ES_swing")

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

        # State tracking
        self.was_oversold = False
        self.was_overbought = False
        self.pullback_low = float('inf')
        self.pullback_high = float('-inf')

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None
        self.last_trade_bar = -200

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
        medium_ema: float,
        trend_ema: float,
        atr: float,
        macd_hist: float
    ) -> bool:
        """
        Check for strong daily uptrend:
        1. Price above trend EMA
        2. EMAs bullishly stacked
        3. MACD positive (but don't require histogram strength for swing)
        """
        # Price must be above trend EMA
        if close < trend_ema:
            return False

        # Trend EMA must be rising (compare to earlier value)
        # This is approximated by medium EMA being above trend EMA
        if medium_ema < trend_ema:
            return False

        # MACD should be positive (trend confirmation)
        if macd_hist < 0:
            return False

        return True

    def _is_strong_downtrend(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        atr: float,
        macd_hist: float
    ) -> bool:
        """Check for strong daily downtrend."""
        # Price must be below trend EMA
        if close > trend_ema:
            return False

        # Trend EMA must be falling
        if medium_ema > trend_ema:
            return False

        # MACD should be negative
        if macd_hist > 0:
            return False

        return True

    def _is_valid_pullback_long(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        atr: float
    ) -> bool:
        """
        Check for valid pullback in uptrend:
        - Price has pulled back to or below medium EMA
        - But not too far below trend EMA (trend broken)
        """
        # Price pulled back to medium EMA area
        pullback_from_high = (self.pullback_high - close) / atr

        if pullback_from_high < self.min_pullback_atr:
            return False  # Not enough pullback

        if pullback_from_high > self.max_pullback_atr:
            return False  # Too much pullback, trend might be broken

        # Price should be near or below medium EMA
        if close > medium_ema + atr * 0.5:
            return False

        # But not too far below trend EMA
        if close < trend_ema - atr * 2.0:
            return False

        return True

    def _is_valid_pullback_short(
        self,
        close: float,
        fast_ema: float,
        medium_ema: float,
        trend_ema: float,
        atr: float
    ) -> bool:
        """Check for valid pullback in downtrend."""
        pullback_from_low = (close - self.pullback_low) / atr

        if pullback_from_low < self.min_pullback_atr:
            return False

        if pullback_from_low > self.max_pullback_atr:
            return False

        # Price should be near or above medium EMA
        if close < medium_ema - atr * 0.5:
            return False

        # But not too far above trend EMA
        if close > trend_ema + atr * 2.0:
            return False

        return True

    def _is_recovery_entry_long(self, bar, rsi: float, fast_ema: float, atr: float) -> bool:
        """
        Check for entry signal after pullback:
        - RSI recovering from oversold
        - Price reclaiming fast EMA
        - Bullish candle
        """
        if not self.was_oversold:
            return False

        # RSI recovering
        if rsi < self.rsi_recovery:
            return False

        # Price reclaiming or above fast EMA
        if bar.close < fast_ema - atr * 0.2:
            return False

        # Bullish candle (close > open)
        if bar.close <= bar.open:
            return False

        return True

    def _is_recovery_entry_short(self, bar, rsi: float, fast_ema: float, atr: float) -> bool:
        """Check for entry signal after pullback in downtrend."""
        if not self.was_overbought:
            return False

        # RSI recovering from overbought
        if rsi > 100 - self.rsi_recovery:
            return False

        # Price below or at fast EMA
        if bar.close > fast_ema + atr * 0.2:
            return False

        # Bearish candle
        if bar.close >= bar.open:
            return False

        return True

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position with trailing stops."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Don't exit before minimum hold time - only catastrophic stop
        # This forces longer holding periods
        if bars_held < self.min_hold_bars:
            # Only exit if loss exceeds 150% of normal stop (catastrophic)
            catastrophic_stop_atr = self.stop_atr * 1.5
            if self.trade_direction == 'long':
                catastrophic_level = self.entry_price - self.current_atr * catastrophic_stop_atr
                if bar.low <= catastrophic_level:
                    engine.close_position()
                    self._reset()
                    return True
            else:
                catastrophic_level = self.entry_price + self.current_atr * catastrophic_stop_atr
                if bar.high >= catastrophic_level:
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
        self.pullback_low = float('inf')
        self.pullback_high = float('-inf')

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

        # Track pullback extremes
        self.pullback_high = max(self.pullback_high, bar.high)
        self.pullback_low = min(self.pullback_low, bar.low)

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
        if self._is_strong_uptrend(bar.close, fast_ema, medium_ema, trend_ema, atr, macd_hist):
            if self._is_valid_pullback_long(bar.close, fast_ema, medium_ema, trend_ema, atr):
                if self._is_recovery_entry_long(bar, rsi, fast_ema, atr):
                    self._enter_long(engine, bar.close)

        elif self._is_strong_downtrend(bar.close, fast_ema, medium_ema, trend_ema, atr, macd_hist):
            if self._is_valid_pullback_short(bar.close, fast_ema, medium_ema, trend_ema, atr):
                if self._is_recovery_entry_short(bar, rsi, fast_ema, atr):
                    self._enter_short(engine, bar.close)

        # Reset extremes on trend reversal signals
        if bar.close > self.pullback_high - atr * 0.5:
            self.pullback_high = bar.high
            self.was_overbought = False
        if bar.close < self.pullback_low + atr * 0.5:
            self.pullback_low = bar.low
            self.was_oversold = False


def run_backtest():
    """Run the ES swing backtest."""
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

    strategy = ESSwingStrategy(
        trend_ema=400,           # Reduced for more responsiveness
        medium_ema=100,
        fast_ema=30,
        min_pullback_atr=1.5,    # Lower threshold for more trades
        max_pullback_atr=6.0,
        rsi_period=21,
        rsi_oversold=40.0,       # Less extreme
        rsi_overbought=60.0,
        rsi_recovery=48.0,
        macd_fast=24,
        macd_slow=52,
        macd_signal=18,
        atr_period=40,
        stop_atr=4.0,            # Wider stop for longer holds
        target_atr=12.0,         # 3:1 R:R
        trail_trigger_atr=6.0,
        trail_distance_atr=3.0,
        max_hold_bars=288,
        min_hold_bars=96,        # 8 hours minimum (was 24)
        min_volume=30,           # Lower volume threshold
        min_bars_between_trades=36,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES SWING Strategy Results (8-24h holds)")
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

        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
