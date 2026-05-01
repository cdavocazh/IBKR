#!/usr/bin/env python3
"""
Verify ES strategy: run backtest and output SCORE.

Enhanced with Finl_Agent_CC frameworks:
- VIX 7-tier opportunity framework
- CTA proxy (ES vs 200 SMA positioning)
- Credit conditions (HY OAS)
- Yield curve (2s10s spread)
- DXY correlation
- Dr. Copper growth signal
- Fidenza stop-loss framework

Outputs:
  stdout: SCORE: <float>
  stderr: JSON with full metrics
"""

import importlib.util
import json
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.engine import BacktestEngine, OrderType

_scoring_path = Path(__file__).parent / "scoring" / "robustness.py"
_scoring_spec = importlib.util.spec_from_file_location("robustness", _scoring_path)
_scoring_mod = importlib.util.module_from_spec(_scoring_spec)
_scoring_spec.loader.exec_module(_scoring_mod)
compute_robustness_score = _scoring_mod.compute_robustness_score

MACRO_PATH = Path("/Users/kriszhang/Github/macro_2/historical_data")


def load_daily_es_trend():
    """Load daily ES data and compute trend signals.

    Returns a dict of date -> {trend, daily_rsi, daily_atr, sma20, sma50, sma200}
    for use as a daily overlay on the 5-min backtest.
    """
    path = PROJECT_ROOT / "data" / "es" / "ES_daily.parquet"
    if not path.exists():
        return {}

    df = pd.read_parquet(path).sort_index()
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    trend_data = {}
    for i in range(50, len(df)):  # need 50 bars for SMA50
        date = df.index[i]
        d = date.date() if hasattr(date, "date") else date

        # SMAs
        sma20 = float(np.mean(closes[i - 20:i]))
        sma50 = float(np.mean(closes[i - 50:i]))
        sma200 = float(np.mean(closes[max(0, i - 200):i])) if i >= 200 else None

        # Daily RSI (14-period)
        rsi = None
        if i >= 15:
            changes = [closes[j] - closes[j - 1] for j in range(i - 14, i)]
            gains = [c if c > 0 else 0 for c in changes]
            losses = [-c if c < 0 else 0 for c in changes]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rsi = 100 - (100 / (1 + avg_gain / avg_loss))
            else:
                rsi = 100.0

        # Daily ATR (14-period)
        daily_atr = None
        if i >= 15:
            trs = []
            for j in range(i - 14, i):
                tr = max(highs[j] - lows[j],
                         abs(highs[j] - closes[j - 1]),
                         abs(lows[j] - closes[j - 1]))
                trs.append(tr)
            daily_atr = sum(trs) / 14

        # Trend classification
        price = closes[i]
        if price > sma20 and sma20 > sma50:
            trend = 1  # Bullish
        elif price < sma20 and sma20 < sma50:
            trend = -1  # Bearish
        else:
            trend = 0  # Sideways

        trend_data[d] = {
            "trend": trend,
            "daily_rsi": rsi,
            "daily_atr": daily_atr,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "close": float(price),
        }

    return trend_data


def load_nlp_regime():
    """Load NLP sentiment regime signal from latest analysis."""
    path = PROJECT_ROOT / "data" / "news" / "sentiment_analysis.json"
    if not path.exists():
        return {"regime": "SIDEWAYS", "net_sentiment": 0.0, "confidence": 0.0}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("regime_signal", {"regime": "SIDEWAYS", "net_sentiment": 0.0, "confidence": 0.0})
    except Exception:
        return {"regime": "SIDEWAYS", "net_sentiment": 0.0, "confidence": 0.0}


def load_digest_context():
    """Load market context from /digest_ES output."""
    path = PROJECT_ROOT / "guides" / "market_context_ES.md"
    if not path.exists():
        return {"trend": "SIDEWAYS", "vix_tier": 2}
    try:
        import re as _re
        content = path.read_text()
        ctx = {"trend": "SIDEWAYS", "vix_tier": 2}
        trend_match = _re.search(r'\*\*Trend\*\*:\s*(\w+)', content)
        if trend_match:
            ctx["trend"] = trend_match.group(1).upper()
        vix_match = _re.search(r'\*\*VIX Regime\*\*:\s*Tier\s*(\d)', content)
        if vix_match:
            ctx["vix_tier"] = int(vix_match.group(1))
        return ctx
    except Exception:
        return {"trend": "SIDEWAYS", "vix_tier": 2}


def load_daily_sentiment():
    """Load daily sentiment CSV built by scripts/build_sentiment_csv.py.

    Returns a dict of date -> composite_sentiment (float, -1 to +1).
    """
    path = PROJECT_ROOT / "data" / "news" / "daily_sentiment.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        sentiment = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            sentiment[d] = float(row["composite_sentiment"])
        return sentiment
    except Exception:
        return {}


def load_garch_forecast():
    """Load GARCH(1,1) daily volatility forecasts.

    Returns a dict of date -> {forecast_vol, realized_vol, vol_ratio, persistence}.
    vol_ratio > 1.0 means GARCH predicts volatility increase.
    """
    path = PROJECT_ROOT / "data" / "es" / "garch_daily_forecast.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        forecasts = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            forecasts[d] = {
                "forecast_vol": float(row["forecast_vol"]),
                "realized_vol": float(row["realized_vol"]),
                "vol_ratio": float(row["vol_ratio"]),
                "persistence": float(row["persistence"]),
            }
        return forecasts
    except Exception:
        return {}


def load_particle_regime():
    """Load particle filter regime probabilities.

    Returns a dict of date -> {p_bull, p_bear, p_sideways, regime, confidence}.
    Uses Bayesian SMC for smooth regime transitions vs static thresholds.
    """
    path = PROJECT_ROOT / "data" / "es" / "particle_regime_daily.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        regimes = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            regimes[d] = {
                "p_bull": float(row["p_bull"]),
                "p_bear": float(row["p_bear"]),
                "p_sideways": float(row["p_sideways"]),
                "regime": str(row["regime"]),
                "confidence": float(row["confidence"]),
            }
        return regimes
    except Exception:
        return {}


def load_tsfresh_signal():
    """Load tsfresh composite daily signal.

    Returns a dict of date -> composite z-score.
    Positive = bullish features (high FFT energy, volume expansion, range mass shift).
    Negative = bearish features.
    """
    path = PROJECT_ROOT / "data" / "es" / "tsfresh_daily_signal.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        signals = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            signals[d] = float(row["tsfresh_composite"])
        return signals
    except Exception:
        return {}


def load_hourly_regime_features():
    """Load pre-computed hourly regime features (3yr hourly data → daily lookup).

    Returns dict of date -> {
        hourly_trend: int (-1, 0, 1),
        hourly_atr_percentile: float (0-100),
        hourly_momentum_z: float (z-score, clipped -3 to 3),
        hourly_vol_regime: str ("low"/"normal"/"high"),
    }
    """
    path = PROJECT_ROOT / "data" / "es" / "hourly_regime_features.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        features = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            features[d] = {
                "hourly_trend": int(row["hourly_trend"]),
                "hourly_atr_percentile": float(row["hourly_atr_percentile"]),
                "hourly_momentum_z": float(row["hourly_momentum_z"]),
                "hourly_vol_regime": str(row["hourly_vol_regime"]),
            }
        return features
    except Exception:
        return {}


def load_ml_entry_signal():
    """Load ML entry classifier predictions (walk-forward, no lookahead).
    Returns dict of date -> {ml_long_prob, ml_short_prob, ml_confidence}.
    """
    path = PROJECT_ROOT / "data" / "es" / "ml_entry_signal.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        signals = {}
        for _, row in df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            signals[d] = {
                "ml_long_prob": float(row["ml_long_prob"]),
                "ml_short_prob": float(row["ml_short_prob"]),
                "ml_confidence": float(row["ml_confidence"]),
            }
        return signals
    except Exception:
        return {}


def load_intraday_sentiment():
    """Load 15-min rolling sentiment from data/news/sentiment_intraday.csv
    (produced by tools/sentiment_intraday.py).

    Returns dict keyed by 15-min bucket (UTC datetime, floored to :00/:15/:30/:45)
    with sentiment_15m / sentiment_30m / sentiment_1h / sentiment_4h / sentiment_1d
    plus topic %.
    """
    path = PROJECT_ROOT / "data" / "news" / "sentiment_intraday.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        out = {}
        for _, row in df.iterrows():
            try:
                ts = pd.to_datetime(row["bucket_ts"], utc=True).to_pydatetime()
            except Exception:
                continue
            out[ts] = {
                "sentiment_15m": float(row.get("sentiment_15m", 0) or 0),
                "sentiment_30m": float(row.get("sentiment_30m", 0) or 0),
                "sentiment_1h":  float(row.get("sentiment_1h", 0)  or 0),
                "sentiment_4h":  float(row.get("sentiment_4h", 0)  or 0),
                "sentiment_1d":  float(row.get("sentiment_1d", 0)  or 0),
                "fed_topic_pct":       float(row.get("fed_topic_pct", 0)       or 0),
                "war_topic_pct":       float(row.get("war_topic_pct", 0)       or 0),
                "inflation_topic_pct": float(row.get("inflation_topic_pct", 0) or 0),
            }
        return out
    except Exception:
        return {}


def load_mag7_breadth():
    """Load MAG7 breadth snapshots from data/es/mag7_breadth.csv
    (produced by tools/mag7_breadth.py).

    Returns dict keyed by UTC datetime with breadth indicators per snapshot.
    """
    path = PROJECT_ROOT / "data" / "es" / "mag7_breadth.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        out = {}
        for _, row in df.iterrows():
            try:
                ts = pd.to_datetime(row["ts_utc"], utc=True).to_pydatetime()
            except Exception:
                continue
            out[ts] = {
                "pct_above_5d_ma":      float(row.get("pct_above_5d_ma", 0)  or 0),
                "pct_above_20d_ma":     float(row.get("pct_above_20d_ma", 0) or 0),
                "pct_above_50d_ma":     float(row.get("pct_above_50d_ma", 0) or 0),
                "mag7_market_chg":      float(row.get("mag7_market_chg", 0)  or 0),
                "breadth_momentum_15m": float(row.get("breadth_momentum_15m", 0) or 0),
            }
        return out
    except Exception:
        return {}


def load_polymarket_signals():
    """Load Polymarket prediction-market signals from data/es/polymarket_signals.csv
    (produced by tools/polymarket_signal.py).

    Returns dict keyed by UTC datetime with composite_es_signal + per-topic probs.
    """
    path = PROJECT_ROOT / "data" / "es" / "polymarket_signals.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        out = {}
        for _, row in df.iterrows():
            try:
                ts = pd.to_datetime(row["ts_utc"], utc=True).to_pydatetime()
            except Exception:
                continue
            out[ts] = {
                "composite_es_signal":     float(row.get("composite_es_signal", 0)    or 0),
                "fed_cut_prob_next":       float(row.get("fed_cut_prob_next", 0)      or 0),
                "fed_hike_prob_next":      float(row.get("fed_hike_prob_next", 0)     or 0),
                "recession_prob_12m":      float(row.get("recession_prob_12m", 0)     or 0),
                "iran_escalation_prob":    float(row.get("iran_escalation_prob", 0)   or 0),
                "ukraine_escalation_prob": float(row.get("ukraine_escalation_prob", 0) or 0),
                "fiscal_expansion_prob":   float(row.get("fiscal_expansion_prob", 0)  or 0),
                "shutdown_default_prob":   float(row.get("shutdown_default_prob", 0)  or 0),
            }
        return out
    except Exception:
        return {}


def _lookup_recent(d: dict, ts, max_lookback_min: int = 30):
    """Lookup most recent dict entry at or before ts (within max_lookback_min)."""
    if not d:
        return None
    import datetime as _dtl
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        # Assume UTC for naive timestamps coming from the bar
        ts = ts.replace(tzinfo=_dtl.timezone.utc)
    # Walk back in 1-min steps up to max_lookback_min, looking for matching key
    # (we expect 5/15-min cadence, so max 30 min lookback covers gaps)
    cutoff = ts - _dtl.timedelta(minutes=max_lookback_min)
    candidates = [(k, v) for k, v in d.items()
                  if isinstance(k, _dtl.datetime) and cutoff <= k <= ts]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def load_cusum_events():
    """Load CUSUM event filter signals.

    Returns a set of bar indices where CUSUM triggered, and direction dict.
    Replaces fixed cooldown with event-driven entry timing.
    """
    path = PROJECT_ROOT / "data" / "es" / "cusum_bar_lookup.csv"
    if not path.exists():
        return {}, {}
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        events = set()
        directions = {}
        for _, row in df.iterrows():
            if row["cusum_event"] == 1:
                ts = row["timestamp"]
                events.add(ts)
                directions[ts] = int(row["cusum_direction"])
        return events, directions
    except Exception:
        return {}, {}


def load_config(config_path=None):
    if config_path is None:
        config_path = Path(__file__).parent / "es_strategy_config.py"
    else:
        config_path = Path(config_path)
    spec = importlib.util.spec_from_file_location("es_strategy_config", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


def load_es_data(use_extended=None, config_path=None):
    """Load ES price data for backtesting.

    Args:
        use_extended: If True, use extended hourly dataset (SPY-converted gap + real ES).
                      If None, reads USE_EXTENDED_DATA from config.
        config_path: Optional path to config file. Defaults to es_strategy_config.py.
    """
    cfg = load_config(config_path)
    if use_extended is None:
        use_extended = getattr(cfg, "USE_EXTENDED_DATA", False)

    if use_extended:
        # Extended dataset: SPY hourly (Apr 2023 - Jan 2025) + ES hourly (Jan 2025+)
        ext_path = PROJECT_ROOT / "data" / "es" / "ES_combined_hourly_extended.parquet"
        if ext_path.exists():
            df = pd.read_parquet(ext_path).sort_index()
            # Strip timezone for consistency
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            has_range = (df["high"] - df["low"]) > 0
            has_volume = df["volume"] > 0
            df = df[has_range | has_volume].copy()
            return df

    # Default: 1-min ES data resampled to 5-min
    data_path = PROJECT_ROOT / "data" / "es" / "ES_1min.parquet"
    df = pd.read_parquet(data_path)
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    has_range = (df_5m["high"] - df_5m["low"]) > 0
    has_volume = df_5m["volume"] > 0
    df_5m = df_5m[has_range | has_volume].copy()
    if len(df_5m) < 5000:
        df_orig = pd.read_parquet(data_path)
        df_full = df_orig.resample("5min").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        df_5m = df_full.iloc[int(len(df_full) * 0.5):].copy()
    return df_5m


def load_es_data_4h():
    """Load ES data resampled to 4-hour bars for multi-timeframe mode."""
    data_path = PROJECT_ROOT / "data" / "es" / "ES_1min.parquet"
    if not data_path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(data_path)
    df_4h = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    has_range = (df_4h["high"] - df_4h["low"]) > 0
    df_4h = df_4h[has_range].copy()
    return df_4h


def _load_daily_csv(filename, value_col, date_col="date"):
    """Load a daily CSV from macro_2, return {date: value} dict for fast lookup."""
    path = MACRO_PATH / filename
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if date_col not in df.columns:
        date_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date", value_col])
    result = {}
    for _, row in df.iterrows():
        result[row["_date"].date()] = float(row[value_col])
    return result


def _load_ohlcv_csv(filename, prefix):
    """Load an OHLCV CSV from macro_2, return {date: {open, high, low, close, pct_change}} dict."""
    path = MACRO_PATH / filename
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    date_col = "date" if "date" in df.columns else df.columns[0]
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    close_col = f"{prefix}_close"
    if close_col not in df.columns:
        # Try without prefix
        for c in df.columns:
            if "close" in c.lower():
                close_col = c
                break
    if close_col not in df.columns:
        return {}
    df["_pct_change"] = df[close_col].astype(float).pct_change() * 100
    df["_sma5"] = df[close_col].astype(float).rolling(5).mean()
    result = {}
    for _, row in df.iterrows():
        d = row["_date"].date() if hasattr(row["_date"], "date") else row["_date"]
        result[d] = {
            "close": float(row[close_col]),
            "pct_change": float(row["_pct_change"]) if pd.notna(row["_pct_change"]) else 0.0,
            "sma5": float(row["_sma5"]) if pd.notna(row["_sma5"]) else float(row[close_col]),
        }
    return result


def load_macro_data():
    """Load all macro data into fast-lookup dicts."""
    return {
        "vix": _load_daily_csv("vix_move.csv", "vix"),
        "hy_oas": _load_daily_csv("hy_oas.csv", "hy_oas"),
        "dxy": _load_daily_csv("dxy.csv", "dxy"),
        "copper": _load_daily_csv("copper.csv", "copper_price"),
        "yield_10y": _load_daily_csv("10y_treasury_yield.csv", "10y_yield"),
        "yield_2y": _load_daily_csv("us_2y_yield.csv", "us_2y_yield"),
        "crude_oil": _load_ohlcv_csv("crude_oil_ohlcv.csv", "crude_oil"),
        "gold": _load_ohlcv_csv("gold_ohlcv.csv", "gold"),
        "cboe_skew": _load_daily_csv("cboe_skew.csv", "cboe_skew"),
    }


def _lookup_macro(macro_dict, date, lookback_days=5):
    """Look up macro value for date, with fallback to recent days."""
    import datetime as dt
    if not macro_dict:
        return None
    d = date.date() if hasattr(date, "date") else date
    for offset in range(lookback_days + 1):
        check = d - dt.timedelta(days=offset)
        if check in macro_dict:
            return macro_dict[check]
    return None


# ─── Technical indicator helpers ──────────────────────────────

def compute_rsi(prices, period):
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(len(prices) - period, len(prices))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def compute_atr(highs, lows, closes, period):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / period


def compute_sma(prices, period):
    if len(prices) < period:
        return None
    return sum(list(prices)[-period:]) / period


# ─── Strategy ─────────────────────────────────────────────────

class ESAutoResearchStrategy:
    """ES strategy with sequential regime classification.

    Step 1: Classify regime (BULLISH / BEARISH / SIDEWAYS) using:
            - Technical: SMA crossover, price vs 200 SMA
            - Macro: VIX tier
            - NLP: News sentiment regime signal
            - Digest: Newsletter context trend
    Step 2: Apply regime-specific parameters for entry/exit
    """

    def __init__(self, cfg, macro_data, nlp_regime=None, digest_ctx=None, daily_trend=None, daily_sentiment=None, garch_forecast=None, particle_regime=None, cusum_events=None, cusum_directions=None, tsfresh_signal=None, hourly_regime=None, ml_entry_signal=None, trade_only_dates=None, intraday_sentiment=None, mag7_breadth=None, polymarket_signals=None, macro_calendar=None):
        self.cfg = cfg
        self.macro = macro_data
        self.nlp_regime = nlp_regime or {"regime": "SIDEWAYS", "net_sentiment": 0.0, "confidence": 0.0}
        self.digest_ctx = digest_ctx or {"trend": "SIDEWAYS", "vix_tier": 2}
        self.daily_trend = daily_trend or {}
        self.daily_sentiment = daily_sentiment or {}
        self.garch_forecast = garch_forecast or {}
        self.particle_regime = particle_regime or {}
        self.cusum_events = cusum_events or set()
        self.cusum_directions = cusum_directions or {}
        self.tsfresh_signal = tsfresh_signal or {}
        self.hourly_regime = hourly_regime or {}
        self.ml_entry_signal = ml_entry_signal or {}
        self.trade_only_dates = trade_only_dates  # If set, only enter trades on these dates
        # Phase 4 multi-input feeds (default empty — gracefully no-op when feeds absent)
        self.intraday_sentiment = intraday_sentiment or {}
        self.mag7_breadth = mag7_breadth or {}
        self.polymarket_signals = polymarket_signals or {}
        self.macro_calendar = macro_calendar  # MacroCalendar instance or None
        self._cusum_last_event_bar = -999  # Track bars since last CUSUM event
        self._oil_shock_active = False
        self._skew_panic = False
        self._gold_riskoff = False
        self._mr_mode_active = False
        self._mr_max_hold = 24
        self._mr_rsi_exit = 60
        self._mr_rsi_short_exit = 40
        # Bar scaling: when using hourly data, divide bar-count params by scale factor
        self._bar_scale = getattr(cfg, "BAR_SCALE_FACTOR", 1) if getattr(cfg, "USE_EXTENDED_DATA", False) else 1
        buf_size = max(250, getattr(cfg, "SMA_200", 200) + 50, cfg.SMA_SLOW + 50)
        self.closes = deque(maxlen=buf_size)
        self.highs = deque(maxlen=buf_size)
        self.lows = deque(maxlen=buf_size)
        self.volumes = deque(maxlen=buf_size)

        self.bars_since_entry = 0
        self.bars_since_last_trade = self._scaled_bars(cfg.COOLDOWN_BARS) + 1
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None
        self.trailing_active = False
        self.risk_points = None
        self.current_side = None

        # Daily loss circuit breaker state
        self._current_date = None
        self._daily_pnl = 0.0
        self._daily_circuit_tripped = False
        self._equity_at_day_start = None

        # Adaptive cooldown state (win/loss streak)
        self._recent_results = []  # list of True (win) / False (loss)
        self._last_trade_pnl = 0.0

        # Consecutive loss circuit breaker
        self._consecutive_losses = 0
        self._loss_circuit_cooldown_remaining = 0

        # Exp 2: Max trades per day tracking
        self._trades_today = 0
        self._trades_today_date = None

        # Combined strategy: independent MR state (separate from composite)
        self._mr_bars_since_trade = 999  # MR's own cooldown counter
        self._mr_trades_today = 0         # MR's own daily trade counter
        self._mr_trades_today_date = None
        self._mr_consecutive_losses = 0   # MR's own loss streak
        self._mr_loss_cooldown = 0        # MR's own circuit breaker cooldown

    def _scaled_bars(self, bar_count):
        """Scale bar counts for hourly data (divide by BAR_SCALE_FACTOR)."""
        return max(1, int(bar_count / self._bar_scale))

    def _is_entry_allowed(self, timestamp):
        if hasattr(timestamp, "tz") and timestamp.tz is not None:
            ts_utc = timestamp.tz_convert("UTC")
            utc_hour = ts_utc.hour
            utc_min = ts_utc.minute
        else:
            utc_hour = timestamp.hour
            utc_min = timestamp.minute

        # Check Asia hours window
        if not (self.cfg.ENTRY_UTC_START <= utc_hour < self.cfg.ENTRY_UTC_END):
            return False

        # Avoid US cash open volatility (UTC 14:30-15:00 = CT 8:30-9:00)
        # This is when most quick stop-outs occur due to opening auction noise
        if getattr(self.cfg, "AVOID_US_OPEN", True):
            avoid_start_h = getattr(self.cfg, "AVOID_US_OPEN_START_H", 14)
            avoid_start_m = getattr(self.cfg, "AVOID_US_OPEN_START_M", 30)
            avoid_end_h = getattr(self.cfg, "AVOID_US_OPEN_END_H", 15)
            avoid_end_m = getattr(self.cfg, "AVOID_US_OPEN_END_M", 0)
            curr = utc_hour * 60 + utc_min
            start = avoid_start_h * 60 + avoid_start_m
            end = avoid_end_h * 60 + avoid_end_m
            if start <= curr < end:
                return False

        return True

    def _classify_regime(self, timestamp):
        """Classify market regime: BULLISH, BEARISH, or SIDEWAYS.

        Uses 5 signal sources:
        1. SMA crossover (technical)
        2. Price vs 200 SMA (technical)
        3. VIX tier (macro)
        4. NLP news sentiment regime (from news_sentiment_nlp.py)
        5. Digest newsletter context (from /digest_ES)
        """
        cfg = self.cfg
        sma_fast = compute_sma(list(self.closes), cfg.SMA_FAST)
        sma_slow = compute_sma(list(self.closes), cfg.SMA_SLOW)
        sma_200 = compute_sma(list(self.closes), getattr(cfg, "SMA_200", 200))

        # 1. SMA crossover signal
        sma_signal = 0
        if sma_fast is not None and sma_slow is not None:
            if sma_fast > sma_slow:
                sma_signal = 1
            elif sma_fast < sma_slow:
                sma_signal = -1

        # 2. Price vs 200 SMA
        price_signal = 0
        if sma_200 is not None and self.closes[-1] > 0:
            if self.closes[-1] > sma_200:
                price_signal = 1
            elif self.closes[-1] < sma_200:
                price_signal = -1

        # 3. VIX regime
        vix = _lookup_macro(self.macro.get("vix", {}), timestamp)
        vix_signal = 0
        if vix is not None:
            if vix < cfg.VIX_TIER_2:
                vix_signal = 1
            elif vix > cfg.VIX_TIER_4:
                vix_signal = -1

        # 4. NLP sentiment regime signal
        nlp_signal = 0
        nlp_conf = self.nlp_regime.get("confidence", 0)
        nlp_regime = self.nlp_regime.get("regime", "SIDEWAYS")
        if nlp_conf > 0.3:  # Only use if confidence is meaningful
            if nlp_regime == "BULLISH":
                nlp_signal = 1
            elif nlp_regime == "BEARISH":
                nlp_signal = -1

        # 5. Digest newsletter context
        digest_signal = 0
        digest_trend = self.digest_ctx.get("trend", "SIDEWAYS")
        if digest_trend == "BULLISH":
            digest_signal = 1
        elif digest_trend == "BEARISH":
            digest_signal = -1

        # 6. Daily trend overlay (from ES_daily.parquet)
        daily_signal = 0
        import datetime as _dt
        d = timestamp.date() if hasattr(timestamp, "date") else timestamp
        if isinstance(d, _dt.datetime):
            d = d.date()
        daily = self.daily_trend.get(d)
        if daily is None:
            # Try previous day
            for offset in range(1, 5):
                prev = d - _dt.timedelta(days=offset)
                daily = self.daily_trend.get(prev)
                if daily:
                    break
        if daily:
            daily_signal = daily["trend"]  # -1, 0, or 1

        # 7. Particle filter regime (Bayesian SMC — smooth regime probabilities)
        pf_signal = 0
        pf_confidence = 0.0
        if self.particle_regime and getattr(cfg, "PARTICLE_REGIME_ENABLED", False):
            import datetime as _dtpf
            pf_d = timestamp.date() if hasattr(timestamp, "date") else timestamp
            if isinstance(pf_d, _dtpf.datetime):
                pf_d = pf_d.date()
            pf_data = self.particle_regime.get(pf_d)
            if pf_data is None:
                for off in range(1, 5):
                    pf_data = self.particle_regime.get(pf_d - _dtpf.timedelta(days=off))
                    if pf_data:
                        break
            if pf_data:
                pf_confidence = pf_data["confidence"]
                if pf_data["regime"] == "BULLISH":
                    pf_signal = 1
                elif pf_data["regime"] == "BEARISH":
                    pf_signal = -1

        # 8. Hourly regime overlay (from 3yr hourly features)
        hourly_signal = 0
        hourly_conf = 0.5  # Default confidence
        if self.hourly_regime:
            import datetime as _dthr
            hr_d = timestamp.date() if hasattr(timestamp, "date") else timestamp
            if isinstance(hr_d, _dthr.datetime):
                hr_d = hr_d.date()
            # Use PREVIOUS day's hourly regime (no lookahead)
            hr_data = None
            for off in range(1, 5):
                hr_data = self.hourly_regime.get(hr_d - _dthr.timedelta(days=off))
                if hr_data:
                    break
            if hr_data:
                hourly_signal = hr_data["hourly_trend"]
                # Scale confidence by momentum z-score magnitude
                hourly_conf = min(1.0, abs(hr_data.get("hourly_momentum_z", 0)) / 2.0 + 0.3)

        # Weighted composite (6-8 sources)
        nlp_weight = getattr(cfg, "REGIME_NLP_WEIGHT", 0.15)
        digest_weight = getattr(cfg, "REGIME_DIGEST_WEIGHT", 0.10)
        daily_weight = getattr(cfg, "REGIME_DAILY_TREND_WEIGHT", 0.20)
        pf_weight = getattr(cfg, "REGIME_PARTICLE_WEIGHT", 0.0)
        hourly_weight = getattr(cfg, "REGIME_HOURLY_WEIGHT", 0.0)

        w = cfg.REGIME_SMA_CROSS_WEIGHT * sma_signal \
            + cfg.REGIME_PRICE_VS_200_WEIGHT * price_signal \
            + cfg.REGIME_VIX_WEIGHT * vix_signal \
            + nlp_weight * nlp_signal \
            + digest_weight * digest_signal \
            + daily_weight * daily_signal \
            + pf_weight * pf_signal * pf_confidence \
            + hourly_weight * hourly_signal * hourly_conf

        if w > 0.2:
            return "BULLISH"
        elif w < -0.2:
            return "BEARISH"
        else:
            return "SIDEWAYS"

    def _is_correction_active(self, timestamp):
        """Detect if a correction is underway within a BULL regime.

        A correction is detected when:
        - Price drops below SMA_FAST (short-term trend broken)
        - AND either VIX is elevated (>= tier 3) or NLP/digest is bearish
        This allows the BULL regime to take defensive SHORT positions.
        """
        cfg = self.cfg
        sma_fast = compute_sma(list(self.closes), cfg.SMA_FAST)
        if sma_fast is None:
            return False

        price_below_fast = self.closes[-1] < sma_fast

        if not price_below_fast:
            return False

        # Check additional confirmation: VIX elevated or NLP/digest bearish
        vix = _lookup_macro(self.macro.get("vix", {}), timestamp)
        vix_elevated = vix is not None and vix >= cfg.VIX_TIER_3

        nlp_bearish = self.nlp_regime.get("regime") == "BEARISH" and self.nlp_regime.get("confidence", 0) > 0.3
        digest_bearish = self.digest_ctx.get("trend") == "BEARISH"

        return vix_elevated or nlp_bearish or digest_bearish

    def _get_regime_params(self, regime):
        """Get regime-specific parameters.

        BULL regime can switch to defensive (SHORT) mode during corrections.
        """
        cfg = self.cfg
        if regime == "BULLISH":
            return {
                "allowed_side": getattr(cfg, "BULL_SIDE", "LONG"),
                "rsi_oversold": cfg.BULL_RSI_OVERSOLD,
                "rsi_overbought": cfg.BULL_RSI_OVERBOUGHT,
                "composite_threshold": cfg.BULL_COMPOSITE_THRESHOLD,
                "stop_atr_mult": cfg.BULL_STOP_ATR_MULT,
                "tp_atr_mult": cfg.BULL_TP_ATR_MULT,
                "trailing_start_r": cfg.BULL_TRAILING_START_R,
                "trailing_atr_mult": cfg.BULL_TRAILING_ATR_MULT,
                "max_hold_bars": cfg.BULL_MAX_HOLD_BARS,
                "risk_mult": cfg.BULL_RISK_MULT,
                "w_rsi": cfg.BULL_WEIGHT_RSI,
                "w_trend": cfg.BULL_WEIGHT_TREND,
                "w_momentum": cfg.BULL_WEIGHT_MOMENTUM,
                "w_bb": cfg.BULL_WEIGHT_BB,
                "w_vix": cfg.BULL_WEIGHT_VIX,
                "w_macro": cfg.BULL_WEIGHT_MACRO,
                "w_sentiment": getattr(cfg, "BULL_WEIGHT_SENTIMENT", 0.15),
            }
        elif regime == "BEARISH":
            return {
                "allowed_side": getattr(cfg, "BEAR_SIDE", "SHORT"),
                "rsi_oversold": cfg.BEAR_RSI_OVERSOLD,
                "rsi_overbought": cfg.BEAR_RSI_OVERBOUGHT,
                "composite_threshold": cfg.BEAR_COMPOSITE_THRESHOLD,
                "stop_atr_mult": cfg.BEAR_STOP_ATR_MULT,
                "tp_atr_mult": cfg.BEAR_TP_ATR_MULT,
                "trailing_start_r": cfg.BEAR_TRAILING_START_R,
                "trailing_atr_mult": cfg.BEAR_TRAILING_ATR_MULT,
                "max_hold_bars": cfg.BEAR_MAX_HOLD_BARS,
                "risk_mult": cfg.BEAR_RISK_MULT,
                "w_rsi": cfg.BEAR_WEIGHT_RSI,
                "w_trend": cfg.BEAR_WEIGHT_TREND,
                "w_momentum": cfg.BEAR_WEIGHT_MOMENTUM,
                "w_bb": cfg.BEAR_WEIGHT_BB,
                "w_vix": cfg.BEAR_WEIGHT_VIX,
                "w_macro": cfg.BEAR_WEIGHT_MACRO,
                "w_sentiment": getattr(cfg, "BEAR_WEIGHT_SENTIMENT", 0.10),
            }
        else:  # SIDEWAYS
            return {
                "allowed_side": getattr(cfg, "SIDE_SIDE", "BOTH"),
                "rsi_oversold": cfg.SIDE_RSI_OVERSOLD,
                "rsi_overbought": cfg.SIDE_RSI_OVERBOUGHT,
                "composite_threshold": cfg.SIDE_COMPOSITE_THRESHOLD,
                "stop_atr_mult": cfg.SIDE_STOP_ATR_MULT,
                "tp_atr_mult": cfg.SIDE_TP_ATR_MULT,
                "trailing_start_r": cfg.SIDE_TRAILING_START_R,
                "trailing_atr_mult": cfg.SIDE_TRAILING_ATR_MULT,
                "max_hold_bars": cfg.SIDE_MAX_HOLD_BARS,
                "risk_mult": cfg.SIDE_RISK_MULT,
                "w_rsi": cfg.SIDE_WEIGHT_RSI,
                "w_trend": cfg.SIDE_WEIGHT_TREND,
                "w_momentum": cfg.SIDE_WEIGHT_MOMENTUM,
                "w_bb": cfg.SIDE_WEIGHT_BB,
                "w_vix": cfg.SIDE_WEIGHT_VIX,
                "w_macro": cfg.SIDE_WEIGHT_MACRO,
                "w_sentiment": getattr(cfg, "SIDE_WEIGHT_SENTIMENT", 0.10),
            }

    def _get_vix_tier(self, vix):
        if vix is None:
            return 2, "normal"
        cfg = self.cfg
        if vix < cfg.VIX_TIER_1:
            return 1, "complacency"
        elif vix < cfg.VIX_TIER_2:
            return 2, "normal"
        elif vix < cfg.VIX_TIER_3:
            return 3, "elevated"
        elif vix < cfg.VIX_TIER_4:
            return 4, "riskoff"
        elif vix < cfg.VIX_TIER_5:
            return 5, "opportunity"
        elif vix < cfg.VIX_TIER_6:
            return 6, "career"
        return 7, "homerun"

    def _get_vix_model_override(self, timestamp):
        """VIX Model Switching: return override params based on VIX level."""
        cfg = self.cfg
        if not getattr(cfg, "VIX_MODEL_SWITCH_ENABLED", False):
            return None
        import datetime as _dtvm
        d = timestamp.date() if hasattr(timestamp, "date") else timestamp
        if isinstance(d, _dtvm.datetime):
            d = d.date()
        vix = _lookup_macro(self.macro.get("vix", {}), d)
        if vix is None:
            return None
        low_thresh = getattr(cfg, "VIX_MODEL_LOW_THRESHOLD", 20.0)
        high_thresh = getattr(cfg, "VIX_MODEL_HIGH_THRESHOLD", 30.0)
        if vix < low_thresh:
            prefix = "VLOW"
        elif vix > high_thresh:
            prefix = "VHIGH"
        else:
            prefix = "VMED"
        return {
            "composite_threshold": getattr(cfg, f"{prefix}_COMPOSITE_THRESHOLD", 0.40),
            "stop_atr_mult": getattr(cfg, f"{prefix}_STOP_ATR_MULT", 2.0),
            "tp_atr_mult": getattr(cfg, f"{prefix}_TP_ATR_MULT", 2.0),
            "max_hold_bars": getattr(cfg, f"{prefix}_MAX_HOLD_BARS", 288),
            "risk_mult": getattr(cfg, f"{prefix}_RISK_MULT", 0.4),
            "allowed_side": getattr(cfg, f"{prefix}_ALLOWED_SIDE", "BOTH"),
            "cooldown_bars": getattr(cfg, f"{prefix}_COOLDOWN_BARS", 96),
            "w_rsi": getattr(cfg, f"{prefix}_WEIGHT_RSI", 0.15),
            "w_trend": getattr(cfg, f"{prefix}_WEIGHT_TREND", 0.20),
            "w_momentum": getattr(cfg, f"{prefix}_WEIGHT_MOMENTUM", 0.13),
            "w_bb": getattr(cfg, f"{prefix}_WEIGHT_BB", 0.10),
            "w_vix": getattr(cfg, f"{prefix}_WEIGHT_VIX", 0.10),
            "w_macro": getattr(cfg, f"{prefix}_WEIGHT_MACRO", 0.10),
        }

    def _compute_adaptive_max_hold(self, bar, rp):
        """Adaptive hold period based on ATR regime + VIX level."""
        cfg = self.cfg
        base_hold = self._scaled_bars(rp["max_hold_bars"])

        if not getattr(cfg, "ADAPTIVE_HOLD_ENABLED", False):
            return base_hold

        import datetime as _dtah
        ah_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
        if isinstance(ah_date, _dtah.datetime):
            ah_date = ah_date.date()

        daily = self.daily_trend.get(ah_date)
        if daily is None:
            for off in range(1, 5):
                daily = self.daily_trend.get(ah_date - _dtah.timedelta(days=off))
                if daily:
                    break

        max_hold = base_hold

        # 1. ATR regime scaling
        if daily and daily.get("daily_atr") and daily.get("close", 0) > 0:
            atr_pct = daily["daily_atr"] / daily["close"] * 100
            low_atr = getattr(cfg, "ADAPTIVE_HOLD_LOW_ATR_PCT", 1.0)
            high_atr = getattr(cfg, "ADAPTIVE_HOLD_HIGH_ATR_PCT", 2.0)
            if atr_pct < low_atr:
                max_hold = int(base_hold * getattr(cfg, "ADAPTIVE_HOLD_LOW_ATR_MULT", 1.5))
            elif atr_pct > high_atr:
                max_hold = int(base_hold * getattr(cfg, "ADAPTIVE_HOLD_HIGH_ATR_MULT", 0.3))

            # 2. Swing/Scalp mode detection
            swing_thresh = getattr(cfg, "ADAPTIVE_HOLD_SWING_ATR_PCT", 1.0)
            scalp_thresh = getattr(cfg, "ADAPTIVE_HOLD_SCALP_ATR_PCT", 2.0)
            if atr_pct < swing_thresh:
                max_hold = max(max_hold, self._scaled_bars(144))  # At least 12h in swing
            elif atr_pct > scalp_thresh:
                scalp_max = self._scaled_bars(getattr(cfg, "ADAPTIVE_HOLD_SCALP_MAX", 48))
                max_hold = min(max_hold, scalp_max)

        # 3. VIX-based hold cap
        vix = _lookup_macro(self.macro.get("vix", {}), ah_date)
        if vix is not None:
            vix_low = getattr(cfg, "VIX_MODEL_LOW_THRESHOLD", 20.0)
            vix_high = getattr(cfg, "VIX_MODEL_HIGH_THRESHOLD", 30.0)
            if vix < vix_low:
                vix_cap = self._scaled_bars(getattr(cfg, "ADAPTIVE_HOLD_VIX_LOW_MAX", 576))
            elif vix > vix_high:
                vix_cap = self._scaled_bars(getattr(cfg, "ADAPTIVE_HOLD_VIX_HIGH_MAX", 48))
            else:
                vix_cap = self._scaled_bars(getattr(cfg, "ADAPTIVE_HOLD_VIX_MED_MAX", 288))
            max_hold = min(max_hold, vix_cap)

        return max(self._scaled_bars(getattr(cfg, "MIN_HOLD_BARS", 24)), max_hold)

    def _compute_vix_score(self, side, vix):
        """VIX-based scoring incorporating mean-reversion framework.

        Key insight: VIX is mean-reverting. Natural state is below 20.
        - VIX > 30: Almost always buy dips (spikes are temporary)
        - VIX < 16: Charm/vanna flows exhausted, no more dealer buying pressure
        - VIX 16-20: Normal, supportive for longs
        """
        cfg = self.cfg
        tier, _ = self._get_vix_tier(vix)
        score, boost = 0.0, 0.0
        if side == "LONG":
            if tier == 1:
                score = 0.1       # VIX<16: charm/vanna exhausted — poor for longs
            elif tier == 2:
                score, boost = 0.6, cfg.VIX_NORMAL_LONG_BOOST  # Normal: supportive
            elif tier == 3:
                score = 0.3       # Elevated: cautious
            elif tier == 4:
                score, boost = 0.8, cfg.VIX_OPPORTUNITY_LONG_BOOST  # VIX>30: buy dips!
            elif tier >= 5:
                # VIX 40-50+: career/homerun dip-buy — max conviction
                boosts = [cfg.VIX_OPPORTUNITY_LONG_BOOST, cfg.VIX_CAREER_LONG_BOOST,
                          cfg.VIX_HOMERUN_LONG_BOOST]
                score, boost = 1.0, boosts[min(tier - 5, 2)]
        else:  # SHORT
            if tier == 1:
                score, boost = 0.8, cfg.VIX_COMPLACENCY_SHORT_BOOST  # Charm exhausted
            elif tier == 2:
                score = 0.3       # Normal: don't fight the trend
            elif tier == 3:
                score, boost = 0.5, cfg.VIX_ELEVATED_SHORT_BOOST  # Cautious short
            elif tier == 4:
                score = 0.1       # VIX>30: DON'T short — dip-buy zone
                boost = cfg.VIX_RISKOFF_SHORT_BOOST  # Should be 0 or very small
            elif tier >= 5:
                score = 0.0       # VIX 40+: absolutely no shorts — buy the panic
        return score, boost

    def _compute_macro_score(self, side, timestamp):
        cfg = self.cfg
        ts = pd.Timestamp(timestamp)
        score, boost, components = 0.0, 0.0, 0

        hy_oas = _lookup_macro(self.macro.get("hy_oas", {}), ts)
        if hy_oas is not None:
            components += 1
            if side == "LONG" and hy_oas < cfg.HY_OAS_NORMAL:
                score += 0.7; boost += cfg.CREDIT_TIGHTENING_LONG_BOOST
            elif side == "LONG" and hy_oas < cfg.HY_OAS_ELEVATED:
                score += 0.4
            elif side == "SHORT" and hy_oas > cfg.HY_OAS_STRESSED:
                score += 0.8; boost += cfg.CREDIT_WIDENING_SHORT_BOOST
            elif side == "SHORT" and hy_oas > cfg.HY_OAS_ELEVATED:
                score += 0.5

        y10 = _lookup_macro(self.macro.get("yield_10y", {}), ts)
        y2 = _lookup_macro(self.macro.get("yield_2y", {}), ts)
        if y10 is not None and y2 is not None:
            components += 1
            spread = y10 - y2
            if side == "SHORT" and spread < 0:
                score += 0.6; boost += cfg.YIELD_CURVE_INVERTED_SHORT_BOOST
            elif side == "LONG" and spread > 0.5:
                score += 0.6; boost += cfg.YIELD_CURVE_STEEP_LONG_BOOST
            elif side == "LONG" and spread > 0:
                score += 0.4

        dxy = _lookup_macro(self.macro.get("dxy", {}), ts)
        if dxy is not None:
            components += 1
            if side == "SHORT" and dxy > cfg.DXY_STRONG_THRESHOLD:
                score += 0.6; boost += cfg.DXY_STRONG_SHORT_BOOST
            elif side == "LONG" and dxy < cfg.DXY_WEAK_THRESHOLD:
                score += 0.6; boost += cfg.DXY_WEAK_LONG_BOOST
            elif side == "LONG" and dxy < cfg.DXY_STRONG_THRESHOLD:
                score += 0.3

        copper = _lookup_macro(self.macro.get("copper", {}), ts)
        if copper is not None:
            components += 1
            import datetime as dt
            d = ts.date() if hasattr(ts, "date") else ts
            copper_prev = None
            for offset in range(cfg.COPPER_MOMENTUM_LOOKBACK, cfg.COPPER_MOMENTUM_LOOKBACK + 10):
                check = d - dt.timedelta(days=offset)
                if check in self.macro.get("copper", {}):
                    copper_prev = self.macro["copper"][check]
                    break
            if copper_prev and copper_prev > 0:
                copper_chg = (copper - copper_prev) / copper_prev * 100
                if side == "LONG" and copper_chg > 0:
                    score += 0.6; boost += cfg.COPPER_RISING_LONG_BOOST
                elif side == "SHORT" and copper_chg < -2:
                    score += 0.6; boost += cfg.COPPER_FALLING_SHORT_BOOST

        if components > 0:
            score = score / components
        return min(1.0, score), boost

    def _compute_cta_proxy(self, side):
        cfg = self.cfg
        sma200 = compute_sma(list(self.closes), getattr(cfg, "SMA_200", 200))
        if sma200 is None or sma200 == 0:
            return 0.0
        pct = (self.closes[-1] - sma200) / sma200 * 100
        if side == "LONG" and pct < cfg.CTA_BUY_POTENTIAL_PCT:
            return cfg.CTA_BUY_POTENTIAL_LONG_BOOST
        elif side == "SHORT" and pct > cfg.CTA_FULL_DEPLOY_PCT:
            return cfg.CTA_FULL_DEPLOY_SHORT_BOOST
        return 0.0

    def _compute_composite(self, side, timestamp, rp):
        """Composite score using regime-specific weights."""
        cfg = self.cfg
        score = 0.0

        # RSI
        rsi = compute_rsi(list(self.closes), cfg.RSI_PERIOD)
        rsi_fast = compute_rsi(list(self.closes), cfg.RSI_FAST_PERIOD)
        rsi_score = 0.0
        if rsi is not None:
            if side == "LONG":
                if rsi < rp["rsi_oversold"]: rsi_score = 1.0
                elif rsi < 45: rsi_score = (45 - rsi) / max(1, 45 - rp["rsi_oversold"])
            else:
                if rsi > rp["rsi_overbought"]: rsi_score = 1.0
                elif rsi > 55: rsi_score = (rsi - 55) / max(1, rp["rsi_overbought"] - 55)
            if rsi_fast is not None:
                if side == "LONG" and rsi_fast < cfg.RSI_FAST_OVERSOLD:
                    rsi_score = min(1.0, rsi_score + 0.3)
                elif side == "SHORT" and rsi_fast > cfg.RSI_FAST_OVERBOUGHT:
                    rsi_score = min(1.0, rsi_score + 0.3)
        score += rp["w_rsi"] * rsi_score

        # Trend
        sma_fast = compute_sma(list(self.closes), cfg.SMA_FAST)
        sma_slow = compute_sma(list(self.closes), cfg.SMA_SLOW)
        trend_score = 0.0
        if sma_fast is not None and sma_slow is not None and sma_slow > 0:
            if side == "LONG" and sma_fast > sma_slow:
                trend_score = min(1.0, (sma_fast - sma_slow) / sma_slow * 200)
            elif side == "SHORT" and sma_fast < sma_slow:
                trend_score = min(1.0, (sma_slow - sma_fast) / sma_slow * 200)
        score += rp["w_trend"] * trend_score

        # Momentum
        momentum_score = 0.0
        if len(self.closes) >= 12:
            pct_chg = (self.closes[-1] - self.closes[-12]) / self.closes[-12] * 100
            if side == "LONG" and pct_chg > 0:
                momentum_score = min(1.0, pct_chg / 0.5)
            elif side == "SHORT" and pct_chg < 0:
                momentum_score = min(1.0, abs(pct_chg) / 0.5)
        score += rp["w_momentum"] * momentum_score

        # Bollinger Bands
        bb_score = 0.0
        if len(self.closes) >= cfg.BB_PERIOD:
            prices = list(self.closes)
            bb_sma = sum(prices[-cfg.BB_PERIOD:]) / cfg.BB_PERIOD
            var = sum((p - bb_sma) ** 2 for p in prices[-cfg.BB_PERIOD:]) / cfg.BB_PERIOD
            std = var ** 0.5
            if std > 0:
                upper = bb_sma + cfg.BB_STD * std
                lower = bb_sma - cfg.BB_STD * std
                px = self.closes[-1]
                if side == "LONG" and px < lower: bb_score = 1.0
                elif side == "LONG" and px < bb_sma and bb_sma != lower:
                    bb_score = max(0, (bb_sma - px) / (bb_sma - lower))
                elif side == "SHORT" and px > upper: bb_score = 1.0
                elif side == "SHORT" and px > bb_sma and upper != bb_sma:
                    bb_score = max(0, (px - bb_sma) / (upper - bb_sma))
        score += rp["w_bb"] * bb_score

        # Volume confirmation signal
        vol_score = 0.0
        vol_weight = getattr(cfg, "VOLUME_SIGNAL_WEIGHT", 0.10)
        vol_lookback = getattr(cfg, "VOLUME_AVG_LOOKBACK", 20)
        if len(self.volumes) >= vol_lookback:
            vol_list = list(self.volumes)
            avg_vol = sum(vol_list[-vol_lookback:]) / vol_lookback
            current_vol = vol_list[-1] if vol_list[-1] > 0 else 0
            if avg_vol > 0 and current_vol > 0:
                vol_ratio = current_vol / avg_vol
                vol_surge_thresh = getattr(cfg, "VOLUME_SURGE_THRESHOLD", 1.5)
                vol_dry_thresh = getattr(cfg, "VOLUME_DRY_THRESHOLD", 0.5)
                if vol_ratio >= vol_surge_thresh:
                    # High volume confirms conviction — boost entry
                    vol_score = min(1.0, (vol_ratio - 1.0) / 2.0)
                elif vol_ratio <= vol_dry_thresh:
                    # Low volume = no conviction — penalize entry
                    vol_score = -0.5
        score += vol_weight * vol_score

        # VIX
        vix = _lookup_macro(self.macro.get("vix", {}), timestamp)
        vix_score, vix_boost = self._compute_vix_score(side, vix)
        score += rp["w_vix"] * vix_score + vix_boost

        # Macro
        macro_score, macro_boost = self._compute_macro_score(side, timestamp)
        score += rp["w_macro"] * macro_score + macro_boost

        # CTA
        score += self._compute_cta_proxy(side)

        # NLP sentiment boost (from news_sentiment_nlp.py analysis)
        nlp_sent = self.nlp_regime.get("net_sentiment", 0)
        nlp_conf = self.nlp_regime.get("confidence", 0)
        nlp_boost_weight = getattr(cfg, "NLP_SENTIMENT_BOOST", 0.10)
        if nlp_conf > 0.3:
            if side == "LONG" and nlp_sent > 0.1:
                score += nlp_boost_weight * min(1.0, nlp_sent * 2)
            elif side == "SHORT" and nlp_sent < -0.1:
                score += nlp_boost_weight * min(1.0, abs(nlp_sent) * 2)

        # Digest context boost (from /digest_ES newsletter analysis)
        digest_trend = self.digest_ctx.get("trend", "SIDEWAYS")
        digest_boost_weight = getattr(cfg, "DIGEST_CONTEXT_BOOST", 0.05)
        if side == "LONG" and digest_trend == "BULLISH":
            score += digest_boost_weight
        elif side == "SHORT" and digest_trend == "BEARISH":
            score += digest_boost_weight

        # Daily trend boost (from ES_daily.parquet trend overlay)
        import datetime as _dt
        d = timestamp.date() if hasattr(timestamp, "date") else timestamp
        if isinstance(d, _dt.datetime):
            d = d.date()
        daily = self.daily_trend.get(d)
        if daily is None:
            for offset in range(1, 5):
                prev = d - _dt.timedelta(days=offset)
                daily = self.daily_trend.get(prev)
                if daily:
                    break
        if daily:
            daily_boost = getattr(cfg, "DAILY_TREND_BOOST", 0.10)
            daily_t = daily["trend"]
            if side == "LONG" and daily_t == 1:
                score += daily_boost
            elif side == "SHORT" and daily_t == -1:
                score += daily_boost
            # Penalty for trading against the daily trend
            daily_penalty = getattr(cfg, "DAILY_COUNTER_TREND_PENALTY", 0.05)
            if side == "LONG" and daily_t == -1:
                score -= daily_penalty
            elif side == "SHORT" and daily_t == 1:
                score -= daily_penalty

            # Daily RSI as direct entry signal
            daily_rsi = daily.get("daily_rsi")
            if daily_rsi is not None:
                daily_rsi_weight = getattr(cfg, "DAILY_RSI_WEIGHT", 0.10)
                daily_rsi_os = getattr(cfg, "DAILY_RSI_OVERSOLD", 35)
                daily_rsi_ob = getattr(cfg, "DAILY_RSI_OVERBOUGHT", 65)
                daily_rsi_score = 0.0
                if side == "LONG":
                    if daily_rsi < daily_rsi_os:
                        daily_rsi_score = 1.0  # Oversold on daily = strong buy
                    elif daily_rsi < 50:
                        daily_rsi_score = (50 - daily_rsi) / max(1, 50 - daily_rsi_os)
                else:  # SHORT
                    if daily_rsi > daily_rsi_ob:
                        daily_rsi_score = 1.0  # Overbought on daily = strong sell
                    elif daily_rsi > 50:
                        daily_rsi_score = (daily_rsi - 50) / max(1, daily_rsi_ob - 50)
                score += daily_rsi_weight * daily_rsi_score

            # Daily ATR-based volatility scaling
            # Higher daily ATR = more volatile = widen entry threshold (be more selective)
            # Lower daily ATR = calmer = tighter entry threshold (more trades)
            daily_atr = daily.get("daily_atr")
            if daily_atr is not None and daily.get("close", 0) > 0:
                atr_pct = daily_atr / daily["close"] * 100  # ATR as % of price
                atr_vol_adj = getattr(cfg, "DAILY_ATR_VOL_ADJUST", 0.05)
                # Low vol (ATR < 1%) = slight boost; High vol (ATR > 2%) = slight penalty
                if atr_pct < 1.0:
                    score += atr_vol_adj  # Calm market, easier to trade
                elif atr_pct > 2.5:
                    score -= atr_vol_adj  # Very volatile, be more selective

        # WSJ + DJ-N daily sentiment signal (from daily_sentiment.csv)
        import datetime as _dt2
        d2 = timestamp.date() if hasattr(timestamp, "date") else timestamp
        if isinstance(d2, _dt2.datetime):
            d2 = d2.date()
        sent_val = self.daily_sentiment.get(d2)
        if sent_val is None:
            # Look back up to 3 days for nearest sentiment
            for offset in range(1, 4):
                prev = d2 - _dt2.timedelta(days=offset)
                sent_val = self.daily_sentiment.get(prev)
                if sent_val is not None:
                    break
        if sent_val is not None and sent_val != 0.0:
            w_sent = rp.get("w_sentiment", getattr(cfg, "SENTIMENT_SIGNAL_WEIGHT", 0.15))

            sent_score = 0.0
            if side == "LONG" and sent_val > 0:
                sent_score = min(1.0, sent_val * 2)  # Scale up: 0.5 sentiment -> 1.0 score
            elif side == "SHORT" and sent_val < 0:
                sent_score = min(1.0, abs(sent_val) * 2)
            elif side == "LONG" and sent_val < -0.2:
                sent_score = -0.3  # Penalize longs when sentiment is clearly bearish
            elif side == "SHORT" and sent_val > 0.2:
                sent_score = -0.3  # Penalize shorts when sentiment is clearly bullish
            score += w_sent * sent_score

        # tsfresh composite signal (data-driven features: FFT, volume change, range mass, var coeff)
        tsfresh_weight = getattr(cfg, "TSFRESH_SIGNAL_WEIGHT", 0.0)
        if tsfresh_weight > 0 and self.tsfresh_signal:
            import datetime as _dttf
            tf_d = timestamp.date() if hasattr(timestamp, "date") else timestamp
            if isinstance(tf_d, _dttf.datetime):
                tf_d = tf_d.date()
            tf_val = self.tsfresh_signal.get(tf_d)
            if tf_val is None:
                for off in range(1, 5):
                    tf_val = self.tsfresh_signal.get(tf_d - _dttf.timedelta(days=off))
                    if tf_val is not None:
                        break
            if tf_val is not None:
                # Positive composite = bullish features, negative = bearish
                tf_score = 0.0
                if side == "LONG" and tf_val > 0:
                    tf_score = min(1.0, tf_val)  # z-score, typically 0-2
                elif side == "SHORT" and tf_val < 0:
                    tf_score = min(1.0, abs(tf_val))
                elif side == "LONG" and tf_val < -0.5:
                    tf_score = -0.3  # Penalize longs when features are bearish
                elif side == "SHORT" and tf_val > 0.5:
                    tf_score = -0.3  # Penalize shorts when features are bullish
                score += tsfresh_weight * tf_score

        # Hourly regime overlay (3yr hourly features — vol regime + momentum alignment)
        hourly_vol_adj = getattr(cfg, "HOURLY_VOL_REGIME_ADJUST", 0.0)
        hourly_mom_boost = getattr(cfg, "HOURLY_MOMENTUM_ENTRY_BOOST", 0.0)
        if (hourly_vol_adj > 0 or hourly_mom_boost > 0) and self.hourly_regime:
            import datetime as _dthr2
            hr_d2 = timestamp.date() if hasattr(timestamp, "date") else timestamp
            if isinstance(hr_d2, _dthr2.datetime):
                hr_d2 = hr_d2.date()
            hr_data2 = None
            for off in range(1, 5):
                hr_data2 = self.hourly_regime.get(hr_d2 - _dthr2.timedelta(days=off))
                if hr_data2:
                    break
            if hr_data2:
                # Vol regime: calm market = easier entries, high vol = more selective
                if hourly_vol_adj > 0:
                    if hr_data2["hourly_vol_regime"] == "low":
                        score += hourly_vol_adj
                    elif hr_data2["hourly_vol_regime"] == "high":
                        score -= hourly_vol_adj
                # Momentum alignment: boost when hourly momentum aligns with trade direction
                if hourly_mom_boost > 0:
                    mom_z = hr_data2.get("hourly_momentum_z", 0)
                    if side == "LONG" and mom_z > 0.5:
                        score += hourly_mom_boost * min(1.0, mom_z / 2.0)
                    elif side == "SHORT" and mom_z < -0.5:
                        score += hourly_mom_boost * min(1.0, abs(mom_z) / 2.0)

        # ML entry classifier signal (walk-forward trained, no lookahead)
        ml_weight = getattr(cfg, "ML_ENTRY_SIGNAL_WEIGHT", 0.0)
        if ml_weight > 0 and self.ml_entry_signal:
            import datetime as _dtml
            ml_d = timestamp.date() if hasattr(timestamp, "date") else timestamp
            if isinstance(ml_d, _dtml.datetime):
                ml_d = ml_d.date()
            ml_val = self.ml_entry_signal.get(ml_d)
            if ml_val is None:
                for off in range(1, 5):
                    ml_val = self.ml_entry_signal.get(ml_d - _dtml.timedelta(days=off))
                    if ml_val is not None:
                        break
            if ml_val is not None:
                ml_conf = ml_val["ml_confidence"]
                ml_conf_gate = getattr(cfg, "ML_ENTRY_CONFIDENCE_GATE", 0.1)
                if ml_conf >= ml_conf_gate:
                    if side == "LONG":
                        ml_score = max(0.0, (ml_val["ml_long_prob"] - 0.5) * 2)
                    else:
                        ml_score = max(0.0, (ml_val["ml_short_prob"] - 0.5) * 2)
                    score += ml_weight * ml_score

        # ─── PHASE 4: Intraday sentiment (15-min rolling) ──────────────
        if getattr(cfg, "INTRADAY_SENTIMENT_ENABLED", False) and self.intraday_sentiment:
            window_col = "sentiment_" + getattr(cfg, "INTRADAY_SENTIMENT_WINDOW", "15m")
            isent_w = getattr(cfg, "INTRADAY_SENTIMENT_WEIGHT", 0.0)
            isent_thresh = getattr(cfg, "INTRADAY_SENTIMENT_THRESHOLD", 0.10)
            if isent_w > 0:
                row = _lookup_recent(self.intraday_sentiment, timestamp, max_lookback_min=30)
                if row is not None:
                    sent_val = row.get(window_col, 0.0)
                    if abs(sent_val) >= isent_thresh:
                        # +sentiment helps LONG, hurts SHORT (and vice versa)
                        if side == "LONG" and sent_val > 0:
                            score += isent_w * min(1.0, sent_val * 2)
                        elif side == "SHORT" and sent_val < 0:
                            score += isent_w * min(1.0, abs(sent_val) * 2)
                        elif side == "LONG" and sent_val < -isent_thresh:
                            score += isent_w * -0.5  # penalty
                        elif side == "SHORT" and sent_val > isent_thresh:
                            score += isent_w * -0.5

        # ─── PHASE 4: MAG7 mega-cap breadth ────────────────────────────
        if getattr(cfg, "MAG7_BREADTH_ENABLED", False) and self.mag7_breadth:
            mb_w = getattr(cfg, "MAG7_BREADTH_WEIGHT", 0.0)
            mb_mom_w = getattr(cfg, "MAG7_BREADTH_MOMENTUM_WEIGHT", 0.0)
            mb_thresh = getattr(cfg, "MAG7_BREADTH_THRESHOLD", 0.50)
            if mb_w > 0 or mb_mom_w > 0:
                row = _lookup_recent(self.mag7_breadth, timestamp, max_lookback_min=15)
                if row is not None:
                    breadth = row.get("pct_above_5d_ma", 0.5)
                    momentum = row.get("breadth_momentum_15m", 0.0)
                    # LONG benefits when breadth > threshold; SHORT when breadth < (1 - threshold)
                    if mb_w > 0:
                        if side == "LONG":
                            score += mb_w * max(-0.5, min(1.0, (breadth - mb_thresh) * 2))
                        else:
                            score += mb_w * max(-0.5, min(1.0, ((1 - mb_thresh) - breadth) * 2))
                    if mb_mom_w > 0:
                        # Momentum: positive = breadth improving (favor LONG)
                        if side == "LONG" and momentum > 0:
                            score += mb_mom_w * min(1.0, momentum * 5)
                        elif side == "SHORT" and momentum < 0:
                            score += mb_mom_w * min(1.0, abs(momentum) * 5)

        # ─── PHASE 4: Polymarket prediction-market signals ─────────────
        if getattr(cfg, "POLYMARKET_ENABLED", False) and self.polymarket_signals:
            comp_w = getattr(cfg, "POLYMARKET_COMPOSITE_WEIGHT", 0.0)
            fed_w = getattr(cfg, "POLYMARKET_FED_WEIGHT", 0.0)
            rec_w = getattr(cfg, "POLYMARKET_RECESSION_WEIGHT", 0.0)
            geo_w = getattr(cfg, "POLYMARKET_GEOPOLITICS_WEIGHT", 0.0)
            fis_w = getattr(cfg, "POLYMARKET_FISCAL_WEIGHT", 0.0)
            if any(w > 0 for w in (comp_w, fed_w, rec_w, geo_w, fis_w)):
                row = _lookup_recent(self.polymarket_signals, timestamp, max_lookback_min=15)
                if row is not None:
                    # Composite ES signal: positive = risk-on (helps LONG)
                    if comp_w > 0:
                        comp = row.get("composite_es_signal", 0.0)
                        if side == "LONG" and comp > 0:
                            score += comp_w * min(1.0, comp * 2)
                        elif side == "SHORT" and comp < 0:
                            score += comp_w * min(1.0, abs(comp) * 2)
                    # Fed cut prob: high = liquidity (LONG-friendly), Hike prob = SHORT-friendly
                    if fed_w > 0:
                        cut_prob = row.get("fed_cut_prob_next", 0.0)
                        hike_prob = row.get("fed_hike_prob_next", 0.0)
                        if side == "LONG":
                            score += fed_w * (cut_prob - hike_prob)
                        else:
                            score += fed_w * (hike_prob - cut_prob)
                    # Recession prob: helps SHORT, hurts LONG
                    if rec_w > 0:
                        rec_prob = row.get("recession_prob_12m", 0.0)
                        if side == "SHORT":
                            score += rec_w * rec_prob
                        else:
                            score -= rec_w * rec_prob * 0.5  # softer penalty
                    # Geopolitics escalation: helps SHORT
                    if geo_w > 0:
                        geo_max = max(row.get("iran_escalation_prob", 0.0),
                                      row.get("ukraine_escalation_prob", 0.0))
                        if side == "SHORT":
                            score += geo_w * geo_max
                        else:
                            score -= geo_w * geo_max * 0.3
                    # Fiscal expansion: helps LONG; shutdown/default: helps SHORT
                    if fis_w > 0:
                        fiscal = row.get("fiscal_expansion_prob", 0.0)
                        shutdown = row.get("shutdown_default_prob", 0.0)
                        if side == "LONG":
                            score += fis_w * (fiscal - shutdown)
                        else:
                            score += fis_w * (shutdown - fiscal)

        return min(1.0, max(0.0, score))

    def _handle_mr_entry(self, engine, bar, atr, cfg, mr_date):
        """Mean-reversion entry for high-vol days.

        Buy when RSI(12) < 25 (oversold bounce), exit when RSI > 60.
        Optionally short when RSI > 75 (overbought fade).
        Quick holds (max 2 hours), small positions.
        """
        # Check cooldown
        effective_cooldown = self._scaled_bars(getattr(cfg, "COOLDOWN_BARS", 36))
        if self.bars_since_last_trade < effective_cooldown:
            return

        # Consecutive loss circuit breaker
        if self._loss_circuit_cooldown_remaining > 0:
            return

        # Max MR trades per day
        if getattr(cfg, "MR_MODE_MAX_TRADES_DAY", 3) > 0:
            if self._trades_today_date != mr_date:
                self._trades_today_date = mr_date
                self._trades_today = 0
            if self._trades_today >= getattr(cfg, "MR_MODE_MAX_TRADES_DAY", 3):
                return

        if not self._is_entry_allowed(bar.timestamp):
            return

        # Compute short-period RSI for mean reversion
        mr_rsi_period = getattr(cfg, "MR_MODE_RSI_PERIOD", 12)
        if len(self.closes) < mr_rsi_period + 2:
            return
        mr_rsi = compute_rsi(list(self.closes), mr_rsi_period)
        if mr_rsi is None:
            return

        mr_side = getattr(cfg, "MR_MODE_SIDE", "LONG")
        mr_entry_rsi = getattr(cfg, "MR_MODE_RSI_ENTRY", 25)
        mr_short_entry_rsi = getattr(cfg, "MR_MODE_RSI_SHORT_ENTRY", 75)
        side = None

        # Long entry: RSI oversold
        if mr_rsi < mr_entry_rsi and mr_side in ("LONG", "BOTH"):
            side = "LONG"
        # Short entry: RSI overbought
        elif mr_rsi > mr_short_entry_rsi and mr_side in ("SHORT", "BOTH"):
            side = "SHORT"

        if side is None:
            return

        # Position sizing
        mr_risk_mult = getattr(cfg, "MR_MODE_RISK_MULT", 0.3)
        mr_stop_atr = getattr(cfg, "MR_MODE_STOP_ATR", 1.5)
        stop_distance = atr * mr_stop_atr
        if stop_distance <= 0:
            return

        contracts = self._compute_position_size(stop_distance, mr_risk_mult)
        if contracts <= 0:
            return

        # Set stop and TP
        if side == "LONG":
            stop = bar.close - stop_distance
            tp = bar.close + stop_distance * 2.0  # 2:1 R:R
        else:
            stop = bar.close + stop_distance
            tp = bar.close - stop_distance * 2.0

        # Execute
        if side == "LONG":
            engine.buy(contracts)
        else:
            engine.sell(contracts)

        self.entry_price = bar.close
        self.stop_price = stop
        self.tp_price = tp
        self.risk_points = stop_distance
        self.current_side = side
        self.bars_since_entry = 0
        self.bars_since_last_trade = 0
        self._trades_today += 1
        self.trailing_active = False

        # Store MR-specific params for position management
        self._mr_mode_active = True
        self._mr_max_hold = self._scaled_bars(getattr(cfg, "MR_MODE_MAX_HOLD", 24))
        self._mr_rsi_exit = getattr(cfg, "MR_MODE_RSI_EXIT", 60)
        self._mr_rsi_short_exit = getattr(cfg, "MR_MODE_RSI_SHORT_EXIT", 40)

    def _handle_mr_entry_combined(self, engine, bar, atr, cfg, mr_date):
        """Combined strategy MR entry — uses independent state from composite.

        Key differences from legacy _handle_mr_entry:
        - Uses self._mr_bars_since_trade (not shared bars_since_last_trade)
        - Uses self._mr_trades_today (not shared _trades_today)
        - Uses self._mr_loss_cooldown (not shared _loss_circuit_cooldown_remaining)
        - Uses COMBINED_MR_ENTRY_UTC hours (US hours, not Asia)
        - Uses COMBINED_MR_TP_ATR (sweepable)
        """
        # MR's own cooldown (independent of composite)
        mr_cooldown = self._scaled_bars(getattr(cfg, "COMBINED_MR_COOLDOWN_BARS", 6))
        if self._mr_bars_since_trade < mr_cooldown:
            return

        # MR's own circuit breaker (independent of composite)
        if self._mr_loss_cooldown > 0:
            return

        # MR's own daily trade counter (independent of composite)
        mr_max_trades = getattr(cfg, "MR_MODE_MAX_TRADES_DAY", 3)
        if self._mr_trades_today_date != mr_date:
            self._mr_trades_today_date = mr_date
            self._mr_trades_today = 0
        if self._mr_trades_today >= mr_max_trades:
            return

        # MR entry hours: US hours (not Asia hours used by composite)
        mr_utc_start = getattr(cfg, "COMBINED_MR_ENTRY_UTC_START", 14)
        mr_utc_end = getattr(cfg, "COMBINED_MR_ENTRY_UTC_END", 20)
        ts = bar.timestamp
        if hasattr(ts, "hour"):
            # Convert to UTC from Chicago (add 6 for approximate CDT)
            utc_hour = ts.hour + 6
            if utc_hour >= 24:
                utc_hour -= 24
            if utc_hour < mr_utc_start or utc_hour >= mr_utc_end:
                return

        # Compute short-period RSI for mean reversion
        mr_rsi_period = getattr(cfg, "MR_MODE_RSI_PERIOD", 12)
        if len(self.closes) < mr_rsi_period + 2:
            return
        mr_rsi = compute_rsi(list(self.closes), mr_rsi_period)
        if mr_rsi is None:
            return

        mr_side = getattr(cfg, "MR_MODE_SIDE", "LONG")
        mr_entry_rsi = getattr(cfg, "MR_MODE_RSI_ENTRY", 25)
        mr_short_entry_rsi = getattr(cfg, "MR_MODE_RSI_SHORT_ENTRY", 75)
        side = None

        if mr_rsi < mr_entry_rsi and mr_side in ("LONG", "BOTH"):
            side = "LONG"
        elif mr_rsi > mr_short_entry_rsi and mr_side in ("SHORT", "BOTH"):
            side = "SHORT"

        if side is None:
            return

        # Position sizing
        mr_risk_mult = getattr(cfg, "MR_MODE_RISK_MULT", 0.4)
        mr_stop_atr = getattr(cfg, "MR_MODE_STOP_ATR", 1.5)
        stop_distance = atr * mr_stop_atr
        if stop_distance <= 0:
            return

        contracts = self._compute_position_size(stop_distance, mr_risk_mult)
        if contracts <= 0:
            return

        # Set stop and TP using COMBINED_MR_TP_ATR (sweepable)
        mr_tp_atr = getattr(cfg, "COMBINED_MR_TP_ATR", 2.0)
        if side == "LONG":
            stop = bar.close - stop_distance
            tp = bar.close + stop_distance * mr_tp_atr / mr_stop_atr
        else:
            stop = bar.close + stop_distance
            tp = bar.close - stop_distance * mr_tp_atr / mr_stop_atr

        # Execute
        if side == "LONG":
            engine.buy(contracts)
        else:
            engine.sell(contracts)

        self.entry_price = bar.close
        self.stop_price = stop
        self.tp_price = tp
        self.risk_points = stop_distance
        self.current_side = side
        self.bars_since_entry = 0
        self.trailing_active = False

        # Update MR-independent state (NOT shared composite state)
        self._mr_bars_since_trade = 0
        self._mr_trades_today += 1

        # Store MR-specific params for position management
        self._mr_mode_active = True
        self._mr_max_hold = self._scaled_bars(getattr(cfg, "MR_MODE_MAX_HOLD", 24))
        self._mr_rsi_exit = getattr(cfg, "MR_MODE_RSI_EXIT", 55)
        self._mr_rsi_short_exit = getattr(cfg, "MR_MODE_RSI_SHORT_EXIT", 45)

    def _compute_position_size(self, stop_distance, risk_mult=1.0):
        if stop_distance <= 0:
            return 0
        risk_dollars = stop_distance * self.cfg.ES_POINT_VALUE
        adjusted_risk = self.cfg.RISK_PER_TRADE * risk_mult
        contracts = int(adjusted_risk / risk_dollars)
        # Skip trade if 1 contract risk exceeds max allowed % of capital
        max_risk_pct = getattr(self.cfg, "MAX_SINGLE_TRADE_RISK_PCT", 10.0)
        if contracts < 1 and risk_dollars > self.cfg.INITIAL_CAPITAL * max_risk_pct / 100:
            return 0  # Risk too high relative to capital — skip trade
        return max(1, contracts)

    def on_bar(self, engine, bar):
        cfg = self.cfg
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.volumes.append(bar.volume)
        self.bars_since_last_trade += 1

        # Independent MR state ticks (always, regardless of position)
        self._mr_bars_since_trade += 1
        if self._mr_loss_cooldown > 0:
            self._mr_loss_cooldown -= 1

        # Consecutive loss circuit breaker cooldown (composite)
        if self._loss_circuit_cooldown_remaining > 0:
            self._loss_circuit_cooldown_remaining -= 1

        min_data = max(cfg.SMA_SLOW, cfg.RSI_PERIOD, cfg.ATR_PERIOD, getattr(cfg, "SMA_200", 200)) + 10
        if len(self.closes) < min_data:
            return

        atr = compute_atr(list(self.highs), list(self.lows), list(self.closes), cfg.ATR_PERIOD)
        if atr is None or atr < cfg.MIN_ATR_THRESHOLD:
            return

        # ── Daily loss circuit breaker ──
        import datetime as _dtcb
        bar_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
        if isinstance(bar_date, _dtcb.datetime):
            bar_date = bar_date.date()
        if bar_date != self._current_date:
            # New day: reset circuit breaker
            self._current_date = bar_date
            self._daily_pnl = 0.0
            self._daily_circuit_tripped = False
            self._equity_at_day_start = engine.capital + (
                engine.position.unrealized_pnl if not engine.position.is_flat else 0
            )
        elif self._equity_at_day_start and self._equity_at_day_start > 0:
            current_equity = engine.capital + (
                engine.position.unrealized_pnl if not engine.position.is_flat else 0
            )
            daily_loss_pct = (current_equity - self._equity_at_day_start) / self._equity_at_day_start * 100
            circuit_threshold = getattr(cfg, "DAILY_LOSS_CIRCUIT_PCT", -2.0)
            if daily_loss_pct <= circuit_threshold:
                self._daily_circuit_tripped = True

        if not engine.position.is_flat:
            self.bars_since_entry += 1
            self._manage_position(engine, bar, atr)
            return

        # ── COMBINED STRATEGY ROUTING ──
        # Check if this is a high-vol day and route to MR scalper BEFORE
        # composite gates (vol gate, cooldown, circuit breaker) can block it.
        # MR has fully independent state — its own cooldown, trade counter,
        # and circuit breaker, so composite restrictions don't interfere.
        if getattr(cfg, "COMBINED_STRATEGY_ENABLED", False):
            import datetime as _dtmr
            mr_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(mr_date, _dtmr.datetime):
                mr_date = mr_date.date()
            mr_daily = self.daily_trend.get(mr_date)
            if mr_daily is None:
                for _off in range(1, 5):
                    mr_daily = self.daily_trend.get(mr_date - _dtmr.timedelta(days=_off))
                    if mr_daily:
                        break
            mr_atr_pct = None
            if mr_daily and mr_daily.get("daily_atr") and mr_daily.get("close", 0) > 0:
                mr_atr_pct = mr_daily["daily_atr"] / mr_daily["close"] * 100

            mr_thresh = getattr(cfg, "COMBINED_MR_ATR_THRESHOLD", 1.5)
            if mr_atr_pct is not None and mr_atr_pct >= mr_thresh:
                # HIGH-VOL DAY → MR scalper with independent state
                self._handle_mr_entry_combined(engine, bar, atr, cfg, mr_date)
                return  # Skip composite logic entirely on high-vol days

        # ── Legacy MR mode (if someone still uses MR_MODE_ENABLED directly) ──
        if getattr(cfg, "MR_MODE_ENABLED", False):
            import datetime as _dtmr2
            mr_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(mr_date, _dtmr2.datetime):
                mr_date = mr_date.date()
            mr_daily = self.daily_trend.get(mr_date)
            if mr_daily is None:
                for _off in range(1, 5):
                    mr_daily = self.daily_trend.get(mr_date - _dtmr2.timedelta(days=_off))
                    if mr_daily:
                        break
            mr_atr_pct = None
            if mr_daily and mr_daily.get("daily_atr") and mr_daily.get("close", 0) > 0:
                mr_atr_pct = mr_daily["daily_atr"] / mr_daily["close"] * 100
            mr_thresh = getattr(cfg, "MR_MODE_ATR_PCT", 1.5)
            if mr_atr_pct is not None and mr_atr_pct >= mr_thresh:
                self._handle_mr_entry(engine, bar, atr, cfg, mr_date)
                return

        # ── Composite strategy gates (only reached on normal-vol days) ──
        effective_cooldown = self._get_adaptive_cooldown()
        if self.bars_since_last_trade < effective_cooldown:
            return

        # Consecutive loss circuit breaker: pause after N consecutive losses
        if self._loss_circuit_cooldown_remaining > 0:
            return

        # CUSUM event gate: only enter near a structural break
        cusum_enabled = getattr(cfg, "CUSUM_ENTRY_ENABLED", False)
        if cusum_enabled and self.cusum_events:
            cusum_window = getattr(cfg, "CUSUM_WINDOW_BARS", 6)
            ts = bar.timestamp
            cusum_hit = False
            for offset in range(cusum_window):
                check_ts = ts - pd.Timedelta(minutes=5 * offset)
                if check_ts in self.cusum_events:
                    cusum_hit = True
                    self._cusum_last_direction = self.cusum_directions.get(check_ts, 0)
                    break
            if not cusum_hit:
                return  # No CUSUM event nearby — skip entry

        if bar.volume < cfg.MIN_VOLUME_THRESHOLD:
            return
        if not self._is_entry_allowed(bar.timestamp):
            return

        # Skip new entries if daily circuit breaker tripped
        if self._daily_circuit_tripped:
            return

        # Trade-only-dates gate (multi-TF: only enter on designated days)
        if self.trade_only_dates is not None:
            import datetime as _dtgate
            gate_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(gate_date, _dtgate.datetime):
                gate_date = gate_date.date()
            if gate_date not in self.trade_only_dates:
                return

        # ─── PHASE 4: Macro release blackout window ──────────────────
        # Block entries N min before / M min after FOMC/CPI/NFP/PCE/earnings.
        # Configurable via MACRO_BLACKOUT_LOOKBACK_MIN / LOOKAHEAD_MIN / MIN_IMPACT.
        if getattr(cfg, "MACRO_BLACKOUT_ENABLED", False) and self.macro_calendar is not None:
            try:
                import datetime as _dtblk
                bts = bar.timestamp
                if hasattr(bts, "to_pydatetime"):
                    bts = bts.to_pydatetime()
                if bts.tzinfo is None:
                    bts = bts.replace(tzinfo=_dtblk.timezone.utc)
                is_black, _release = self.macro_calendar.is_blackout_window(
                    bts,
                    lookback_min=getattr(cfg, "MACRO_BLACKOUT_LOOKBACK_MIN", 30),
                    lookahead_min=getattr(cfg, "MACRO_BLACKOUT_LOOKAHEAD_MIN", 60),
                    min_impact=getattr(cfg, "MACRO_BLACKOUT_MIN_IMPACT", "HIGH"),
                )
                if is_black:
                    return
            except Exception:
                pass

        # ── Structural experiment gates ──
        import datetime as _dtexp
        exp_date = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
        if isinstance(exp_date, _dtexp.datetime):
            exp_date = exp_date.date()

        # Lookup daily ATR% for vol-based gates
        _daily_atr_pct = None
        _exp_daily = self.daily_trend.get(exp_date)
        if _exp_daily is None:
            for _off in range(1, 5):
                _exp_daily = self.daily_trend.get(exp_date - _dtexp.timedelta(days=_off))
                if _exp_daily:
                    break
        if _exp_daily and _exp_daily.get("daily_atr") and _exp_daily.get("close", 0) > 0:
            _daily_atr_pct = _exp_daily["daily_atr"] / _exp_daily["close"] * 100

        # ── Oil shock gate: disable shorts when oil surges ──
        if getattr(cfg, "OIL_SHOCK_GATE_ENABLED", False):
            oil_data = self.macro.get("crude_oil", {})
            oil = None
            for _off in range(0, 5):
                oil = oil_data.get(exp_date - _dtexp.timedelta(days=_off))
                if oil:
                    break
            if oil is not None:
                oil_move = abs(oil["pct_change"])
                oil_thresh = getattr(cfg, "OIL_SHOCK_THRESHOLD_PCT", 3.0)
                if oil_move > oil_thresh:
                    if getattr(cfg, "OIL_SHOCK_HALT_ALL", False):
                        return  # Halt all trading during oil shock
                    # Otherwise just block shorts — oil shocks cause whipsaw bounces
                    self._oil_shock_active = True
                else:
                    self._oil_shock_active = False

        # ── CBOE Skew gate: institutional panic detection ──
        if getattr(cfg, "SKEW_GATE_ENABLED", False):
            skew_data = self.macro.get("cboe_skew", {})
            skew = _lookup_macro(skew_data, exp_date) if skew_data else None
            if skew is not None:
                skew_thresh = getattr(cfg, "SKEW_PANIC_THRESHOLD", 140.0)
                if skew > skew_thresh:
                    self._skew_panic = True
                else:
                    self._skew_panic = False

        # ── Gold surge gate: risk-off flow detection ──
        if getattr(cfg, "GOLD_RISKOFF_GATE_ENABLED", False):
            gold_data = self.macro.get("gold", {})
            gold = None
            for _off in range(0, 5):
                gold = gold_data.get(exp_date - _dtexp.timedelta(days=_off))
                if gold:
                    break
            if gold is not None:
                gold_move = gold["pct_change"]
                gold_thresh = getattr(cfg, "GOLD_SURGE_THRESHOLD_PCT", 2.0)
                if gold_move > gold_thresh:
                    self._gold_riskoff = True
                else:
                    self._gold_riskoff = False

        # Exp 1: Volatility regime gate
        _vol_gate_active = False
        if getattr(cfg, "VOL_REGIME_GATE_ENABLED", False) and _daily_atr_pct is not None:
            halt_thresh = getattr(cfg, "VOL_GATE_HALT_ATR_PCT", 3.5)
            reduce_thresh = getattr(cfg, "VOL_GATE_REDUCE_ATR_PCT", 2.5)
            if _daily_atr_pct > halt_thresh:
                return  # Too volatile — halt all trading
            elif _daily_atr_pct > reduce_thresh:
                _vol_gate_active = True
                # Will reduce size and disable shorts later in entry logic

        # Exp 2: Max trades per day
        if getattr(cfg, "MAX_TRADES_PER_DAY_ENABLED", False):
            if self._trades_today_date != exp_date:
                self._trades_today_date = exp_date
                self._trades_today = 0
            max_daily = getattr(cfg, "MAX_TRADES_PER_DAY", 2)
            if self._trades_today >= max_daily:
                return

        # Step 1: Classify regime
        regime = self._classify_regime(bar.timestamp)
        rp = self._get_regime_params(regime)

        # VIX Model Switch: override regime params if enabled
        vix_override = self._get_vix_model_override(bar.timestamp)
        if vix_override is not None:
            rp = {**rp, **vix_override}

        # Step 1b: REGIME-SPECIFIC ENTRY PHILOSOPHY
        # Bullish → BUY THE DIP (wait for pullbacks, then go long)
        # Bearish → SELL THE RIP (wait for rallies that fail, then go short)
        # Sideways → MEAN REVERSION (fade extremes in both directions)
        #
        # This means in BULL, we ONLY go long but on pullbacks (RSI oversold).
        # In BEAR, we ONLY go short but on bounces (RSI overbought).
        # In SIDEWAYS, we go both ways at BB/RSI extremes.
        allowed = rp["allowed_side"]

        # Oil/Skew/Gold gates — disable shorts during crisis signals
        if getattr(self, "_oil_shock_active", False):
            allowed = "LONG"  # No shorts during oil shock
        if getattr(self, "_skew_panic", False) and getattr(cfg, "SKEW_GATE_ENABLED", False):
            allowed = "LONG"  # No shorts when institutions are panic-hedging
            rp = dict(rp)
            rp["risk_mult"] = rp["risk_mult"] * getattr(cfg, "SKEW_PANIC_RISK_SCALE", 0.5)
        if getattr(self, "_gold_riskoff", False) and getattr(cfg, "GOLD_RISKOFF_GATE_ENABLED", False):
            allowed = "LONG"  # No shorts during gold surge (risk-off)

        # Exp 1: Vol gate — disable shorts and reduce size
        if _vol_gate_active:
            allowed = "LONG"  # Only longs in high-vol
            rp = dict(rp)
            rp["risk_mult"] = rp["risk_mult"] * getattr(cfg, "VOL_GATE_REDUCE_SIZE_SCALE", 0.25)

        # Exp 4: Crisis short disabling (VIX + ATR)
        if getattr(cfg, "CRISIS_SHORT_DISABLE_ENABLED", False):
            crisis_vix = getattr(cfg, "CRISIS_SHORT_DISABLE_VIX", 30.0)
            crisis_atr = getattr(cfg, "CRISIS_SHORT_DISABLE_ATR_PCT", 2.0)
            _exp_vix = _lookup_macro(self.macro.get("vix", {}), exp_date) if self.macro else None
            if _exp_vix is not None and _daily_atr_pct is not None:
                if _exp_vix > crisis_vix and _daily_atr_pct > crisis_atr:
                    allowed = "LONG"  # Only longs during crisis

        # Exp 7: Dual-mode strategy
        if getattr(cfg, "DUAL_MODE_ENABLED", False) and _daily_atr_pct is not None:
            crisis_thresh = getattr(cfg, "CRISIS_MODE_ATR_PCT", 2.0)
            if _daily_atr_pct > crisis_thresh:
                if getattr(cfg, "CRISIS_MODE_ONLY_LONGS", True):
                    allowed = "LONG"
                rp = dict(rp)
                rp["risk_mult"] = rp["risk_mult"] * getattr(cfg, "CRISIS_MODE_SIZE_SCALE", 0.3)
                # Only enter on extreme RSI in crisis
                rsi_now = compute_rsi(list(self.closes), cfg.RSI_PERIOD)
                if rsi_now is not None:
                    crisis_rsi = getattr(cfg, "CRISIS_MODE_RSI_EXTREME", 20)
                    if rsi_now > crisis_rsi:
                        return  # Not extreme enough for crisis mode entry

        # Check for correction within BULL regime (defensive mode)
        correction_active = False
        if regime == "BULLISH" and getattr(cfg, "BULL_DEFENSIVE_ENABLED", True):
            correction_active = self._is_correction_active(bar.timestamp)
        if correction_active:
            allowed = "BOTH"
            rp = dict(rp)
            rp["risk_mult"] = rp["risk_mult"] * getattr(cfg, "BULL_DEFENSIVE_RISK_MULT", 0.5)
            rp["stop_atr_mult"] = getattr(cfg, "BULL_DEFENSIVE_STOP_ATR", rp["stop_atr_mult"])
            rp["tp_atr_mult"] = getattr(cfg, "BULL_DEFENSIVE_TP_ATR", rp["tp_atr_mult"])
            rp["composite_threshold"] = getattr(cfg, "BULL_DEFENSIVE_THRESHOLD", rp["composite_threshold"] + 0.05)

        # Exp 6: Intraday trend filter — require recent price direction to match entry
        if getattr(cfg, "INTRADAY_TREND_FILTER_ENABLED", False):
            lookback = getattr(cfg, "INTRADAY_TREND_LOOKBACK", 12)
            if len(self.closes) >= lookback:
                recent_move = list(self.closes)[-1] - list(self.closes)[-lookback]
                trend_strength = getattr(cfg, "INTRADAY_TREND_STRENGTH", 0.3)
                min_move = atr * trend_strength
                if allowed == "SHORT" and recent_move > -min_move:
                    return  # Price not falling — don't short
                elif allowed == "LONG" and recent_move < min_move:
                    pass  # Allow longs on dips (don't require uptrend)

        # Step 1c: DIP/RIP FILTER — enforce counter-trend entry requirement
        # In BULL: only enter long when RSI is oversold (buying the dip)
        # In BEAR: only enter short when RSI is overbought (selling the rip)
        dip_rip_enabled = getattr(cfg, "DIP_RIP_FILTER_ENABLED", True)
        if dip_rip_enabled and not correction_active:
            rsi = compute_rsi(list(self.closes), cfg.RSI_PERIOD)
            if rsi is not None:
                dip_rsi_thresh = getattr(cfg, "DIP_BUY_RSI_THRESHOLD", 40)
                rip_rsi_thresh = getattr(cfg, "RIP_SELL_RSI_THRESHOLD", 60)
                if regime == "BULLISH" and rsi > dip_rsi_thresh:
                    return  # Not a dip — wait for pullback
                elif regime == "BEARISH" and rsi < rip_rsi_thresh:
                    return  # Not a rip — wait for bounce

        # ═══════════════════════════════════════════════════════════
        # SEQUENTIAL DECISION PIPELINE
        # Each stage is a gate — must pass all stages to enter.
        # This replaces the single composite threshold approach.
        # ═══════════════════════════════════════════════════════════

        # Lookup daily data (used across multiple stages)
        import datetime as _dt2
        d = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
        if isinstance(d, _dt2.datetime):
            d = d.date()
        daily = self.daily_trend.get(d)
        if daily is None:
            for off in range(1, 5):
                daily = self.daily_trend.get(d - _dt2.timedelta(days=off))
                if daily:
                    break

        # Lookup macro data (used across multiple stages)
        vix = _lookup_macro(self.macro.get("vix", {}), bar.timestamp)
        hy_oas = _lookup_macro(self.macro.get("hy_oas", {}), bar.timestamp)
        dxy = _lookup_macro(self.macro.get("dxy", {}), bar.timestamp)

        # ── STAGE 1: MACRO FILTER ──
        # Assess macro environment — reject trades in hostile conditions
        seq_enabled = getattr(cfg, "SEQUENTIAL_DECISION_ENABLED", True)
        if seq_enabled:
            macro_pass = True
            macro_score = 0.0  # -1 to +1 scale

            # VIX regime assessment
            if vix is not None:
                if vix < cfg.VIX_TIER_1:
                    macro_score += 0.2  # Complacent — good for shorts
                elif vix < cfg.VIX_TIER_2:
                    macro_score += 0.3  # Normal — good for longs
                elif vix < cfg.VIX_TIER_3:
                    macro_score -= 0.1  # Elevated — caution
                elif vix < cfg.VIX_TIER_5:
                    macro_score -= 0.3  # Risk-off — strong caution
                else:
                    macro_score -= 0.5  # Panic — only contrarian longs

            # Credit conditions
            if hy_oas is not None:
                if hy_oas > cfg.HY_OAS_SEVERE:
                    macro_score -= 0.3
                elif hy_oas > cfg.HY_OAS_STRESSED:
                    macro_score -= 0.15
                elif hy_oas < cfg.HY_OAS_NORMAL:
                    macro_score += 0.1

            # Reject if macro is too hostile (configurable threshold)
            macro_reject_thresh = getattr(cfg, "SEQ_MACRO_REJECT_THRESHOLD", -0.4)
            if macro_score <= macro_reject_thresh:
                macro_pass = False

            if not macro_pass:
                return

        # ── STAGE 2: DAILY TREND GATE ──
        # Require daily trend agreement
        daily_gate = getattr(cfg, "DAILY_TREND_GATE", True)
        if daily_gate and daily:
            daily_t = daily["trend"]
            if allowed == "LONG" and daily_t == -1:
                return
            elif allowed == "SHORT" and daily_t == 1:
                return

        # ── STAGE 3: TECHNICAL FILTER (composite score) ──
        long_score = self._compute_composite("LONG", bar.timestamp, rp) if allowed in ("LONG", "BOTH") else 0
        short_score = self._compute_composite("SHORT", bar.timestamp, rp) if allowed in ("SHORT", "BOTH") else 0

        threshold = rp["composite_threshold"]

        # Sentiment threshold boost: lower threshold when daily sentiment agrees
        sent_boost = getattr(cfg, "SENTIMENT_THRESHOLD_BOOST", 0.05)
        if sent_boost > 0 and self.daily_sentiment:
            import datetime as _dt3
            d3 = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(d3, _dt3.datetime):
                d3 = d3.date()
            sv = self.daily_sentiment.get(d3)
            if sv is None:
                for _off in range(1, 4):
                    sv = self.daily_sentiment.get(d3 - _dt3.timedelta(days=_off))
                    if sv is not None:
                        break
            if sv is not None:
                if long_score >= short_score and sv > 0.15:
                    threshold = max(0.1, threshold - sent_boost)
                elif short_score > long_score and sv < -0.15:
                    threshold = max(0.1, threshold - sent_boost)

        composite_entry = False
        if long_score >= threshold and long_score >= short_score:
            side = "LONG"
            composite = long_score
            composite_entry = True
        elif short_score >= threshold and short_score > long_score:
            side = "SHORT"
            composite = short_score
            composite_entry = True

        # ── BREAKOUT ENTRY (fallback when composite doesn't trigger) ──
        # Catches strong momentum moves with volume confirmation
        breakout_enabled = getattr(cfg, "BREAKOUT_ENTRY_ENABLED", True)
        if not composite_entry and breakout_enabled:
            breakout_lookback = self._scaled_bars(getattr(cfg, "BREAKOUT_LOOKBACK", 48))
            breakout_vol_mult = getattr(cfg, "BREAKOUT_VOL_MULT", 2.0)

            if len(self.closes) >= breakout_lookback and len(self.volumes) >= 20:
                recent_high = max(list(self.highs)[-breakout_lookback:])
                recent_low = min(list(self.lows)[-breakout_lookback:])
                vol_list = list(self.volumes)
                avg_vol = sum(vol_list[-20:]) / 20 if sum(vol_list[-20:]) > 0 else 0
                current_vol = vol_list[-1] if vol_list[-1] > 0 else 0
                vol_confirmed = avg_vol > 0 and current_vol >= avg_vol * breakout_vol_mult

                if vol_confirmed:
                    # Bullish breakout: price above recent high + volume surge
                    if bar.close > recent_high and allowed in ("LONG", "BOTH"):
                        side = "LONG"
                        composite = max(long_score, threshold)  # At least threshold
                        composite_entry = True
                    # Bearish breakout: price below recent low + volume surge
                    elif bar.close < recent_low and allowed in ("SHORT", "BOTH"):
                        side = "SHORT"
                        composite = max(short_score, threshold)
                        composite_entry = True

        if not composite_entry:
            return

        # ── STAGE 4: VOLUME CONFIRMATION GATE ──
        vol_gate = getattr(cfg, "SEQ_VOLUME_GATE_ENABLED", True)
        if vol_gate and len(self.volumes) >= 20:
            vol_list = list(self.volumes)
            avg_vol = sum(vol_list[-20:]) / 20
            current_vol = vol_list[-1]
            if avg_vol > 0 and current_vol > 0:
                vol_ratio = current_vol / avg_vol
                vol_min_ratio = getattr(cfg, "SEQ_VOLUME_MIN_RATIO", 0.3)
                if vol_ratio < vol_min_ratio:
                    return  # Reject: no volume conviction

        # ═══════════════════════════════════════════════════════════
        # ADAPTIVE TP/SL BASED ON MACRO + TA
        # Stop and target dynamically adjust to market conditions
        # ═══════════════════════════════════════════════════════════

        # ── Adaptive Stop-Loss ──
        base_stop_mult = rp["stop_atr_mult"]

        # GARCH volatility forecast scaling (forward-looking, replaces naive ATR regime)
        garch_enabled = getattr(cfg, "GARCH_ENABLED", False)
        garch_vol_scale = 1.0
        if garch_enabled and self.garch_forecast:
            import datetime as _dtg
            gd = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(gd, _dtg.datetime):
                gd = gd.date()
            garch = self.garch_forecast.get(gd)
            if garch is None:
                fallback_days = getattr(cfg, "GARCH_FALLBACK_LOOKBACK", 5)
                for off in range(1, fallback_days + 1):
                    garch = self.garch_forecast.get(gd - _dtg.timedelta(days=off))
                    if garch:
                        break
            if garch:
                vol_ratio = garch["vol_ratio"]
                # Skip entries when GARCH predicts extreme vol increase
                extreme_thresh = getattr(cfg, "GARCH_EXTREME_VOL_THRESHOLD", 2.0)
                if vol_ratio > extreme_thresh:
                    return  # Too volatile for new entries

                blend = getattr(cfg, "GARCH_BLEND_WEIGHT", 0.5)
                if vol_ratio > 1.0:
                    increase_scale = getattr(cfg, "GARCH_VOL_INCREASE_SCALE", 1.3)
                    garch_vol_scale = 1.0 + blend * (increase_scale - 1.0) * min(vol_ratio - 1.0, 1.0)
                else:
                    decrease_scale = getattr(cfg, "GARCH_VOL_DECREASE_SCALE", 0.8)
                    garch_vol_scale = 1.0 + blend * (decrease_scale - 1.0) * min(1.0 - vol_ratio, 0.5)

        base_stop_mult *= garch_vol_scale

        # Scale by daily ATR regime (fallback when GARCH unavailable)
        if daily and daily.get("daily_atr") and daily.get("close", 0) > 0:
            daily_atr_pct = daily["daily_atr"] / daily["close"] * 100
            if daily_atr_pct < 1.0:
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_LOW_VOL_SCALE", 0.8)
            elif daily_atr_pct > 2.0:
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_HIGH_VOL_SCALE", 1.3)

        # VIX-scaled stops: wider in high-vol to avoid whipsaw stops
        if vix is not None:
            if vix > cfg.VIX_TIER_5:
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_VIX_PANIC_SCALE", 1.8)
            elif vix > cfg.VIX_TIER_4:
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_VIX_RISKOFF_SCALE", 1.3)
            elif vix < cfg.VIX_TIER_1:
                # Low VIX = complacent: can use tighter stops (less noise)
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_VIX_LOW_SCALE", 0.9)

        # Credit stress: tighter stops when credit is deteriorating
        if hy_oas is not None and hy_oas > cfg.HY_OAS_STRESSED:
            base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_CREDIT_STRESS_SCALE", 1.2)

        # DXY strength: dollar strength affects ES inversely
        if dxy is not None:
            if dxy > getattr(cfg, "DXY_STRONG_THRESHOLD", 103) and side == "LONG":
                base_stop_mult *= getattr(cfg, "ADAPTIVE_STOP_DXY_STRONG_SCALE", 0.85)

        stop_distance = atr * base_stop_mult
        if stop_distance <= 0:
            return

        # ── Adaptive Take-Profit ──
        base_tp_mult = rp["tp_atr_mult"]

        # GARCH TP scaling: widen TP when vol is expected to increase (bigger moves)
        if garch_enabled and garch_vol_scale != 1.0:
            base_tp_mult *= garch_vol_scale

        # Trend strength scaling: strong daily trend = let winners run (wider TP)
        if daily:
            daily_rsi = daily.get("daily_rsi")
            daily_t = daily.get("trend", 0)
            # Aligned with daily trend: widen TP
            if (side == "LONG" and daily_t == 1) or (side == "SHORT" and daily_t == -1):
                base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_TREND_ALIGNED_SCALE", 1.5)
            # Counter-trend: tighten TP (take what you can get)
            elif (side == "LONG" and daily_t == -1) or (side == "SHORT" and daily_t == 1):
                base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_COUNTER_TREND_SCALE", 0.7)

            # RSI-based TP scaling
            if daily_rsi is not None:
                if side == "LONG" and daily_rsi > 65:
                    # Already extended — tighten TP
                    base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_RSI_EXTENDED_SCALE", 0.8)
                elif side == "SHORT" and daily_rsi < 35:
                    base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_RSI_EXTENDED_SCALE", 0.8)
                elif side == "LONG" and daily_rsi < 35:
                    # Oversold bounce — widen TP (room to run)
                    base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_RSI_REVERSAL_SCALE", 1.3)
                elif side == "SHORT" and daily_rsi > 65:
                    base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_RSI_REVERSAL_SCALE", 1.3)

        # VIX-based TP: higher VIX = larger moves possible = wider TP
        if vix is not None:
            if vix > cfg.VIX_TIER_4:
                base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_VIX_HIGH_SCALE", 1.5)
            elif vix > cfg.VIX_TIER_2:
                base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_VIX_ELEVATED_SCALE", 1.2)

        # Volume surge: high volume = strong conviction = wider TP
        if len(self.volumes) >= 20:
            vol_list = list(self.volumes)
            avg_vol = sum(vol_list[-20:]) / 20
            if avg_vol > 0 and vol_list[-1] > 0:
                vol_ratio = vol_list[-1] / avg_vol
                if vol_ratio > getattr(cfg, "VOLUME_SURGE_THRESHOLD", 1.5):
                    base_tp_mult *= getattr(cfg, "ADAPTIVE_TP_VOLUME_SURGE_SCALE", 1.3)

        # Enforce minimum R:R ratio
        min_rr = getattr(cfg, "MIN_RR_RATIO", 2.0)
        min_tp_mult = base_stop_mult * min_rr
        tp_mult = max(base_tp_mult, min_tp_mult)

        # ── STAGE 5: Position Sizing ──
        risk_mult = rp["risk_mult"]

        # Confidence-weighted sizing
        confidence_sizing = getattr(cfg, "CONFIDENCE_SIZING_ENABLED", True)
        if confidence_sizing:
            high_conf = getattr(cfg, "CONFIDENCE_HIGH_THRESHOLD", 0.6)
            if composite >= high_conf:
                risk_mult *= getattr(cfg, "CONFIDENCE_HIGH_MULT", 1.5)
            elif composite < threshold + 0.05:
                risk_mult *= getattr(cfg, "CONFIDENCE_LOW_MULT", 0.5)

        # Macro-scaled sizing: reduce size in adverse macro
        if seq_enabled:
            if macro_score < -0.2:
                risk_mult *= getattr(cfg, "SEQ_MACRO_ADVERSE_SIZE_SCALE", 0.6)
            elif macro_score > 0.3:
                risk_mult *= getattr(cfg, "SEQ_MACRO_FAVORABLE_SIZE_SCALE", 1.2)

        # Volatility regime scaling
        vol_scaling = getattr(cfg, "VOL_REGIME_SCALING_ENABLED", True)
        if vol_scaling and daily and daily.get("daily_atr") and daily.get("close", 0) > 0:
            daily_atr_pct = daily["daily_atr"] / daily["close"] * 100
            if daily_atr_pct > getattr(cfg, "VOL_EXTREME_THRESHOLD_PCT", 2.5):
                risk_mult *= getattr(cfg, "VOL_EXTREME_SIZE_SCALE", 0.5)
            elif daily_atr_pct > getattr(cfg, "VOL_HIGH_THRESHOLD_PCT", 1.8):
                risk_mult *= getattr(cfg, "VOL_HIGH_SIZE_SCALE", 0.75)

        contracts = self._compute_position_size(stop_distance, risk_mult)

        # ── Execute Entry ──
        if side == "LONG":
            stop = bar.close - stop_distance
            tp = bar.close + atr * tp_mult
            if cfg.USE_LIMIT_ORDERS:
                engine.buy(contracts, OrderType.LIMIT, limit_price=bar.close - atr * cfg.LIMIT_OFFSET_ATR)
            else:
                engine.buy(contracts)
        else:
            stop = bar.close + stop_distance
            tp = bar.close - atr * tp_mult
            if cfg.USE_LIMIT_ORDERS:
                engine.sell(contracts, OrderType.LIMIT, limit_price=bar.close + atr * cfg.LIMIT_OFFSET_ATR)
            else:
                engine.sell(contracts)

        self.entry_price = bar.close
        self.stop_price = stop
        self.tp_price = tp
        self.risk_points = stop_distance
        self.current_side = side
        self.bars_since_entry = 0
        self.bars_since_last_trade = 0
        self._trades_today += 1  # Exp 2: track daily trade count
        self.trailing_active = False
        self._current_rp = rp
        self._entry_composite = composite
        self._entry_vix = vix
        self._entry_macro_score = macro_score if seq_enabled else 0

    def _manage_position(self, engine, bar, atr):
        """Macro-adaptive position management with dynamic TP/SL."""
        cfg = self.cfg
        rp = getattr(self, "_current_rp", None) or self._get_regime_params("SIDEWAYS")

        if self.entry_price is None and engine.position.avg_price > 0:
            self.entry_price = engine.position.avg_price
            if self.current_side == "LONG":
                self.stop_price = self.entry_price - (self.risk_points or atr * rp["stop_atr_mult"])
                self.tp_price = self.entry_price + atr * rp["tp_atr_mult"]
            else:
                self.stop_price = self.entry_price + (self.risk_points or atr * rp["stop_atr_mult"])
                self.tp_price = self.entry_price - atr * rp["tp_atr_mult"]

        if self.entry_price is None:
            return

        # ── Mean Reversion mode: simplified exit logic ──
        if getattr(self, "_mr_mode_active", False):
            # Stop hit
            if self.current_side == "LONG" and bar.low <= self.stop_price:
                self._close_and_reset(engine, bar); return
            if self.current_side == "SHORT" and bar.high >= self.stop_price:
                self._close_and_reset(engine, bar); return
            # TP hit
            if self.current_side == "LONG" and bar.high >= self.tp_price:
                self._close_and_reset(engine, bar); return
            if self.current_side == "SHORT" and bar.low <= self.tp_price:
                self._close_and_reset(engine, bar); return
            # RSI-based exit
            mr_rsi_period = getattr(cfg, "MR_MODE_RSI_PERIOD", 12)
            if len(self.closes) >= mr_rsi_period + 2:
                mr_rsi = compute_rsi(list(self.closes), mr_rsi_period)
                if mr_rsi is not None:
                    if self.current_side == "LONG" and mr_rsi > self._mr_rsi_exit:
                        self._close_and_reset(engine, bar); return
                    if self.current_side == "SHORT" and mr_rsi < self._mr_rsi_short_exit:
                        self._close_and_reset(engine, bar); return
            # Max hold
            if self.bars_since_entry >= self._mr_max_hold:
                self._close_and_reset(engine, bar); return
            return  # Skip normal position management for MR trades

        # Lookup current macro for in-trade adjustments
        vix = _lookup_macro(self.macro.get("vix", {}), bar.timestamp)
        hy_oas = _lookup_macro(self.macro.get("hy_oas", {}), bar.timestamp)
        entry_vix = getattr(self, "_entry_vix", None)

        # ── Macro regime shift detection ──
        # If VIX jumped significantly since entry, tighten stops
        if vix is not None and entry_vix is not None:
            vix_change = vix - entry_vix
            vix_spike_thresh = getattr(cfg, "INTRADE_VIX_SPIKE_THRESHOLD", 5.0)
            if vix_change > vix_spike_thresh:
                # VIX spiked since entry — tighten stop aggressively
                spike_tighten = getattr(cfg, "INTRADE_VIX_SPIKE_TIGHTEN", 0.5)
                if engine.position.is_long:
                    tight = bar.close - atr * spike_tighten
                    self.stop_price = max(self.stop_price, tight)
                elif engine.position.is_short:
                    # VIX spike helps shorts — widen TP instead
                    new_tp = self.entry_price - atr * rp["tp_atr_mult"] * 1.5
                    if engine.position.is_short:
                        self.tp_price = min(self.tp_price, new_tp)

        # ── Credit deterioration in-trade ──
        if hy_oas is not None and hy_oas > cfg.HY_OAS_STRESSED:
            credit_tighten = getattr(cfg, "INTRADE_CREDIT_STRESS_TIGHTEN", 0.7)
            if engine.position.is_long:
                tight = bar.close - atr * rp["stop_atr_mult"] * credit_tighten
                self.stop_price = max(self.stop_price, tight)

        # ── Standard risk-off stop tightening ──
        if vix is not None and vix > cfg.VIX_TIER_4:
            tighten = cfg.RISKOFF_STOP_TIGHTEN_MULT
            if engine.position.is_long:
                tight = bar.close - atr * rp["stop_atr_mult"] * tighten
                self.stop_price = max(self.stop_price, tight)
            elif engine.position.is_short:
                tight = bar.close + atr * rp["stop_atr_mult"] * tighten
                self.stop_price = min(self.stop_price, tight)

        # ── Stop loss (fires any time) ──
        if engine.position.is_long and bar.low <= self.stop_price:
            self._close_and_reset(engine, bar); return
        elif engine.position.is_short and bar.high >= self.stop_price:
            self._close_and_reset(engine, bar); return

        # ── Take profit ──
        if engine.position.is_long and bar.high >= self.tp_price:
            self._close_and_reset(engine, bar); return
        elif engine.position.is_short and bar.low <= self.tp_price:
            self._close_and_reset(engine, bar); return

        # ── Max hold (adaptive: ATR + VIX + swing/scalp) ──
        max_hold = self._compute_adaptive_max_hold(bar, rp)
        if self.bars_since_entry >= max_hold and self.bars_since_entry >= self._scaled_bars(cfg.MIN_HOLD_BARS):
            self._close_and_reset(engine, bar); return

        # ── Breakeven move ──
        if self.risk_points and not self.trailing_active:
            if engine.position.is_long:
                if bar.close - self.entry_price >= self.risk_points * cfg.BREAKEVEN_R:
                    self.stop_price = max(self.stop_price, self.entry_price + 0.25)
            elif engine.position.is_short:
                if self.entry_price - bar.close >= self.risk_points * cfg.BREAKEVEN_R:
                    self.stop_price = min(self.stop_price, self.entry_price - 0.25)

        # ── Adaptive trailing stop (macro-aware) ──
        if self.risk_points:
            trailing_start = rp["trailing_start_r"]
            trailing_atr = rp["trailing_atr_mult"]

            # Tighter trailing when VIX is elevated (protect gains)
            if vix is not None and vix > cfg.VIX_TIER_3:
                trailing_atr *= getattr(cfg, "INTRADE_TRAILING_VIX_TIGHTEN", 0.7)

            if engine.position.is_long:
                profit_r = (bar.close - self.entry_price) / self.risk_points
                if profit_r >= trailing_start:
                    self.trailing_active = True
                    self.stop_price = max(self.stop_price, bar.close - atr * trailing_atr)
            elif engine.position.is_short:
                profit_r = (self.entry_price - bar.close) / self.risk_points
                if profit_r >= trailing_start:
                    self.trailing_active = True
                    self.stop_price = min(self.stop_price, bar.close + atr * trailing_atr)

        # ── Momentum-based exit (daily trend reversal) ──
        momentum_exit = getattr(cfg, "MOMENTUM_EXIT_ENABLED", True)
        if momentum_exit and self.risk_points:
            import datetime as _dt3
            d = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            if isinstance(d, _dt3.datetime):
                d = d.date()
            daily = self.daily_trend.get(d)
            if daily is None:
                for off in range(1, 5):
                    daily = self.daily_trend.get(d - _dt3.timedelta(days=off))
                    if daily:
                        break
            if daily:
                daily_t = daily["trend"]
                daily_rsi = daily.get("daily_rsi")
                in_profit = False
                if engine.position.is_long:
                    in_profit = bar.close > self.entry_price
                elif engine.position.is_short:
                    in_profit = bar.close < self.entry_price

                min_hold_for_momentum = self._scaled_bars(getattr(cfg, "MOMENTUM_EXIT_MIN_BARS", 24))
                if self.bars_since_entry >= min_hold_for_momentum and in_profit:
                    if engine.position.is_long and daily_t == -1:
                        self._close_and_reset(engine, bar); return
                    elif engine.position.is_short and daily_t == 1:
                        self._close_and_reset(engine, bar); return

                # RSI extreme tightening
                rsi_exit = getattr(cfg, "MOMENTUM_RSI_EXIT_ENABLED", True)
                if rsi_exit and daily_rsi is not None and self.bars_since_entry >= self._scaled_bars(cfg.MIN_HOLD_BARS):
                    rsi_extreme_exit = getattr(cfg, "MOMENTUM_RSI_EXTREME", 75)
                    rsi_tighten_atr = getattr(cfg, "INTRADE_RSI_EXTREME_TIGHTEN_ATR", 0.3)
                    if engine.position.is_long and daily_rsi > rsi_extreme_exit:
                        self.stop_price = max(self.stop_price, bar.close - atr * rsi_tighten_atr)
                    elif engine.position.is_short and daily_rsi < (100 - rsi_extreme_exit):
                        self.stop_price = min(self.stop_price, bar.close + atr * rsi_tighten_atr)

        # ── RSI extreme stop tightening (intraday) ──
        if cfg.STOP_TIGHTEN_ON_RSI_EXTREME:
            rsi = compute_rsi(list(self.closes), cfg.RSI_PERIOD)
            if rsi is not None:
                rsi_ob = rp.get("rsi_overbought", cfg.RSI_FAST_OVERBOUGHT)
                rsi_os = rp.get("rsi_oversold", cfg.RSI_FAST_OVERSOLD)
                if engine.position.is_long and rsi > rsi_ob:
                    self.stop_price = max(self.stop_price, bar.close - atr * cfg.STOP_TIGHTEN_ATR_MULT)
                elif engine.position.is_short and rsi < rsi_os:
                    self.stop_price = min(self.stop_price, bar.close + atr * cfg.STOP_TIGHTEN_ATR_MULT)

    def _close_and_reset(self, engine, bar):
        """Close position and track win/loss for adaptive cooldown.

        Routes loss tracking to MR or composite depending on which system
        opened the trade (self._mr_mode_active).
        """
        # Determine win/loss before closing
        if self.entry_price is not None:
            if self.current_side == "LONG":
                pnl = bar.close - self.entry_price
            else:
                pnl = self.entry_price - bar.close
            is_win = pnl > 0

            if getattr(self, "_mr_mode_active", False):
                # ── MR trade: update MR-independent loss tracking ──
                if is_win:
                    self._mr_consecutive_losses = 0
                else:
                    self._mr_consecutive_losses += 1
                    max_consec = getattr(self.cfg, "COMBINED_MR_MAX_CONSECUTIVE_LOSSES", 5)
                    if self._mr_consecutive_losses >= max_consec:
                        cooldown = getattr(self.cfg, "CONSECUTIVE_LOSS_COOLDOWN_BARS", 78)
                        self._mr_loss_cooldown = self._scaled_bars(cooldown)
            else:
                # ── Composite trade: update composite loss tracking ──
                self._recent_results.append(is_win)
                max_streak = getattr(self.cfg, "STREAK_LOOKBACK", 5)
                if len(self._recent_results) > max_streak:
                    self._recent_results = self._recent_results[-max_streak:]

                if is_win:
                    self._consecutive_losses = 0
                else:
                    self._consecutive_losses += 1
                    max_consec = getattr(self.cfg, "MAX_CONSECUTIVE_LOSSES", 3)
                    if self._consecutive_losses >= max_consec:
                        cooldown = getattr(self.cfg, "CONSECUTIVE_LOSS_COOLDOWN_BARS", 78)
                        self._loss_circuit_cooldown_remaining = self._scaled_bars(cooldown)

        engine.close_position()
        self._reset_state()

    def _reset_state(self):
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None
        self.trailing_active = False
        self.risk_points = None
        self.current_side = None
        self.bars_since_entry = 0
        self._mr_mode_active = False

    def _get_adaptive_cooldown(self):
        """Adaptive cooldown: shorter after wins, longer after losses."""
        cfg = self.cfg
        base_cooldown = self._scaled_bars(cfg.COOLDOWN_BARS)
        adaptive_enabled = getattr(cfg, "ADAPTIVE_COOLDOWN_ENABLED", True)
        if not adaptive_enabled or not self._recent_results:
            return base_cooldown

        # Count recent wins
        recent = self._recent_results[-getattr(cfg, "STREAK_LOOKBACK", 5):]
        win_rate = sum(1 for r in recent if r) / len(recent)

        win_cooldown_mult = getattr(cfg, "COOLDOWN_WIN_STREAK_MULT", 0.5)
        loss_cooldown_mult = getattr(cfg, "COOLDOWN_LOSS_STREAK_MULT", 2.0)

        if win_rate >= 0.6:
            # Winning streak — trade more aggressively
            return max(6, int(base_cooldown * win_cooldown_mult))
        elif win_rate <= 0.2:
            # Losing streak — pull back
            return int(base_cooldown * loss_cooldown_mult)
        return base_cooldown


def run_backtest(config_path=None):
    cfg = load_config(config_path)
    df = load_es_data(config_path=config_path)
    macro_data = load_macro_data()
    nlp_regime = load_nlp_regime()
    digest_ctx = load_digest_context()
    daily_trend = load_daily_es_trend()
    daily_sentiment = load_daily_sentiment()
    garch_forecast = load_garch_forecast()
    particle_regime = load_particle_regime()
    cusum_events, cusum_directions = load_cusum_events()
    tsfresh_signal = load_tsfresh_signal()
    hourly_regime = load_hourly_regime_features()
    ml_entry_signal = load_ml_entry_signal()

    # Phase 4 multi-input feeds (gracefully empty if files don't exist)
    intraday_sentiment = load_intraday_sentiment()
    mag7_breadth = load_mag7_breadth()
    polymarket_signals = load_polymarket_signals()
    # Macro calendar — only instantiate if blackout enabled in config (lazy)
    macro_calendar = None
    if getattr(cfg, "MACRO_BLACKOUT_ENABLED", False):
        try:
            from tools.macro_calendar import MacroCalendar
            macro_calendar = MacroCalendar()
        except Exception as e:
            print(f"Warning: could not load MacroCalendar: {e}", file=sys.stderr)

    multi_tf = getattr(cfg, "MULTI_TF_ENABLED", False)

    if not multi_tf:
        # Single-timeframe mode (original)
        engine = BacktestEngine(
            data=df,
            initial_capital=cfg.INITIAL_CAPITAL,
            commission_per_contract=2.25,
            slippage_ticks=1,
            max_position=50,
        )
        strategy = ESAutoResearchStrategy(
            cfg, macro_data, nlp_regime, digest_ctx, daily_trend, daily_sentiment,
            garch_forecast, particle_regime, cusum_events, cusum_directions,
            tsfresh_signal, hourly_regime, ml_entry_signal,
            intraday_sentiment=intraday_sentiment, mag7_breadth=mag7_breadth,
            polymarket_signals=polymarket_signals, macro_calendar=macro_calendar,
        )
        engine.set_strategy(strategy.on_bar)
        return engine.run()

    # ── Multi-Timeframe Mode ──
    # Split trading days into normal-vol (5-min) and high-vol (4h) sets
    vol_thresh = getattr(cfg, "MULTI_TF_VOL_THRESHOLD", 1.5)
    normal_dates = set()
    highvol_dates = set()
    for d, info in daily_trend.items():
        if info.get("daily_atr") and info.get("close", 0) > 0:
            atr_pct = info["daily_atr"] / info["close"] * 100
            if atr_pct >= vol_thresh:
                highvol_dates.add(d)
            else:
                normal_dates.add(d)
        else:
            normal_dates.add(d)

    # Build filtered DataFrames
    df_5m = df.copy()
    df_5m_tz = df_5m.index.tz_localize(None) if df_5m.index.tz is None else df_5m.index.tz_convert("America/Chicago").tz_localize(None)
    df_5m_dates = pd.Series(df_5m_tz).dt.date.values
    normal_mask = pd.array([d in normal_dates for d in df_5m_dates])
    df_normal = df_5m[normal_mask]

    # Load ALL 4h bars (continuous for indicator computation)
    # Strategy will only ENTER trades on high-vol days
    df_4h_all = load_es_data_4h()
    df_highvol = df_4h_all  # Use full continuous data

    # ── Run 5-min backtest on normal-vol days ──
    # Full capital to 5-min (primary), 4h mode uses small separate allocation
    capital_split = cfg.INITIAL_CAPITAL * 0.85
    if len(df_normal) > 200:
        engine_normal = BacktestEngine(
            data=df_normal,
            initial_capital=capital_split,
            commission_per_contract=2.25,
            slippage_ticks=1,
            max_position=50,
        )
        strategy_normal = ESAutoResearchStrategy(
            cfg, macro_data, nlp_regime, digest_ctx, daily_trend, daily_sentiment,
            garch_forecast, particle_regime, cusum_events, cusum_directions,
            tsfresh_signal, hourly_regime, ml_entry_signal,
            trade_only_dates=normal_dates,
            intraday_sentiment=intraday_sentiment, mag7_breadth=mag7_breadth,
            polymarket_signals=polymarket_signals, macro_calendar=macro_calendar,
        )
        engine_normal.set_strategy(strategy_normal.on_bar)
        results_normal = engine_normal.run()
    else:
        results_normal = {"total_return_pct": 0, "max_drawdown": 0, "total_trades": 0,
                          "win_rate": 0, "sharpe_ratio": 0, "profit_factor": 0,
                          "final_equity": capital_split, "trades": pd.DataFrame()}

    # ── Run 4h backtest on high-vol days with overridden params ──
    capital_4h = cfg.INITIAL_CAPITAL * 0.15  # Small allocation to 4h mode
    if len(df_highvol) > 10:
        # Create a modified config for 4h mode
        import types
        cfg_4h = types.SimpleNamespace(**{k: getattr(cfg, k) for k in dir(cfg) if not k.startswith("_")})
        # Override params for 4h bars
        cfg_4h.BAR_SCALE_FACTOR = 1  # 4h bars are already the native timeframe
        cfg_4h.INITIAL_CAPITAL = capital_4h
        cfg_4h.COOLDOWN_BARS = getattr(cfg, "MULTI_TF_4H_COOLDOWN", 6)
        cfg_4h.MIN_HOLD_BARS = getattr(cfg, "MULTI_TF_4H_MIN_HOLD", 3)
        # Override all regime stop/TP/hold with 4h values
        for attr in ["BULL_STOP_ATR_MULT", "BEAR_STOP_ATR_MULT", "SIDE_STOP_ATR_MULT"]:
            setattr(cfg_4h, attr, getattr(cfg, "MULTI_TF_4H_STOP_MULT", 2.5))
        for attr in ["BULL_TP_ATR_MULT", "BEAR_TP_ATR_MULT", "SIDE_TP_ATR_MULT"]:
            setattr(cfg_4h, attr, getattr(cfg, "MULTI_TF_4H_TP_MULT", 4.0))
        for attr in ["BULL_MAX_HOLD_BARS", "BEAR_MAX_HOLD_BARS", "SIDE_MAX_HOLD_BARS"]:
            setattr(cfg_4h, attr, getattr(cfg, "MULTI_TF_4H_MAX_HOLD", 30))
        for attr in ["BULL_RISK_MULT", "BEAR_RISK_MULT", "SIDE_RISK_MULT"]:
            setattr(cfg_4h, attr, getattr(cfg, "MULTI_TF_4H_RISK_MULT", 0.3))
        for attr in ["BULL_COMPOSITE_THRESHOLD", "BEAR_COMPOSITE_THRESHOLD", "SIDE_COMPOSITE_THRESHOLD"]:
            setattr(cfg_4h, attr, getattr(cfg, "MULTI_TF_4H_COMPOSITE_THRESH", 0.40))
        # Allowed side
        allowed_4h = getattr(cfg, "MULTI_TF_4H_ALLOWED_SIDE", "BOTH")
        cfg_4h.BULL_SIDE = allowed_4h
        cfg_4h.BEAR_SIDE = allowed_4h
        cfg_4h.SIDE_SIDE = allowed_4h
        # Disable sub-features that are 5-min specific
        cfg_4h.INTRADAY_TREND_FILTER_ENABLED = False
        cfg_4h.BREAKOUT_ENTRY_ENABLED = False
        # Disable structural experiment gates (4h has its own regime handling)
        cfg_4h.VOL_REGIME_GATE_ENABLED = False
        cfg_4h.CRISIS_SHORT_DISABLE_ENABLED = False
        cfg_4h.HIGH_VOL_HOLD_REDUCTION_ENABLED = False
        cfg_4h.DUAL_MODE_ENABLED = False
        cfg_4h.ADAPTIVE_HOLD_ENABLED = False
        cfg_4h.VIX_MODEL_SWITCH_ENABLED = False
        cfg_4h.MULTI_TF_ENABLED = False  # Prevent recursion
        # Scale down risk per trade for small capital
        cfg_4h.RISK_PER_TRADE = min(cfg.RISK_PER_TRADE, capital_4h * 0.02)  # Max 2% of 4h capital

        engine_4h = BacktestEngine(
            data=df_4h_all,  # Full continuous 4h data (trade_only_dates gates entries)
            initial_capital=capital_4h,
            commission_per_contract=2.25,
            slippage_ticks=1,
            max_position=50,
        )
        strategy_4h = ESAutoResearchStrategy(
            cfg_4h, macro_data, nlp_regime, digest_ctx, daily_trend, daily_sentiment,
            garch_forecast, particle_regime, cusum_events, cusum_directions,
            tsfresh_signal, hourly_regime, ml_entry_signal,
            trade_only_dates=highvol_dates,
            intraday_sentiment=intraday_sentiment, mag7_breadth=mag7_breadth,
            polymarket_signals=polymarket_signals, macro_calendar=macro_calendar,
        )
        engine_4h.set_strategy(strategy_4h.on_bar)
        results_4h = engine_4h.run()
    else:
        results_4h = {"total_return_pct": 0, "max_drawdown": 0, "total_trades": 0,
                      "win_rate": 0, "sharpe_ratio": 0, "profit_factor": 0,
                      "final_equity": capital_4h, "trades": pd.DataFrame()}

    # ── Merge results ──
    normal_pnl = results_normal["final_equity"] - capital_split
    h4_pnl = results_4h["final_equity"] - capital_4h
    combined_equity = cfg.INITIAL_CAPITAL + normal_pnl + h4_pnl
    combined_return = (combined_equity / cfg.INITIAL_CAPITAL - 1) * 100
    combined_trades = results_normal["total_trades"] + results_4h["total_trades"]

    # Conservative DD: max of individual DDs
    combined_dd = max(results_normal["max_drawdown"], results_4h["max_drawdown"])

    # Merge trades for win rate
    trades_list = []
    for r in [results_normal, results_4h]:
        t = r.get("trades")
        if t is not None and isinstance(t, pd.DataFrame) and len(t) > 0:
            trades_list.append(t)
    if trades_list:
        all_trades = pd.concat(trades_list, ignore_index=True)
        combined_wr = (all_trades["pnl"] > 0).mean() * 100 if len(all_trades) > 0 else 0
        combined_pf = abs(all_trades[all_trades["pnl"] > 0]["pnl"].sum() / all_trades[all_trades["pnl"] < 0]["pnl"].sum()) if (all_trades["pnl"] < 0).any() else 10.0
    else:
        all_trades = pd.DataFrame()
        combined_wr = 0
        combined_pf = 0

    # Combined Sharpe (approximate)
    if combined_trades > 0 and len(trades_list) > 0:
        pnls = all_trades["pnl"]
        combined_sharpe = pnls.mean() / pnls.std() * (252 ** 0.5) if pnls.std() > 0 else 0
    else:
        combined_sharpe = 0

    return {
        "total_return_pct": round(combined_return, 2),
        "max_drawdown": round(combined_dd, 2),
        "total_trades": combined_trades,
        "win_rate": round(combined_wr, 2),
        "sharpe_ratio": round(combined_sharpe, 4),
        "profit_factor": round(combined_pf, 4),
        "final_equity": round(combined_equity, 2),
        "trades": all_trades,
        "_normal_days": len(normal_dates),
        "_highvol_days": len(highvol_dates),
        "_normal_return": round(results_normal["total_return_pct"], 2),
        "_4h_return": round(results_4h["total_return_pct"], 2),
    }


# ─── Step-callable BacktestRunner (Phase 5C foundation) ────────────────
# Wraps engine + strategy + dataframe iterator so a Gym env (or any
# bar-by-bar consumer) can drive the backtest one step at a time, with
# per-step "action" multipliers applied to the strategy.
#
# Used by scripts/sentiment_rl_agent.py for PPO training.

class BacktestRunner:
    """Step-callable wrapper around run_backtest's setup.

    Lifecycle:
        runner = BacktestRunner(config_path=None, cfg_overrides={...})
        obs = runner.reset()
        while not done:
            action = agent.predict(obs)
            obs, reward, done, info = runner.step(action)
        results = runner.results()  # final results dict (same shape as run_backtest)

    Action dict (all optional):
        position_size_mult     : float in [0, 2]   — applied to RISK_PER_TRADE
        sentiment_weight_adj   : float in [-0.5, +0.5] — added to INTRADAY_SENTIMENT_WEIGHT
        mr_weight_adj          : float in [-0.5, +0.5] — added to MR_MODE_RISK_MULT
        blackout_strict_mode   : bool — extends MACRO_BLACKOUT_LOOKAHEAD_MIN by 50%
    """

    def __init__(self, config_path=None, cfg_overrides=None,
                 capital_at_risk_floor: float = 1000.0):
        self.cfg = load_config(config_path)
        if cfg_overrides:
            for k, v in cfg_overrides.items():
                setattr(self.cfg, k, v)
        # Save original values so each step's overrides can be rolled back
        self._cfg_originals = {
            "RISK_PER_TRADE": self.cfg.RISK_PER_TRADE,
            "INTRADAY_SENTIMENT_WEIGHT": getattr(self.cfg, "INTRADAY_SENTIMENT_WEIGHT", 0.0),
            "MR_MODE_RISK_MULT": getattr(self.cfg, "MR_MODE_RISK_MULT", 0.4),
            "MACRO_BLACKOUT_LOOKAHEAD_MIN": getattr(self.cfg, "MACRO_BLACKOUT_LOOKAHEAD_MIN", 60),
        }
        self.capital_at_risk_floor = capital_at_risk_floor
        self.df = None
        self.engine = None
        self.strategy = None
        self._iter = None
        self._idx = 0
        self._last_equity = None
        self._done = False

    def _build(self):
        from backtest.engine import BacktestEngine
        cfg = self.cfg
        self.df = load_es_data()  # reuse same loader as run_backtest
        macro_data = load_macro_data()
        nlp_regime = load_nlp_regime()
        digest_ctx = load_digest_context()
        daily_trend = load_daily_es_trend()
        daily_sentiment = load_daily_sentiment()
        garch_forecast = load_garch_forecast()
        particle_regime = load_particle_regime()
        cusum_events, cusum_directions = load_cusum_events()
        tsfresh_signal = load_tsfresh_signal()
        hourly_regime = load_hourly_regime_features()
        ml_entry_signal = load_ml_entry_signal()
        intraday_sentiment = load_intraday_sentiment()
        mag7_breadth = load_mag7_breadth()
        polymarket_signals = load_polymarket_signals()
        macro_calendar = None
        if getattr(cfg, "MACRO_BLACKOUT_ENABLED", False):
            try:
                from tools.macro_calendar import MacroCalendar
                macro_calendar = MacroCalendar()
            except Exception:
                pass

        self.engine = BacktestEngine(
            data=self.df,
            initial_capital=cfg.INITIAL_CAPITAL,
            commission_per_contract=2.25,
            slippage_ticks=1,
            max_position=50,
        )
        self.strategy = ESAutoResearchStrategy(
            cfg, macro_data, nlp_regime, digest_ctx, daily_trend, daily_sentiment,
            garch_forecast, particle_regime, cusum_events, cusum_directions,
            tsfresh_signal, hourly_regime, ml_entry_signal,
            intraday_sentiment=intraday_sentiment, mag7_breadth=mag7_breadth,
            polymarket_signals=polymarket_signals, macro_calendar=macro_calendar,
        )
        self.engine.set_strategy(self.strategy.on_bar)

    def reset(self):
        self._build()
        self._iter = iter(self.df.iterrows())
        self._idx = 0
        self._last_equity = float(self.engine.initial_capital)
        self._done = False
        return self.observation()

    def _apply_action(self, action: dict):
        """Mutate cfg in-place per the agent's action; rolled back at next step."""
        if action is None:
            return
        if "position_size_mult" in action:
            mult = float(action["position_size_mult"])
            self.cfg.RISK_PER_TRADE = max(
                self.capital_at_risk_floor,
                self._cfg_originals["RISK_PER_TRADE"] * max(0.0, mult),
            )
        if "sentiment_weight_adj" in action:
            self.cfg.INTRADAY_SENTIMENT_WEIGHT = max(0.0, min(0.5,
                self._cfg_originals["INTRADAY_SENTIMENT_WEIGHT"]
                + float(action["sentiment_weight_adj"])))
        if "mr_weight_adj" in action:
            self.cfg.MR_MODE_RISK_MULT = max(0.0, min(2.0,
                self._cfg_originals["MR_MODE_RISK_MULT"]
                + float(action["mr_weight_adj"])))
        if action.get("blackout_strict_mode"):
            self.cfg.MACRO_BLACKOUT_LOOKAHEAD_MIN = int(
                self._cfg_originals["MACRO_BLACKOUT_LOOKAHEAD_MIN"] * 1.5
            )
        else:
            self.cfg.MACRO_BLACKOUT_LOOKAHEAD_MIN = self._cfg_originals["MACRO_BLACKOUT_LOOKAHEAD_MIN"]

    def step(self, action=None):
        """Advance one bar. Returns (observation, reward, done, info)."""
        if self._iter is None:
            raise RuntimeError("Call reset() before step()")
        if self._done:
            return self.observation(), 0.0, True, {"warning": "already done"}
        self._apply_action(action)
        try:
            timestamp, row = next(self._iter)
        except StopIteration:
            self._done = True
            return self.observation(), 0.0, True, {"end_of_data": True}
        equity_before = self._last_equity
        equity_after = self.engine.step_one_bar(self._idx, timestamp, row)
        self._idx += 1
        # Reward: change in equity (PnL this bar). Caller can shape further.
        reward = equity_after - (equity_before or self.engine.initial_capital)
        self._last_equity = equity_after
        return self.observation(), float(reward), False, {
            "ts": str(timestamp),
            "equity": equity_after,
            "in_position": not self.engine.position.is_flat,
        }

    def observation(self) -> "list[float]":
        """12-dim state vector for the RL agent.

        Order:
            [vix_tier_norm, atr_pct, bull, bear, side, sentiment_15m, sentiment_24h,
             mag7_breadth, fed_cut_prob, hour_norm, recent_pnl_norm, dd_norm]
        Empty/missing values default to 0 — agent should be robust to that.
        """
        cfg = self.cfg
        ts = self.engine.current_bar.timestamp if self.engine and self.engine.current_bar else None
        # 1. VIX tier (1-7) → normalized
        vix_tier = 2  # default normal
        try:
            vix = _lookup_macro(self.strategy.macro.get("vix", {}), ts) if ts else None
            if vix is not None:
                tiers = [
                    getattr(cfg, "VIX_TIER_1", 16),
                    getattr(cfg, "VIX_TIER_2", 20),
                    getattr(cfg, "VIX_TIER_3", 28),
                    getattr(cfg, "VIX_TIER_4", 35),
                    getattr(cfg, "VIX_TIER_5", 40),
                    getattr(cfg, "VIX_TIER_6", 50),
                ]
                vix_tier = sum(1 for t in tiers if vix > t) + 1
        except Exception:
            pass
        # 2. ATR%
        atr_pct = 0.0
        try:
            if ts is not None:
                from datetime import timedelta as _td
                d = ts.date() if hasattr(ts, "date") else None
                if d is not None and d in self.strategy.daily_trend:
                    info = self.strategy.daily_trend[d]
                    if info.get("daily_atr") and info.get("close", 0) > 0:
                        atr_pct = min(0.05, info["daily_atr"] / info["close"])
        except Exception:
            pass
        # 3. Regime one-hot — best-effort, default SIDE
        bull = bear = 0.0
        side = 1.0
        # 4. Intraday sentiment (15m / 24h)
        sent_15m = sent_24h = 0.0
        try:
            row = _lookup_recent(self.strategy.intraday_sentiment, ts, max_lookback_min=30) if ts else None
            if row is not None:
                sent_15m = float(row.get("sentiment_15m", 0) or 0)
                sent_24h = float(row.get("sentiment_1d", 0) or 0)
        except Exception:
            pass
        # 5. MAG7 breadth
        mag7 = 0.5
        try:
            row = _lookup_recent(self.strategy.mag7_breadth, ts, max_lookback_min=15) if ts else None
            if row is not None:
                mag7 = float(row.get("pct_above_5d_ma", 0.5) or 0.5)
        except Exception:
            pass
        # 6. Fed cut prob (Polymarket)
        fed_cut = 0.0
        try:
            row = _lookup_recent(self.strategy.polymarket_signals, ts, max_lookback_min=30) if ts else None
            if row is not None:
                fed_cut = float(row.get("fed_cut_prob_next", 0) or 0)
        except Exception:
            pass
        # 7. Hour of day (UTC), normalized to [0, 1]
        hour_norm = (ts.hour / 24.0) if (ts is not None and hasattr(ts, "hour")) else 0.5
        # 8. Recent PnL (last bar) — normalized
        recent_pnl = 0.0
        try:
            ec = self.engine.equity_curve
            if len(ec) >= 2:
                recent_pnl = (ec[-1][1] - ec[-2][1]) / max(self.engine.initial_capital, 1)
                recent_pnl = max(-0.05, min(0.05, recent_pnl)) * 20  # scale to ~[-1, +1]
        except Exception:
            pass
        # 9. Drawdown
        dd = 0.0
        try:
            ec = self.engine.equity_curve
            if ec:
                eqs = [e for _, e in ec]
                peak = max(eqs)
                cur = eqs[-1]
                if peak > 0:
                    dd = (peak - cur) / peak
        except Exception:
            pass
        return [
            float(vix_tier / 7.0),
            float(atr_pct * 20),  # 5% ATR → 1.0
            bull, bear, side,
            sent_15m, sent_24h,
            mag7,
            fed_cut,
            float(hour_norm),
            float(recent_pnl),
            float(min(1.0, dd / 0.20)),
        ]

    def results(self) -> dict:
        if not self.engine:
            return {}
        return self.engine.finalize()


def main():
    import argparse as _argparse
    parser = _argparse.ArgumentParser(description="Verify ES strategy and output SCORE.")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to strategy config file (default: es_strategy_config.py)")
    args = parser.parse_args()

    try:
        results = run_backtest(config_path=args.config)
        total_return_pct = results["total_return_pct"]
        max_dd_pct = results["max_drawdown"]
        total_trades = results["total_trades"]
        win_rate = results["win_rate"]
        sharpe = results["sharpe_ratio"]
        pf = results["profit_factor"]
        final_equity = results["final_equity"]

        score_result = compute_robustness_score(
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd_pct,
            total_trades=total_trades,
            win_rate=win_rate,
        )
        score_result["sharpe_ratio"] = round(sharpe, 4)
        score_result["profit_factor"] = round(pf, 4)
        score_result["final_equity"] = round(final_equity, 2)

        if len(results.get("trades", [])) > 0:
            trades_df = results["trades"]
            long_t = trades_df[trades_df["side"] == "LONG"]
            short_t = trades_df[trades_df["side"] == "SHORT"]
            score_result["long_trades"] = len(long_t)
            score_result["short_trades"] = len(short_t)
            score_result["long_pnl"] = round(long_t["pnl"].sum(), 2) if len(long_t) > 0 else 0
            score_result["short_pnl"] = round(short_t["pnl"].sum(), 2) if len(short_t) > 0 else 0
            score_result["avg_bars_held"] = round(trades_df["bars_held"].mean(), 1)

        for k, v in score_result.items():
            if hasattr(v, "item"):
                score_result[k] = v.item()

        print(f"SCORE: {score_result['score']}")
        print(json.dumps(score_result), file=sys.stderr)

    except Exception as e:
        print("SCORE: 0", file=sys.stdout)
        print(json.dumps({"error": str(e), "score": 0}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
