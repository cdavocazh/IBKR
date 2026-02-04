"""
Market Regime Detection System

Identifies three market regimes:
- BULLISH: Uptrend, buy-the-dip opportunities
- NEUTRAL: Ranging/consolidating, mean reversion at extremes
- BEARISH: Downtrend, sell-the-rip opportunities

Regime detection uses multiple signals:
1. Price vs Moving Averages (trend)
2. Moving Average Slope (momentum)
3. ADX (trend strength)
4. Volatility (VIX proxy via ATR)
5. Higher Highs / Lower Lows (market structure)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd
import numpy as np


class MarketRegime(Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


@dataclass
class RegimeIndicators:
    """Key indicators for regime-based trading."""
    # Trend indicators
    sma_20: float
    sma_50: float
    sma_200: float
    ema_9: float
    ema_21: float

    # Momentum
    rsi_14: float
    rsi_7: float
    macd: float
    macd_signal: float
    macd_histogram: float

    # Trend strength
    adx: float
    plus_di: float
    minus_di: float

    # Volatility
    atr_14: float
    atr_percent: float  # ATR as % of price
    bollinger_width: float

    # Price levels
    high_20: float
    low_20: float
    high_50: float
    low_50: float

    # Regime
    regime: MarketRegime
    regime_strength: float  # 0-100, how confident


class RegimeDetector:
    """
    Detect market regime using multiple indicators.

    Lookback period for regime determination is configurable,
    typically 2-4 weeks (10-20 trading days).
    """

    def __init__(
        self,
        trend_lookback: int = 20,
        structure_lookback: int = 10,
        adx_threshold: float = 25.0,
        trend_threshold: float = 0.02,  # 2% above/below MA
    ):
        """
        Initialize regime detector.

        Args:
            trend_lookback: Bars for trend analysis
            structure_lookback: Bars for HH/LL analysis
            adx_threshold: ADX level to confirm trending
            trend_threshold: % deviation from MA to confirm trend
        """
        self.trend_lookback = trend_lookback
        self.structure_lookback = structure_lookback
        self.adx_threshold = adx_threshold
        self.trend_threshold = trend_threshold

    def detect_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect market regime for each bar in the DataFrame.

        Args:
            df: OHLCV DataFrame

        Returns:
            DataFrame with added regime columns
        """
        df = df.copy()

        # Calculate all indicators
        df = self._add_moving_averages(df)
        df = self._add_rsi(df)
        df = self._add_macd(df)
        df = self._add_adx(df)
        df = self._add_atr(df)
        df = self._add_bollinger(df)
        df = self._add_structure(df)

        # Determine regime
        df["regime"] = df.apply(self._classify_regime, axis=1)
        df["regime_strength"] = df.apply(self._calculate_regime_strength, axis=1)

        return df

    def get_current_regime(self, df: pd.DataFrame) -> tuple[MarketRegime, RegimeIndicators]:
        """
        Get current market regime and key indicators.

        Args:
            df: OHLCV DataFrame with enough history

        Returns:
            Tuple of (MarketRegime, RegimeIndicators)
        """
        df = self.detect_regime(df)
        latest = df.iloc[-1]

        indicators = RegimeIndicators(
            sma_20=latest.get("sma_20", 0),
            sma_50=latest.get("sma_50", 0),
            sma_200=latest.get("sma_200", 0),
            ema_9=latest.get("ema_9", 0),
            ema_21=latest.get("ema_21", 0),
            rsi_14=latest.get("rsi_14", 50),
            rsi_7=latest.get("rsi_7", 50),
            macd=latest.get("macd", 0),
            macd_signal=latest.get("macd_signal", 0),
            macd_histogram=latest.get("macd_hist", 0),
            adx=latest.get("adx", 0),
            plus_di=latest.get("plus_di", 0),
            minus_di=latest.get("minus_di", 0),
            atr_14=latest.get("atr_14", 0),
            atr_percent=latest.get("atr_percent", 0),
            bollinger_width=latest.get("bb_width", 0),
            high_20=latest.get("high_20", 0),
            low_20=latest.get("low_20", 0),
            high_50=latest.get("high_50", 0),
            low_50=latest.get("low_50", 0),
            regime=MarketRegime(latest["regime"]),
            regime_strength=latest["regime_strength"],
        )

        return MarketRegime(latest["regime"]), indicators

    def _add_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add SMA and EMA indicators."""
        df["sma_20"] = df["close"].rolling(20).mean()
        df["sma_50"] = df["close"].rolling(50).mean()
        df["sma_200"] = df["close"].rolling(200).mean()

        df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()

        # MA slopes (rate of change over 5 periods)
        df["sma_20_slope"] = df["sma_20"].pct_change(5)
        df["sma_50_slope"] = df["sma_50"].pct_change(5)

        # Price relative to MAs
        df["price_vs_sma20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
        df["price_vs_sma50"] = (df["close"] - df["sma_50"]) / df["sma_50"]
        df["price_vs_sma200"] = (df["close"] - df["sma_200"]) / df["sma_200"]

        return df

    def _add_rsi(self, df: pd.DataFrame, periods: list = [7, 14]) -> pd.DataFrame:
        """Add RSI indicators."""
        for period in periods:
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss.replace(0, np.inf)
            df[f"rsi_{period}"] = 100 - (100 / (1 + rs))

        return df

    def _add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MACD indicator."""
        ema_12 = df["close"].ewm(span=12, adjust=False).mean()
        ema_26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        return df

    def _add_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add ADX and DI indicators."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        # Smoothed values
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)

        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
        adx = dx.ewm(span=period, adjust=False).mean()

        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        df["adx"] = adx

        return df

    def _add_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add ATR indicator."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        df["atr_14"] = tr.rolling(period).mean()
        df["atr_percent"] = df["atr_14"] / df["close"] * 100

        return df

    def _add_bollinger(self, df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
        """Add Bollinger Bands."""
        sma = df["close"].rolling(period).mean()
        std_dev = df["close"].rolling(period).std()

        df["bb_upper"] = sma + std * std_dev
        df["bb_lower"] = sma - std * std_dev
        df["bb_middle"] = sma
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"] * 100
        df["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

        return df

    def _add_structure(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add market structure indicators (HH, HL, LH, LL)."""
        lookback = self.structure_lookback

        df["high_20"] = df["high"].rolling(20).max()
        df["low_20"] = df["low"].rolling(20).min()
        df["high_50"] = df["high"].rolling(50).max()
        df["low_50"] = df["low"].rolling(50).min()

        # Higher highs / Lower lows over lookback period
        df["hh_count"] = 0
        df["ll_count"] = 0

        for i in range(lookback, len(df)):
            window = df.iloc[i-lookback:i+1]
            highs = window["high"].values
            lows = window["low"].values

            # Count higher highs
            hh = sum(1 for j in range(1, len(highs)) if highs[j] > max(highs[:j]))
            # Count lower lows
            ll = sum(1 for j in range(1, len(lows)) if lows[j] < min(lows[:j]))

            df.iloc[i, df.columns.get_loc("hh_count")] = hh
            df.iloc[i, df.columns.get_loc("ll_count")] = ll

        return df

    def _classify_regime(self, row) -> str:
        """Classify market regime for a single row."""
        # Check for NaN values
        if pd.isna(row.get("sma_50")) or pd.isna(row.get("adx")):
            return MarketRegime.NEUTRAL.value

        bullish_signals = 0
        bearish_signals = 0

        # 1. Price vs Moving Averages
        if row.get("price_vs_sma20", 0) > self.trend_threshold:
            bullish_signals += 1
        elif row.get("price_vs_sma20", 0) < -self.trend_threshold:
            bearish_signals += 1

        if row.get("price_vs_sma50", 0) > self.trend_threshold:
            bullish_signals += 1
        elif row.get("price_vs_sma50", 0) < -self.trend_threshold:
            bearish_signals += 1

        # 2. MA Alignment (Golden Cross / Death Cross)
        if row.get("sma_20", 0) > row.get("sma_50", 0):
            bullish_signals += 1
        else:
            bearish_signals += 1

        if row.get("sma_50", 0) > row.get("sma_200", 0):
            bullish_signals += 1
        elif row.get("sma_50", 0) < row.get("sma_200", 0):
            bearish_signals += 1

        # 3. MA Slope
        if row.get("sma_20_slope", 0) > 0.01:
            bullish_signals += 1
        elif row.get("sma_20_slope", 0) < -0.01:
            bearish_signals += 1

        # 4. ADX + DI
        if row.get("adx", 0) > self.adx_threshold:
            if row.get("plus_di", 0) > row.get("minus_di", 0):
                bullish_signals += 2  # Strong signal
            else:
                bearish_signals += 2

        # 5. MACD
        if row.get("macd_hist", 0) > 0:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # 6. Market Structure (HH/LL)
        if row.get("hh_count", 0) > row.get("ll_count", 0):
            bullish_signals += 1
        elif row.get("ll_count", 0) > row.get("hh_count", 0):
            bearish_signals += 1

        # Determine regime
        total_signals = bullish_signals + bearish_signals
        if total_signals == 0:
            return MarketRegime.NEUTRAL.value

        bull_ratio = bullish_signals / total_signals

        if bull_ratio >= 0.65:
            return MarketRegime.BULLISH.value
        elif bull_ratio <= 0.35:
            return MarketRegime.BEARISH.value
        else:
            return MarketRegime.NEUTRAL.value

    def _calculate_regime_strength(self, row) -> float:
        """Calculate confidence level of regime classification (0-100)."""
        if pd.isna(row.get("adx")):
            return 50.0

        strength = 50.0  # Base

        # ADX contributes to strength
        adx = row.get("adx", 0)
        if adx > 40:
            strength += 20
        elif adx > 30:
            strength += 15
        elif adx > 25:
            strength += 10
        elif adx < 20:
            strength -= 10

        # Price distance from MAs
        price_vs_ma = abs(row.get("price_vs_sma50", 0))
        if price_vs_ma > 0.05:
            strength += 15
        elif price_vs_ma > 0.03:
            strength += 10

        # MA alignment adds confidence
        if row.get("sma_20", 0) > row.get("sma_50", 0) > row.get("sma_200", 0):
            strength += 10  # Perfect bull alignment
        elif row.get("sma_20", 0) < row.get("sma_50", 0) < row.get("sma_200", 0):
            strength += 10  # Perfect bear alignment

        return min(100, max(0, strength))

    def print_regime_report(self, df: pd.DataFrame):
        """Print a report on current market regime."""
        regime, indicators = self.get_current_regime(df)

        print("\n" + "=" * 60)
        print("MARKET REGIME ANALYSIS")
        print("=" * 60)

        print(f"\nCurrent Regime: {regime.value}")
        print(f"Confidence: {indicators.regime_strength:.1f}%")

        print("\n--- Trend Indicators ---")
        print(f"Price vs SMA20: {(df['close'].iloc[-1] / indicators.sma_20 - 1) * 100:+.2f}%")
        print(f"Price vs SMA50: {(df['close'].iloc[-1] / indicators.sma_50 - 1) * 100:+.2f}%")
        print(f"Price vs SMA200: {(df['close'].iloc[-1] / indicators.sma_200 - 1) * 100:+.2f}%")
        print(f"EMA9 vs EMA21: {'Bullish' if indicators.ema_9 > indicators.ema_21 else 'Bearish'}")

        print("\n--- Momentum ---")
        print(f"RSI(14): {indicators.rsi_14:.1f}")
        print(f"RSI(7): {indicators.rsi_7:.1f}")
        print(f"MACD Histogram: {indicators.macd_histogram:+.2f}")

        print("\n--- Trend Strength ---")
        print(f"ADX: {indicators.adx:.1f} ({'Trending' if indicators.adx > 25 else 'Ranging'})")
        print(f"+DI: {indicators.plus_di:.1f}")
        print(f"-DI: {indicators.minus_di:.1f}")

        print("\n--- Volatility ---")
        print(f"ATR(14): {indicators.atr_14:.2f}")
        print(f"ATR%: {indicators.atr_percent:.2f}%")
        print(f"Bollinger Width: {indicators.bollinger_width:.2f}%")

        print("\n--- Key Levels ---")
        print(f"20-Day High: {indicators.high_20:.2f}")
        print(f"20-Day Low: {indicators.low_20:.2f}")
        print(f"50-Day High: {indicators.high_50:.2f}")
        print(f"50-Day Low: {indicators.low_50:.2f}")

        print("\n" + "=" * 60)

        # Regime-specific recommendations
        print("\n--- TRADING RECOMMENDATIONS ---")
        if regime == MarketRegime.BULLISH:
            print("\nBULLISH REGIME - Buy the Dip Strategy:")
            print("  Entry Signals:")
            print(f"    - RSI(7) < 30 (currently {indicators.rsi_7:.1f})")
            print(f"    - Price near SMA20 ({indicators.sma_20:.2f})")
            print(f"    - Price at lower Bollinger Band")
            print(f"    - Pullback to 20-day low ({indicators.low_20:.2f})")
            print("  Exit Signals:")
            print(f"    - RSI(7) > 70")
            print(f"    - Price at 20-day high ({indicators.high_20:.2f})")
            print(f"    - Upper Bollinger Band")

        elif regime == MarketRegime.BEARISH:
            print("\nBEARISH REGIME - Sell the Rip Strategy:")
            print("  Entry Signals (Short):")
            print(f"    - RSI(7) > 70 (currently {indicators.rsi_7:.1f})")
            print(f"    - Price near SMA20 ({indicators.sma_20:.2f})")
            print(f"    - Price at upper Bollinger Band")
            print(f"    - Rally to 20-day high ({indicators.high_20:.2f})")
            print("  Exit Signals:")
            print(f"    - RSI(7) < 30")
            print(f"    - Price at 20-day low ({indicators.low_20:.2f})")
            print(f"    - Lower Bollinger Band")

        else:  # NEUTRAL
            print("\nNEUTRAL REGIME - Mean Reversion at Extremes:")
            print("  Long Entry Signals:")
            print(f"    - RSI(7) < 25 (currently {indicators.rsi_7:.1f})")
            print(f"    - Price at lower Bollinger Band")
            print(f"    - Price near 20-day low ({indicators.low_20:.2f})")
            print("  Short Entry Signals:")
            print(f"    - RSI(7) > 75")
            print(f"    - Price at upper Bollinger Band")
            print(f"    - Price near 20-day high ({indicators.high_20:.2f})")
            print("  Exit at middle Bollinger Band (mean)")

        print("\n" + "=" * 60)
