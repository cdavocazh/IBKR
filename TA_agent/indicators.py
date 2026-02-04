"""
Core Technical Analysis Indicators

Mainstream indicators used in technical analysis:
1. Trend Indicators: SMA, EMA, MACD, ADX
2. Momentum Indicators: RSI, Stochastic, CCI, Williams %R
3. Volatility Indicators: Bollinger Bands, ATR, Keltner Channels
4. Volume Indicators: OBV, VWAP, Volume SMA
5. Support/Resistance: Pivot Points, Fibonacci Retracements
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass


@dataclass
class IndicatorResult:
    """Container for indicator calculation results."""
    name: str
    value: float
    signal: str  # 'bullish', 'bearish', 'neutral'
    strength: float  # 0-100
    details: Dict


class Indicators:
    """Collection of technical analysis indicators."""

    # ==================== TREND INDICATORS ====================

    @staticmethod
    def sma(prices: List[float], period: int) -> Optional[float]:
        """Simple Moving Average."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    @staticmethod
    def ema(prices: List[float], period: int) -> Optional[float]:
        """Exponential Moving Average."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    @staticmethod
    def ema_series(prices: List[float], period: int) -> List[float]:
        """Calculate EMA series for entire price list."""
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema_values = []
        ema = sum(prices[:period]) / period
        ema_values.extend([None] * (period - 1))
        ema_values.append(ema)
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
            ema_values.append(ema)
        return ema_values

    @staticmethod
    def macd(
        prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Optional[Tuple[float, float, float]]:
        """
        MACD (Moving Average Convergence Divergence).
        Returns: (macd_line, signal_line, histogram)
        """
        if len(prices) < slow_period + signal_period:
            return None

        fast_ema = Indicators.ema_series(prices, fast_period)
        slow_ema = Indicators.ema_series(prices, slow_period)

        macd_line = []
        for i in range(len(prices)):
            if fast_ema[i] is not None and slow_ema[i] is not None:
                macd_line.append(fast_ema[i] - slow_ema[i])
            else:
                macd_line.append(None)

        # Filter out None values for signal calculation
        valid_macd = [x for x in macd_line if x is not None]
        if len(valid_macd) < signal_period:
            return None

        signal_ema = Indicators.ema(valid_macd, signal_period)
        if signal_ema is None:
            return None

        current_macd = macd_line[-1]
        histogram = current_macd - signal_ema

        return (current_macd, signal_ema, histogram)

    @staticmethod
    def adx(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[Tuple[float, float, float]]:
        """
        Average Directional Index (ADX).
        Returns: (adx, +DI, -DI)
        """
        if len(highs) < period + 1:
            return None

        # Calculate True Range and Directional Movement
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]
            prev_high = highs[i-1]
            prev_low = lows[i-1]
            prev_close = closes[i-1]

            # True Range
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            # Directional Movement
            up_move = high - prev_high
            down_move = prev_low - low

            plus_dm = up_move if up_move > down_move and up_move > 0 else 0
            minus_dm = down_move if down_move > up_move and down_move > 0 else 0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        if len(tr_list) < period:
            return None

        # Smoothed averages
        def smooth_average(data, period):
            if len(data) < period:
                return None
            first_avg = sum(data[:period]) / period
            smoothed = [first_avg]
            for i in range(period, len(data)):
                smoothed.append(smoothed[-1] - (smoothed[-1] / period) + data[i])
            return smoothed

        atr_smooth = smooth_average(tr_list, period)
        plus_dm_smooth = smooth_average(plus_dm_list, period)
        minus_dm_smooth = smooth_average(minus_dm_list, period)

        if not all([atr_smooth, plus_dm_smooth, minus_dm_smooth]):
            return None

        # Calculate +DI and -DI
        plus_di = (plus_dm_smooth[-1] / atr_smooth[-1]) * 100 if atr_smooth[-1] != 0 else 0
        minus_di = (minus_dm_smooth[-1] / atr_smooth[-1]) * 100 if atr_smooth[-1] != 0 else 0

        # Calculate DX and ADX
        dx_list = []
        for i in range(len(atr_smooth)):
            pdi = (plus_dm_smooth[i] / atr_smooth[i]) * 100 if atr_smooth[i] != 0 else 0
            mdi = (minus_dm_smooth[i] / atr_smooth[i]) * 100 if atr_smooth[i] != 0 else 0
            if pdi + mdi != 0:
                dx = abs(pdi - mdi) / (pdi + mdi) * 100
            else:
                dx = 0
            dx_list.append(dx)

        if len(dx_list) < period:
            return None

        adx = sum(dx_list[-period:]) / period

        return (adx, plus_di, minus_di)

    # ==================== MOMENTUM INDICATORS ====================

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """Relative Strength Index."""
        if len(prices) < period + 1:
            return None

        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            gains.append(max(0, change))
            losses.append(max(0, -change))

        if len(gains) < period:
            return None

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def stochastic(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        k_period: int = 14,
        d_period: int = 3
    ) -> Optional[Tuple[float, float]]:
        """
        Stochastic Oscillator.
        Returns: (%K, %D)
        """
        if len(closes) < k_period + d_period:
            return None

        k_values = []
        for i in range(k_period - 1, len(closes)):
            highest_high = max(highs[i-k_period+1:i+1])
            lowest_low = min(lows[i-k_period+1:i+1])

            if highest_high == lowest_low:
                k = 50.0
            else:
                k = ((closes[i] - lowest_low) / (highest_high - lowest_low)) * 100
            k_values.append(k)

        if len(k_values) < d_period:
            return None

        k = k_values[-1]
        d = sum(k_values[-d_period:]) / d_period

        return (k, d)

    @staticmethod
    def cci(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 20
    ) -> Optional[float]:
        """Commodity Channel Index."""
        if len(closes) < period:
            return None

        # Typical Price
        tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]

        # SMA of Typical Price
        tp_sma = sum(tp[-period:]) / period

        # Mean Deviation
        mean_dev = sum(abs(tp[i] - tp_sma) for i in range(-period, 0)) / period

        if mean_dev == 0:
            return 0.0

        cci = (tp[-1] - tp_sma) / (0.015 * mean_dev)

        return cci

    @staticmethod
    def williams_r(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """Williams %R."""
        if len(closes) < period:
            return None

        highest_high = max(highs[-period:])
        lowest_low = min(lows[-period:])

        if highest_high == lowest_low:
            return -50.0

        williams = ((highest_high - closes[-1]) / (highest_high - lowest_low)) * -100

        return williams

    # ==================== VOLATILITY INDICATORS ====================

    @staticmethod
    def bollinger_bands(
        prices: List[float],
        period: int = 20,
        std_dev: float = 2.0
    ) -> Optional[Tuple[float, float, float]]:
        """
        Bollinger Bands.
        Returns: (middle_band, upper_band, lower_band)
        """
        if len(prices) < period:
            return None

        middle = sum(prices[-period:]) / period
        variance = sum((p - middle) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5

        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)

        return (middle, upper, lower)

    @staticmethod
    def atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """Average True Range."""
        if len(highs) < period + 1:
            return None

        tr_list = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_list.append(tr)

        if len(tr_list) < period:
            return None

        return sum(tr_list[-period:]) / period

    @staticmethod
    def keltner_channels(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        ema_period: int = 20,
        atr_period: int = 10,
        multiplier: float = 2.0
    ) -> Optional[Tuple[float, float, float]]:
        """
        Keltner Channels.
        Returns: (middle, upper, lower)
        """
        middle = Indicators.ema(closes, ema_period)
        atr = Indicators.atr(highs, lows, closes, atr_period)

        if middle is None or atr is None:
            return None

        upper = middle + (multiplier * atr)
        lower = middle - (multiplier * atr)

        return (middle, upper, lower)

    # ==================== VOLUME INDICATORS ====================

    @staticmethod
    def obv(closes: List[float], volumes: List[int]) -> Optional[float]:
        """On-Balance Volume."""
        if len(closes) < 2 or len(volumes) < 2:
            return None

        obv = 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv += volumes[i]
            elif closes[i] < closes[i-1]:
                obv -= volumes[i]

        return obv

    @staticmethod
    def vwap(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[int]
    ) -> Optional[float]:
        """Volume Weighted Average Price."""
        if len(closes) < 1 or len(volumes) < 1:
            return None

        typical_prices = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
        cumulative_tp_vol = sum(tp * vol for tp, vol in zip(typical_prices, volumes))
        cumulative_vol = sum(volumes)

        if cumulative_vol == 0:
            return None

        return cumulative_tp_vol / cumulative_vol

    @staticmethod
    def volume_sma(volumes: List[int], period: int = 20) -> Optional[float]:
        """Volume Simple Moving Average."""
        if len(volumes) < period:
            return None
        return sum(volumes[-period:]) / period

    # ==================== SUPPORT/RESISTANCE ====================

    @staticmethod
    def pivot_points(
        high: float,
        low: float,
        close: float
    ) -> Dict[str, float]:
        """
        Standard Pivot Points.
        Returns dict with: PP, R1, R2, R3, S1, S2, S3
        """
        pp = (high + low + close) / 3

        r1 = (2 * pp) - low
        s1 = (2 * pp) - high

        r2 = pp + (high - low)
        s2 = pp - (high - low)

        r3 = high + 2 * (pp - low)
        s3 = low - 2 * (high - pp)

        return {
            'PP': pp,
            'R1': r1, 'R2': r2, 'R3': r3,
            'S1': s1, 'S2': s2, 'S3': s3
        }

    @staticmethod
    def fibonacci_retracements(
        swing_high: float,
        swing_low: float,
        is_uptrend: bool = True
    ) -> Dict[str, float]:
        """
        Fibonacci Retracement Levels.
        Returns dict with: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%
        """
        diff = swing_high - swing_low

        if is_uptrend:
            # Retracements from high in uptrend
            levels = {
                '0.0%': swing_high,
                '23.6%': swing_high - (diff * 0.236),
                '38.2%': swing_high - (diff * 0.382),
                '50.0%': swing_high - (diff * 0.5),
                '61.8%': swing_high - (diff * 0.618),
                '78.6%': swing_high - (diff * 0.786),
                '100.0%': swing_low,
            }
        else:
            # Retracements from low in downtrend
            levels = {
                '0.0%': swing_low,
                '23.6%': swing_low + (diff * 0.236),
                '38.2%': swing_low + (diff * 0.382),
                '50.0%': swing_low + (diff * 0.5),
                '61.8%': swing_low + (diff * 0.618),
                '78.6%': swing_low + (diff * 0.786),
                '100.0%': swing_high,
            }

        return levels

    # ==================== TREND STRENGTH ====================

    @staticmethod
    def trend_strength(
        closes: List[float],
        period: int = 20
    ) -> Optional[Tuple[float, str]]:
        """
        Calculate trend strength and direction.
        Returns: (strength 0-100, direction 'up'/'down'/'sideways')
        """
        if len(closes) < period:
            return None

        recent = closes[-period:]

        # Linear regression slope
        x = list(range(period))
        x_mean = sum(x) / period
        y_mean = sum(recent) / period

        numerator = sum((x[i] - x_mean) * (recent[i] - y_mean) for i in range(period))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(period))

        if denominator == 0:
            return (0, 'sideways')

        slope = numerator / denominator

        # Normalize slope to strength (0-100)
        price_range = max(recent) - min(recent)
        if price_range == 0:
            return (0, 'sideways')

        normalized_slope = (slope * period) / price_range
        strength = min(100, abs(normalized_slope) * 50)

        if normalized_slope > 0.1:
            direction = 'up'
        elif normalized_slope < -0.1:
            direction = 'down'
        else:
            direction = 'sideways'

        return (strength, direction)
