"""
ES Optimized Scalping Strategy

Key optimizations based on analysis:
1. ONLY trade when regime is CONFIRMED (not transitioning)
2. Require multiple confirmation signals
3. Better risk:reward ratio (tighter stops, wider targets in trends)
4. Volume spike confirmation
5. Avoid trading during regime uncertainty

From analysis:
- Bull-to-bear: RSI ~57, trend_strength ~2.6 (overbought in uptrend = reversal)
- Bear-to-bull: RSI ~43, trend_strength ~-0.97 (oversold in downtrend = reversal)
- Most regime changes go through NEUTRAL first

Holding Period: 15-45 minutes (3-9 bars on 5-min data)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESScalpOptimizedStrategy(Strategy):
    """ES Optimized Scalping Strategy."""

    def __init__(
        self,
        # Trend detection
        fast_ema: int = 20,
        slow_ema: int = 50,
        trend_ema: int = 100,

        # Entry filters
        rsi_period: int = 7,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,

        # ATR settings
        atr_period: int = 14,
        stop_atr: float = 1.0,       # Tighter stop
        target_atr: float = 2.0,     # Better R:R

        # Volume filter
        volume_mult: float = 1.3,    # Need 30% above average
        volume_lookback: int = 20,

        # Position management
        max_hold_bars: int = 9,      # ~45 min max
        min_volume: int = 150,

        # MACD filter
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
    ):
        super().__init__(name="ES_scalp_opt")

        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trend_ema = trend_ema

        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_atr = target_atr

        self.volume_mult = volume_mult
        self.volume_lookback = volume_lookback
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume

        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # State
        self.prev_rsi = None
        self.prev_macd_hist = None

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
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
        Returns: 'strong_bull', 'bull', 'strong_bear', 'bear', 'neutral'
        """
        # Strong bull: price > all EMAs, EMAs stacked bullish
        if close > fast_ema > slow_ema > trend_ema:
            return 'strong_bull'

        # Bull: price above trend EMA
        if close > trend_ema and fast_ema > slow_ema:
            return 'bull'

        # Strong bear: price < all EMAs, EMAs stacked bearish
        if close < fast_ema < slow_ema < trend_ema:
            return 'strong_bear'

        # Bear: price below trend EMA
        if close < trend_ema and fast_ema < slow_ema:
            return 'bear'

        return 'neutral'

    def _is_volume_spike(self) -> bool:
        """Check if current volume is a spike."""
        if len(self.volumes) < self.volume_lookback + 1:
            return False
        avg_vol = sum(self.volumes[-self.volume_lookback-1:-1]) / self.volume_lookback
        return self.volumes[-1] >= avg_vol * self.volume_mult if avg_vol > 0 else False

    def _check_long_entry(
        self,
        bar,
        trend: str,
        rsi: float,
        macd_hist: float,
        fast_ema: float,
    ) -> bool:
        """
        Long entry conditions:
        1. Trend is bull or strong_bull
        2. RSI pullback (was oversold or crossing up from low)
        3. MACD histogram positive or turning positive
        4. Price near or above fast EMA
        5. Volume confirmation
        """
        # Only trade in bullish trends
        if trend not in ['bull', 'strong_bull']:
            return False

        # RSI conditions: either oversold OR recovering from oversold
        rsi_ok = False
        if rsi < 40:  # Oversold zone
            rsi_ok = True
        elif self.prev_rsi is not None and self.prev_rsi < 35 and rsi > self.prev_rsi:
            # RSI was oversold and now recovering
            rsi_ok = True

        if not rsi_ok:
            return False

        # MACD confirmation: histogram positive or turning positive
        macd_ok = False
        if macd_hist > 0:
            macd_ok = True
        elif self.prev_macd_hist is not None and macd_hist > self.prev_macd_hist and macd_hist > -0.5:
            # MACD turning up from negative
            macd_ok = True

        if not macd_ok:
            return False

        # Price near fast EMA (within 0.5 ATR)
        if abs(bar.close - fast_ema) > self.current_atr * 0.5:
            return False

        # Volume spike
        if not self._is_volume_spike():
            return False

        return True

    def _check_short_entry(
        self,
        bar,
        trend: str,
        rsi: float,
        macd_hist: float,
        fast_ema: float,
    ) -> bool:
        """
        Short entry conditions:
        1. Trend is bear or strong_bear
        2. RSI bounce (was overbought or crossing down from high)
        3. MACD histogram negative or turning negative
        4. Price near or below fast EMA
        5. Volume confirmation
        """
        # Only trade in bearish trends
        if trend not in ['bear', 'strong_bear']:
            return False

        # RSI conditions
        rsi_ok = False
        if rsi > 60:  # Overbought zone
            rsi_ok = True
        elif self.prev_rsi is not None and self.prev_rsi > 65 and rsi < self.prev_rsi:
            rsi_ok = True

        if not rsi_ok:
            return False

        # MACD confirmation
        macd_ok = False
        if macd_hist < 0:
            macd_ok = True
        elif self.prev_macd_hist is not None and macd_hist < self.prev_macd_hist and macd_hist < 0.5:
            macd_ok = True

        if not macd_ok:
            return False

        # Price near fast EMA
        if abs(bar.close - fast_ema) > self.current_atr * 0.5:
            return False

        # Volume spike
        if not self._is_volume_spike():
            return False

        return True

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'
        self.stop_price = price - self.current_atr * self.stop_atr
        self.target_price = price + self.current_atr * self.target_atr
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'short'
        self.stop_price = price + self.current_atr * self.stop_atr
        self.target_price = price - self.current_atr * self.target_atr
        engine.sell(1)

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

            # Move stop to breakeven after 1 ATR profit
            profit = bar.close - self.entry_price
            if profit >= self.current_atr:
                self.stop_price = max(self.stop_price, self.entry_price + 0.25)

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

            # Move stop to breakeven
            profit = self.entry_price - bar.close
            if profit >= self.current_atr:
                self.stop_price = min(self.stop_price, self.entry_price - 0.25)

        return False

    def _reset(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
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
            self.trend_ema,
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

        # Determine trend
        trend = self._get_trend(fast_ema, slow_ema, trend_ema, bar.close)

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            self.prev_rsi = rsi
            self.prev_macd_hist = macd_hist
            return

        # Check for entries
        if self._check_long_entry(bar, trend, rsi, macd_hist, fast_ema):
            self._enter_long(engine, bar.close)
        elif self._check_short_entry(bar, trend, rsi, macd_hist, fast_ema):
            self._enter_short(engine, bar.close)

        self.prev_rsi = rsi
        self.prev_macd_hist = macd_hist


def run_backtest():
    """Run the optimized scalp backtest."""
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

    strategy = ESScalpOptimizedStrategy(
        fast_ema=20,
        slow_ema=50,
        trend_ema=100,
        rsi_period=7,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        atr_period=14,
        stop_atr=1.0,
        target_atr=2.0,
        volume_mult=1.3,
        volume_lookback=20,
        max_hold_bars=9,
        min_volume=150,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES Scalp OPTIMIZED Strategy Results")
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

        print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}%")
        print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}%")
