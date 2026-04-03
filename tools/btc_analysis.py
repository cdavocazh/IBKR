"""Bitcoin futures technical analysis and positioning tools.

Reads 5-minute Binance BTCUSDT futures data from local CSVs and provides:
- Multi-timeframe OHLCV aggregation (5min → 30min / 1H / 4H / 1D)
- Trend context per timeframe (EMAs, higher-high/lower-low structure)
- Volume & Open Interest analysis (OI vs price divergence, volume profile)
- Funding rate regime (current, averages, annualized cost, crowd signal)
- Positioning analysis (global L/S, top trader ratios, z-score extremes)
- Trade idea generation (entry, stop-loss, take-profit, risk-reward)

Data sources (all in /btc-enhanced-streak-mitigation/binance-futures-data/data/):
- price.csv             — 5min OHLCV candles (~12.5K rows)
- funding_rate.csv      — 8-hour funding rates (~2.8K rows, since 2019)
- open_interest.csv     — 5min OI snapshots (~83K rows)
- global_ls_ratio.csv   — 5min global long/short ratio (~386K rows)
- top_trader_account_ratio.csv — 5min top trader account L/S (~446K rows)
- top_trader_position_ratio.csv — 5min top trader position L/S (~446K rows)

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tools.config import BTC_DATA_DIR


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _load_btc_csv(filename: str, tail: int | None = None) -> pd.DataFrame | None:
    """Load a BTC data CSV, parse timestamps, sort ascending.

    Args:
        filename: CSV filename (e.g. 'price.csv').
        tail: If set, only return the last N rows (for performance on large files).
    """
    path = os.path.join(BTC_DATA_DIR, filename)
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
        if tail and len(df) > tail:
            df = df.tail(tail).reset_index(drop=True)
        return df
    except Exception:
        return None


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 5-minute OHLCV data to a higher timeframe.

    Args:
        df: DataFrame with timestamp, open, high, low, close, volume columns.
        rule: Pandas resample rule (e.g. '30min', '1h', '4h', '1D').
    """
    df = df.set_index("timestamp")
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    resampled = resampled.reset_index()
    return resampled


def _compute_emas(series: pd.Series, periods: list[int]) -> dict[int, pd.Series]:
    """Compute EMAs for given periods."""
    return {p: series.ewm(span=p, adjust=False).mean() for p in periods}


def _compute_rsi(series: pd.Series, period: int = 14) -> float | None:
    """Compute RSI for the latest value."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    if avg_loss.iloc[-1] == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _detect_trend(df: pd.DataFrame) -> dict:
    """Detect trend from OHLCV data using EMA alignment and structure."""
    if len(df) < 21:
        return {"bias": "insufficient_data", "details": "Not enough candles"}

    close = df["close"]
    current = float(close.iloc[-1])

    emas = _compute_emas(close, [9, 21, 50])
    ema9 = float(emas[9].iloc[-1])
    ema21 = float(emas[21].iloc[-1])
    ema50 = float(emas[50].iloc[-1]) if len(close) >= 50 else None

    # EMA alignment
    if ema50 is not None:
        if ema9 > ema21 > ema50 and current > ema9:
            bias = "strongly_bullish"
        elif ema9 > ema21 and current > ema21:
            bias = "bullish"
        elif ema9 < ema21 < ema50 and current < ema9:
            bias = "strongly_bearish"
        elif ema9 < ema21 and current < ema21:
            bias = "bearish"
        else:
            bias = "ranging"
    else:
        if ema9 > ema21 and current > ema9:
            bias = "bullish"
        elif ema9 < ema21 and current < ema9:
            bias = "bearish"
        else:
            bias = "ranging"

    # RSI
    rsi = _compute_rsi(close)

    # Recent high/low structure (last 20 candles)
    recent = df.tail(20)
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    range_pct = round((recent_high - recent_low) / recent_low * 100, 2) if recent_low > 0 else 0

    result = {
        "bias": bias,
        "current_price": round(current, 1),
        "ema_9": round(ema9, 1),
        "ema_21": round(ema21, 1),
        "rsi_14": rsi,
        "recent_high": round(recent_high, 1),
        "recent_low": round(recent_low, 1),
        "range_pct": range_pct,
    }
    if ema50 is not None:
        result["ema_50"] = round(ema50, 1)
    return result


def _find_support_resistance(df: pd.DataFrame, lookback: int = 100) -> dict:
    """Find key support/resistance levels from recent price pivots."""
    if len(df) < 10:
        return {"supports": [], "resistances": []}

    data = df.tail(lookback)
    highs = data["high"].values
    lows = data["low"].values
    current = float(data["close"].iloc[-1])

    # Find local pivot highs and lows (simple 5-bar pivots)
    pivots_high = []
    pivots_low = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            pivots_high.append(float(highs[i]))
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            pivots_low.append(float(lows[i]))

    # Cluster nearby levels (within 0.3%)
    def cluster(levels: list[float], pct: float = 0.003) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        for lv in levels[1:]:
            if (lv - clusters[-1][-1]) / clusters[-1][-1] < pct:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return [round(np.mean(c), 1) for c in clusters]

    supports = sorted([s for s in cluster(pivots_low) if s < current], reverse=True)[:3]
    resistances = sorted([r for r in cluster(pivots_high) if r > current])[:3]

    return {
        "supports": supports,
        "resistances": resistances,
    }


def _zscore(series: pd.Series, current: float, window: int = 100) -> float | None:
    """Compute z-score of current value vs rolling window."""
    recent = series.tail(window).dropna()
    if len(recent) < 20:
        return None
    mean = float(recent.mean())
    std = float(recent.std())
    if std == 0:
        return 0.0
    return round((current - mean) / std, 2)


# ═══════════════════════════════════════════════════════════════════════
# 1. FULL BTC MARKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_btc_market() -> str:
    """Comprehensive BTC futures analysis: multi-timeframe trend, volume/OI,
    funding, positioning, support/resistance, and trade idea.

    Returns:
        JSON string with trend_context, volume_oi, funding, positioning,
        levels, trade_idea, and summary.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

    # ── Load price data ────────────────────────────────────────────────
    price_df = _load_btc_csv("price.csv")
    if price_df is None or len(price_df) == 0:
        return json.dumps({"error": "Price data not found at " + BTC_DATA_DIR})

    current_price = float(price_df["close"].iloc[-1])
    result["current_price"] = round(current_price, 1)
    result["data_through"] = str(price_df["timestamp"].iloc[-1])

    # ── Multi-timeframe trend context ──────────────────────────────────
    timeframes = {
        "5min": price_df.tail(288),  # ~1 day
        "30min": _resample_ohlcv(price_df, "30min").tail(336),
        "1H": _resample_ohlcv(price_df, "1h").tail(168),
        "4H": _resample_ohlcv(price_df, "4h").tail(180),
        "1D": _resample_ohlcv(price_df, "1D").tail(90),
    }

    trend_context = {}
    for tf_name, tf_df in timeframes.items():
        if len(tf_df) >= 10:
            trend_context[tf_name] = _detect_trend(tf_df)

    result["trend_context"] = trend_context

    # Composite bias
    biases = [t.get("bias", "") for t in trend_context.values()]
    bull_count = sum(1 for b in biases if "bull" in b)
    bear_count = sum(1 for b in biases if "bear" in b)
    if bull_count >= 4:
        composite_bias = "bullish"
    elif bear_count >= 4:
        composite_bias = "bearish"
    elif bull_count >= 3:
        composite_bias = "leaning_bullish"
    elif bear_count >= 3:
        composite_bias = "leaning_bearish"
    else:
        composite_bias = "mixed/ranging"
    result["composite_bias"] = composite_bias

    # ── Volume & Open Interest ─────────────────────────────────────────
    oi_df = _load_btc_csv("open_interest.csv", tail=50000)
    vol_oi = {}

    # Volume analysis from price data
    recent_vol = price_df.tail(288)["volume"]
    avg_vol_24h = float(recent_vol.mean()) if len(recent_vol) > 0 else None
    prev_vol = price_df.tail(576).head(288)["volume"]
    avg_vol_prev = float(prev_vol.mean()) if len(prev_vol) > 0 else None
    if avg_vol_24h and avg_vol_prev and avg_vol_prev > 0:
        vol_oi["volume_change_24h_pct"] = round((avg_vol_24h - avg_vol_prev) / avg_vol_prev * 100, 1)

    if oi_df is not None and len(oi_df) > 0:
        latest_oi = float(oi_df["sum_open_interest"].iloc[-1])
        latest_oi_usd = float(oi_df["sum_open_interest_value"].iloc[-1])
        vol_oi["current_oi_btc"] = round(latest_oi, 1)
        vol_oi["current_oi_usd"] = round(latest_oi_usd, 0)

        # OI 24h change
        oi_24h_ago = oi_df[oi_df["timestamp"] <= oi_df["timestamp"].iloc[-1] - timedelta(hours=24)]
        if len(oi_24h_ago) > 0:
            oi_prev = float(oi_24h_ago["sum_open_interest"].iloc[-1])
            oi_change = round((latest_oi - oi_prev) / oi_prev * 100, 2) if oi_prev > 0 else 0
            vol_oi["oi_change_24h_pct"] = oi_change

            # OI-price divergence check
            price_24h_ago_ts = price_df[price_df["timestamp"] <= price_df["timestamp"].iloc[-1] - timedelta(hours=24)]
            if len(price_24h_ago_ts) > 0:
                price_prev = float(price_24h_ago_ts["close"].iloc[-1])
                price_change = round((current_price - price_prev) / price_prev * 100, 2)
                vol_oi["price_change_24h_pct"] = price_change

                # Divergence: price up + OI down = weak rally, price down + OI up = short buildup
                if price_change > 0.5 and oi_change < -1:
                    vol_oi["divergence"] = "weak_rally (price up, OI declining — longs taking profit)"
                elif price_change < -0.5 and oi_change > 1:
                    vol_oi["divergence"] = "short_buildup (price down, OI rising — new shorts entering)"
                elif price_change > 0.5 and oi_change > 1:
                    vol_oi["divergence"] = "strong_trend (price up, OI rising — new longs entering)"
                elif price_change < -0.5 and oi_change < -1:
                    vol_oi["divergence"] = "capitulation (price down, OI declining — longs liquidated)"
                else:
                    vol_oi["divergence"] = "neutral"

    result["volume_oi"] = vol_oi

    # ── Funding Rate ───────────────────────────────────────────────────
    funding_df = _load_btc_csv("funding_rate.csv", tail=500)
    funding = {}
    if funding_df is not None and len(funding_df) > 0:
        latest_fr = float(funding_df["funding_rate"].iloc[-1])
        funding["current_rate"] = round(latest_fr, 4)
        funding["current_rate_pct"] = round(latest_fr * 100, 2)
        funding["annualized_pct"] = round(latest_fr * 3 * 365 * 100, 2)  # 3x daily

        # Averages
        recent_7d = funding_df.tail(21)["funding_rate"]  # 3 per day * 7 days
        recent_30d = funding_df.tail(90)["funding_rate"]
        funding["avg_7d"] = round(float(recent_7d.mean()), 4) if len(recent_7d) > 0 else None
        funding["avg_30d"] = round(float(recent_30d.mean()), 4) if len(recent_30d) > 0 else None

        # Funding regime
        if latest_fr > 0.0005:
            funding["regime"] = "extremely_positive (crowded longs — contrarian bearish signal)"
        elif latest_fr > 0.0002:
            funding["regime"] = "elevated_positive (bullish bias, moderate long crowding)"
        elif latest_fr > 0.0001:
            funding["regime"] = "mildly_positive (neutral — normal bullish lean)"
        elif latest_fr > -0.0001:
            funding["regime"] = "neutral"
        elif latest_fr > -0.0002:
            funding["regime"] = "mildly_negative (bearish bias, could signal bottom)"
        else:
            funding["regime"] = "strongly_negative (crowded shorts — contrarian bullish signal)"

        # Mark price if available
        if "mark_price" in funding_df.columns:
            mark_prices = funding_df["mark_price"].dropna()
            if len(mark_prices) > 0:
                funding["mark_price"] = round(float(mark_prices.iloc[-1]), 2)

    result["funding"] = funding

    # ── Positioning ────────────────────────────────────────────────────
    positioning = _analyze_positioning_data()
    result["positioning"] = positioning

    # ── Support / Resistance ───────────────────────────────────────────
    # Use 4H for major levels
    tf_4h = timeframes.get("4H")
    if tf_4h is not None and len(tf_4h) >= 20:
        levels = _find_support_resistance(tf_4h, lookback=min(len(tf_4h), 200))
    else:
        levels = {"supports": [], "resistances": []}
    result["levels"] = levels

    # ── Trade Idea ─────────────────────────────────────────────────────
    trade_idea = _generate_trade_idea(
        current_price, composite_bias, trend_context, vol_oi,
        funding, positioning, levels
    )
    result["trade_idea"] = trade_idea

    # ── Summary ────────────────────────────────────────────────────────
    summary_parts = [
        f"BTC at ${current_price:,.1f}.",
        f"Composite bias: {composite_bias}.",
    ]
    if "price_change_24h_pct" in vol_oi:
        summary_parts.append(f"24h change: {vol_oi['price_change_24h_pct']:+.2f}%.")
    if "divergence" in vol_oi and vol_oi["divergence"] != "neutral":
        summary_parts.append(f"OI divergence: {vol_oi['divergence']}.")
    if funding.get("regime"):
        summary_parts.append(f"Funding: {funding['regime'].split(' (')[0]}.")
    if trade_idea.get("direction"):
        summary_parts.append(
            f"Trade idea: {trade_idea['direction']} from ${trade_idea.get('entry', 'N/A')}, "
            f"TP ${trade_idea.get('take_profit', 'N/A')}, "
            f"SL ${trade_idea.get('stop_loss', 'N/A')}, "
            f"R:R {trade_idea.get('risk_reward', 'N/A')}."
        )
    result["summary"] = " ".join(summary_parts)

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 2. TREND ANALYSIS ONLY
# ═══════════════════════════════════════════════════════════════════════

def analyze_btc_trend() -> str:
    """Multi-timeframe BTC trend analysis: EMA alignment, RSI, structure.

    Returns:
        JSON string with current_price, timeframe trends, composite_bias.
    """
    price_df = _load_btc_csv("price.csv")
    if price_df is None or len(price_df) == 0:
        return json.dumps({"error": "Price data not found"})

    current_price = float(price_df["close"].iloc[-1])
    result = {
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "current_price": round(current_price, 1),
        "data_through": str(price_df["timestamp"].iloc[-1]),
    }

    timeframes = {
        "5min": price_df.tail(288),
        "30min": _resample_ohlcv(price_df, "30min").tail(336),
        "1H": _resample_ohlcv(price_df, "1h").tail(168),
        "4H": _resample_ohlcv(price_df, "4h").tail(180),
        "1D": _resample_ohlcv(price_df, "1D").tail(90),
    }

    trend_context = {}
    for tf_name, tf_df in timeframes.items():
        if len(tf_df) >= 10:
            trend_context[tf_name] = _detect_trend(tf_df)

    result["trend_context"] = trend_context

    biases = [t.get("bias", "") for t in trend_context.values()]
    bull_count = sum(1 for b in biases if "bull" in b)
    bear_count = sum(1 for b in biases if "bear" in b)
    if bull_count >= 4:
        result["composite_bias"] = "bullish"
    elif bear_count >= 4:
        result["composite_bias"] = "bearish"
    elif bull_count >= 3:
        result["composite_bias"] = "leaning_bullish"
    elif bear_count >= 3:
        result["composite_bias"] = "leaning_bearish"
    else:
        result["composite_bias"] = "mixed/ranging"

    # Levels from 4H
    tf_4h = timeframes.get("4H")
    if tf_4h is not None and len(tf_4h) >= 20:
        result["levels"] = _find_support_resistance(tf_4h, lookback=min(len(tf_4h), 200))

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 3. POSITIONING ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def _analyze_positioning_data() -> dict:
    """Internal helper to analyze all positioning data."""
    positioning = {}

    # Global L/S ratio
    gls = _load_btc_csv("global_ls_ratio.csv", tail=50000)
    if gls is not None and len(gls) > 0:
        latest_ls = float(gls["ls_ratio"].iloc[-1])
        latest_long = float(gls["long_pct"].iloc[-1])
        latest_short = float(gls["short_pct"].iloc[-1])
        z = _zscore(gls["ls_ratio"], latest_ls, window=2000)
        positioning["global_ls"] = {
            "ls_ratio": round(latest_ls, 2),
            "long_pct": round(latest_long * 100, 1),
            "short_pct": round(latest_short * 100, 1),
            "zscore": z,
        }
        if z is not None:
            if z > 2:
                positioning["global_ls"]["signal"] = "extreme_long_crowding — contrarian bearish"
            elif z > 1:
                positioning["global_ls"]["signal"] = "elevated_longs — caution"
            elif z < -2:
                positioning["global_ls"]["signal"] = "extreme_short_crowding — contrarian bullish"
            elif z < -1:
                positioning["global_ls"]["signal"] = "elevated_shorts — potential bottom"
            else:
                positioning["global_ls"]["signal"] = "neutral"

    # Top trader account ratio
    tta = _load_btc_csv("top_trader_account_ratio.csv", tail=50000)
    if tta is not None and len(tta) > 0:
        latest_ls = float(tta["ls_ratio"].iloc[-1])
        z = _zscore(tta["ls_ratio"], latest_ls, window=2000)
        positioning["top_trader_accounts"] = {
            "ls_ratio": round(latest_ls, 2),
            "long_pct": round(float(tta["long_pct"].iloc[-1]) * 100, 1),
            "short_pct": round(float(tta["short_pct"].iloc[-1]) * 100, 1),
            "zscore": z,
        }

    # Top trader position ratio
    ttp = _load_btc_csv("top_trader_position_ratio.csv", tail=50000)
    if ttp is not None and len(ttp) > 0:
        latest_ls = float(ttp["ls_ratio"].iloc[-1])
        z = _zscore(ttp["ls_ratio"], latest_ls, window=2000)
        positioning["top_trader_positions"] = {
            "ls_ratio": round(latest_ls, 2),
            "long_pct": round(float(ttp["long_pct"].iloc[-1]) * 100, 1),
            "short_pct": round(float(ttp["short_pct"].iloc[-1]) * 100, 1),
            "zscore": z,
        }

    # Composite positioning signal
    zscores = [
        positioning.get("global_ls", {}).get("zscore"),
        positioning.get("top_trader_accounts", {}).get("zscore"),
        positioning.get("top_trader_positions", {}).get("zscore"),
    ]
    valid_z = [z for z in zscores if z is not None]
    if valid_z:
        avg_z = np.mean(valid_z)
        if avg_z > 1.5:
            positioning["composite_signal"] = "crowded_longs — elevated liquidation risk"
        elif avg_z > 0.5:
            positioning["composite_signal"] = "leaning_long — normal bullish positioning"
        elif avg_z < -1.5:
            positioning["composite_signal"] = "crowded_shorts — squeeze potential"
        elif avg_z < -0.5:
            positioning["composite_signal"] = "leaning_short — bearish sentiment"
        else:
            positioning["composite_signal"] = "balanced"
        positioning["avg_zscore"] = round(float(avg_z), 2)

    return positioning


def analyze_btc_positioning() -> str:
    """BTC futures positioning analysis: L/S ratios, top trader data,
    z-score extremes, contrarian signals, and actionable trade implications.

    Returns:
        JSON string with positioning data, interpretation, funding context,
        actionable signal, and trade implications.
    """
    result = {
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    # Price context
    price_df = _load_btc_csv("price.csv")
    if price_df is not None and len(price_df) > 0:
        result["current_price"] = round(float(price_df["close"].iloc[-1]), 1)

    # Positioning
    positioning = _analyze_positioning_data()
    result["positioning"] = positioning

    # Funding context
    funding_df = _load_btc_csv("funding_rate.csv", tail=100)
    latest_fr = None
    funding_ann = None
    if funding_df is not None and len(funding_df) > 0:
        latest_fr = float(funding_df["funding_rate"].iloc[-1])
        funding_ann = round(latest_fr * 3 * 365 * 100, 2)
        result["funding_rate"] = round(latest_fr, 4)
        result["funding_annualized_pct"] = funding_ann

        # Funding regime interpretation
        if latest_fr > 0.0005:
            result["funding_regime"] = "extremely_positive"
            funding_interp = "Extremely expensive longs — high cost of carry. Shorts get paid. Contrarian bearish signal."
        elif latest_fr > 0.0002:
            funding_interp = "Elevated funding — longs paying significant premium. Caution on new longs."
            result["funding_regime"] = "elevated_positive"
        elif latest_fr > 0.0001:
            funding_interp = "Mildly positive — normal bullish lean, no extreme."
            result["funding_regime"] = "mildly_positive"
        elif latest_fr > -0.0001:
            funding_interp = "Neutral funding — no directional bias from derivatives market."
            result["funding_regime"] = "neutral"
        elif latest_fr > -0.0002:
            funding_interp = "Mildly negative — shorts paying longs. Could signal a bottom forming."
            result["funding_regime"] = "mildly_negative"
        else:
            funding_interp = "Strongly negative — shorts paying heavy carry. Short squeeze fuel building."
            result["funding_regime"] = "strongly_negative"
        result["funding_interpretation"] = funding_interp

    # ── Interpretation and actionable signal ──────────────────────────
    avg_z = positioning.get("avg_zscore", 0)
    composite_sig = positioning.get("composite_signal", "balanced")

    # Positioning interpretation
    if avg_z is not None and avg_z > 2.0:
        pos_interp = "Extreme long crowding — high liquidation risk. Violent pullback possible on any catalyst."
    elif avg_z is not None and avg_z > 1.0:
        pos_interp = "Elevated longs — caution on new long entries. Watch for profit-taking."
    elif avg_z is not None and avg_z < -2.0:
        pos_interp = "Extreme short crowding — short squeeze potential. Contrarian long setup."
    elif avg_z is not None and avg_z < -1.0:
        pos_interp = "Elevated shorts — potential squeeze fuel accumulating."
    else:
        pos_interp = "Balanced positioning — no extreme crowding in either direction."
    result["positioning_interpretation"] = pos_interp

    # Synthesize actionable signal
    longs_crowded = avg_z is not None and avg_z > 1.0
    shorts_crowded = avg_z is not None and avg_z < -1.0
    funding_expensive = latest_fr is not None and latest_fr > 0.0002
    funding_negative = latest_fr is not None and latest_fr < -0.0001

    trade_implications = []
    if longs_crowded and funding_expensive:
        actionable = "CONTRARIAN_SHORT"
        risk = "high"
        trade_implications.append("Crowded longs + expensive funding = elevated liquidation risk")
        trade_implications.append("Consider short entries on any momentum breakdown")
        trade_implications.append("Trailing stops recommended — squeeze could extend before reversing")
    elif shorts_crowded and funding_negative:
        actionable = "CONTRARIAN_LONG"
        risk = "high"
        trade_implications.append("Crowded shorts + negative funding = short squeeze fuel")
        trade_implications.append("Consider long entries — shorts paying carry while price holds")
        trade_implications.append("Target: prior resistance level; SL: below recent swing low")
    elif longs_crowded:
        actionable = "CAUTION_LONG"
        risk = "medium"
        trade_implications.append("Positioning skewed long — avoid adding longs at current levels")
        trade_implications.append("Wait for positioning to normalize or a washout before new entries")
    elif shorts_crowded:
        actionable = "LEAN_LONG"
        risk = "medium"
        trade_implications.append("Short crowding without negative funding — moderate squeeze potential")
        trade_implications.append("Small long entries with tight stops could capture squeeze move")
    else:
        actionable = "NEUTRAL"
        risk = "low"
        trade_implications.append("No extreme positioning — trade based on technical setup and trend")
        trade_implications.append("No contrarian edge from positioning data")

    result["actionable_signal"] = actionable
    result["risk_level"] = risk
    result["trade_implications"] = trade_implications

    # Summary
    price_str = f"${result.get('current_price', 0):,.1f}" if result.get("current_price") else "N/A"
    funding_str = f"{funding_ann:+.2f}% ann" if funding_ann is not None else "N/A"
    z_str = f"avg z={avg_z:.2f}" if avg_z is not None else "N/A"
    result["summary"] = (
        f"BTC at {price_str}. Positioning: {composite_sig} ({z_str}). "
        f"Funding: {funding_str}. "
        f"Signal: {actionable}. Risk: {risk}."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# TRADE IDEA GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def _generate_trade_idea(
    current_price: float,
    composite_bias: str,
    trend_context: dict,
    vol_oi: dict,
    funding: dict,
    positioning: dict,
    levels: dict,
) -> dict:
    """Generate a trade idea based on multi-timeframe and positioning data."""

    supports = levels.get("supports", [])
    resistances = levels.get("resistances", [])

    # Default trade idea
    idea = {
        "direction": None,
        "confidence": "low",
        "reasoning": [],
    }

    reasons = []
    bull_points = 0
    bear_points = 0

    # Trend alignment
    if "bull" in composite_bias:
        bull_points += 2
        reasons.append(f"Multi-TF trend is {composite_bias}")
    elif "bear" in composite_bias:
        bear_points += 2
        reasons.append(f"Multi-TF trend is {composite_bias}")

    # Funding contrarian
    fr_regime = funding.get("regime", "")
    if "strongly_negative" in fr_regime:
        bull_points += 1
        reasons.append("Funding strongly negative — short squeeze potential")
    elif "extremely_positive" in fr_regime:
        bear_points += 1
        reasons.append("Funding extremely positive — crowded longs risk")

    # Positioning contrarian
    composite_pos = positioning.get("composite_signal", "")
    if "crowded_shorts" in composite_pos:
        bull_points += 1
        reasons.append("Positioning: crowded shorts — squeeze setup")
    elif "crowded_longs" in composite_pos:
        bear_points += 1
        reasons.append("Positioning: crowded longs — liquidation risk")

    # OI-price divergence
    divergence = vol_oi.get("divergence", "")
    if "strong_trend" in divergence and "bull" in composite_bias:
        bull_points += 1
        reasons.append("OI confirming uptrend (rising OI + rising price)")
    elif "short_buildup" in divergence:
        bear_points += 1
        reasons.append("Short buildup detected (falling price + rising OI)")
    elif "weak_rally" in divergence:
        bear_points += 1
        reasons.append("Weak rally (rising price but declining OI)")
    elif "capitulation" in divergence and "bear" in composite_bias:
        bull_points += 1
        reasons.append("Capitulation detected — potential reversal zone")

    # Determine direction
    if bull_points >= 3 and bull_points > bear_points:
        direction = "LONG"
        confidence = "high" if bull_points >= 4 else "medium"
    elif bear_points >= 3 and bear_points > bull_points:
        direction = "SHORT"
        confidence = "high" if bear_points >= 4 else "medium"
    elif bull_points > bear_points and bull_points >= 2:
        direction = "LONG"
        confidence = "medium" if bull_points >= 3 else "low"
    elif bear_points > bull_points and bear_points >= 2:
        direction = "SHORT"
        confidence = "medium" if bear_points >= 3 else "low"
    else:
        idea["direction"] = "NO_TRADE"
        idea["confidence"] = "low"
        idea["reasoning"] = reasons if reasons else ["No clear edge — conflicting signals"]
        return idea

    idea["direction"] = direction
    idea["confidence"] = confidence
    idea["reasoning"] = reasons

    # Compute levels
    if direction == "LONG":
        # Entry: current price or nearest support
        entry = current_price
        if supports:
            nearest_support = supports[0]
            if nearest_support > current_price * 0.995:  # within 0.5%
                entry = nearest_support
        idea["entry"] = round(entry, 1)

        # Stop loss: below nearest support
        if supports:
            sl = supports[0] * 0.995 if supports[0] < entry else entry * 0.985
        else:
            sl = entry * 0.985  # default 1.5% SL
        idea["stop_loss"] = round(sl, 1)

        # Take profit: nearest resistance or 2:1 R:R minimum
        risk = entry - sl
        min_tp = entry + risk * 2
        if resistances:
            tp = max(resistances[0], min_tp)
        else:
            tp = min_tp
        idea["take_profit"] = round(tp, 1)

    else:  # SHORT
        entry = current_price
        if resistances:
            nearest_res = resistances[0]
            if nearest_res < current_price * 1.005:
                entry = nearest_res
        idea["entry"] = round(entry, 1)

        # Stop loss: above nearest resistance
        if resistances:
            sl = resistances[0] * 1.005 if resistances[0] > entry else entry * 1.015
        else:
            sl = entry * 1.015
        idea["stop_loss"] = round(sl, 1)

        # Take profit
        risk = sl - entry
        min_tp = entry - risk * 2
        if supports:
            tp = min(supports[0], min_tp)
        else:
            tp = min_tp
        idea["take_profit"] = round(tp, 1)

    # Risk-reward
    risk_amt = abs(idea["entry"] - idea["stop_loss"])
    reward_amt = abs(idea["take_profit"] - idea["entry"])
    if risk_amt > 0:
        idea["risk_reward"] = f"1:{round(reward_amt / risk_amt, 1)}"
    else:
        idea["risk_reward"] = "N/A"

    idea["risk_usd_per_btc"] = round(risk_amt, 1)
    idea["reward_usd_per_btc"] = round(reward_amt, 1)

    return idea
