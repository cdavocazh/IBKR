"""John Murphy Technical Analysis frameworks.

Implements 13+ TA frameworks from *Technical Analysis of the Financial Markets*
by John J. Murphy, applicable to any supported asset (BTC, commodities, indices).

Frameworks:
  1. Trend Analysis — higher highs/lows structure, trend direction & strength
  2. Support & Resistance — horizontal pivots, role reversal detection
  3. Volume Confirmation — volume-price divergence (assets with volume data)
  4. Moving Average Analysis — SMA 50/200, golden/death cross, MA slope
  5. MACD — line, signal, histogram, divergence detection
  6. RSI — overbought/oversold, centerline crossover, divergence
  7. Bollinger Bands — bandwidth, %B, squeeze detection
  8. Fibonacci Retracements — swing-based 23.6/38.2/50/61.8% levels
  9. Intermarket Analysis — commodity/bond/stock/dollar relationships
  10. Relative Strength — asset vs benchmark, RS line direction
  11. Dow Theory — primary trend, confirmation between averages
  12. Pattern Recognition — simplified double top/bottom detection
  13. Stochastic Oscillator — %K, %D, overbought/oversold

Data sources:
  - /btc-enhanced-streak-mitigation/binance-futures-data/data/ (BTC 5min OHLCV)
  - /macro_2/historical_data/ (daily prices for commodities, indices, FX)
  - yfinance (on-demand OHLCV for any stock/ETF ticker, cached 30 min)

Supported assets: btc, crude_oil, gold, silver, copper, es_futures, sp500,
                  russell_2000, dxy, rty_futures, plus any stock/ETF ticker
                  (e.g., AAPL, NVDA, QQQ, XLE) via yfinance

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

from tools.config import HISTORICAL_DATA_DIR, BTC_DATA_DIR


# ═══════════════════════════════════════════════════════════════════════
# ASSET DATA ROUTING
# ═══════════════════════════════════════════════════════════════════════

ASSET_DATA_MAP: dict[str, dict] = {
    # BTC — full OHLCV from Binance futures 5min candles
    "btc":           {"source": "btc",   "file": "price.csv"},
    # Macro CSVs — daily close-only prices
    "crude_oil":     {"source": "macro", "csv": "crude_oil.csv",         "col": "crude_oil_price"},
    "gold":          {"source": "macro", "csv": "gold.csv",              "col": "gold_price"},
    "silver":        {"source": "macro", "csv": "silver.csv",            "col": "silver_price"},
    "copper":        {"source": "macro", "csv": "copper.csv",            "col": "copper_price"},
    "es_futures":    {"source": "macro", "csv": "es_futures.csv",        "col": "es_price"},
    "sp500":         {"source": "macro", "csv": "es_futures.csv",        "col": "es_price"},
    "russell_2000":  {"source": "macro", "csv": "russell_2000.csv",      "col": "russell_2000_value"},
    "dxy":           {"source": "macro", "csv": "dxy.csv",               "col": "dxy"},
    "rty_futures":   {"source": "macro", "csv": "rty_futures.csv",       "col": "rty_price"},
}

# ── Stock OHLCV cache (yfinance, on-demand) ──────────────────────────
_STOCK_OHLCV_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_STOCK_CACHE_TTL = 1800  # 30 minutes, matching fred_data._ETF_CACHE_TTL


def _load_asset_data(asset: str, timeframe: str = "1D") -> pd.DataFrame | None:
    """Load price data for an asset, returning a DataFrame with OHLCV columns.

    For BTC: loads 5min data and resamples to the requested timeframe.
    For macro assets: loads daily CSV (close-only) and synthesizes OHLC.
    For stock/ETF tickers: fetches daily OHLCV from yfinance (cached 30 min).

    Returns DataFrame with columns: timestamp, open, high, low, close, volume (if available).
    """
    cfg = ASSET_DATA_MAP.get(asset.lower())
    if cfg:
        if cfg["source"] == "btc":
            return _load_btc_data(timeframe)
        else:
            return _load_macro_data(cfg["csv"], cfg["col"])

    # Fallback: try as a stock/ETF ticker via yfinance
    return _load_stock_data(asset, period="1y")


def _load_btc_data(timeframe: str = "1D") -> pd.DataFrame | None:
    """Load BTC 5min OHLCV and resample to timeframe."""
    path = os.path.join(BTC_DATA_DIR, "price.csv")
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
        # Keep last ~30K candles for performance (enough for daily analysis)
        if len(df) > 30000:
            df = df.tail(30000).reset_index(drop=True)

        # Resample to requested timeframe
        tf_map = {"5min": None, "30min": "30min", "1H": "1h", "1h": "1h",
                  "4H": "4h", "4h": "4h", "1D": "1D", "1d": "1D"}
        rule = tf_map.get(timeframe)
        if rule:
            df = df.set_index("timestamp")
            resampled = df.resample(rule).agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna().reset_index()
            return resampled
        return df
    except Exception:
        return None


def _load_macro_data(csv_file: str, col: str) -> pd.DataFrame | None:
    """Load a macro CSV with close-only data, synthesize OHLCV columns."""
    path = os.path.join(HISTORICAL_DATA_DIR, csv_file)
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path)
        date_col = "date" if "date" in df.columns else "timestamp"
        if col not in df.columns or date_col not in df.columns:
            return None
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, col])
        df = df.sort_values(date_col, ascending=True).reset_index(drop=True)

        # Synthesize OHLCV from close-only data
        result = pd.DataFrame({
            "timestamp": df[date_col],
            "close": df[col].astype(float),
        })
        result["open"] = result["close"]
        result["high"] = result["close"]
        result["low"] = result["close"]
        result["volume"] = 0.0  # No volume data for macro CSVs
        return result
    except Exception:
        return None


def _load_stock_data(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """Fetch daily OHLCV for a stock/ETF ticker via yfinance with in-memory TTL cache.

    Returns DataFrame with columns: timestamp, open, high, low, close, volume.
    Cached for 30 minutes to avoid repeated API calls.
    Uses period='1y' (~250 bars) so SMA 200 and all frameworks work.
    """
    cache_key = f"{ticker.upper()}:{period}"
    now = time.time()

    # Check cache
    if cache_key in _STOCK_OHLCV_CACHE:
        cached_time, cached_df = _STOCK_OHLCV_CACHE[cache_key]
        if now - cached_time < _STOCK_CACHE_TTL:
            return cached_df.copy()

    try:
        import yfinance as yf
        data = yf.download(ticker, period=period, progress=False, timeout=15)
        if data is None or data.empty or len(data) < 20:
            return None

        # Handle yfinance MultiIndex columns (newer versions return MultiIndex for single ticker)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        df = pd.DataFrame({
            "timestamp": data.index,
            "open": data["Open"].values,
            "high": data["High"].values,
            "low": data["Low"].values,
            "close": data["Close"].values,
            "volume": data["Volume"].values.astype(float),
        }).reset_index(drop=True)

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.dropna(subset=["close"]).sort_values("timestamp").reset_index(drop=True)

        # Cache the result
        _STOCK_OHLCV_CACHE[cache_key] = (now, df.copy())
        return df

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# PRIVATE TA COMPUTATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _trend_classification(df: pd.DataFrame) -> dict:
    """Murphy Framework 1: Trend Analysis — higher highs/lows structure."""
    if len(df) < 20:
        return {"direction": "insufficient_data"}

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(close)

    # Detect swing highs/lows (5-bar pivots)
    swing_highs = []
    swing_lows = []
    for i in range(2, n - 2):
        if high[i] > high[i-1] and high[i] > high[i-2] and high[i] > high[i+1] and high[i] > high[i+2]:
            swing_highs.append((i, high[i]))
        if low[i] < low[i-1] and low[i] < low[i-2] and low[i] < low[i+1] and low[i] < low[i+2]:
            swing_lows.append((i, low[i]))

    # Determine trend from recent swing sequence
    direction = "ranging"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1][1] > swing_highs[-2][1]  # Higher high
        hl = swing_lows[-1][1] > swing_lows[-2][1]    # Higher low
        lh = swing_highs[-1][1] < swing_highs[-2][1]  # Lower high
        ll = swing_lows[-1][1] < swing_lows[-2][1]    # Lower low

        if hh and hl:
            direction = "uptrend"
        elif lh and ll:
            direction = "downtrend"
        elif hh and ll:
            direction = "expanding_range"
        elif lh and hl:
            direction = "contracting_range"

    # Trend strength via ADX approximation (using directional movement)
    recent = df.tail(20)
    price_range = float(recent["high"].max() - recent["low"].min())
    net_move = float(abs(close[-1] - close[-20])) if n >= 20 else 0
    strength = "strong" if price_range > 0 and net_move / price_range > 0.5 else "moderate" if net_move / price_range > 0.25 else "weak"

    return {
        "direction": direction,
        "strength": strength,
        "current_price": round(float(close[-1]), 2),
        "swing_highs_count": len(swing_highs),
        "swing_lows_count": len(swing_lows),
        "recent_swing_high": round(float(swing_highs[-1][1]), 2) if swing_highs else None,
        "recent_swing_low": round(float(swing_lows[-1][1]), 2) if swing_lows else None,
    }


def _support_resistance_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
    """Murphy Framework 2: Support & Resistance from price pivots."""
    data = df.tail(lookback)
    if len(data) < 20:
        return {"supports": [], "resistances": []}

    high = data["high"].values
    low = data["low"].values
    close = data["close"].values
    current = float(close[-1])

    # Find pivots
    supports = []
    resistances = []
    for i in range(2, len(high) - 2):
        if high[i] > high[i-1] and high[i] > high[i+1]:
            resistances.append(float(high[i]))
        if low[i] < low[i-1] and low[i] < low[i+1]:
            supports.append(float(low[i]))

    # Cluster nearby levels (within 1%)
    def cluster_levels(levels, threshold_pct=1.0):
        if not levels:
            return []
        levels.sort()
        clusters = [[levels[0]]]
        for lvl in levels[1:]:
            if (lvl - clusters[-1][-1]) / clusters[-1][-1] * 100 < threshold_pct:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        return [round(np.mean(c), 2) for c in clusters]

    support_levels = [s for s in cluster_levels(supports) if s < current]
    resistance_levels = [r for r in cluster_levels(resistances) if r > current]

    # Sort: supports descending (nearest first), resistances ascending
    support_levels.sort(reverse=True)
    resistance_levels.sort()

    return {
        "supports": support_levels[:5],
        "resistances": resistance_levels[:5],
        "nearest_support": support_levels[0] if support_levels else None,
        "nearest_resistance": resistance_levels[0] if resistance_levels else None,
        "support_distance_pct": round((current - support_levels[0]) / current * 100, 2) if support_levels else None,
        "resistance_distance_pct": round((resistance_levels[0] - current) / current * 100, 2) if resistance_levels else None,
    }


def _volume_confirmation(df: pd.DataFrame) -> dict:
    """Murphy Framework 3: Volume should confirm the trend."""
    if "volume" not in df.columns or df["volume"].sum() == 0:
        return {"available": False, "note": "No volume data for this asset"}

    recent = df.tail(20)
    close = recent["close"].values
    volume = recent["volume"].values

    # Price direction
    price_up = close[-1] > close[0]

    # Volume trend (simple: compare avg last 5 vs avg prior 15)
    if len(volume) >= 20:
        recent_vol = np.mean(volume[-5:])
        prior_vol = np.mean(volume[:15])
        vol_increasing = recent_vol > prior_vol * 1.1
        vol_ratio = round(recent_vol / prior_vol, 2) if prior_vol > 0 else 0
    else:
        vol_increasing = False
        vol_ratio = 1.0

    # Confirmation: price up + volume up = confirmed, price up + volume down = suspect
    if price_up and vol_increasing:
        signal = "CONFIRMED — price rising with increasing volume"
    elif price_up and not vol_increasing:
        signal = "SUSPECT — price rising but volume declining (weak rally)"
    elif not price_up and vol_increasing:
        signal = "CONFIRMED — price falling with increasing volume (strong selling)"
    else:
        signal = "MIXED — price falling with declining volume (selling exhaustion?)"

    return {
        "available": True,
        "price_direction": "up" if price_up else "down",
        "volume_increasing": bool(vol_increasing),
        "volume_ratio": vol_ratio,
        "signal": signal,
    }


def _moving_average_analysis(df: pd.DataFrame) -> dict:
    """Murphy Framework 4: Moving Average Analysis — SMA 50/200, crossovers."""
    close = df["close"]
    n = len(close)
    result: dict = {}

    # SMA 50
    if n >= 50:
        sma50 = close.rolling(50).mean()
        result["sma_50"] = round(float(sma50.iloc[-1]), 2)
        result["price_vs_sma50"] = "above" if float(close.iloc[-1]) > result["sma_50"] else "below"
        # SMA 50 slope (20-day change)
        if n >= 70:
            slope = float(sma50.iloc[-1] - sma50.iloc[-20])
            result["sma50_slope"] = "rising" if slope > 0 else "falling"

    # SMA 200
    if n >= 200:
        sma200 = close.rolling(200).mean()
        result["sma_200"] = round(float(sma200.iloc[-1]), 2)
        result["price_vs_sma200"] = "above" if float(close.iloc[-1]) > result["sma_200"] else "below"
        result["sma200_slope"] = "rising" if float(sma200.iloc[-1] - sma200.iloc[-20]) > 0 else "falling"

        # Golden Cross / Death Cross detection
        if n >= 250 and "sma_50" in result:
            sma50_vals = close.rolling(50).mean()
            sma200_vals = sma200
            # Check for recent crossover (last 20 bars)
            for i in range(-20, 0):
                if i - 1 >= -n:
                    s50_now = sma50_vals.iloc[i]
                    s200_now = sma200_vals.iloc[i]
                    s50_prev = sma50_vals.iloc[i - 1]
                    s200_prev = sma200_vals.iloc[i - 1]
                    if not any(pd.isna(v) for v in [s50_now, s200_now, s50_prev, s200_prev]):
                        if s50_prev < s200_prev and s50_now > s200_now:
                            result["crossover"] = "GOLDEN_CROSS (bullish — SMA50 crossed above SMA200)"
                            break
                        elif s50_prev > s200_prev and s50_now < s200_now:
                            result["crossover"] = "DEATH_CROSS (bearish — SMA50 crossed below SMA200)"
                            break
            if "crossover" not in result:
                if result.get("sma_50", 0) > result.get("sma_200", 0):
                    result["crossover"] = "SMA50 above SMA200 (bullish alignment)"
                else:
                    result["crossover"] = "SMA50 below SMA200 (bearish alignment)"

    # SMA 20 (short-term)
    if n >= 20:
        sma20 = close.rolling(20).mean()
        result["sma_20"] = round(float(sma20.iloc[-1]), 2)

    return result


def _macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Murphy Framework 5: MACD (Moving Average Convergence Divergence)."""
    close = df["close"]
    if len(close) < slow + signal:
        return {"available": False}

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    macd_val = round(float(macd_line.iloc[-1]), 4)
    signal_val = round(float(signal_line.iloc[-1]), 4)
    hist_val = round(float(histogram.iloc[-1]), 4)

    # Signal crossover detection
    if len(histogram) >= 2:
        prev_hist = float(histogram.iloc[-2])
        if prev_hist <= 0 and hist_val > 0:
            crossover = "BULLISH_CROSS — MACD crossed above signal line"
        elif prev_hist >= 0 and hist_val < 0:
            crossover = "BEARISH_CROSS — MACD crossed below signal line"
        else:
            crossover = "bullish" if hist_val > 0 else "bearish"
    else:
        crossover = "N/A"

    # Histogram momentum
    hist_direction = "expanding" if len(histogram) >= 3 and abs(hist_val) > abs(float(histogram.iloc[-3])) else "contracting"

    return {
        "available": True,
        "macd_line": macd_val,
        "signal_line": signal_val,
        "histogram": hist_val,
        "crossover": crossover,
        "histogram_direction": hist_direction,
        "centerline": "above_zero" if macd_val > 0 else "below_zero",
    }


def _rsi_analysis(df: pd.DataFrame, period: int = 14) -> dict:
    """Murphy Framework 6: Relative Strength Index."""
    close = df["close"]
    if len(close) < period + 5:
        return {"available": False}

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    last_avg_loss = float(avg_loss.iloc[-1])
    if last_avg_loss == 0:
        rsi_val = 100.0
    else:
        rs = float(avg_gain.iloc[-1]) / last_avg_loss
        rsi_val = round(100.0 - (100.0 / (1.0 + rs)), 2)

    # Zone classification
    if rsi_val >= 70:
        zone = "overbought"
    elif rsi_val <= 30:
        zone = "oversold"
    elif rsi_val >= 50:
        zone = "bullish_momentum"
    else:
        zone = "bearish_momentum"

    # Simple RSI divergence detection (last 20 bars)
    divergence = None
    prices = close.tail(20).values
    if len(prices) >= 20:
        rsi_series = []
        for i in range(len(close) - 20, len(close)):
            al = float(avg_loss.iloc[i]) if i < len(avg_loss) and not pd.isna(avg_loss.iloc[i]) else 0.001
            ag = float(avg_gain.iloc[i]) if i < len(avg_gain) and not pd.isna(avg_gain.iloc[i]) else 0
            rsi_series.append(100 - 100 / (1 + ag / max(al, 0.001)))

        if len(rsi_series) >= 20:
            price_higher = prices[-1] > prices[0]
            rsi_higher = rsi_series[-1] > rsi_series[0]
            if price_higher and not rsi_higher:
                divergence = "BEARISH_DIVERGENCE — price making highs but RSI declining"
            elif not price_higher and rsi_higher:
                divergence = "BULLISH_DIVERGENCE — price making lows but RSI rising"

    return {
        "available": True,
        "rsi": rsi_val,
        "zone": zone,
        "divergence": divergence,
    }


def _bollinger_bands(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> dict:
    """Murphy Framework 7: Bollinger Bands — bandwidth, %B, squeeze."""
    close = df["close"]
    if len(close) < period + 5:
        return {"available": False}

    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std

    current = float(close.iloc[-1])
    upper_val = float(upper.iloc[-1])
    lower_val = float(lower.iloc[-1])
    sma_val = float(sma.iloc[-1])

    bandwidth = round((upper_val - lower_val) / sma_val * 100, 2) if sma_val > 0 else 0
    pct_b = round((current - lower_val) / (upper_val - lower_val) * 100, 2) if (upper_val - lower_val) > 0 else 50

    # Squeeze detection (bandwidth in bottom 20th percentile of last 120 periods)
    if len(close) >= 120:
        bw_series = ((upper - lower) / sma * 100).dropna()
        squeeze = bool(bandwidth < float(bw_series.quantile(0.2)))
    else:
        squeeze = bandwidth < 5.0  # Simple threshold

    # Position assessment
    if pct_b > 100:
        position = "above_upper_band (overextended)"
    elif pct_b > 80:
        position = "near_upper_band (bullish)"
    elif pct_b < 0:
        position = "below_lower_band (overextended)"
    elif pct_b < 20:
        position = "near_lower_band (bearish)"
    else:
        position = "within_bands (neutral)"

    return {
        "available": True,
        "upper_band": round(upper_val, 2),
        "middle_band": round(sma_val, 2),
        "lower_band": round(lower_val, 2),
        "bandwidth_pct": bandwidth,
        "percent_b": pct_b,
        "squeeze": squeeze,
        "position": position,
    }


def _fibonacci_retracements(df: pd.DataFrame, lookback: int = 60) -> dict:
    """Murphy Framework 8: Fibonacci Retracement levels from swing high/low."""
    data = df.tail(lookback)
    if len(data) < 10:
        return {"available": False}

    high = data["high"].values
    low = data["low"].values
    close = float(data["close"].iloc[-1])

    swing_high = float(np.max(high))
    swing_low = float(np.min(low))
    swing_range = swing_high - swing_low

    if swing_range <= 0:
        return {"available": False}

    # Standard Fibonacci levels
    fib_levels = {
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "fib_236": round(swing_high - 0.236 * swing_range, 2),
        "fib_382": round(swing_high - 0.382 * swing_range, 2),
        "fib_500": round(swing_high - 0.500 * swing_range, 2),
        "fib_618": round(swing_high - 0.618 * swing_range, 2),
        "fib_786": round(swing_high - 0.786 * swing_range, 2),
    }

    # Determine which Fibonacci zone price is in
    if close > fib_levels["fib_236"]:
        zone = "Above 23.6% — strong uptrend or near swing high"
    elif close > fib_levels["fib_382"]:
        zone = "23.6%-38.2% — shallow pullback"
    elif close > fib_levels["fib_500"]:
        zone = "38.2%-50% — standard retracement"
    elif close > fib_levels["fib_618"]:
        zone = "50%-61.8% — deep retracement (key decision zone)"
    else:
        zone = "Below 61.8% — deep correction or potential trend reversal"

    fib_levels["current_price"] = round(close, 2)
    fib_levels["fibonacci_zone"] = zone
    fib_levels["available"] = True

    return fib_levels


def _intermarket_correlations() -> dict:
    """Murphy Framework 9: Intermarket Analysis (commodity/bond/stock/dollar)."""
    # Load all relevant macro data
    assets = {
        "crude_oil": ("crude_oil.csv", "crude_oil_price"),
        "gold": ("gold.csv", "gold_price"),
        "copper": ("copper.csv", "copper_price"),
        "10y_yield": ("10y_treasury_yield.csv", "10y_yield"),
        "es_futures": ("es_futures.csv", "es_price"),
        "dxy": ("dxy.csv", "dxy"),
    }

    series: dict[str, pd.Series] = {}
    for name, (csv, col) in assets.items():
        path = os.path.join(HISTORICAL_DATA_DIR, csv)
        if not os.path.isfile(path):
            continue
        try:
            df = pd.read_csv(path)
            date_col = "date" if "date" in df.columns else "timestamp"
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col, col]).sort_values(date_col)
            df = df.set_index(date_col)
            series[name] = df[col].astype(float)
        except Exception:
            continue

    if len(series) < 4:
        return {"available": False, "note": "Insufficient intermarket data"}

    # Align on common dates
    combined = pd.DataFrame(series).dropna()
    if len(combined) < 30:
        return {"available": False, "note": "Insufficient overlapping dates"}

    # Compute 20-day rolling correlations for key Murphy relationships
    returns = combined.pct_change().dropna()
    window = min(20, len(returns) - 1)
    if window < 10:
        return {"available": False}

    relationships: list[dict] = []

    # 1. Commodity-Bond: Commodities ↑ → Bond prices ↓ (yields ↑)
    # Murphy: rising commodities = rising inflation = rising yields
    if "copper" in returns.columns and "10y_yield" in returns.columns:
        corr = float(returns["copper"].tail(window).corr(returns["10y_yield"].tail(window)))
        relationships.append({
            "pair": "Copper vs 10Y Yield",
            "murphy_theory": "Positive (rising commodities → rising yields)",
            "actual_correlation": round(corr, 3),
            "aligned": corr > 0.1,
        })

    # 2. Dollar-Commodity: DXY ↑ → Commodities ↓
    if "dxy" in returns.columns and "gold" in returns.columns:
        corr = float(returns["dxy"].tail(window).corr(returns["gold"].tail(window)))
        relationships.append({
            "pair": "DXY vs Gold",
            "murphy_theory": "Negative (strong dollar → weaker commodities)",
            "actual_correlation": round(corr, 3),
            "aligned": corr < -0.1,
        })

    if "dxy" in returns.columns and "crude_oil" in returns.columns:
        corr = float(returns["dxy"].tail(window).corr(returns["crude_oil"].tail(window)))
        relationships.append({
            "pair": "DXY vs Crude Oil",
            "murphy_theory": "Negative (strong dollar → weaker oil)",
            "actual_correlation": round(corr, 3),
            "aligned": corr < -0.1,
        })

    # 3. Bond-Stock: Lower yields → Stocks ↑ (generally positive for equities)
    if "10y_yield" in returns.columns and "es_futures" in returns.columns:
        corr = float(returns["10y_yield"].tail(window).corr(returns["es_futures"].tail(window)))
        relationships.append({
            "pair": "10Y Yield vs S&P 500",
            "murphy_theory": "Context-dependent (growth: positive / inflation: negative)",
            "actual_correlation": round(corr, 3),
            "context": "positive" if corr > 0 else "negative",
        })

    # 4. Gold-DXY-Yield triangulation
    if "gold" in returns.columns and "10y_yield" in returns.columns:
        corr = float(returns["gold"].tail(window).corr(returns["10y_yield"].tail(window)))
        relationships.append({
            "pair": "Gold vs 10Y Yield",
            "murphy_theory": "Negative (gold = inflation hedge, competes with yield)",
            "actual_correlation": round(corr, 3),
            "aligned": corr < -0.1,
        })

    # Regime classification
    aligned_count = sum(1 for r in relationships if r.get("aligned", False))
    total = len(relationships)

    return {
        "available": True,
        "relationships": relationships,
        "alignment_score": f"{aligned_count}/{total} relationships aligned with Murphy theory",
        "regime": (
            "Classic Murphy regime — intermarket relationships working normally"
            if aligned_count >= total * 0.6
            else "Anomalous regime — intermarket relationships breaking down"
        ),
    }


def _relative_strength(asset_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """Murphy Framework 10: Relative Strength — asset vs benchmark."""
    if len(asset_df) < 20 or len(benchmark_df) < 20:
        return {"available": False}

    # Align on index (use tail to match lengths)
    n = min(len(asset_df), len(benchmark_df))
    a_close = asset_df["close"].tail(n).values
    b_close = benchmark_df["close"].tail(n).values

    # RS line = asset / benchmark
    rs_line = a_close / np.where(b_close == 0, 1, b_close)

    # RS direction (last 20 values)
    rs_recent = rs_line[-20:]
    if len(rs_recent) >= 20:
        rs_change = (rs_recent[-1] - rs_recent[0]) / rs_recent[0] * 100
        direction = "outperforming" if rs_change > 1 else "underperforming" if rs_change < -1 else "inline"
    else:
        rs_change = 0
        direction = "insufficient_data"

    return {
        "available": True,
        "rs_ratio": round(float(rs_line[-1]), 4),
        "rs_change_pct": round(float(rs_change), 2),
        "direction": direction,
    }


def _dow_theory() -> dict:
    """Murphy Framework 11: Dow Theory — primary trend, confirmation between averages."""
    es_df = _load_macro_data("es_futures.csv", "es_price")
    rty_df = _load_macro_data("rty_futures.csv", "rty_price")

    if es_df is None or rty_df is None or len(es_df) < 50 or len(rty_df) < 50:
        return {"available": False}

    # Trend for each index (50-day MA direction)
    es_close = es_df["close"]
    rty_close = rty_df["close"]

    es_sma50 = es_close.rolling(50).mean()
    rty_sma50 = rty_close.rolling(50).mean()

    es_above = float(es_close.iloc[-1]) > float(es_sma50.iloc[-1])
    rty_above = float(rty_close.iloc[-1]) > float(rty_sma50.iloc[-1])

    es_trend = "bullish" if es_above else "bearish"
    rty_trend = "bullish" if rty_above else "bearish"

    # Dow Theory: averages must confirm each other
    if es_trend == rty_trend == "bullish":
        confirmation = "CONFIRMED_BULLISH — both averages in uptrend (Dow Theory buy signal)"
    elif es_trend == rty_trend == "bearish":
        confirmation = "CONFIRMED_BEARISH — both averages in downtrend (Dow Theory sell signal)"
    else:
        confirmation = f"NON_CONFIRMATION — S&P 500 {es_trend}, Russell 2000 {rty_trend} (divergence warning)"

    return {
        "available": True,
        "sp500_trend": es_trend,
        "russell_2000_trend": rty_trend,
        "sp500_vs_sma50": "above" if es_above else "below",
        "russell_vs_sma50": "above" if rty_above else "below",
        "confirmation": confirmation,
    }


def _pattern_recognition(df: pd.DataFrame, lookback: int = 60) -> dict:
    """Murphy Framework 12: Simplified chart pattern detection."""
    data = df.tail(lookback)
    if len(data) < 30:
        return {"patterns": []}

    high = data["high"].values
    low = data["low"].values
    close = data["close"].values
    patterns = []

    # Find swing highs/lows
    swing_highs = []
    swing_lows = []
    for i in range(2, len(high) - 2):
        if high[i] > high[i-1] and high[i] > high[i+1]:
            swing_highs.append((i, float(high[i])))
        if low[i] < low[i-1] and low[i] < low[i+1]:
            swing_lows.append((i, float(low[i])))

    # Double Top: two swing highs at similar level with a valley between
    if len(swing_highs) >= 2:
        for j in range(len(swing_highs) - 1):
            h1_idx, h1_val = swing_highs[j]
            h2_idx, h2_val = swing_highs[j + 1]
            # Within 2% of each other and at least 10 bars apart
            if abs(h1_val - h2_val) / h1_val < 0.02 and h2_idx - h1_idx >= 10:
                patterns.append({
                    "pattern": "DOUBLE_TOP",
                    "level": round((h1_val + h2_val) / 2, 2),
                    "signal": "Bearish reversal — resistance tested twice",
                })
                break

    # Double Bottom: two swing lows at similar level
    if len(swing_lows) >= 2:
        for j in range(len(swing_lows) - 1):
            l1_idx, l1_val = swing_lows[j]
            l2_idx, l2_val = swing_lows[j + 1]
            if abs(l1_val - l2_val) / l1_val < 0.02 and l2_idx - l1_idx >= 10:
                patterns.append({
                    "pattern": "DOUBLE_BOTTOM",
                    "level": round((l1_val + l2_val) / 2, 2),
                    "signal": "Bullish reversal — support tested twice",
                })
                break

    # Head & Shoulders (simplified: 3 highs where middle is highest)
    if len(swing_highs) >= 3:
        for j in range(len(swing_highs) - 2):
            h1 = swing_highs[j][1]
            h2 = swing_highs[j+1][1]
            h3 = swing_highs[j+2][1]
            if h2 > h1 and h2 > h3 and abs(h1 - h3) / h1 < 0.03:
                patterns.append({
                    "pattern": "HEAD_AND_SHOULDERS",
                    "head_level": round(h2, 2),
                    "neckline_approx": round((h1 + h3) / 2, 2),
                    "signal": "Bearish reversal pattern",
                })
                break

    return {"patterns": patterns if patterns else [{"pattern": "NONE_DETECTED"}]}


def _stochastic_oscillator(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    """Murphy Framework 13: Stochastic Oscillator (%K, %D)."""
    if len(df) < k_period + d_period:
        return {"available": False}

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # %K = (Close - Lowest Low) / (Highest High - Lowest Low) × 100
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    denom = highest_high - lowest_low
    k_line = ((close - lowest_low) / denom.replace(0, np.nan) * 100).dropna()

    if len(k_line) < d_period:
        return {"available": False}

    # %D = SMA of %K
    d_line = k_line.rolling(d_period).mean()

    k_val = round(float(k_line.iloc[-1]), 2)
    d_val = round(float(d_line.iloc[-1]), 2)

    # Zone
    if k_val >= 80:
        zone = "overbought"
    elif k_val <= 20:
        zone = "oversold"
    else:
        zone = "neutral"

    # Crossover
    if len(k_line) >= 2 and len(d_line) >= 2:
        k_prev = float(k_line.iloc[-2])
        d_prev = float(d_line.iloc[-2])
        if k_prev < d_prev and k_val > d_val:
            crossover = "BULLISH_CROSS — %K crossed above %D"
        elif k_prev > d_prev and k_val < d_val:
            crossover = "BEARISH_CROSS — %K crossed below %D"
        else:
            crossover = "%K above %D" if k_val > d_val else "%K below %D"
    else:
        crossover = "N/A"

    return {
        "available": True,
        "percent_k": k_val,
        "percent_d": d_val,
        "zone": zone,
        "crossover": crossover,
    }


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC TOOL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def murphy_technical_analysis(asset: str, timeframe: str = "1D") -> str:
    """Comprehensive Murphy Technical Analysis applying 10 core frameworks.

    Analyzes an asset using John Murphy's TA methodology:
    trend structure, support/resistance, volume, moving averages, MACD,
    RSI, Bollinger Bands, Fibonacci, Stochastic, and pattern recognition.
    (Intermarket, Relative Strength, and Dow Theory are separate tools.)

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, silver,
               copper, es_futures, sp500, russell_2000, dxy, rty_futures.
               Also supports any stock/ETF ticker via yfinance (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe for analysis. BTC supports: 30min, 1H, 4H, 1D.
                   All other assets: 1D only.

    Returns:
        JSON string with complete technical analysis across all frameworks.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "timeframe": timeframe,
        "analysis": "murphy_technical_analysis",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 20:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    result["data_points"] = len(df)
    result["current_price"] = round(float(df["close"].iloc[-1]), 2)

    # Apply Murphy frameworks with error handling so failures don't omit silently
    _frameworks = [
        ("1_trend", _trend_classification),
        ("2_support_resistance", _support_resistance_levels),
        ("3_volume", _volume_confirmation),
        ("4_moving_averages", _moving_average_analysis),
        ("5_macd", _macd),
        ("6_rsi", _rsi_analysis),
        ("7_bollinger_bands", _bollinger_bands),
        ("8_fibonacci", _fibonacci_retracements),
        ("9_stochastic", _stochastic_oscillator),
        ("10_patterns", _pattern_recognition),
    ]
    for key, fn in _frameworks:
        try:
            result[key] = fn(df)
        except Exception as e:
            result[key] = {"available": False, "error": f"Framework failed: {e}"}

    # Composite Signal — weighted assessment
    bullish = 0
    bearish = 0
    total = 0

    trend = result["1_trend"].get("direction", "")
    if trend in ("uptrend",):
        bullish += 2
    elif trend in ("downtrend",):
        bearish += 2
    total += 2

    ma = result["4_moving_averages"]
    if ma.get("price_vs_sma50") == "above":
        bullish += 1
    elif ma.get("price_vs_sma50") == "below":
        bearish += 1
    total += 1
    if ma.get("price_vs_sma200") == "above":
        bullish += 1
    elif ma.get("price_vs_sma200") == "below":
        bearish += 1
    total += 1

    macd_data = result["5_macd"]
    if macd_data.get("available"):
        if macd_data.get("histogram", 0) > 0:
            bullish += 1
        else:
            bearish += 1
        total += 1

    rsi_data = result["6_rsi"]
    if rsi_data.get("available"):
        rsi_val = rsi_data.get("rsi", 50)
        if rsi_val > 50:
            bullish += 1
        elif rsi_val < 50:
            bearish += 1
        total += 1

    stoch = result["9_stochastic"]
    if stoch.get("available"):
        k = stoch.get("percent_k", 50)
        if k > 50:
            bullish += 1
        elif k < 50:
            bearish += 1
        total += 1

    bb = result["7_bollinger_bands"]
    if bb.get("available"):
        pct_b = bb.get("percent_b", 50)
        if pct_b > 60:
            bullish += 1
        elif pct_b < 40:
            bearish += 1
        total += 1

    if total > 0:
        score = (bullish - bearish) / total
        if score > 0.3:
            composite = "BULLISH"
        elif score < -0.3:
            composite = "BEARISH"
        else:
            composite = "NEUTRAL"
    else:
        composite = "NEUTRAL"
        score = 0

    # Confidence from score magnitude
    abs_score = abs(score)
    confidence = "high" if abs_score >= 0.6 else ("medium" if abs_score >= 0.3 else "low")

    # Framework breakdown — show each framework's contribution
    framework_breakdown = []
    framework_breakdown.append(f"Trend: {'BULLISH' if trend in ('uptrend',) else ('BEARISH' if trend in ('downtrend',) else 'NEUTRAL')}")

    if ma.get("price_vs_sma50"):
        framework_breakdown.append(f"SMA 50: {'BULLISH' if ma.get('price_vs_sma50') == 'above' else 'BEARISH'}")
    if ma.get("price_vs_sma200"):
        framework_breakdown.append(f"SMA 200: {'BULLISH' if ma.get('price_vs_sma200') == 'above' else 'BEARISH'}")

    if macd_data.get("available"):
        hist = macd_data.get("histogram", 0)
        framework_breakdown.append(f"MACD: {'BULLISH' if hist > 0 else 'BEARISH'} (hist={hist:.2f})" if hist else "MACD: NEUTRAL")

    if rsi_data.get("available"):
        rsi_v = rsi_data.get("rsi", 50)
        zone = "overbought" if rsi_v > 70 else ("oversold" if rsi_v < 30 else ("bullish" if rsi_v > 50 else "bearish"))
        framework_breakdown.append(f"RSI: {zone.upper()} ({rsi_v:.1f})")

    if stoch.get("available"):
        k_val = stoch.get("percent_k", 50)
        s_zone = "overbought" if k_val > 80 else ("oversold" if k_val < 20 else ("bullish" if k_val > 50 else "bearish"))
        framework_breakdown.append(f"Stochastic: {s_zone.upper()} (%K={k_val:.1f})")

    if bb.get("available"):
        pct_b_val = bb.get("percent_b", 50)
        b_zone = "upper" if pct_b_val > 80 else ("lower" if pct_b_val < 20 else "middle")
        squeeze_active = bb.get("squeeze", False)
        bb_str = f"Bollinger: {b_zone.upper()} (%B={pct_b_val:.1f})"
        if squeeze_active:
            bb_str += " SQUEEZE"
        framework_breakdown.append(bb_str)

    result["composite_signal"] = {
        "signal": composite,
        "confidence": confidence,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "total_indicators": total,
        "score": round(score, 2),
        "framework_breakdown": framework_breakdown,
    }

    return json.dumps(result, indent=2)


def murphy_intermarket_analysis() -> str:
    """Murphy's Intermarket Analysis — commodity/bond/stock/dollar relationships.

    Analyzes the four-market model from Murphy's *Intermarket Technical Analysis*:
    - Commodities ↔ Bonds (inverse): rising commodities = rising inflation = falling bonds
    - Bonds ↔ Stocks (positive): falling rates support equities
    - Dollar ↔ Commodities (inverse): strong dollar weakens commodity prices
    - Gold ↔ Dollar (inverse): gold as dollar hedge

    Returns:
        JSON string with intermarket relationships, correlations, and regime assessment.
    """
    result: dict = {
        "analysis": "murphy_intermarket",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d"),
    }

    intermarket = _intermarket_correlations()
    result.update(intermarket)

    # Add Dow Theory as part of intermarket
    dow = _dow_theory()
    result["dow_theory"] = dow

    return json.dumps(result, indent=2)


def murphy_trend_report(asset: str, timeframe: str = "1D") -> str:
    """Focused Murphy trend analysis: direction, MAs, Fibonacci, S/R, patterns.

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, etc.
               Also supports stock/ETF tickers (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe (1D default, BTC supports 30min/1H/4H/1D).

    Returns:
        JSON string with trend-focused analysis.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "timeframe": timeframe,
        "analysis": "murphy_trend_report",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 20:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    result["current_price"] = round(float(df["close"].iloc[-1]), 2)
    result["trend"] = _trend_classification(df)
    result["moving_averages"] = _moving_average_analysis(df)
    result["fibonacci"] = _fibonacci_retracements(df)
    result["support_resistance"] = _support_resistance_levels(df)
    result["patterns"] = _pattern_recognition(df)

    # Add Dow Theory if asset is an index
    if asset_lower in ("es_futures", "sp500", "rty_futures", "russell_2000"):
        result["dow_theory"] = _dow_theory()

    return json.dumps(result, indent=2)


def murphy_momentum_report(asset: str, timeframe: str = "1D") -> str:
    """Murphy momentum oscillator dashboard: RSI, MACD, Stochastic, Bollinger.

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, etc.
               Also supports stock/ETF tickers (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe (1D default, BTC supports 30min/1H/4H/1D).

    Returns:
        JSON string with momentum-focused analysis.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "timeframe": timeframe,
        "analysis": "murphy_momentum_report",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 30:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    result["current_price"] = round(float(df["close"].iloc[-1]), 2)
    result["rsi"] = _rsi_analysis(df)
    result["macd"] = _macd(df)
    result["stochastic"] = _stochastic_oscillator(df)
    result["bollinger_bands"] = _bollinger_bands(df)
    result["volume"] = _volume_confirmation(df)

    # Momentum composite
    ob = 0  # overbought signals
    os_count = 0  # oversold signals

    rsi = result["rsi"]
    if rsi.get("available") and rsi.get("rsi", 50) >= 70:
        ob += 1
    elif rsi.get("available") and rsi.get("rsi", 50) <= 30:
        os_count += 1

    stoch = result["stochastic"]
    if stoch.get("available") and stoch.get("percent_k", 50) >= 80:
        ob += 1
    elif stoch.get("available") and stoch.get("percent_k", 50) <= 20:
        os_count += 1

    bb = result["bollinger_bands"]
    if bb.get("available") and bb.get("percent_b", 50) > 100:
        ob += 1
    elif bb.get("available") and bb.get("percent_b", 50) < 0:
        os_count += 1

    if ob >= 2:
        momentum = "OVERBOUGHT — multiple oscillators at extreme (caution for longs)"
    elif os_count >= 2:
        momentum = "OVERSOLD — multiple oscillators at extreme (potential bounce)"
    elif ob == 1:
        momentum = "MILDLY_OVERBOUGHT — one oscillator extended"
    elif os_count == 1:
        momentum = "MILDLY_OVERSOLD — one oscillator extended"
    else:
        momentum = "NEUTRAL — no extreme readings"

    result["momentum_composite"] = momentum

    return json.dumps(result, indent=2)


def clear_stock_ta_cache() -> str:
    """Clear the in-memory stock OHLCV cache used by Murphy TA.

    Call this to force fresh data fetches from yfinance on the next analysis.
    Useful when you want to ensure the latest price data after market hours change.

    Returns:
        JSON string confirming cache clearance with count of evicted entries.
    """
    count = len(_STOCK_OHLCV_CACHE)
    _STOCK_OHLCV_CACHE.clear()
    return json.dumps({
        "action": "cache_cleared",
        "entries_evicted": count,
        "note": "Next Murphy TA call for stock tickers will fetch fresh data from yfinance.",
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE TA TOOLS — Lightweight on-demand RSI, S/R, Breakout
# ═══════════════════════════════════════════════════════════════════════

def _analyze_breakout_internal(df: pd.DataFrame, supports: list[float],
                               resistances: list[float]) -> dict:
    """Detect breakout through support/resistance with confirmation signals.

    Checks whether price has recently broken through an S/R level and validates
    with 4 confirmation signals: volume, Bollinger expansion, RSI room, MA alignment.
    Also detects retests and false breakouts.
    """
    close = df["close"].values
    current = float(close[-1])
    n = len(close)
    if n < 20:
        return {"breakout_detected": False, "reason": "insufficient_data"}

    # ── 1) Detect breakout: price crossing an S/R level within last 5 bars ──
    breakout_type = None
    broken_level = None
    lookback_bars = min(5, n - 1)

    for r in resistances:
        # Check if price was below resistance recently and is now above
        bars_below = sum(1 for i in range(-lookback_bars - 1, -1) if close[i] < r)
        if bars_below >= 2 and current > r:
            breakout_type = "BULLISH_BREAKOUT"
            broken_level = r
            break

    if not breakout_type:
        for s in supports:
            bars_above = sum(1 for i in range(-lookback_bars - 1, -1) if close[i] > s)
            if bars_above >= 2 and current < s:
                breakout_type = "BEARISH_BREAKDOWN"
                broken_level = s
                break

    if not breakout_type:
        # Check proximity — price near but hasn't broken through yet
        nearest_r = resistances[0] if resistances else None
        nearest_s = supports[0] if supports else None
        proximity_pct = 0.5  # within 0.5% of level

        approaching = None
        if nearest_r and abs(current - nearest_r) / current * 100 < proximity_pct:
            approaching = {"level": nearest_r, "type": "resistance",
                           "distance_pct": round(abs(current - nearest_r) / current * 100, 3)}
        elif nearest_s and abs(current - nearest_s) / current * 100 < proximity_pct:
            approaching = {"level": nearest_s, "type": "support",
                           "distance_pct": round(abs(current - nearest_s) / current * 100, 3)}

        return {
            "breakout_detected": False,
            "current_price": round(current, 2),
            "nearest_resistance": nearest_r,
            "nearest_support": nearest_s,
            "approaching": approaching,
        }

    # ── 2) Confirmation signals ──
    confirmations = []

    # Volume confirmation — recent volume > 1.5x average
    # Skip entirely for close-only assets (volume=0) like macro CSVs
    vol_confirmed = False
    has_volume = "volume" in df.columns and float(df["volume"].sum()) > 0
    if has_volume:
        vol = df["volume"].values
        if n >= 20:
            recent_vol = float(np.mean(vol[-3:]))
            avg_vol = float(np.mean(vol[-20:-3])) if n > 23 else float(np.mean(vol[:-3]))
            if avg_vol > 0 and recent_vol > avg_vol * 1.5:
                vol_confirmed = True
                confirmations.append("VOLUME — breakout on above-average volume (1.5x+)")
            else:
                confirmations.append(f"VOLUME — weak ({recent_vol / avg_vol:.1f}x avg)")

    # Bollinger Band expansion — bandwidth expanding (not in squeeze)
    bb_data = _bollinger_bands(df)
    bb_confirmed = False
    if bb_data.get("available"):
        if not bb_data.get("squeeze", False) and bb_data.get("bandwidth_pct", 0) > 3:
            bb_confirmed = True
            confirmations.append(f"BOLLINGER — bands expanding (BW={bb_data['bandwidth_pct']:.1f}%)")
        else:
            confirmations.append(f"BOLLINGER — squeeze active or narrow (BW={bb_data.get('bandwidth_pct', 0):.1f}%)")

    # RSI has room — not already overbought (for bullish) or oversold (for bearish)
    rsi_data = _rsi_analysis(df)
    rsi_confirmed = False
    if rsi_data.get("available"):
        rsi_val = rsi_data.get("rsi", 50)
        if breakout_type == "BULLISH_BREAKOUT" and rsi_val < 75:
            rsi_confirmed = True
            confirmations.append(f"RSI — has room to run ({rsi_val:.1f}, not overbought)")
        elif breakout_type == "BEARISH_BREAKDOWN" and rsi_val > 25:
            rsi_confirmed = True
            confirmations.append(f"RSI — has room to fall ({rsi_val:.1f}, not oversold)")
        else:
            confirmations.append(f"RSI — already extended ({rsi_val:.1f})")

    # MA alignment — price above SMA50 for bullish, below for bearish
    ma_data = _moving_average_analysis(df)
    ma_confirmed = False
    sma50 = ma_data.get("sma_50")
    if sma50:
        if breakout_type == "BULLISH_BREAKOUT" and current > sma50:
            ma_confirmed = True
            confirmations.append(f"MA — price above SMA50 ({sma50:.2f}), trend aligned")
        elif breakout_type == "BEARISH_BREAKDOWN" and current < sma50:
            ma_confirmed = True
            confirmations.append(f"MA — price below SMA50 ({sma50:.2f}), trend aligned")
        else:
            confirmations.append(f"MA — price {'below' if breakout_type == 'BULLISH_BREAKOUT' else 'above'} SMA50 ({sma50:.2f}), against trend")

    # ── 3) Confidence scoring ──
    # For close-only assets (no volume data), max confirmations = 3 instead of 4
    if has_volume:
        confirmed_count = sum([vol_confirmed, bb_confirmed, rsi_confirmed, ma_confirmed])
        max_confirmations = 4
        confidence = {4: "HIGH", 3: "MODERATE", 2: "LOW"}.get(confirmed_count, "WEAK")
    else:
        confirmed_count = sum([bb_confirmed, rsi_confirmed, ma_confirmed])
        max_confirmations = 3
        confidence = {3: "HIGH", 2: "MODERATE", 1: "LOW"}.get(confirmed_count, "WEAK")

    # ── 4) Retest detection — price pulled back near broken level after breakout ──
    retest = None
    if n >= 5 and broken_level:
        # Check if any of the last 3 bars touched the broken level
        threshold = abs(broken_level) * 0.003  # within 0.3%
        for i in range(-3, 0):
            bar_low = float(df["low"].values[i])
            bar_high = float(df["high"].values[i])
            if abs(bar_low - broken_level) < threshold or abs(bar_high - broken_level) < threshold:
                retest = {
                    "detected": True,
                    "level": broken_level,
                    "note": "Price retested the broken level — if it holds, this confirms the breakout and is a potential entry point.",
                }
                break

    # ── 5) False breakout warning ──
    false_breakout = False
    if broken_level:
        if breakout_type == "BULLISH_BREAKOUT" and current < broken_level:
            false_breakout = True
        elif breakout_type == "BEARISH_BREAKDOWN" and current > broken_level:
            false_breakout = True

    breakout_pct = round(abs(current - broken_level) / broken_level * 100, 2) if broken_level else 0

    return {
        "breakout_detected": True,
        "breakout_type": breakout_type,
        "broken_level": broken_level,
        "current_price": round(current, 2),
        "breakout_distance_pct": breakout_pct,
        "confidence": confidence,
        "confirmations_met": confirmed_count,
        "confirmations_total": max_confirmations,
        "confirmation_details": confirmations,
        "retest": retest,
        "false_breakout_warning": false_breakout,
        "rsi": rsi_data.get("rsi") if rsi_data.get("available") else None,
        "volume_confirmed": vol_confirmed,
    }


def calculate_rsi(asset: str, period: int = 14, timeframe: str = "1D",
                  extra_periods: str = "") -> str:
    """Calculate RSI (Relative Strength Index) for any asset on demand.

    Lightweight standalone RSI tool. Returns the current RSI value, zone
    classification, divergence detection, and multi-period RSI for a
    comprehensive momentum read.

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, silver,
               copper, es_futures, sp500, russell_2000, dxy, rty_futures.
               Also supports any stock/ETF ticker (e.g., AAPL, NVDA, QQQ).
        period: RSI period (default 14). Common values: 7 (short-term),
                9 (futures/crypto), 14 (standard), 21 (longer-term).
        timeframe: Timeframe for analysis (default 1D). BTC supports:
                   30min, 1H, 4H, 1D. All others: 1D only.
        extra_periods: Comma-separated custom periods to include (e.g. "9,25").
                       Standard 7/14/21 are always included.

    Returns:
        JSON string with RSI value, zone, divergence, multi-period RSI,
        and actionable signal.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "analysis": "rsi",
        "timeframe": timeframe,
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 30:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    result["current_price"] = round(float(df["close"].iloc[-1]), 2)
    result["data_points"] = len(df)

    # Primary RSI at requested period
    primary = _rsi_analysis(df, period=period)
    result[f"rsi_{period}"] = primary.get("rsi")
    result["rsi"] = primary.get("rsi")  # canonical key for programmatic access
    result["zone"] = primary.get("zone")
    result["divergence"] = primary.get("divergence")

    # Multi-period RSI for context — standard + custom periods
    base_periods = {7, 14, 21}
    if extra_periods:
        for ep in extra_periods.split(","):
            ep = ep.strip()
            if ep.isdigit() and 2 <= int(ep) <= 200:
                base_periods.add(int(ep))
    multi_periods = sorted(p for p in base_periods if p != period)
    result["multi_period"] = {}
    for p in multi_periods:
        r = _rsi_analysis(df, period=p)
        if r.get("available"):
            result["multi_period"][f"rsi_{p}"] = r.get("rsi")

    # Actionable signal
    rsi_val = primary.get("rsi", 50)
    if rsi_val >= 80:
        signal = "STRONGLY_OVERBOUGHT — high probability of mean reversion. Avoid new longs."
    elif rsi_val >= 70:
        signal = "OVERBOUGHT — momentum extended. Watch for bearish divergence."
    elif rsi_val <= 20:
        signal = "STRONGLY_OVERSOLD — high probability of bounce. Watch for bullish divergence."
    elif rsi_val <= 30:
        signal = "OVERSOLD — selling exhaustion possible. Look for reversal confirmation."
    elif rsi_val >= 60:
        signal = "BULLISH_MOMENTUM — above centerline, trend favors longs."
    elif rsi_val <= 40:
        signal = "BEARISH_MOMENTUM — below centerline, trend favors shorts."
    else:
        signal = "NEUTRAL — no strong directional bias from RSI."

    if primary.get("divergence"):
        signal += f" {primary['divergence']}"

    result["signal"] = signal

    # Cross-tool follow-up suggestions
    suggestions = []
    if rsi_val <= 30:
        suggestions.append(f"RSI oversold — use find_support_resistance('{asset}') to find the bounce level")
        suggestions.append(f"Then use analyze_breakout('{asset}') to check if support is breaking down")
    elif rsi_val >= 70:
        suggestions.append(f"RSI overbought — use find_support_resistance('{asset}') to find resistance ceiling")
        suggestions.append(f"Use analyze_breakout('{asset}') to check if resistance is being breached")
    else:
        suggestions.append(f"Use find_support_resistance('{asset}') for key levels context")
    suggestions.append(f"Use quick_ta_snapshot('{asset}') for RSI + S/R + breakout combined view")
    result["suggested_followups"] = suggestions

    return json.dumps(result, indent=2)


def find_support_resistance(asset: str, timeframe: str = "1D",
                            lookback: int = 100) -> str:
    """Find support and resistance levels for any asset on demand.

    Lightweight standalone S/R tool. Returns key price levels with proximity
    analysis showing how close the current price is to each level, plus
    strength classification based on clustering density.

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, silver,
               copper, es_futures, sp500, russell_2000, dxy, rty_futures.
               Also supports any stock/ETF ticker (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe for analysis (default 1D). BTC supports:
                   30min, 1H, 4H, 1D. All others: 1D only.
        lookback: Number of bars to look back for pivot detection (default 100).

    Returns:
        JSON string with support/resistance levels, proximity analysis,
        and nearest actionable levels.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "analysis": "support_resistance",
        "timeframe": timeframe,
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 20:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    current = round(float(df["close"].iloc[-1]), 2)
    result["current_price"] = current
    result["data_points"] = len(df)

    # Core S/R from existing helper
    sr = _support_resistance_levels(df, lookback=lookback)
    result["supports"] = sr.get("supports", [])
    result["resistances"] = sr.get("resistances", [])
    result["nearest_support"] = sr.get("nearest_support")
    result["nearest_resistance"] = sr.get("nearest_resistance")
    result["support_distance_pct"] = sr.get("support_distance_pct")
    result["resistance_distance_pct"] = sr.get("resistance_distance_pct")

    # Proximity analysis — how close is price to each level
    proximity = []
    for s in sr.get("supports", []):
        dist_pct = round((current - s) / current * 100, 2)
        proximity.append({"level": s, "type": "support", "distance_pct": dist_pct,
                          "zone": "immediate" if dist_pct < 1 else ("nearby" if dist_pct < 3 else "distant")})
    for r in sr.get("resistances", []):
        dist_pct = round((r - current) / current * 100, 2)
        proximity.append({"level": r, "type": "resistance", "distance_pct": dist_pct,
                          "zone": "immediate" if dist_pct < 1 else ("nearby" if dist_pct < 3 else "distant")})
    result["proximity"] = proximity

    # Position assessment (with fallback for one-sided levels)
    s_dist = sr.get("support_distance_pct")
    r_dist = sr.get("resistance_distance_pct")
    if s_dist is not None and r_dist is not None:
        if s_dist < 1:
            position = "AT_SUPPORT — price sitting on support, watch for bounce or break"
        elif r_dist < 1:
            position = "AT_RESISTANCE — price testing resistance, watch for breakout or rejection"
        elif s_dist < r_dist:
            position = "CLOSER_TO_SUPPORT — more downside room to resistance"
        else:
            position = "CLOSER_TO_RESISTANCE — approaching resistance overhead"
    elif s_dist is not None and r_dist is None:
        position = "ABOVE_ALL_RESISTANCES — price in open air, no overhead resistance found"
    elif r_dist is not None and s_dist is None:
        position = "BELOW_ALL_SUPPORTS — price below all identified support levels"
    else:
        position = "NO_LEVELS — insufficient S/R levels for position assessment"
    result["position"] = position

    # Add trend context from MAs
    ma = _moving_average_analysis(df)
    result["trend_context"] = {
        "sma_50": ma.get("sma_50"),
        "price_vs_sma50": ma.get("price_vs_sma50"),
        "sma_200": ma.get("sma_200"),
        "price_vs_sma200": ma.get("price_vs_sma200"),
    }

    # Cross-tool follow-up suggestions
    suggestions = []
    suggestions.append(f"Use calculate_rsi('{asset_lower}') to check momentum at these levels")
    suggestions.append(f"Use analyze_breakout('{asset_lower}') to detect if S/R is breaking")
    if position.startswith("AT_SUPPORT"):
        suggestions.append(f"Price at support — if RSI is oversold, this could be a bounce entry")
    elif position.startswith("AT_RESISTANCE"):
        suggestions.append(f"Price at resistance — use analyze_breakout('{asset_lower}') to check for confirmed breakout")
    result["suggested_followups"] = suggestions

    return json.dumps(result, indent=2)


def analyze_breakout(asset: str, timeframe: str = "1D") -> str:
    """Analyze whether an asset is breaking out through support or resistance.

    Detects price breaking through key S/R levels and validates with
    4 confirmation signals: volume surge, Bollinger Band expansion,
    RSI room (not already extended), and MA alignment. Also detects
    retests of broken levels and warns about potential false breakouts.

    Confidence scoring:
    - HIGH: 4/4 confirmations — strong breakout, high follow-through probability
    - MODERATE: 3/4 confirmations — likely breakout, monitor for follow-through
    - LOW: 2/4 confirmations — tentative breakout, wait for more confirmation
    - WEAK: 0-1/4 confirmations — likely false breakout, do not chase

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, silver,
               copper, es_futures, sp500, russell_2000, dxy, rty_futures.
               Also supports any stock/ETF ticker (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe for analysis (default 1D). BTC supports:
                   30min, 1H, 4H, 1D. All others: 1D only.

    Returns:
        JSON string with breakout detection, confirmation signals,
        confidence level, retest status, and false breakout warnings.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "analysis": "breakout",
        "timeframe": timeframe,
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 20:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    result["current_price"] = round(float(df["close"].iloc[-1]), 2)
    result["data_points"] = len(df)

    # Get S/R levels
    sr = _support_resistance_levels(df)
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])

    result["support_levels"] = supports
    result["resistance_levels"] = resistances

    # Run breakout analysis
    breakout = _analyze_breakout_internal(df, supports, resistances)
    result.update(breakout)

    # Add trend context
    trend = _trend_classification(df)
    result["trend"] = {
        "direction": trend.get("direction"),
        "strength": trend.get("strength"),
    }

    # Cross-tool follow-up suggestions + stop-loss integration
    suggestions = []
    if breakout.get("breakout_detected"):
        broken_level = breakout.get("broken_level")
        btype = breakout.get("breakout_type", "")
        confidence = breakout.get("confidence", "WEAK")
        direction = "long" if "BULLISH" in btype else "short"
        current_price = result.get("current_price", 0)
        suggestions.append(
            f"Breakout confirmed — use protrader_stop_loss_framework('{asset_lower}', "
            f"{current_price}, '{direction}') to set stop-loss at/below the broken level "
            f"({broken_level:.2f})"
        )
        if confidence in ("HIGH", "MODERATE"):
            suggestions.append(f"Confidence {confidence} — suitable for position entry with proper risk management")
        else:
            suggestions.append(f"Confidence {confidence} — wait for more confirmation or use smaller position size")
        if breakout.get("false_breakout_warning"):
            suggestions.append("FALSE BREAKOUT WARNING — do not enter, wait for price to reclaim the level")
    else:
        suggestions.append(f"No breakout — use calculate_rsi('{asset_lower}') to check momentum direction")
        suggestions.append(f"Use find_support_resistance('{asset_lower}') for detailed S/R proximity analysis")
    suggestions.append(f"Use quick_ta_snapshot('{asset_lower}') for RSI + S/R + breakout combined view")
    result["suggested_followups"] = suggestions

    return json.dumps(result, indent=2)


def quick_ta_snapshot(asset: str, timeframe: str = "1D") -> str:
    """Quick technical analysis snapshot: RSI + S/R + Breakout in one call.

    Lightweight alternative to the full 13-framework murphy_technical_analysis.
    Runs all 3 standalone TA tools (RSI, Support/Resistance, Breakout) and
    combines results into a single actionable snapshot.

    Args:
        asset: Asset to analyze. Built-in: btc, crude_oil, gold, silver,
               copper, es_futures, sp500, russell_2000, dxy, rty_futures.
               Also supports any stock/ETF ticker (e.g., AAPL, NVDA, QQQ).
        timeframe: Timeframe for analysis (default 1D). BTC supports:
                   30min, 1H, 4H, 1D. All others: 1D only.

    Returns:
        JSON string with combined RSI, S/R levels, breakout status,
        position assessment, and actionable summary.
    """
    asset_lower = asset.lower().strip()
    result: dict = {
        "asset": asset_lower,
        "analysis": "quick_ta_snapshot",
        "timeframe": timeframe,
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    df = _load_asset_data(asset_lower, timeframe)
    if df is None or len(df) < 30:
        result["error"] = (
            f"Could not load data for '{asset}'. "
            f"Built-in: {', '.join(ASSET_DATA_MAP.keys())}. "
            f"Stock/ETF tickers (e.g., AAPL, NVDA) are also supported via yfinance."
        )
        return json.dumps(result, indent=2)

    current = round(float(df["close"].iloc[-1]), 2)
    result["current_price"] = current
    result["data_points"] = len(df)

    # ── 1) RSI ──
    rsi_data = _rsi_analysis(df, period=14)
    rsi_val = rsi_data.get("rsi", 50)
    result["rsi"] = {
        "rsi_14": round(rsi_val, 2) if rsi_val else None,
        "zone": rsi_data.get("zone"),
        "divergence": rsi_data.get("divergence"),
    }
    for p in (7, 21):
        r = _rsi_analysis(df, period=p)
        if r.get("available"):
            result["rsi"][f"rsi_{p}"] = round(r.get("rsi", 0), 2)

    # ── 2) Support / Resistance ──
    sr = _support_resistance_levels(df)
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])
    result["support_resistance"] = {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": sr.get("nearest_support"),
        "nearest_resistance": sr.get("nearest_resistance"),
        "support_distance_pct": sr.get("support_distance_pct"),
        "resistance_distance_pct": sr.get("resistance_distance_pct"),
    }

    # Position assessment
    s_dist = sr.get("support_distance_pct")
    r_dist = sr.get("resistance_distance_pct")
    if s_dist is not None and r_dist is not None:
        if s_dist < 1:
            position = "AT_SUPPORT"
        elif r_dist < 1:
            position = "AT_RESISTANCE"
        elif s_dist < r_dist:
            position = "CLOSER_TO_SUPPORT"
        else:
            position = "CLOSER_TO_RESISTANCE"
    elif s_dist is not None:
        position = "ABOVE_ALL_RESISTANCES"
    elif r_dist is not None:
        position = "BELOW_ALL_SUPPORTS"
    else:
        position = "NO_LEVELS"
    result["position"] = position

    # ── 3) Breakout ──
    breakout = _analyze_breakout_internal(df, supports, resistances)
    result["breakout"] = {
        "detected": breakout.get("breakout_detected", False),
        "type": breakout.get("breakout_type"),
        "broken_level": breakout.get("broken_level"),
        "confidence": breakout.get("confidence"),
        "confirmations": f"{breakout.get('confirmations_met', 0)}/{breakout.get('confirmations_total', 4)}",
        "false_breakout_warning": breakout.get("false_breakout_warning", False),
        "retest": breakout.get("retest"),
    }

    # ── 4) Trend context ──
    trend = _trend_classification(df)
    ma = _moving_average_analysis(df)
    result["trend"] = {
        "direction": trend.get("direction"),
        "strength": trend.get("strength"),
        "sma_50": ma.get("sma_50"),
        "sma_200": ma.get("sma_200"),
        "price_vs_sma50": ma.get("price_vs_sma50"),
        "price_vs_sma200": ma.get("price_vs_sma200"),
    }

    # ── 5) Actionable summary ──
    zone = rsi_data.get("zone", "neutral")
    bo_detected = breakout.get("breakout_detected", False)

    summary_parts = []
    summary_parts.append(f"Trend: {trend.get('direction', '?')} ({trend.get('strength', '?')})")
    summary_parts.append(f"RSI(14): {rsi_val:.1f} ({zone})")
    summary_parts.append(f"Position: {position}")

    if bo_detected:
        bo_type = breakout.get("breakout_type", "")
        bo_conf = breakout.get("confidence", "?")
        summary_parts.append(f"BREAKOUT: {bo_type} confidence={bo_conf}")
        if breakout.get("false_breakout_warning"):
            summary_parts.append("WARNING: Possible false breakout")
    else:
        if sr.get("nearest_resistance") and r_dist:
            summary_parts.append(f"Next resistance: {sr['nearest_resistance']:.2f} ({r_dist:.1f}% away)")
        if sr.get("nearest_support") and s_dist:
            summary_parts.append(f"Next support: {sr['nearest_support']:.2f} ({s_dist:.1f}% away)")

    # Actionable signal
    if bo_detected and breakout.get("confidence") in ("HIGH", "MODERATE"):
        direction = "long" if "BULLISH" in breakout.get("breakout_type", "") else "short"
        action = f"ACTIONABLE: {breakout['breakout_type']} breakout with {breakout['confidence']} confidence. Consider {direction} entry with stop at {breakout.get('broken_level', '?')}"
    elif zone == "overbought" and position == "AT_RESISTANCE":
        action = "CAUTION: Overbought at resistance — high probability of rejection. Avoid new longs."
    elif zone == "oversold" and position == "AT_SUPPORT":
        action = "OPPORTUNITY: Oversold at support — watch for bounce confirmation before entering long."
    elif zone == "overbought":
        action = "WATCH: RSI overbought — momentum extended, watch for mean reversion."
    elif zone == "oversold":
        action = "WATCH: RSI oversold — potential bounce incoming, check S/R for entry level."
    else:
        action = "NEUTRAL: No strong directional signal. Monitor for breakout or RSI extremes."

    result["summary"] = " | ".join([p for p in summary_parts if p])
    result["action"] = action

    # Follow-up suggestions
    suggestions = []
    if bo_detected:
        broken_level = breakout.get("broken_level", 0)
        direction = "long" if "BULLISH" in breakout.get("breakout_type", "") else "short"
        suggestions.append(f"Set stop-loss: /sl {asset_lower} {current} {direction}")
    suggestions.append(f"Full 13-framework analysis: /ta {asset_lower}")
    if asset_lower not in ASSET_DATA_MAP:
        suggestions.append(f"Fundamental + TA synthesis: use fundamental_ta_synthesis('{asset_lower}')")
    result["suggested_followups"] = suggestions

    return json.dumps(result, indent=2)


def fundamental_ta_synthesis(ticker: str, timeframe: str = "1D") -> str:
    """Synthesize fundamental valuation + technical analysis for a stock.

    Combines equity valuation data (P/E, margins, growth) with technical
    signals (RSI, S/R, breakout, trend) to determine if fundamentals
    align with technicals for a higher-conviction signal.

    Args:
        ticker: Stock ticker (e.g., AAPL, NVDA, MSFT).
        timeframe: Timeframe for TA (default 1D).

    Returns:
        JSON string with fundamental + technical synthesis and alignment assessment.
    """
    from tools.equity_analysis import analyze_equity_valuation

    ticker_upper = ticker.upper().strip()
    result: dict = {
        "ticker": ticker_upper,
        "analysis": "fundamental_ta_synthesis",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    # ── 1) Fundamental analysis ──
    try:
        fund_json = analyze_equity_valuation(ticker_upper)
        fund = json.loads(fund_json)
        if "error" in fund:
            result["fundamental_error"] = fund["error"]
            fund = None
    except Exception as e:
        result["fundamental_error"] = str(e)
        fund = None

    # ── 2) Technical analysis (quick snapshot) ──
    ta_json = quick_ta_snapshot(ticker_upper, timeframe)
    ta = json.loads(ta_json)
    if "error" in ta:
        result["technical_error"] = ta["error"]
        ta = None

    if fund is None and ta is None:
        result["error"] = f"Could not load fundamental or technical data for '{ticker_upper}'."
        return json.dumps(result, indent=2)

    # ── 3) Extract fundamental signals ──
    fund_signal = "UNKNOWN"
    fund_details = {}
    if fund:
        metrics = fund.get("latest_metrics", {})
        margins = fund.get("margins", {})

        pe = metrics.get("pe_ratio") or metrics.get("trailing_pe")
        revenue_growth = metrics.get("revenue_growth_yoy")
        eps_growth = metrics.get("eps_growth_yoy")
        roe = metrics.get("roe")
        gross_margin = margins.get("gross_margin") if margins else None
        net_margin = margins.get("net_margin") if margins else None

        fund_details = {
            "pe_ratio": pe,
            "revenue_growth_yoy": revenue_growth,
            "eps_growth_yoy": eps_growth,
            "roe": roe,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
        }

        bullish_count = 0
        bearish_count = 0
        if pe is not None:
            if pe < 20:
                bullish_count += 1
            elif pe > 40:
                bearish_count += 1
        if revenue_growth is not None:
            if revenue_growth > 10:
                bullish_count += 1
            elif revenue_growth < -5:
                bearish_count += 1
        if roe is not None:
            if roe > 15:
                bullish_count += 1
            elif roe < 5:
                bearish_count += 1
        if eps_growth is not None:
            if eps_growth > 10:
                bullish_count += 1
            elif eps_growth < -10:
                bearish_count += 1

        if bullish_count >= 3:
            fund_signal = "BULLISH"
        elif bearish_count >= 3:
            fund_signal = "BEARISH"
        elif bullish_count > bearish_count:
            fund_signal = "SLIGHTLY_BULLISH"
        elif bearish_count > bullish_count:
            fund_signal = "SLIGHTLY_BEARISH"
        else:
            fund_signal = "NEUTRAL"

    result["fundamental"] = {
        "signal": fund_signal,
        "details": fund_details,
        "company": fund.get("company", ticker_upper) if fund else ticker_upper,
    }

    # ── 4) Extract technical signals ──
    ta_signal = "UNKNOWN"
    ta_details = {}
    if ta:
        rsi_data = ta.get("rsi", {})
        trend_data = ta.get("trend", {})
        breakout_data = ta.get("breakout", {})

        ta_details = {
            "rsi_14": rsi_data.get("rsi_14"),
            "rsi_zone": rsi_data.get("zone"),
            "trend_direction": trend_data.get("direction"),
            "trend_strength": trend_data.get("strength"),
            "breakout_detected": breakout_data.get("detected", False),
            "breakout_confidence": breakout_data.get("confidence"),
            "position": ta.get("position"),
        }

        trend_dir = trend_data.get("direction", "")
        rsi_zone = rsi_data.get("zone", "")

        if trend_dir == "uptrend" and rsi_zone in ("bullish_momentum", "overbought"):
            ta_signal = "BULLISH"
        elif trend_dir == "downtrend" and rsi_zone in ("bearish_momentum", "oversold"):
            ta_signal = "BEARISH"
        elif trend_dir == "uptrend":
            ta_signal = "SLIGHTLY_BULLISH"
        elif trend_dir == "downtrend":
            ta_signal = "SLIGHTLY_BEARISH"
        else:
            ta_signal = "NEUTRAL"

        if breakout_data.get("detected"):
            if "BULLISH" in (breakout_data.get("type") or ""):
                ta_signal = "BULLISH"
            elif "BEARISH" in (breakout_data.get("type") or ""):
                ta_signal = "BEARISH"

    result["technical"] = {
        "signal": ta_signal,
        "details": ta_details,
        "current_price": ta.get("current_price") if ta else None,
    }

    # ── 5) Synthesis ──
    bullish_signals = {"BULLISH", "SLIGHTLY_BULLISH"}
    bearish_signals = {"BEARISH", "SLIGHTLY_BEARISH"}

    if fund_signal in bullish_signals and ta_signal in bullish_signals:
        alignment = "ALIGNED_BULLISH"
        conviction = "HIGH" if fund_signal == "BULLISH" and ta_signal == "BULLISH" else "MODERATE"
        synthesis = (
            f"Fundamentals and technicals both bullish for {ticker_upper}. "
            f"Higher-conviction setup. Consider long entry with proper risk management."
        )
    elif fund_signal in bearish_signals and ta_signal in bearish_signals:
        alignment = "ALIGNED_BEARISH"
        conviction = "HIGH" if fund_signal == "BEARISH" and ta_signal == "BEARISH" else "MODERATE"
        synthesis = (
            f"Fundamentals and technicals both bearish for {ticker_upper}. "
            f"Avoid new longs. Consider short or wait for reversal signals."
        )
    elif fund_signal in bullish_signals and ta_signal in bearish_signals:
        alignment = "DIVERGENT_FUND_BULLISH"
        conviction = "LOW"
        synthesis = (
            f"Fundamentals bullish but technicals bearish for {ticker_upper}. "
            f"Stock may be in a pullback. Watch for RSI oversold + support hold for value entry."
        )
    elif fund_signal in bearish_signals and ta_signal in bullish_signals:
        alignment = "DIVERGENT_TA_BULLISH"
        conviction = "LOW"
        synthesis = (
            f"Technicals bullish but fundamentals bearish for {ticker_upper}. "
            f"Could be momentum/speculative rally. Use tight stops."
        )
    else:
        alignment = "NEUTRAL"
        conviction = "LOW"
        synthesis = f"Mixed or neutral signals for {ticker_upper}. No strong directional conviction."

    result["synthesis"] = {
        "alignment": alignment,
        "conviction": conviction,
        "assessment": synthesis,
    }

    suggestions = []
    if alignment.startswith("ALIGNED_BULLISH"):
        suggestions.append(f"Set entry: /sl {ticker_upper.lower()} {ta.get('current_price', 0)} long")
        suggestions.append(f"Full TA: /ta {ticker_upper}")
    elif alignment.startswith("ALIGNED_BEARISH"):
        suggestions.append(f"Full TA for short setup: /ta {ticker_upper}")
    elif alignment == "DIVERGENT_FUND_BULLISH":
        suggestions.append(f"Watch RSI for oversold bounce: /rsi {ticker_upper}")
        suggestions.append(f"Find entry level: /sr {ticker_upper}")
    suggestions.append(f"Peer comparison: /peers {ticker_upper}")
    suggestions.append(f"Graham value analysis: /graham {ticker_upper}")
    result["suggested_followups"] = suggestions

    return json.dumps(result, indent=2)
