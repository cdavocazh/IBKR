"""
Regime-Specific Trading Strategies

Three strategies that adapt to market conditions:
1. BuyTheDip - For bullish regimes
2. SellTheRip - For bearish regimes
3. MeanReversionExtremes - For neutral/ranging regimes

Plus an adaptive strategy that switches based on detected regime.
"""

from typing import Optional
import numpy as np
from .strategy import Strategy, Indicator
from .regime import RegimeDetector, MarketRegime


class BuyTheDipStrategy(Strategy):
    """
    Buy-the-Dip Strategy for BULLISH regimes.

    Logic:
    - Only trade in established uptrends
    - Buy when price pulls back to support levels
    - Use RSI oversold as entry signal
    - Exit on strength (RSI overbought or target)

    Key Indicators:
    - RSI(7) for timing entries/exits
    - Price relative to SMA20/SMA50 for trend
    - Bollinger Bands for support levels
    - ATR for stop loss sizing
    """

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_period: int = 7,
        trend_ma_period: int = 50,
        stop_atr_multiple: float = 2.0,
        target_atr_multiple: float = 3.0,
    ):
        super().__init__(name="BuyTheDip")
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_period = rsi_period
        self.trend_ma_period = trend_ma_period
        self.stop_atr_multiple = stop_atr_multiple
        self.target_atr_multiple = target_atr_multiple

        # State
        self.prices = []
        self.highs = []
        self.lows = []
        self.entry_price: Optional[float] = None
        self.stop_loss: Optional[float] = None
        self.take_profit: Optional[float] = None

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        # Need enough data
        if len(self.prices) < self.trend_ma_period + 10:
            return

        # Calculate indicators
        rsi = Indicator.rsi(self.prices, self.rsi_period)
        sma = Indicator.sma(self.prices, self.trend_ma_period)
        sma_20 = Indicator.sma(self.prices, 20)
        atr = Indicator.atr(self.highs, self.lows, self.prices, 14)
        bb = Indicator.bollinger_bands(self.prices, 20, 2.0)

        if rsi is None or sma is None or atr is None or bb is None:
            return

        middle, upper, lower = bb

        # Check if in uptrend (price above 50 SMA, 20 SMA above 50 SMA)
        in_uptrend = bar.close > sma and sma_20 > sma

        # Manage existing position
        if engine.position.is_long:
            # Check stop loss
            if bar.low <= self.stop_loss:
                engine.close_position()
                self.entry_price = None
                return

            # Check take profit
            if bar.high >= self.take_profit:
                engine.close_position()
                self.entry_price = None
                return

            # Exit on RSI overbought
            if rsi > self.rsi_overbought:
                engine.close_position()
                self.entry_price = None
                return

        # Entry logic - only in uptrend
        elif engine.position.is_flat and in_uptrend:
            # Buy the dip conditions:
            # 1. RSI oversold
            # 2. Price near lower Bollinger or SMA20
            near_support = bar.close <= lower * 1.01 or bar.close <= sma_20 * 1.01

            if rsi < self.rsi_oversold and near_support:
                engine.buy(1)
                self.entry_price = bar.close
                self.stop_loss = bar.close - (atr * self.stop_atr_multiple)
                self.take_profit = bar.close + (atr * self.target_atr_multiple)


class SellTheRipStrategy(Strategy):
    """
    Sell-the-Rip Strategy for BEARISH regimes.

    Logic:
    - Only trade in established downtrends
    - Short when price rallies to resistance levels
    - Use RSI overbought as entry signal
    - Exit on weakness (RSI oversold or target)

    Key Indicators:
    - RSI(7) for timing entries/exits
    - Price relative to SMA20/SMA50 for trend
    - Bollinger Bands for resistance levels
    - ATR for stop loss sizing
    """

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_period: int = 7,
        trend_ma_period: int = 50,
        stop_atr_multiple: float = 2.0,
        target_atr_multiple: float = 3.0,
    ):
        super().__init__(name="SellTheRip")
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_period = rsi_period
        self.trend_ma_period = trend_ma_period
        self.stop_atr_multiple = stop_atr_multiple
        self.target_atr_multiple = target_atr_multiple

        # State
        self.prices = []
        self.highs = []
        self.lows = []
        self.entry_price: Optional[float] = None
        self.stop_loss: Optional[float] = None
        self.take_profit: Optional[float] = None

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        if len(self.prices) < self.trend_ma_period + 10:
            return

        # Calculate indicators
        rsi = Indicator.rsi(self.prices, self.rsi_period)
        sma = Indicator.sma(self.prices, self.trend_ma_period)
        sma_20 = Indicator.sma(self.prices, 20)
        atr = Indicator.atr(self.highs, self.lows, self.prices, 14)
        bb = Indicator.bollinger_bands(self.prices, 20, 2.0)

        if rsi is None or sma is None or atr is None or bb is None:
            return

        middle, upper, lower = bb

        # Check if in downtrend
        in_downtrend = bar.close < sma and sma_20 < sma

        # Manage existing position
        if engine.position.is_short:
            # Check stop loss
            if bar.high >= self.stop_loss:
                engine.close_position()
                self.entry_price = None
                return

            # Check take profit
            if bar.low <= self.take_profit:
                engine.close_position()
                self.entry_price = None
                return

            # Exit on RSI oversold
            if rsi < self.rsi_oversold:
                engine.close_position()
                self.entry_price = None
                return

        # Entry logic - only in downtrend
        elif engine.position.is_flat and in_downtrend:
            # Sell the rip conditions:
            # 1. RSI overbought
            # 2. Price near upper Bollinger or SMA20
            near_resistance = bar.close >= upper * 0.99 or bar.close >= sma_20 * 0.99

            if rsi > self.rsi_overbought and near_resistance:
                engine.sell(1)
                self.entry_price = bar.close
                self.stop_loss = bar.close + (atr * self.stop_atr_multiple)
                self.take_profit = bar.close - (atr * self.target_atr_multiple)


class MeanReversionExtremesStrategy(Strategy):
    """
    Mean Reversion at Extremes for NEUTRAL regimes.

    Logic:
    - Trade when price reaches extreme levels in ranging market
    - Buy at extreme lows, sell at extreme highs
    - Exit at mean (middle Bollinger)

    Key Indicators:
    - RSI(7) with extreme thresholds (25/75)
    - Bollinger Bands for extremes
    - ADX to confirm ranging (< 25)
    """

    def __init__(
        self,
        rsi_extreme_low: float = 25.0,
        rsi_extreme_high: float = 75.0,
        rsi_period: int = 7,
        adx_max: float = 25.0,  # Only trade when ADX below this
        stop_atr_multiple: float = 1.5,
    ):
        super().__init__(name="MeanReversionExtremes")
        self.rsi_extreme_low = rsi_extreme_low
        self.rsi_extreme_high = rsi_extreme_high
        self.rsi_period = rsi_period
        self.adx_max = adx_max
        self.stop_atr_multiple = stop_atr_multiple

        # State
        self.prices = []
        self.highs = []
        self.lows = []
        self.entry_price: Optional[float] = None
        self.stop_loss: Optional[float] = None

    def _calculate_adx(self, period: int = 14) -> Optional[float]:
        """Calculate ADX."""
        if len(self.prices) < period + 1:
            return None

        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, len(self.prices)):
            high = self.highs[i]
            low = self.lows[i]
            prev_close = self.prices[i-1]
            prev_high = self.highs[i-1]
            prev_low = self.lows[i-1]

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            plus_dm = high - prev_high if high - prev_high > prev_low - low and high - prev_high > 0 else 0
            minus_dm = prev_low - low if prev_low - low > high - prev_high and prev_low - low > 0 else 0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        if len(tr_list) < period:
            return None

        # Smoothed averages
        atr = sum(tr_list[-period:]) / period
        plus_di = 100 * sum(plus_dm_list[-period:]) / period / atr if atr > 0 else 0
        minus_di = 100 * sum(minus_dm_list[-period:]) / period / atr if atr > 0 else 0

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
        return dx

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        if len(self.prices) < 50:
            return

        # Calculate indicators
        rsi = Indicator.rsi(self.prices, self.rsi_period)
        bb = Indicator.bollinger_bands(self.prices, 20, 2.0)
        atr = Indicator.atr(self.highs, self.lows, self.prices, 14)
        adx = self._calculate_adx(14)

        if rsi is None or bb is None or atr is None or adx is None:
            return

        middle, upper, lower = bb

        # Only trade in ranging market (low ADX)
        is_ranging = adx < self.adx_max

        # Manage existing position
        if engine.position.is_long:
            # Stop loss
            if bar.low <= self.stop_loss:
                engine.close_position()
                self.entry_price = None
                return

            # Exit at mean
            if bar.close >= middle:
                engine.close_position()
                self.entry_price = None
                return

        elif engine.position.is_short:
            # Stop loss
            if bar.high >= self.stop_loss:
                engine.close_position()
                self.entry_price = None
                return

            # Exit at mean
            if bar.close <= middle:
                engine.close_position()
                self.entry_price = None
                return

        # Entry logic - only in ranging market
        elif engine.position.is_flat and is_ranging:
            # Extreme low - buy
            if rsi < self.rsi_extreme_low and bar.close <= lower:
                engine.buy(1)
                self.entry_price = bar.close
                self.stop_loss = bar.close - (atr * self.stop_atr_multiple)

            # Extreme high - sell
            elif rsi > self.rsi_extreme_high and bar.close >= upper:
                engine.sell(1)
                self.entry_price = bar.close
                self.stop_loss = bar.close + (atr * self.stop_atr_multiple)


class AdaptiveRegimeStrategy(Strategy):
    """
    Adaptive Strategy that switches based on market regime.

    Automatically detects regime and applies appropriate strategy:
    - BULLISH: Buy the dip
    - BEARISH: Sell the rip
    - NEUTRAL: Mean reversion at extremes

    Re-evaluates regime every N bars.
    """

    def __init__(
        self,
        regime_lookback: int = 20,
        regime_reeval_bars: int = 5,
    ):
        super().__init__(name="AdaptiveRegime")
        self.regime_lookback = regime_lookback
        self.regime_reeval_bars = regime_reeval_bars

        # Sub-strategies
        self.buy_dip = BuyTheDipStrategy()
        self.sell_rip = SellTheRipStrategy()
        self.mean_rev = MeanReversionExtremesStrategy()

        # State
        self.bar_count = 0
        self.current_regime = MarketRegime.NEUTRAL
        self.regime_detector = RegimeDetector()

        # Price history for regime detection
        self.ohlcv_history = []

    def on_bar(self, engine, bar):
        self.bar_count += 1

        # Store OHLCV for regime detection
        self.ohlcv_history.append({
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })

        # Also update sub-strategies
        self.buy_dip.prices.append(bar.close)
        self.buy_dip.highs.append(bar.high)
        self.buy_dip.lows.append(bar.low)

        self.sell_rip.prices.append(bar.close)
        self.sell_rip.highs.append(bar.high)
        self.sell_rip.lows.append(bar.low)

        self.mean_rev.prices.append(bar.close)
        self.mean_rev.highs.append(bar.high)
        self.mean_rev.lows.append(bar.low)

        # Need enough history
        if len(self.ohlcv_history) < 200:
            return

        # Re-evaluate regime periodically
        if self.bar_count % self.regime_reeval_bars == 0:
            import pandas as pd
            df = pd.DataFrame(self.ohlcv_history[-250:])
            df.index = pd.date_range(end="2024-01-01", periods=len(df), freq="D")
            df = self.regime_detector.detect_regime(df)
            self.current_regime = MarketRegime(df["regime"].iloc[-1])

        # Close opposite positions when regime changes
        if self.current_regime == MarketRegime.BULLISH and engine.position.is_short:
            engine.close_position()
        elif self.current_regime == MarketRegime.BEARISH and engine.position.is_long:
            engine.close_position()

        # Delegate to appropriate strategy
        if self.current_regime == MarketRegime.BULLISH:
            # Only call the core logic, not on_bar (we already updated prices)
            self._execute_buy_dip(engine, bar)
        elif self.current_regime == MarketRegime.BEARISH:
            self._execute_sell_rip(engine, bar)
        else:
            self._execute_mean_rev(engine, bar)

    def _execute_buy_dip(self, engine, bar):
        """Execute buy-the-dip logic."""
        s = self.buy_dip
        if len(s.prices) < 60:
            return

        rsi = Indicator.rsi(s.prices, s.rsi_period)
        sma = Indicator.sma(s.prices, s.trend_ma_period)
        sma_20 = Indicator.sma(s.prices, 20)
        atr = Indicator.atr(s.highs, s.lows, s.prices, 14)
        bb = Indicator.bollinger_bands(s.prices, 20, 2.0)

        if None in [rsi, sma, atr, bb]:
            return

        middle, upper, lower = bb
        in_uptrend = bar.close > sma and sma_20 > sma

        if engine.position.is_long:
            if s.stop_loss and bar.low <= s.stop_loss:
                engine.close_position()
                s.entry_price = None
            elif s.take_profit and bar.high >= s.take_profit:
                engine.close_position()
                s.entry_price = None
            elif rsi > s.rsi_overbought:
                engine.close_position()
                s.entry_price = None

        elif engine.position.is_flat and in_uptrend:
            near_support = bar.close <= lower * 1.01 or bar.close <= sma_20 * 1.01
            if rsi < s.rsi_oversold and near_support:
                engine.buy(1)
                s.entry_price = bar.close
                s.stop_loss = bar.close - (atr * s.stop_atr_multiple)
                s.take_profit = bar.close + (atr * s.target_atr_multiple)

    def _execute_sell_rip(self, engine, bar):
        """Execute sell-the-rip logic."""
        s = self.sell_rip
        if len(s.prices) < 60:
            return

        rsi = Indicator.rsi(s.prices, s.rsi_period)
        sma = Indicator.sma(s.prices, s.trend_ma_period)
        sma_20 = Indicator.sma(s.prices, 20)
        atr = Indicator.atr(s.highs, s.lows, s.prices, 14)
        bb = Indicator.bollinger_bands(s.prices, 20, 2.0)

        if None in [rsi, sma, atr, bb]:
            return

        middle, upper, lower = bb
        in_downtrend = bar.close < sma and sma_20 < sma

        if engine.position.is_short:
            if s.stop_loss and bar.high >= s.stop_loss:
                engine.close_position()
                s.entry_price = None
            elif s.take_profit and bar.low <= s.take_profit:
                engine.close_position()
                s.entry_price = None
            elif rsi < s.rsi_oversold:
                engine.close_position()
                s.entry_price = None

        elif engine.position.is_flat and in_downtrend:
            near_resistance = bar.close >= upper * 0.99 or bar.close >= sma_20 * 0.99
            if rsi > s.rsi_overbought and near_resistance:
                engine.sell(1)
                s.entry_price = bar.close
                s.stop_loss = bar.close + (atr * s.stop_atr_multiple)
                s.take_profit = bar.close - (atr * s.target_atr_multiple)

    def _execute_mean_rev(self, engine, bar):
        """Execute mean reversion logic."""
        s = self.mean_rev
        if len(s.prices) < 50:
            return

        rsi = Indicator.rsi(s.prices, s.rsi_period)
        bb = Indicator.bollinger_bands(s.prices, 20, 2.0)
        atr = Indicator.atr(s.highs, s.lows, s.prices, 14)
        adx = s._calculate_adx(14)

        if None in [rsi, bb, atr, adx]:
            return

        middle, upper, lower = bb
        is_ranging = adx < s.adx_max

        if engine.position.is_long:
            if s.stop_loss and bar.low <= s.stop_loss:
                engine.close_position()
                s.entry_price = None
            elif bar.close >= middle:
                engine.close_position()
                s.entry_price = None

        elif engine.position.is_short:
            if s.stop_loss and bar.high >= s.stop_loss:
                engine.close_position()
                s.entry_price = None
            elif bar.close <= middle:
                engine.close_position()
                s.entry_price = None

        elif engine.position.is_flat and is_ranging:
            if rsi < s.rsi_extreme_low and bar.close <= lower:
                engine.buy(1)
                s.entry_price = bar.close
                s.stop_loss = bar.close - (atr * s.stop_atr_multiple)
            elif rsi > s.rsi_extreme_high and bar.close >= upper:
                engine.sell(1)
                s.entry_price = bar.close
                s.stop_loss = bar.close + (atr * s.stop_atr_multiple)
