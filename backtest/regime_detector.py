"""
Market Regime Detector for ES Futures

Based on analysis of historical data, this module detects:
1. Bull regime - strong upward momentum
2. Bear regime - strong downward momentum
3. Neutral regime - ranging/consolidating

Key findings from trend_analysis.py:
- Bull-to-bear transitions: RSI ~57, trend_strength ~2.6
- Bear-to-bull transitions: RSI ~43, trend_strength ~-0.97
- MACD histogram is key differentiator
- Most transitions go through neutral (not direct bull<->bear)
"""

import numpy as np
from typing import Optional, Tuple
from enum import Enum


class Regime(Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


class RegimeDetector:
    """
    Detects market regime using multiple indicators.

    Primary signals (from analysis):
    - Trend strength (price vs SMA50 / ATR)
    - MACD histogram
    - RSI position and slope
    - Volatility regime
    """

    def __init__(
        self,
        # Trend detection
        trend_ema_period: int = 50,
        trend_strength_bull: float = 1.5,    # Above this = bull
        trend_strength_bear: float = -1.5,   # Below this = bear

        # MACD settings
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        macd_bull_threshold: float = 0.3,
        macd_bear_threshold: float = -0.3,

        # RSI settings
        rsi_period: int = 14,
        rsi_bull_zone: Tuple[float, float] = (40, 70),   # Bull entries
        rsi_bear_zone: Tuple[float, float] = (30, 60),   # Bear entries

        # ATR for normalization
        atr_period: int = 14,

        # Confirmation periods
        regime_confirmation_bars: int = 3,

        # Volatility filter
        high_vol_threshold: float = 0.15,  # Annualized volatility
    ):
        self.trend_ema_period = trend_ema_period
        self.trend_strength_bull = trend_strength_bull
        self.trend_strength_bear = trend_strength_bear

        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.macd_bull_threshold = macd_bull_threshold
        self.macd_bear_threshold = macd_bear_threshold

        self.rsi_period = rsi_period
        self.rsi_bull_zone = rsi_bull_zone
        self.rsi_bear_zone = rsi_bear_zone

        self.atr_period = atr_period
        self.regime_confirmation_bars = regime_confirmation_bars
        self.high_vol_threshold = high_vol_threshold

        # State
        self.current_regime = Regime.NEUTRAL
        self.regime_bars = 0
        self.prev_regimes = []

    def calculate_trend_strength(
        self,
        close: float,
        sma: float,
        atr: float
    ) -> float:
        """Calculate trend strength as (close - SMA) / ATR."""
        if atr == 0:
            return 0.0
        return (close - sma) / atr

    def calculate_macd(
        self,
        closes: list,
    ) -> Optional[Tuple[float, float, float]]:
        """Calculate MACD line, signal, and histogram."""
        if len(closes) < self.macd_slow + self.macd_signal:
            return None

        # Fast EMA
        multiplier_fast = 2 / (self.macd_fast + 1)
        ema_fast = sum(closes[:self.macd_fast]) / self.macd_fast
        for price in closes[self.macd_fast:]:
            ema_fast = (price * multiplier_fast) + (ema_fast * (1 - multiplier_fast))

        # Slow EMA
        multiplier_slow = 2 / (self.macd_slow + 1)
        ema_slow = sum(closes[:self.macd_slow]) / self.macd_slow
        for price in closes[self.macd_slow:]:
            ema_slow = (price * multiplier_slow) + (ema_slow * (1 - multiplier_slow))

        macd_line = ema_fast - ema_slow

        # Signal line (simplified)
        macd_values = []
        for i in range(max(0, len(closes) - self.macd_signal), len(closes)):
            if i >= self.macd_slow:
                f = sum(closes[:i+1][-self.macd_fast:]) / min(self.macd_fast, i+1)
                s = sum(closes[:i+1][-self.macd_slow:]) / min(self.macd_slow, i+1)
                macd_values.append(f - s)

        if len(macd_values) >= self.macd_signal:
            signal_line = sum(macd_values[-self.macd_signal:]) / self.macd_signal
        else:
            signal_line = macd_line

        histogram = macd_line - signal_line

        return (macd_line, signal_line, histogram)

    def calculate_rsi(self, closes: list) -> Optional[float]:
        """Calculate RSI."""
        if len(closes) < self.rsi_period + 1:
            return None

        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [c if c > 0 else 0 for c in changes[-self.rsi_period:]]
        losses = [-c if c < 0 else 0 for c in changes[-self.rsi_period:]]

        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_sma(self, prices: list, period: int) -> Optional[float]:
        """Calculate SMA."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def calculate_atr(
        self,
        highs: list,
        lows: list,
        closes: list,
    ) -> Optional[float]:
        """Calculate ATR."""
        if len(closes) < self.atr_period + 1:
            return None

        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)

        return sum(true_ranges[-self.atr_period:]) / self.atr_period

    def detect_regime(
        self,
        closes: list,
        highs: list,
        lows: list,
    ) -> Tuple[Regime, float, dict]:
        """
        Detect current market regime.

        Returns:
            (regime, confidence, details)
        """
        min_bars = max(
            self.trend_ema_period,
            self.macd_slow + self.macd_signal,
            self.rsi_period + 1,
            self.atr_period + 1
        )

        if len(closes) < min_bars:
            return (Regime.NEUTRAL, 0.0, {})

        # Calculate indicators
        sma = self.calculate_sma(closes, self.trend_ema_period)
        atr = self.calculate_atr(highs, lows, closes)
        trend_strength = self.calculate_trend_strength(closes[-1], sma, atr)

        macd_data = self.calculate_macd(closes)
        macd_hist = macd_data[2] if macd_data else 0

        rsi = self.calculate_rsi(closes)

        # Scoring system
        bull_score = 0
        bear_score = 0
        max_score = 5

        # Trend strength scoring (weight: 2)
        if trend_strength > self.trend_strength_bull:
            bull_score += 2
        elif trend_strength < self.trend_strength_bear:
            bear_score += 2
        elif trend_strength > 0:
            bull_score += 1
        elif trend_strength < 0:
            bear_score += 1

        # MACD scoring (weight: 1.5)
        if macd_hist > self.macd_bull_threshold:
            bull_score += 1.5
        elif macd_hist < self.macd_bear_threshold:
            bear_score += 1.5
        elif macd_hist > 0:
            bull_score += 0.5
        elif macd_hist < 0:
            bear_score += 0.5

        # RSI scoring (weight: 1)
        if rsi is not None:
            if rsi > 55:
                bull_score += 1
            elif rsi < 45:
                bear_score += 1

        # SMA slope scoring (weight: 0.5)
        if len(closes) > self.trend_ema_period + 5:
            sma_5_ago = self.calculate_sma(closes[:-5], self.trend_ema_period)
            if sma and sma_5_ago:
                sma_slope = (sma - sma_5_ago) / sma_5_ago * 100
                if sma_slope > 0.05:
                    bull_score += 0.5
                elif sma_slope < -0.05:
                    bear_score += 0.5

        # Determine regime
        details = {
            'trend_strength': trend_strength,
            'macd_hist': macd_hist,
            'rsi': rsi,
            'bull_score': bull_score,
            'bear_score': bear_score,
        }

        # Need clear majority to switch regimes
        if bull_score >= 3.5 and bull_score > bear_score + 1.5:
            new_regime = Regime.BULL
            confidence = bull_score / max_score
        elif bear_score >= 3.5 and bear_score > bull_score + 1.5:
            new_regime = Regime.BEAR
            confidence = bear_score / max_score
        else:
            new_regime = Regime.NEUTRAL
            confidence = 1 - abs(bull_score - bear_score) / max_score

        # Regime change confirmation
        if new_regime != self.current_regime:
            self.prev_regimes.append(new_regime)
            if len(self.prev_regimes) > self.regime_confirmation_bars:
                self.prev_regimes.pop(0)

            # Need consecutive bars to confirm
            if len(self.prev_regimes) >= self.regime_confirmation_bars:
                if all(r == new_regime for r in self.prev_regimes):
                    self.current_regime = new_regime
                    self.regime_bars = 0
        else:
            self.regime_bars += 1
            self.prev_regimes = []

        return (self.current_regime, confidence, details)

    def get_regime_params(self, regime: Regime) -> dict:
        """Get optimal strategy parameters for the given regime."""

        if regime == Regime.BULL:
            return {
                'bias': 'long',
                'entry_rsi_low': 35,
                'entry_rsi_high': 60,
                'stop_atr_mult': 1.5,
                'target_atr_mult': 2.5,
                'max_hold_bars': 24,
                'position_size': 1,
                'use_trailing': True,
                'trail_trigger_atr': 1.5,
            }
        elif regime == Regime.BEAR:
            return {
                'bias': 'short',
                'entry_rsi_low': 40,
                'entry_rsi_high': 65,
                'stop_atr_mult': 1.5,
                'target_atr_mult': 2.5,
                'max_hold_bars': 24,
                'position_size': 1,
                'use_trailing': True,
                'trail_trigger_atr': 1.5,
            }
        else:  # NEUTRAL
            return {
                'bias': 'both',
                'entry_rsi_low': 25,
                'entry_rsi_high': 75,
                'stop_atr_mult': 1.2,
                'target_atr_mult': 1.5,
                'max_hold_bars': 12,
                'position_size': 1,
                'use_trailing': False,
                'trail_trigger_atr': None,
            }


# Convenience function
def create_regime_detector(**kwargs) -> RegimeDetector:
    """Create a regime detector with optional custom parameters."""
    return RegimeDetector(**kwargs)
