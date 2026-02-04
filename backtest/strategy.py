"""
Strategy Base Class and Example Strategies

Provides:
- Abstract base class for strategies
- Common technical indicators
- Example strategy implementations
"""

from abc import ABC, abstractmethod
from collections import deque
from typing import Optional
import numpy as np


class Strategy(ABC):
    """
    Abstract base class for trading strategies.

    Subclass this and implement on_bar() to create your strategy.
    """

    def __init__(self, name: str = "Strategy"):
        self.name = name

    @abstractmethod
    def on_bar(self, engine, bar):
        """
        Called on each new bar.

        Args:
            engine: BacktestEngine instance
            bar: Current Bar object with OHLCV data

        Use engine.buy(), engine.sell(), engine.close_position()
        to place orders.
        """
        pass

    def on_start(self, engine):
        """Called before backtest starts. Override to initialize state."""
        pass

    def on_end(self, engine):
        """Called after backtest ends. Override for cleanup."""
        pass


class Indicator:
    """Common technical indicators."""

    @staticmethod
    def sma(prices: list, period: int) -> Optional[float]:
        """Simple Moving Average."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    @staticmethod
    def ema(prices: list, period: int, smoothing: float = 2.0) -> Optional[float]:
        """Exponential Moving Average."""
        if len(prices) < period:
            return None

        multiplier = smoothing / (period + 1)
        ema = sum(prices[:period]) / period  # SMA for first value

        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    @staticmethod
    def rsi(prices: list, period: int = 14) -> Optional[float]:
        """Relative Strength Index."""
        if len(prices) < period + 1:
            return None

        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c if c > 0 else 0 for c in changes[-period:]]
        losses = [-c if c < 0 else 0 for c in changes[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
        """Average True Range."""
        if len(closes) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)

        return sum(true_ranges[-period:]) / period

    @staticmethod
    def bollinger_bands(
        prices: list,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Optional[tuple]:
        """Bollinger Bands (middle, upper, lower)."""
        if len(prices) < period:
            return None

        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5

        return (sma, sma + std_dev * std, sma - std_dev * std)

    @staticmethod
    def macd(
        prices: list,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Optional[tuple]:
        """MACD (macd_line, signal_line, histogram)."""
        if len(prices) < slow + signal:
            return None

        fast_ema = Indicator.ema(prices, fast)
        slow_ema = Indicator.ema(prices, slow)

        if fast_ema is None or slow_ema is None:
            return None

        macd_line = fast_ema - slow_ema

        # Calculate signal line (EMA of MACD)
        # Simplified: use recent MACD values
        macd_values = []
        for i in range(signal):
            idx = len(prices) - signal + i
            if idx >= slow:
                f = Indicator.ema(prices[:idx+1], fast)
                s = Indicator.ema(prices[:idx+1], slow)
                if f and s:
                    macd_values.append(f - s)

        if len(macd_values) < signal:
            return None

        signal_line = sum(macd_values) / len(macd_values)
        histogram = macd_line - signal_line

        return (macd_line, signal_line, histogram)


class MovingAverageCrossover(Strategy):
    """
    Simple Moving Average Crossover Strategy.

    Buy when fast MA crosses above slow MA.
    Sell when fast MA crosses below slow MA.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        super().__init__(name=f"MA_Crossover_{fast_period}_{slow_period}")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.prices = []
        self.prev_fast_ma = None
        self.prev_slow_ma = None

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        # Need enough data
        if len(self.prices) < self.slow_period:
            return

        fast_ma = Indicator.sma(self.prices, self.fast_period)
        slow_ma = Indicator.sma(self.prices, self.slow_period)

        # Check for crossover
        if self.prev_fast_ma is not None and self.prev_slow_ma is not None:
            # Bullish crossover
            if self.prev_fast_ma <= self.prev_slow_ma and fast_ma > slow_ma:
                if engine.position.is_short:
                    engine.close_position()
                if engine.position.is_flat:
                    engine.buy(1)

            # Bearish crossover
            elif self.prev_fast_ma >= self.prev_slow_ma and fast_ma < slow_ma:
                if engine.position.is_long:
                    engine.close_position()
                if engine.position.is_flat:
                    engine.sell(1)

        self.prev_fast_ma = fast_ma
        self.prev_slow_ma = slow_ma


class RSIMeanReversion(Strategy):
    """
    RSI Mean Reversion Strategy.

    Buy when RSI drops below oversold threshold.
    Sell when RSI rises above overbought threshold.
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ):
        super().__init__(name=f"RSI_MeanRev_{period}")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.prices = []

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        if len(self.prices) < self.period + 1:
            return

        rsi = Indicator.rsi(self.prices, self.period)
        if rsi is None:
            return

        # Oversold - buy signal
        if rsi < self.oversold:
            if engine.position.is_short:
                engine.close_position()
            if engine.position.is_flat:
                engine.buy(1)

        # Overbought - sell signal
        elif rsi > self.overbought:
            if engine.position.is_long:
                engine.close_position()
            if engine.position.is_flat:
                engine.sell(1)


class BreakoutStrategy(Strategy):
    """
    Donchian Channel Breakout Strategy.

    Buy on new high (breakout above N-period high).
    Sell on new low (breakdown below N-period low).
    """

    def __init__(self, lookback: int = 20):
        super().__init__(name=f"Breakout_{lookback}")
        self.lookback = lookback
        self.highs = []
        self.lows = []

    def on_bar(self, engine, bar):
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        if len(self.highs) < self.lookback + 1:
            return

        # Previous N-period high/low (excluding current bar)
        prev_high = max(self.highs[-self.lookback-1:-1])
        prev_low = min(self.lows[-self.lookback-1:-1])

        # Breakout above
        if bar.close > prev_high:
            if engine.position.is_short:
                engine.close_position()
            if engine.position.is_flat:
                engine.buy(1)

        # Breakdown below
        elif bar.close < prev_low:
            if engine.position.is_long:
                engine.close_position()
            if engine.position.is_flat:
                engine.sell(1)


class BollingerBandStrategy(Strategy):
    """
    Bollinger Band Mean Reversion Strategy.

    Buy when price touches lower band.
    Sell when price touches upper band.
    Exit at middle band.
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        super().__init__(name=f"BB_{period}_{std_dev}")
        self.period = period
        self.std_dev = std_dev
        self.prices = []

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        if len(self.prices) < self.period:
            return

        bands = Indicator.bollinger_bands(self.prices, self.period, self.std_dev)
        if bands is None:
            return

        middle, upper, lower = bands

        # Price at lower band - buy
        if bar.close <= lower:
            if engine.position.is_short:
                engine.close_position()
            if engine.position.is_flat:
                engine.buy(1)

        # Price at upper band - sell
        elif bar.close >= upper:
            if engine.position.is_long:
                engine.close_position()
            if engine.position.is_flat:
                engine.sell(1)

        # Exit at middle band
        elif engine.position.is_long and bar.close >= middle:
            engine.close_position()
        elif engine.position.is_short and bar.close <= middle:
            engine.close_position()


class MACDStrategy(Strategy):
    """
    MACD Crossover Strategy.

    Buy when MACD crosses above signal line.
    Sell when MACD crosses below signal line.
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(name=f"MACD_{fast}_{slow}_{signal}")
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.prices = []
        self.prev_histogram = None

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        if len(self.prices) < self.slow + self.signal:
            return

        macd_data = Indicator.macd(self.prices, self.fast, self.slow, self.signal)
        if macd_data is None:
            return

        macd_line, signal_line, histogram = macd_data

        if self.prev_histogram is not None:
            # Bullish crossover (histogram turns positive)
            if self.prev_histogram <= 0 and histogram > 0:
                if engine.position.is_short:
                    engine.close_position()
                if engine.position.is_flat:
                    engine.buy(1)

            # Bearish crossover (histogram turns negative)
            elif self.prev_histogram >= 0 and histogram < 0:
                if engine.position.is_long:
                    engine.close_position()
                if engine.position.is_flat:
                    engine.sell(1)

        self.prev_histogram = histogram
