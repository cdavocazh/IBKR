"""
ES Multi-Day Strategy (1-5 day holding period)

A simpler approach based on what we learned:
1. ES_trend_follow (PF 1.14) worked with strict trend filters
2. GC_buy_dip worked with mean-reversion in uptrends

This strategy:
- Uses daily trend (approximated by 960-bar EMA on 5-min = ~1 week)
- Enters on Bollinger Band touches in trend direction
- Uses time-based exits rather than strict ATR targets
- Designed for 1-5 day holds

Key insight: For longer holds, we need to let the position breathe more.
Don't use tight stops that get hit by intraday noise.
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator


class ESMultiDayStrategy(Strategy):
    """ES Multi-Day Strategy using Bollinger Band mean reversion."""

    def __init__(
        self,
        # Trend determination
        trend_ema: int = 500,           # ~41 hours / ~5 trading days

        # Bollinger Bands for entry
        bb_period: int = 120,           # 10-hour BB
        bb_std: float = 2.0,

        # Entry confirmation
        rsi_period: int = 14,
        rsi_oversold: float = 40.0,     # More generous than typical 30
        rsi_overbought: float = 60.0,

        # Risk management
        atr_period: int = 60,
        stop_atr: float = 6.0,          # Very wide stop for multi-day
        target_pct: float = 2.5,        # Fixed % target
        trail_pct: float = 1.5,         # Trailing stop at 1.5% from high

        # Position management
        max_hold_bars: int = 1200,      # ~5 days (100 hours)
        min_hold_bars: int = 288,       # ~24 hours minimum
        min_volume: int = 20,

        # Entry cooldown
        min_bars_between_trades: int = 144,  # 12 hours
    ):
        super().__init__(name="ES_multiday")

        self.trend_ema = trend_ema
        self.bb_period = bb_period
        self.bb_std = bb_std

        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.target_pct = target_pct / 100
        self.trail_pct = trail_pct / 100

        self.max_hold_bars = max_hold_bars
        self.min_hold_bars = min_hold_bars
        self.min_volume = min_volume
        self.min_bars_between_trades = min_bars_between_trades

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
        self.trailing_stop = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.trade_direction = None
        self.current_atr = None
        self.last_trade_bar = -300

    def _calculate_ema(self, prices: list, period: int) -> Optional[float]:
        """Calculate EMA."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _is_uptrend(self, close: float, trend_ema: float) -> bool:
        """Simple trend check: price above trend EMA."""
        return close > trend_ema

    def _is_downtrend(self, close: float, trend_ema: float) -> bool:
        """Simple trend check: price below trend EMA."""
        return close < trend_ema

    def _is_bb_oversold(
        self,
        bar,
        lower_bb: float,
        rsi: float,
        atr: float
    ) -> bool:
        """
        Check for oversold at lower Bollinger Band:
        - Price touched or pierced lower BB
        - RSI shows oversold
        """
        # Price at or below lower BB
        if bar.low > lower_bb:
            return False

        # RSI confirms oversold
        if rsi > self.rsi_oversold:
            return False

        return True

    def _is_bb_overbought(
        self,
        bar,
        upper_bb: float,
        rsi: float,
        atr: float
    ) -> bool:
        """Check for overbought at upper Bollinger Band."""
        if bar.high < upper_bb:
            return False

        if rsi < self.rsi_overbought:
            return False

        return True

    def _is_reversal_candle_bullish(self, bar) -> bool:
        """Check for bullish reversal candle."""
        # Positive close (green candle)
        if bar.close <= bar.open:
            return False

        # Close in upper half of range
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False

        if (bar.close - bar.low) / range_size < 0.4:
            return False

        return True

    def _is_reversal_candle_bearish(self, bar) -> bool:
        """Check for bearish reversal candle."""
        # Negative close (red candle)
        if bar.close >= bar.open:
            return False

        # Close in lower half of range
        range_size = bar.high - bar.low
        if range_size <= 0:
            return False

        if (bar.high - bar.close) / range_size < 0.4:
            return False

        return True

    def _manage_position(self, engine, bar) -> bool:
        """Manage position with percentage-based trailing stop."""
        if engine.position.is_flat:
            return False

        bars_held = engine.current_index - self.entry_bar

        # Update high/low tracking
        if self.trade_direction == 'long':
            self.highest_since_entry = max(self.highest_since_entry, bar.high)
        else:
            self.lowest_since_entry = min(self.lowest_since_entry, bar.low)

        # Before minimum hold: only exit on catastrophic stop
        if bars_held < self.min_hold_bars:
            if self.trade_direction == 'long':
                # Catastrophic stop (only exit if really bad)
                if bar.low <= self.stop_price:
                    engine.close_position()
                    self._reset()
                    return True
            else:
                if bar.high >= self.stop_price:
                    engine.close_position()
                    self._reset()
                    return True
            return False

        # After minimum hold: apply trailing stop and time limit
        # Time exit
        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset()
            return True

        if self.trade_direction == 'long':
            # Initial stop
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Target hit
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop (percentage from highest)
            trailing_level = self.highest_since_entry * (1 - self.trail_pct)
            if trailing_level > self.stop_price:  # Trail up only
                self.stop_price = trailing_level

            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

        else:  # Short
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            if bar.low <= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop (percentage from lowest)
            trailing_level = self.lowest_since_entry * (1 + self.trail_pct)
            if trailing_level < self.stop_price:  # Trail down only
                self.stop_price = trailing_level

            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True

        return False

    def _reset(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.trade_direction = None

    def _enter_long(self, engine, price: float):
        """Enter long position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'long'
        self.stop_price = price - self.current_atr * self.stop_atr
        self.target_price = price * (1 + self.target_pct)
        self.highest_since_entry = price
        self.lowest_since_entry = price
        self.last_trade_bar = engine.current_index
        engine.buy(1)

    def _enter_short(self, engine, price: float):
        """Enter short position."""
        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = 'short'
        self.stop_price = price + self.current_atr * self.stop_atr
        self.target_price = price * (1 - self.target_pct)
        self.highest_since_entry = price
        self.lowest_since_entry = price
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

        # Need enough data
        min_bars = max(
            self.trend_ema + 10,
            self.bb_period + 10,
            self.rsi_period + 1,
            self.atr_period + 1,
        )
        if len(self.closes) < min_bars:
            return

        # Calculate indicators
        trend_ema = self._calculate_ema(self.closes, self.trend_ema)
        if trend_ema is None:
            return

        bb = Indicator.bollinger_bands(self.closes, self.bb_period, self.bb_std)
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)

        if bb is None or rsi is None or atr is None:
            return

        middle_bb, upper_bb, lower_bb = bb
        self.current_atr = atr

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Check cooldown
        if engine.current_index - self.last_trade_bar < self.min_bars_between_trades:
            return

        # Entry logic: mean reversion at BB extremes in trend direction
        if self._is_uptrend(bar.close, trend_ema):
            # In uptrend, buy dips at lower BB
            if self._is_bb_oversold(bar, lower_bb, rsi, atr):
                if self._is_reversal_candle_bullish(bar):
                    self._enter_long(engine, bar.close)

        elif self._is_downtrend(bar.close, trend_ema):
            # In downtrend, short rallies at upper BB
            if self._is_bb_overbought(bar, upper_bb, rsi, atr):
                if self._is_reversal_candle_bearish(bar):
                    self._enter_short(engine, bar.close)


def run_backtest():
    """Run the ES multi-day backtest."""
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

    strategy = ESMultiDayStrategy(
        trend_ema=500,
        bb_period=120,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=40.0,
        rsi_overbought=60.0,
        atr_period=60,
        stop_atr=6.0,
        target_pct=2.5,
        trail_pct=1.5,
        max_hold_bars=1200,
        min_hold_bars=288,
        min_volume=20,
        min_bars_between_trades=144,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES MULTI-DAY Strategy Results (1-5 day holds)")
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
        avg_bars = results['trades']['bars_held'].mean()
        print(f"\nAvg Bars Held:    {avg_bars:.1f} bars")
        print(f"                  {avg_bars * 5 / 60:.1f} hours")
        print(f"                  {avg_bars * 5 / 60 / 24:.1f} days")

        trades_df = results['trades']
        long_trades = trades_df[trades_df['side'] == 'LONG']
        short_trades = trades_df[trades_df['side'] == 'SHORT']

        if len(long_trades) > 0:
            print(f"\nLong trades:  {len(long_trades)} | Win rate: {(long_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${long_trades['pnl'].mean():.2f}")
        if len(short_trades) > 0:
            print(f"Short trades: {len(short_trades)} | Win rate: {(short_trades['pnl'] > 0).mean() * 100:.1f}% | Avg P&L: ${short_trades['pnl'].mean():.2f}")
