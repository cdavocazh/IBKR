"""
Technical Analysis Engine

Runs comprehensive technical analysis on price data and generates
actionable insights with signal strengths.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from .indicators import Indicators


@dataclass
class TASignal:
    """Individual technical analysis signal."""
    indicator: str
    category: str  # trend, momentum, volatility, volume
    value: float
    signal: str  # bullish, bearish, neutral
    strength: int  # 0-100
    description: str


@dataclass
class TAAnalysis:
    """Complete technical analysis result."""
    symbol: str
    timeframe: str
    timestamp: datetime
    current_price: float
    signals: List[TASignal] = field(default_factory=list)
    overall_bias: str = "neutral"
    bias_strength: int = 0
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    key_observations: List[str] = field(default_factory=list)


class TAAnalyzer:
    """Technical Analysis Analyzer."""

    def __init__(self, data: pd.DataFrame, symbol: str = "ES", timeframe: str = "5min"):
        """
        Initialize analyzer with OHLCV data.

        Args:
            data: DataFrame with columns: open, high, low, close, volume
            symbol: Instrument symbol
            timeframe: Data timeframe
        """
        self.data = data.copy()
        self.symbol = symbol
        self.timeframe = timeframe

        # Extract price arrays
        self.opens = list(data['open'].values)
        self.highs = list(data['high'].values)
        self.lows = list(data['low'].values)
        self.closes = list(data['close'].values)
        self.volumes = list(data['volume'].astype(int).values)

        self.current_price = self.closes[-1]
        self.signals: List[TASignal] = []

    def analyze(self) -> TAAnalysis:
        """Run full technical analysis."""
        self.signals = []

        # Run all indicator categories
        self._analyze_trend()
        self._analyze_momentum()
        self._analyze_volatility()
        self._analyze_volume()

        # Calculate support/resistance
        support, resistance = self._calculate_sr_levels()

        # Determine overall bias
        bias, strength = self._calculate_overall_bias()

        # Generate key observations
        observations = self._generate_observations()

        return TAAnalysis(
            symbol=self.symbol,
            timeframe=self.timeframe,
            timestamp=datetime.now(),
            current_price=self.current_price,
            signals=self.signals,
            overall_bias=bias,
            bias_strength=strength,
            support_levels=support,
            resistance_levels=resistance,
            key_observations=observations
        )

    def _analyze_trend(self):
        """Analyze trend indicators."""
        # SMA Cross (20/50)
        sma20 = Indicators.sma(self.closes, 20)
        sma50 = Indicators.sma(self.closes, 50)
        sma200 = Indicators.sma(self.closes, 200)

        if sma20 and sma50:
            if sma20 > sma50:
                signal = "bullish"
                strength = min(100, int((sma20 - sma50) / sma50 * 1000))
                desc = f"SMA20 ({sma20:.2f}) above SMA50 ({sma50:.2f})"
            else:
                signal = "bearish"
                strength = min(100, int((sma50 - sma20) / sma50 * 1000))
                desc = f"SMA20 ({sma20:.2f}) below SMA50 ({sma50:.2f})"

            self.signals.append(TASignal(
                indicator="SMA Cross (20/50)",
                category="trend",
                value=sma20 - sma50,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # Price vs SMA200
        if sma200:
            if self.current_price > sma200:
                signal = "bullish"
                pct_above = ((self.current_price - sma200) / sma200) * 100
                strength = min(100, int(pct_above * 10))
                desc = f"Price {pct_above:.1f}% above SMA200 ({sma200:.2f})"
            else:
                signal = "bearish"
                pct_below = ((sma200 - self.current_price) / sma200) * 100
                strength = min(100, int(pct_below * 10))
                desc = f"Price {pct_below:.1f}% below SMA200 ({sma200:.2f})"

            self.signals.append(TASignal(
                indicator="Price vs SMA200",
                category="trend",
                value=self.current_price - sma200,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # EMA Cross (12/26)
        ema12 = Indicators.ema(self.closes, 12)
        ema26 = Indicators.ema(self.closes, 26)

        if ema12 and ema26:
            if ema12 > ema26:
                signal = "bullish"
                strength = min(100, int((ema12 - ema26) / ema26 * 1000))
                desc = f"EMA12 ({ema12:.2f}) above EMA26 ({ema26:.2f})"
            else:
                signal = "bearish"
                strength = min(100, int((ema26 - ema12) / ema26 * 1000))
                desc = f"EMA12 ({ema12:.2f}) below EMA26 ({ema26:.2f})"

            self.signals.append(TASignal(
                indicator="EMA Cross (12/26)",
                category="trend",
                value=ema12 - ema26,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # MACD
        macd_result = Indicators.macd(self.closes)
        if macd_result:
            macd_line, signal_line, histogram = macd_result

            if histogram > 0:
                signal = "bullish"
                strength = min(100, int(abs(histogram) * 5))
                desc = f"MACD histogram positive ({histogram:.2f})"
            else:
                signal = "bearish"
                strength = min(100, int(abs(histogram) * 5))
                desc = f"MACD histogram negative ({histogram:.2f})"

            self.signals.append(TASignal(
                indicator="MACD",
                category="trend",
                value=histogram,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # ADX (Trend Strength)
        adx_result = Indicators.adx(self.highs, self.lows, self.closes)
        if adx_result:
            adx, plus_di, minus_di = adx_result

            if adx < 20:
                signal = "neutral"
                desc = f"Weak trend (ADX: {adx:.1f})"
            elif plus_di > minus_di:
                signal = "bullish"
                desc = f"Strong uptrend (ADX: {adx:.1f}, +DI: {plus_di:.1f}, -DI: {minus_di:.1f})"
            else:
                signal = "bearish"
                desc = f"Strong downtrend (ADX: {adx:.1f}, +DI: {plus_di:.1f}, -DI: {minus_di:.1f})"

            self.signals.append(TASignal(
                indicator="ADX",
                category="trend",
                value=adx,
                signal=signal,
                strength=int(min(100, adx * 2)),
                description=desc
            ))

    def _analyze_momentum(self):
        """Analyze momentum indicators."""
        # RSI
        rsi = Indicators.rsi(self.closes, 14)
        if rsi:
            if rsi < 30:
                signal = "bullish"
                strength = int((30 - rsi) * 3)
                desc = f"RSI oversold ({rsi:.1f})"
            elif rsi > 70:
                signal = "bearish"
                strength = int((rsi - 70) * 3)
                desc = f"RSI overbought ({rsi:.1f})"
            elif rsi < 45:
                signal = "bullish"
                strength = int((45 - rsi) * 2)
                desc = f"RSI leaning oversold ({rsi:.1f})"
            elif rsi > 55:
                signal = "bearish"
                strength = int((rsi - 55) * 2)
                desc = f"RSI leaning overbought ({rsi:.1f})"
            else:
                signal = "neutral"
                strength = 0
                desc = f"RSI neutral ({rsi:.1f})"

            self.signals.append(TASignal(
                indicator="RSI (14)",
                category="momentum",
                value=rsi,
                signal=signal,
                strength=min(100, strength),
                description=desc
            ))

        # Stochastic
        stoch = Indicators.stochastic(self.highs, self.lows, self.closes)
        if stoch:
            k, d = stoch

            if k < 20 and d < 20:
                signal = "bullish"
                strength = int((20 - min(k, d)) * 3)
                desc = f"Stochastic oversold (%K: {k:.1f}, %D: {d:.1f})"
            elif k > 80 and d > 80:
                signal = "bearish"
                strength = int((max(k, d) - 80) * 3)
                desc = f"Stochastic overbought (%K: {k:.1f}, %D: {d:.1f})"
            elif k > d:
                signal = "bullish"
                strength = int(min(50, (k - d) * 2))
                desc = f"Stochastic bullish crossover (%K: {k:.1f} > %D: {d:.1f})"
            else:
                signal = "bearish"
                strength = int(min(50, (d - k) * 2))
                desc = f"Stochastic bearish crossover (%K: {k:.1f} < %D: {d:.1f})"

            self.signals.append(TASignal(
                indicator="Stochastic (14,3)",
                category="momentum",
                value=k,
                signal=signal,
                strength=min(100, strength),
                description=desc
            ))

        # CCI
        cci = Indicators.cci(self.highs, self.lows, self.closes)
        if cci:
            if cci < -100:
                signal = "bullish"
                strength = min(100, int(abs(cci + 100) / 2))
                desc = f"CCI oversold ({cci:.1f})"
            elif cci > 100:
                signal = "bearish"
                strength = min(100, int((cci - 100) / 2))
                desc = f"CCI overbought ({cci:.1f})"
            elif cci > 0:
                signal = "bullish"
                strength = min(50, int(cci / 2))
                desc = f"CCI positive ({cci:.1f})"
            else:
                signal = "bearish"
                strength = min(50, int(abs(cci) / 2))
                desc = f"CCI negative ({cci:.1f})"

            self.signals.append(TASignal(
                indicator="CCI (20)",
                category="momentum",
                value=cci,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # Williams %R
        williams = Indicators.williams_r(self.highs, self.lows, self.closes)
        if williams:
            if williams > -20:
                signal = "bearish"
                strength = int((williams + 20) * 3)
                desc = f"Williams %R overbought ({williams:.1f})"
            elif williams < -80:
                signal = "bullish"
                strength = int((-80 - williams) * 3)
                desc = f"Williams %R oversold ({williams:.1f})"
            else:
                signal = "neutral"
                strength = 0
                desc = f"Williams %R neutral ({williams:.1f})"

            self.signals.append(TASignal(
                indicator="Williams %R (14)",
                category="momentum",
                value=williams,
                signal=signal,
                strength=min(100, strength),
                description=desc
            ))

    def _analyze_volatility(self):
        """Analyze volatility indicators."""
        # Bollinger Bands
        bb = Indicators.bollinger_bands(self.closes)
        if bb:
            middle, upper, lower = bb
            bb_width = (upper - lower) / middle * 100

            if self.current_price > upper:
                signal = "bearish"
                strength = min(100, int((self.current_price - upper) / (upper - middle) * 100))
                desc = f"Price above upper BB ({upper:.2f}), potential reversal"
            elif self.current_price < lower:
                signal = "bullish"
                strength = min(100, int((lower - self.current_price) / (middle - lower) * 100))
                desc = f"Price below lower BB ({lower:.2f}), potential reversal"
            elif self.current_price > middle:
                signal = "bullish"
                strength = int((self.current_price - middle) / (upper - middle) * 50)
                desc = f"Price above BB middle ({middle:.2f})"
            else:
                signal = "bearish"
                strength = int((middle - self.current_price) / (middle - lower) * 50)
                desc = f"Price below BB middle ({middle:.2f})"

            self.signals.append(TASignal(
                indicator="Bollinger Bands",
                category="volatility",
                value=self.current_price - middle,
                signal=signal,
                strength=strength,
                description=desc + f" | Width: {bb_width:.2f}%"
            ))

        # ATR
        atr = Indicators.atr(self.highs, self.lows, self.closes)
        if atr:
            atr_pct = (atr / self.current_price) * 100

            if atr_pct > 2:
                volatility = "high"
                strength = min(100, int(atr_pct * 30))
            elif atr_pct > 1:
                volatility = "moderate"
                strength = int(atr_pct * 30)
            else:
                volatility = "low"
                strength = int(atr_pct * 30)

            self.signals.append(TASignal(
                indicator="ATR (14)",
                category="volatility",
                value=atr,
                signal="neutral",
                strength=strength,
                description=f"ATR: {atr:.2f} ({atr_pct:.2f}% of price) - {volatility} volatility"
            ))

        # Keltner Channels
        kc = Indicators.keltner_channels(self.highs, self.lows, self.closes)
        if kc:
            middle, upper, lower = kc

            if self.current_price > upper:
                signal = "bullish"
                strength = min(100, int((self.current_price - upper) / atr * 50)) if atr else 50
                desc = f"Price above Keltner upper ({upper:.2f}), strong momentum"
            elif self.current_price < lower:
                signal = "bearish"
                strength = min(100, int((lower - self.current_price) / atr * 50)) if atr else 50
                desc = f"Price below Keltner lower ({lower:.2f}), strong momentum"
            else:
                signal = "neutral"
                strength = 0
                desc = f"Price within Keltner Channels ({lower:.2f} - {upper:.2f})"

            self.signals.append(TASignal(
                indicator="Keltner Channels",
                category="volatility",
                value=self.current_price - middle,
                signal=signal,
                strength=strength,
                description=desc
            ))

    def _analyze_volume(self):
        """Analyze volume indicators."""
        # Volume vs Average
        vol_sma = Indicators.volume_sma(self.volumes, 20)
        if vol_sma and vol_sma > 0:
            current_vol = self.volumes[-1]
            vol_ratio = current_vol / vol_sma

            if vol_ratio > 2:
                strength = min(100, int((vol_ratio - 1) * 50))
                desc = f"Volume spike ({vol_ratio:.1f}x average)"
            elif vol_ratio > 1.5:
                strength = int((vol_ratio - 1) * 50)
                desc = f"Above average volume ({vol_ratio:.1f}x)"
            elif vol_ratio < 0.5:
                strength = int((1 - vol_ratio) * 50)
                desc = f"Low volume ({vol_ratio:.1f}x average)"
            else:
                strength = 0
                desc = f"Normal volume ({vol_ratio:.1f}x average)"

            # Determine if volume confirms price direction
            price_change = self.closes[-1] - self.closes[-2] if len(self.closes) > 1 else 0
            if price_change > 0 and vol_ratio > 1:
                signal = "bullish"
                desc += " - confirms up move"
            elif price_change < 0 and vol_ratio > 1:
                signal = "bearish"
                desc += " - confirms down move"
            else:
                signal = "neutral"

            self.signals.append(TASignal(
                indicator="Volume Analysis",
                category="volume",
                value=vol_ratio,
                signal=signal,
                strength=strength,
                description=desc
            ))

        # OBV Trend
        if len(self.closes) > 20:
            obv_values = []
            obv = 0
            for i in range(1, len(self.closes)):
                if self.closes[i] > self.closes[i-1]:
                    obv += self.volumes[i]
                elif self.closes[i] < self.closes[i-1]:
                    obv -= self.volumes[i]
                obv_values.append(obv)

            if len(obv_values) >= 20:
                obv_sma = sum(obv_values[-20:]) / 20
                current_obv = obv_values[-1]

                if current_obv > obv_sma:
                    signal = "bullish"
                    strength = min(100, int(abs(current_obv - obv_sma) / abs(obv_sma) * 100)) if obv_sma != 0 else 50
                    desc = "OBV above its average - accumulation"
                else:
                    signal = "bearish"
                    strength = min(100, int(abs(obv_sma - current_obv) / abs(obv_sma) * 100)) if obv_sma != 0 else 50
                    desc = "OBV below its average - distribution"

                self.signals.append(TASignal(
                    indicator="OBV Trend",
                    category="volume",
                    value=current_obv,
                    signal=signal,
                    strength=strength,
                    description=desc
                ))

        # VWAP
        vwap = Indicators.vwap(self.highs[-100:], self.lows[-100:], self.closes[-100:], self.volumes[-100:])
        if vwap:
            if self.current_price > vwap:
                signal = "bullish"
                pct = ((self.current_price - vwap) / vwap) * 100
                strength = min(100, int(pct * 20))
                desc = f"Price above VWAP ({vwap:.2f}) by {pct:.2f}%"
            else:
                signal = "bearish"
                pct = ((vwap - self.current_price) / vwap) * 100
                strength = min(100, int(pct * 20))
                desc = f"Price below VWAP ({vwap:.2f}) by {pct:.2f}%"

            self.signals.append(TASignal(
                indicator="VWAP",
                category="volume",
                value=vwap,
                signal=signal,
                strength=strength,
                description=desc
            ))

    def _calculate_sr_levels(self) -> Tuple[List[float], List[float]]:
        """Calculate support and resistance levels."""
        support = []
        resistance = []

        # Use recent high/low for pivot points
        recent_high = max(self.highs[-20:])
        recent_low = min(self.lows[-20:])
        recent_close = self.closes[-1]

        pivots = Indicators.pivot_points(recent_high, recent_low, recent_close)

        # Add pivot levels
        for level in [pivots['S1'], pivots['S2'], pivots['S3']]:
            if level < self.current_price:
                support.append(round(level, 2))

        for level in [pivots['R1'], pivots['R2'], pivots['R3']]:
            if level > self.current_price:
                resistance.append(round(level, 2))

        # Add Fibonacci levels
        swing_high = max(self.highs[-50:])
        swing_low = min(self.lows[-50:])

        fib = Indicators.fibonacci_retracements(swing_high, swing_low, is_uptrend=True)
        for name, level in fib.items():
            if level < self.current_price and level not in support:
                support.append(round(level, 2))
            elif level > self.current_price and level not in resistance:
                resistance.append(round(level, 2))

        # Sort and limit
        support = sorted(set(support), reverse=True)[:5]
        resistance = sorted(set(resistance))[:5]

        return support, resistance

    def _calculate_overall_bias(self) -> Tuple[str, int]:
        """Calculate overall market bias from all signals."""
        bullish_score = 0
        bearish_score = 0
        total_weight = 0

        # Weight by category
        category_weights = {
            'trend': 2.0,
            'momentum': 1.5,
            'volatility': 1.0,
            'volume': 1.0
        }

        for signal in self.signals:
            weight = category_weights.get(signal.category, 1.0)
            weighted_strength = signal.strength * weight

            if signal.signal == "bullish":
                bullish_score += weighted_strength
            elif signal.signal == "bearish":
                bearish_score += weighted_strength

            total_weight += weight * 100  # Max possible

        if total_weight == 0:
            return "neutral", 0

        net_score = bullish_score - bearish_score
        max_possible = total_weight

        if net_score > max_possible * 0.1:
            bias = "bullish"
            strength = min(100, int((net_score / max_possible) * 200))
        elif net_score < -max_possible * 0.1:
            bias = "bearish"
            strength = min(100, int(abs(net_score / max_possible) * 200))
        else:
            bias = "neutral"
            strength = 0

        return bias, strength

    def _generate_observations(self) -> List[str]:
        """Generate key observations from analysis."""
        observations = []

        # Count signals by type
        bullish_count = sum(1 for s in self.signals if s.signal == "bullish")
        bearish_count = sum(1 for s in self.signals if s.signal == "bearish")
        neutral_count = sum(1 for s in self.signals if s.signal == "neutral")

        observations.append(
            f"Signal distribution: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral"
        )

        # Check for divergences
        rsi_signal = next((s for s in self.signals if "RSI" in s.indicator), None)
        macd_signal = next((s for s in self.signals if "MACD" in s.indicator), None)

        if rsi_signal and macd_signal:
            if rsi_signal.signal != macd_signal.signal:
                observations.append(
                    f"Divergence: RSI ({rsi_signal.signal}) vs MACD ({macd_signal.signal})"
                )

        # Check for extreme readings
        for signal in self.signals:
            if signal.strength > 80:
                observations.append(f"Strong signal: {signal.indicator} ({signal.description})")

        # Trend alignment
        trend_signals = [s for s in self.signals if s.category == "trend"]
        if trend_signals:
            trend_bullish = sum(1 for s in trend_signals if s.signal == "bullish")
            trend_bearish = sum(1 for s in trend_signals if s.signal == "bearish")

            if trend_bullish == len(trend_signals):
                observations.append("All trend indicators aligned bullish")
            elif trend_bearish == len(trend_signals):
                observations.append("All trend indicators aligned bearish")
            else:
                observations.append("Mixed trend signals - consolidation possible")

        return observations
