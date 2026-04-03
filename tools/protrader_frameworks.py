"""Pro Macro Trading Frameworks.

Professional macro trading analysis inspired by institutional approaches.
Provides four tools:

1. protrader_risk_premium_analysis — Risk premium expansion/contraction cycle
   with VIX regime, vanna/charm flow state, CTA positioning proxy,
   wall-of-worry phase, volatility compression detection, and opportunity
   score (0-10).

2. protrader_cross_asset_momentum — Cross-asset relative strength analysis
   across BTC, gold, silver, SPX, DXY. Detects divergences and momentum
   failures. Classifies cross-asset regime.

3. protrader_precious_metals_regime — Gold regime classification
   (structural_bid / macro_driven / risk_asset / transitioning), silver
   speculative beta, parabolic advance detection, correction risk score,
   China seasonal calendar.

4. protrader_usd_regime_analysis — USD structural regime and 'American
   exodus' basket (gold up + DXY down + 30Y yields up). DXY SMA analysis,
   30Y yield 5% ceiling, MOVE index, bond-equity correlation regime.

Data sources:
- /macro_2/historical_data/*.csv  — VIX, ES, gold, silver, copper, DXY
- /macro_2/historical_data/us_30y_yield.csv — 30Y Treasury yield (FRED local)
- /btc-enhanced-streak-mitigation/binance-futures-data/data/price.csv — BTC
- tools.fred_data                 — credit spreads, yield curve, 10Y yield
"""

import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tools.config import HISTORICAL_DATA_DIR, BTC_DATA_DIR
from tools.macro_market_analysis import _load_csv, _safe_fred_call
from tools import fred_data
from tools.fred_data import _fetch_series_raw, _series_summary


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _load_daily_close(csv_file: str, price_col: str) -> pd.DataFrame | None:
    """Load a macro CSV and return a clean DataFrame with date + close columns.

    Returns DataFrame with columns: date (datetime), close (float),
    sorted ascending, NaN-dropped. Returns None on failure.
    """
    df = _load_csv(csv_file)
    if df is None or price_col not in df.columns:
        return None
    try:
        date_col = "date" if "date" in df.columns else "timestamp"
        out = pd.DataFrame({
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "close": pd.to_numeric(df[price_col], errors="coerce"),
        }).dropna()
        out = out.sort_values("date", ascending=True).reset_index(drop=True)
        return out
    except Exception:
        return None


def _load_btc_daily() -> pd.DataFrame | None:
    """Load BTC 5min data and resample to daily closes.

    Returns DataFrame with columns: date, close (sorted ascending).
    """
    path = os.path.join(BTC_DATA_DIR, "price.csv")
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.sort_values("timestamp", ascending=True)
        # Keep last 30K rows for performance
        if len(df) > 30000:
            df = df.tail(30000).reset_index(drop=True)
        daily = df.set_index("timestamp").resample("1D").agg({"close": "last"}).dropna().reset_index()
        daily.columns = ["date", "close"]
        # Strip timezone to match macro CSVs (tz-naive)
        if daily["date"].dt.tz is not None:
            daily["date"] = daily["date"].dt.tz_localize(None)
        return daily
    except Exception:
        return None


def _compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Compute Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _compute_roc(series: pd.Series, period: int = 20) -> pd.Series:
    """Compute Rate of Change (%)."""
    shifted = series.shift(period)
    return ((series - shifted) / shifted) * 100


def _percentile_rank(series: pd.Series, current: float) -> float:
    """Compute percentile rank of current within series."""
    valid = series.dropna()
    if len(valid) == 0:
        return 50.0
    count_below = (valid < current).sum()
    return round(float(count_below) / len(valid) * 100, 1)


def _vix_tier(level: float) -> int:
    """7-tier VIX classification matching market_regime_enhanced."""
    if level >= 40:
        return 7  # Crisis
    elif level >= 30:
        return 6  # Panic
    elif level >= 25:
        return 5  # High stress
    elif level >= 20:
        return 4  # Elevated
    elif level >= 16:
        return 3  # Normal
    elif level >= 13:
        return 2  # Low
    else:
        return 1  # Suppressed


def _compute_bb_width(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series | None:
    """Compute Bollinger Band width (upper - lower).

    Returns a Series of BB widths, or None if insufficient data.
    """
    if len(series) < window:
        return None
    sma = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return upper - lower


def _load_30y_yield() -> pd.DataFrame | None:
    """Load 30Y Treasury yield from local CSV (FRED-sourced).

    Returns DataFrame with columns: date, close (sorted ascending).
    """
    return _load_daily_close("us_30y_yield.csv", "us_30y_yield")


def _align_by_date(*dfs: pd.DataFrame) -> pd.DataFrame:
    """Align multiple DataFrames by date via inner join.

    Each input must have 'date' and 'close' columns.
    Output has 'date' index and one column per input named close_0, close_1, etc.
    """
    if not dfs:
        return pd.DataFrame()

    def _normalize_dates(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
        """Strip timezone + normalize to date-only for clean merging."""
        out = df[["date", "close"]].copy()
        if out["date"].dt.tz is not None:
            out["date"] = out["date"].dt.tz_localize(None)
        out["date"] = out["date"].dt.normalize()
        return out.rename(columns={"close": col_name})

    merged = _normalize_dates(dfs[0], "close_0")
    for i, df in enumerate(dfs[1:], start=1):
        right = _normalize_dates(df, f"close_{i}")
        merged = pd.merge(merged, right, on="date", how="inner")
    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


# ═══════════════════════════════════════════════════════════════════════
# TOOL 1: RISK PREMIUM ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def protrader_risk_premium_analysis() -> str:
    """Analyze the risk premium expansion/contraction cycle.

    Assesses VIX regime + direction, vanna/charm flow state (dealer delta
    hedging unwinds), CTA positioning proxy (ES distance from key moving
    averages), credit state, wall-of-worry phase classification, and a
    composite opportunity score (0-10).

    Key insight: VIX > 30 falling = stored buying energy via vanna/charm.
    VIX < 16 = complacency, setup for shorts. CTAs fully deployed above
    200SMA = buying power depleted.

    Returns:
        JSON string with risk_premium_state, vix_regime, vanna_charm_regime,
        cta_proxy, credit_state, wall_of_worry_phase, opportunity_score,
        signals, and summary.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── VIX Data ──
    vix_df = _load_daily_close("vix_move.csv", "vix")
    vix_regime = {}
    vix_level = None
    vix_direction = "unknown"
    vix_tier_val = 3
    days_since_peak = None

    if vix_df is not None and len(vix_df) >= 20:
        vix_level = float(vix_df["close"].iloc[-1])
        vix_tier_val = _vix_tier(vix_level)

        # 1Y percentile
        last_252 = vix_df["close"].tail(252)
        pctile = _percentile_rank(last_252, vix_level)

        # 5-day direction
        if len(vix_df) >= 6:
            vix_5d_ago = float(vix_df["close"].iloc[-6])
            vix_5d_change = vix_level - vix_5d_ago
            if vix_5d_change < -1.5:
                vix_direction = "falling"
            elif vix_5d_change > 1.5:
                vix_direction = "rising"
            else:
                vix_direction = "stable"

        # Days since 60-day peak
        last_60 = vix_df.tail(60)
        peak_idx = last_60["close"].idxmax()
        peak_date = last_60.loc[peak_idx, "date"]
        latest_date = vix_df["date"].iloc[-1]
        days_since_peak = max(0, (latest_date - peak_date).days)
        peak_level = float(last_60["close"].max())

        vix_regime = {
            "level": round(vix_level, 1),
            "percentile_1y": pctile,
            "tier": vix_tier_val,
            "direction": vix_direction,
            "days_since_peak": days_since_peak,
            "peak_60d": round(peak_level, 1),
        }
    else:
        vix_regime = {"error": "Insufficient VIX data"}

    result["vix_regime"] = vix_regime

    # ── Vanna/Charm Regime ──
    # VIX falling from elevated levels → dealer delta-hedging unwinds → buying pressure
    vanna_charm = {}
    if vix_level is not None:
        if vix_level >= 30 and vix_direction == "falling":
            vc_state = "high_buying_pressure"
            vc_interp = (
                "VIX falling from >30 — massive dealer delta-hedging unwinds "
                "creating strong buying pressure in ES. Vanna+charm flows very supportive."
            )
        elif 20 <= vix_level < 30 and vix_direction == "falling":
            vc_state = "moderate_buying_pressure"
            vc_interp = (
                "VIX falling from elevated levels — dealer hedging unwinds "
                "generating moderate buying pressure. Vanna+charm flows supportive."
            )
        elif vix_level >= 25 and vix_direction == "rising":
            vc_state = "selling_pressure"
            vc_interp = (
                "VIX rising rapidly — dealers adding hedges creating selling "
                "pressure. Vanna+charm flows negative for equities."
            )
        elif vix_level < 16 and vix_direction in ("stable", "falling"):
            vc_state = "complacency"
            vc_interp = (
                "VIX suppressed and stable — complacency zone. Minimal flow "
                "effects but vulnerability to vol spike is elevated."
            )
            signals.append("COMPLACENCY_WARNING")
        else:
            vc_state = "neutral"
            vc_interp = (
                "VIX in normal range — vanna/charm flows are present but not "
                "a dominant force. Standard two-way market."
            )

        if vc_state in ("high_buying_pressure", "moderate_buying_pressure"):
            signals.append("VANNA_CHARM_BUYING")

        vanna_charm = {"state": vc_state, "interpretation": vc_interp}
    else:
        vanna_charm = {"state": "unknown", "interpretation": "VIX data unavailable."}

    result["vanna_charm_regime"] = vanna_charm

    # ── CTA Proxy (ES vs key moving averages) ──
    es_df = _load_daily_close("es_futures.csv", "es_price")
    cta_proxy = {}
    cta_state = "unknown"

    if es_df is not None and len(es_df) >= 200:
        es_price = float(es_df["close"].iloc[-1])
        sma_50 = float(_compute_sma(es_df["close"], 50).iloc[-1])
        sma_200 = float(_compute_sma(es_df["close"], 200).iloc[-1])

        pct_vs_200 = ((es_price - sma_200) / sma_200) * 100
        pct_vs_50 = ((es_price - sma_50) / sma_50) * 100

        if pct_vs_200 > 5:
            cta_state = "fully_deployed"
            cta_interp = (
                f"ES {pct_vs_200:+.1f}% above 200SMA — CTAs fully deployed, "
                "buying power depleted. Downside asymmetry elevated."
            )
            signals.append("CTA_FULLY_DEPLOYED")
        elif pct_vs_200 > 0:
            cta_state = "partially_deployed"
            cta_interp = (
                f"ES {pct_vs_200:+.1f}% above 200SMA — CTAs partially deployed. "
                "Some remaining buying potential if trend strengthens."
            )
        elif pct_vs_200 > -5:
            cta_state = "deleveraging"
            cta_interp = (
                f"ES {pct_vs_200:+.1f}% vs 200SMA — CTAs deleveraging. "
                "Selling pressure from trend-following systems."
            )
            signals.append("CTA_DELEVERAGING")
        else:
            cta_state = "buying_potential"
            cta_interp = (
                f"ES {pct_vs_200:+.1f}% below 200SMA — CTAs have substantial "
                "buying potential when trend reverses. Watch for 200SMA reclaim."
            )
            signals.append("CTA_BUYING_POTENTIAL")

        cta_proxy = {
            "state": cta_state,
            "es_price": round(es_price, 1),
            "sma_50": round(sma_50, 1),
            "sma_200": round(sma_200, 1),
            "es_vs_200sma_pct": round(pct_vs_200, 1),
            "es_vs_50sma_pct": round(pct_vs_50, 1),
            "interpretation": cta_interp,
        }
    else:
        cta_proxy = {"state": "unknown", "interpretation": "Insufficient ES data for CTA proxy."}

    result["cta_proxy"] = cta_proxy

    # ── Credit State ──
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    credit_state = {}

    if credit_data and "high_yield_oas" in credit_data:
        hy = credit_data["high_yield_oas"]
        hy_val = hy.get("latest_value")

        if hy_val is not None:
            # Use regime-aware stress_level from fred_data
            stress = hy.get("stress_level", "normal")
            if stress in ("crisis", "severe_stress"):
                signals.append("CREDIT_STRESS_SEVERE")
            elif stress in ("stressed", "elevated"):
                signals.append("CREDIT_STRESS_ELEVATED")

            # Direction from week-over-week change
            wow = hy.get("wow_change_bps", 0)
            if wow > 20:
                direction = "widening"
            elif wow < -20:
                direction = "tightening"
            else:
                direction = "stable"

            credit_state = {
                "hy_oas_bps": round(hy_val * 100, 0),
                "hy_oas_pct": round(hy_val, 2),
                "direction": direction,
                "stress_level": stress,
                "interpretation": hy.get("interpretation", ""),
            }
        else:
            credit_state = {"error": "HY OAS value unavailable"}
    else:
        credit_state = {"error": "Credit spread data unavailable"}

    result["credit_state"] = credit_state

    # ── Wall of Worry Phase ──
    # fear → recovery → climbing → complacency
    credit_stress = credit_state.get("stress_level", "normal")
    credit_dir = credit_state.get("direction", "stable")

    if vix_level is not None:
        if vix_tier_val >= 5 and credit_stress in ("elevated", "severe"):
            phase = "fear"
            phase_interp = (
                "Fear phase — VIX elevated + credit widening. "
                "Opportunities building for contrarian longs once flow reverses."
            )
            signals.append("WALL_FEAR")
        elif vix_direction == "falling" and vix_tier_val >= 4:
            phase = "recovery"
            phase_interp = (
                "Recovery phase — VIX falling from elevated levels. "
                "Buying phase as vanna/charm flows support equities."
            )
            signals.append("WALL_RECOVERY")
        elif vix_tier_val <= 3 and cta_state == "fully_deployed" and credit_stress == "tight":
            phase = "complacency"
            phase_interp = (
                "Complacency phase — VIX low, CTAs fully deployed, credit tight. "
                "Maximum vulnerability to shock. Position for asymmetric downside."
            )
            signals.append("WALL_COMPLACENCY")
        else:
            phase = "climbing"
            phase_interp = (
                "Climbing phase — normal VIX with trending market. "
                "Standard bull market conditions with reasonable risk premium."
            )
            signals.append("WALL_CLIMBING")
    else:
        phase = "unknown"
        phase_interp = "Insufficient data for phase classification."

    result["wall_of_worry_phase"] = phase
    result["wall_of_worry_interpretation"] = phase_interp

    # ── Risk Premium State ──
    if vix_level is not None:
        if vix_direction == "falling" and vix_tier_val >= 4:
            rp_state = "contracting"
        elif vix_direction == "rising" and vix_tier_val >= 4:
            rp_state = "expanding"
        elif vix_tier_val <= 2:
            rp_state = "compressed"
        else:
            rp_state = "neutral"
    else:
        rp_state = "unknown"

    result["risk_premium_state"] = rp_state

    # ── Opportunity Score (0-10) ──
    # High score = buy-the-dip opportunity. Inverted: high when VIX elevated + falling.
    # Components: VIX opportunity (0.25), vanna/charm (0.25), CTA buying potential (0.25), credit (0.25)

    vix_opp = 0
    if vix_level is not None:
        if vix_tier_val >= 6 and vix_direction == "falling":
            vix_opp = 10
        elif vix_tier_val >= 5 and vix_direction == "falling":
            vix_opp = 8
        elif vix_tier_val >= 4 and vix_direction == "falling":
            vix_opp = 6
        elif vix_tier_val >= 5:
            vix_opp = 5  # Elevated but not falling yet
        elif vix_tier_val <= 2:
            vix_opp = 1  # Complacent — no opportunity
        else:
            vix_opp = 3

    vc_opp = 0
    vc_s = vanna_charm.get("state", "unknown")
    if vc_s == "high_buying_pressure":
        vc_opp = 10
    elif vc_s == "moderate_buying_pressure":
        vc_opp = 7
    elif vc_s == "selling_pressure":
        vc_opp = 4
    elif vc_s == "complacency":
        vc_opp = 1
    else:
        vc_opp = 3

    cta_opp = 0
    if cta_state == "buying_potential":
        cta_opp = 10
    elif cta_state == "deleveraging":
        cta_opp = 6
    elif cta_state == "partially_deployed":
        cta_opp = 4
    elif cta_state == "fully_deployed":
        cta_opp = 1
    else:
        cta_opp = 3

    credit_opp = 0
    if credit_stress == "severe":
        credit_opp = 8  # Contrarian opportunity if not systemic
    elif credit_stress == "elevated":
        credit_opp = 6
    elif credit_stress == "normal":
        credit_opp = 3
    elif credit_stress == "tight":
        credit_opp = 1  # No opportunity — already priced in
    else:
        credit_opp = 3

    opp_score = round(vix_opp * 0.25 + vc_opp * 0.25 + cta_opp * 0.25 + credit_opp * 0.25, 1)

    result["opportunity_score"] = opp_score
    result["opportunity_components"] = {
        "vix_opportunity": vix_opp,
        "vanna_charm_opportunity": vc_opp,
        "cta_buying_potential": cta_opp,
        "credit_opportunity": credit_opp,
    }

    # ── Volatility Compression Detection ──
    vol_comp = {}
    if vix_df is not None and len(vix_df) >= 80:
        vix_closes = vix_df["close"]
        bb_width = _compute_bb_width(vix_closes, window=20, num_std=2.0)
        if bb_width is not None and len(bb_width.dropna()) >= 60:
            current_bb_w = float(bb_width.iloc[-1])
            last_60 = bb_width.tail(60).dropna()
            bb_pctile = _percentile_rank(last_60, current_bb_w)

            compressed = bb_pctile < 20
            if bb_pctile < 10:
                signals.append("VOL_COMPRESSION_EXTREME")
            elif compressed:
                signals.append("VOL_COMPRESSION")

            if compressed:
                vc_interp = (
                    f"VIX Bollinger Band width at {bb_pctile:.0f}th percentile of "
                    "60-day range — volatility highly compressed. Explosive move likely."
                )
            else:
                vc_interp = (
                    f"VIX Bollinger Band width at {bb_pctile:.0f}th percentile — "
                    "normal volatility regime."
                )

            vol_comp = {
                "vix_bb_width_20d": round(current_bb_w, 2),
                "vix_bb_width_percentile_60d": round(bb_pctile, 0),
                "compressed": compressed,
                "interpretation": vc_interp,
            }
        else:
            vol_comp = {"error": "Insufficient VIX data for BB width computation."}
    else:
        vol_comp = {"error": "Insufficient VIX data for volatility compression."}

    result["vol_compression"] = vol_comp

    result["signals"] = signals

    # ── Summary ──
    parts = [f"Risk premium {rp_state}."]
    if vix_level is not None:
        parts.append(
            f"VIX at {vix_level:.1f} (tier {vix_tier_val}, {vix_direction}), "
            f"wall of worry in '{phase}' phase."
        )
    parts.append(f"Opportunity score: {opp_score}/10.")
    if "VANNA_CHARM_BUYING" in signals:
        parts.append("Vanna/charm flows supportive.")
    if "CTA_FULLY_DEPLOYED" in signals:
        parts.append("CTAs fully deployed — buying power depleted.")
    if "CTA_BUYING_POTENTIAL" in signals:
        parts.append("CTAs have substantial buying potential.")
    if "COMPLACENCY_WARNING" in signals:
        parts.append("VIX in complacency zone — vulnerability elevated.")
    if "VOL_COMPRESSION_EXTREME" in signals:
        parts.append("VOLATILITY COMPRESSED — explosive move imminent.")
    elif "VOL_COMPRESSION" in signals:
        parts.append("Volatility compressed — breakout potential building.")
    result["summary"] = " ".join(parts)

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# TOOL 2: CROSS-ASSET MOMENTUM
# ═══════════════════════════════════════════════════════════════════════

def protrader_cross_asset_momentum() -> str:
    """Analyze cross-asset relative strength, correlations, and divergences.

    Computes relative strength ratios (BTC/SPX, gold/SPX, BTC/gold,
    silver/gold), 20-day rolling correlations, detects crypto-macro
    divergences and momentum failures (price new high + RSI declining).
    Classifies cross-asset regime.

    Key insight: persistent BTC underperformance vs SPX leads broader risk.
    Silver/gold ratio spikes signal speculative excess.

    Returns:
        JSON string with relative_strength, correlations_20d, divergences,
        momentum_failures, regime_summary, signals, and summary.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Load all asset data ──
    assets = {
        "spx": _load_daily_close("es_futures.csv", "es_price"),
        "gold": _load_daily_close("gold.csv", "gold_price"),
        "silver": _load_daily_close("silver.csv", "silver_price"),
        "copper": _load_daily_close("copper.csv", "copper_price"),
        "dxy": _load_daily_close("dxy.csv", "dxy"),
        "btc": _load_btc_daily(),
    }

    # Check data availability
    available = {k: v for k, v in assets.items() if v is not None and len(v) >= 30}
    missing = [k for k, v in assets.items() if k not in available]
    if missing:
        result["data_warnings"] = f"Missing or insufficient data: {', '.join(missing)}"

    # ── 20-day Returns ──
    returns_20d = {}
    for name, df in available.items():
        if len(df) >= 21:
            current = float(df["close"].iloc[-1])
            ago_20 = float(df["close"].iloc[-21])
            ret = ((current - ago_20) / ago_20) * 100
            returns_20d[name] = round(ret, 2)
    result["returns_20d"] = returns_20d

    # ── Relative Strength Ratios ──
    pairs = [
        ("btc", "spx", "btc_vs_spx"),
        ("gold", "spx", "gold_vs_spx"),
        ("btc", "gold", "btc_vs_gold"),
        ("silver", "gold", "silver_vs_gold"),
    ]

    rel_strength = {}
    for a_name, b_name, label in pairs:
        a_df = available.get(a_name)
        b_df = available.get(b_name)
        if a_df is None or b_df is None:
            continue
        merged = _align_by_date(a_df, b_df)
        if len(merged) < 21:
            continue

        ratio_current = float(merged["close_0"].iloc[-1] / merged["close_1"].iloc[-1])
        ratio_20d_ago = float(merged["close_0"].iloc[-21] / merged["close_1"].iloc[-21])
        pct_change = ((ratio_current - ratio_20d_ago) / ratio_20d_ago) * 100

        if pct_change < -5:
            trend = f"{a_name}_underperforming"
        elif pct_change > 5:
            trend = f"{a_name}_outperforming"
        else:
            trend = "stable"

        # Signal detection
        signal = None
        if label == "btc_vs_spx" and pct_change < -5:
            signal = "CRYPTO_CYCLE_WEAKENING"
            signals.append(signal)
        elif label == "btc_vs_spx" and pct_change > 8:
            signal = "CRYPTO_CYCLE_STRENGTHENING"
            signals.append(signal)
        elif label == "gold_vs_spx" and pct_change > 8:
            signal = "GOLD_OUTPERFORMANCE"
            signals.append(signal)
        elif label == "silver_vs_gold" and pct_change > 10:
            signal = "SILVER_SPECULATIVE_EXCESS"
            signals.append(signal)

        rel_strength[label] = {
            "ratio_current": round(ratio_current, 4),
            "ratio_20d_ago": round(ratio_20d_ago, 4),
            "pct_change": round(pct_change, 1),
            "trend": trend,
            "signal": signal,
        }

    result["relative_strength"] = rel_strength

    # ── 20-day Correlations ──
    corr_pairs = [
        ("btc", "spx", "btc_spx"),
        ("gold", "spx", "gold_spx"),
        ("gold", "dxy", "gold_dxy"),
        ("silver", "gold", "silver_gold"),
        ("copper", "spx", "copper_spx"),
    ]

    correlations = {}
    for a_name, b_name, label in corr_pairs:
        a_df = available.get(a_name)
        b_df = available.get(b_name)
        if a_df is None or b_df is None:
            continue
        merged = _align_by_date(a_df, b_df)
        if len(merged) < 20:
            continue

        # 20-day returns correlation
        ret_a = merged["close_0"].pct_change().tail(20).dropna()
        ret_b = merged["close_1"].pct_change().tail(20).dropna()
        if len(ret_a) >= 15 and len(ret_b) >= 15:
            corr = float(ret_a.corr(ret_b))
            correlations[label] = round(corr, 2) if not np.isnan(corr) else None

    result["correlations_20d"] = correlations

    # ── Divergence Detection ──
    divergences = []

    # Crypto-macro divergence
    btc_ret = returns_20d.get("btc")
    spx_ret = returns_20d.get("spx")
    if btc_ret is not None and spx_ret is not None:
        if btc_ret < -5 and spx_ret > 1:
            divergences.append({
                "type": "crypto_macro_divergence",
                "description": (
                    f"BTC {btc_ret:+.1f}% while SPX {spx_ret:+.1f}% over 20 days — "
                    "persistent underperformance signals crypto cycle weakening"
                ),
                "severity": "high" if abs(btc_ret - spx_ret) > 10 else "moderate",
            })
        elif btc_ret > 10 and spx_ret < -2:
            divergences.append({
                "type": "crypto_leads_risk_on",
                "description": (
                    f"BTC {btc_ret:+.1f}% while SPX {spx_ret:+.1f}% — "
                    "crypto leading risk appetite higher, potential catch-up trade in equities"
                ),
                "severity": "moderate",
            })

    # Gold-dollar divergence (gold rising with dollar = structural bid)
    gold_ret = returns_20d.get("gold")
    dxy_ret = returns_20d.get("dxy")
    if gold_ret is not None and dxy_ret is not None:
        if gold_ret > 3 and dxy_ret > 1:
            divergences.append({
                "type": "gold_dollar_divergence",
                "description": (
                    f"Gold {gold_ret:+.1f}% with DXY {dxy_ret:+.1f}% — "
                    "traditional inverse relationship broken. Price-insensitive demand."
                ),
                "severity": "high",
            })
            signals.append("GOLD_DOLLAR_DIVERGENCE")

    # Copper-equity divergence (Dr. Copper leading indicator)
    copper_ret = returns_20d.get("copper")
    if copper_ret is not None and spx_ret is not None:
        if copper_ret < -5 and spx_ret > 2:
            divergences.append({
                "type": "copper_equity_divergence",
                "description": (
                    f"Copper {copper_ret:+.1f}% while SPX {spx_ret:+.1f}% — "
                    "Dr. Copper warning: growth expectations deteriorating"
                ),
                "severity": "high",
            })
            signals.append("DR_COPPER_WARNING")

    result["divergences"] = divergences

    # ── Momentum Failures (RSI divergence) ──
    momentum_failures = []

    for name, df in available.items():
        if len(df) < 60:
            continue
        closes = df["close"]
        rsi = _compute_rsi(closes)
        if rsi.isna().all():
            continue

        current_rsi = float(rsi.iloc[-1])
        # Check if price made a new 20-day high
        recent_high = float(closes.tail(20).max())
        current_price = float(closes.iloc[-1])
        prev_rsi_peak = float(rsi.iloc[-21:-1].max()) if len(rsi) > 21 else current_rsi

        # Bearish divergence: new 20d high in price but RSI declining
        if (current_price >= recent_high * 0.998  # Within 0.2% of high
                and current_rsi < prev_rsi_peak - 5  # RSI lower by 5+
                and current_rsi > 50):  # Still in upper territory
            momentum_failures.append({
                "asset": name,
                "type": "price_new_high_rsi_divergence",
                "description": (
                    f"{name.upper()} near 20d high but RSI declining "
                    f"({current_rsi:.0f} vs recent peak {prev_rsi_peak:.0f}) — bearish divergence"
                ),
                "rsi_current": round(current_rsi, 1),
                "rsi_recent_peak": round(prev_rsi_peak, 1),
            })
            signals.append(f"{name.upper()}_RSI_DIVERGENCE")

        # Bullish divergence: new 20d low but RSI rising
        recent_low = float(closes.tail(20).min())
        prev_rsi_trough = float(rsi.iloc[-21:-1].min()) if len(rsi) > 21 else current_rsi
        if (current_price <= recent_low * 1.002
                and current_rsi > prev_rsi_trough + 5
                and current_rsi < 50):
            momentum_failures.append({
                "asset": name,
                "type": "price_new_low_rsi_divergence",
                "description": (
                    f"{name.upper()} near 20d low but RSI rising "
                    f"({current_rsi:.0f} vs recent trough {prev_rsi_trough:.0f}) — bullish divergence"
                ),
                "rsi_current": round(current_rsi, 1),
                "rsi_recent_trough": round(prev_rsi_trough, 1),
            })
            signals.append(f"{name.upper()}_BULLISH_DIVERGENCE")

    result["momentum_failures"] = momentum_failures

    # ── Cross-Asset Regime Classification ──
    positive_count = sum(1 for v in returns_20d.values() if v > 2)
    negative_count = sum(1 for v in returns_20d.values() if v < -2)
    total = len(returns_20d)

    gold_up = returns_20d.get("gold", 0) > 2
    btc_up = returns_20d.get("btc", 0) > 2
    dxy_down = returns_20d.get("dxy", 0) < -1

    if total == 0:
        regime = "unknown"
    elif positive_count >= total * 0.7:
        regime = "risk_on_broad"
        signals.append("BROAD_RISK_ON")
    elif negative_count >= total * 0.7:
        regime = "risk_off_broad"
        signals.append("BROAD_RISK_OFF")
    elif gold_up and btc_up and dxy_down:
        regime = "liquidity_driven"
        signals.append("LIQUIDITY_DRIVEN")
    elif positive_count >= 2 and negative_count >= 2:
        regime = "divergent"
        signals.append("DIVERGENT_REGIME")
    else:
        regime = "risk_on_selective"
        signals.append("SELECTIVE_RISK_ON")

    result["regime_summary"] = regime
    result["signals"] = signals

    # ── Summary ──
    parts = [f"Cross-asset regime: {regime.replace('_', ' ')}."]
    if returns_20d:
        sorted_rets = sorted(returns_20d.items(), key=lambda x: x[1], reverse=True)
        leader = sorted_rets[0]
        laggard = sorted_rets[-1]
        parts.append(
            f"Leader: {leader[0].upper()} ({leader[1]:+.1f}%), "
            f"Laggard: {laggard[0].upper()} ({laggard[1]:+.1f}%)."
        )
    if divergences:
        parts.append(f"{len(divergences)} divergence(s) detected.")
    if momentum_failures:
        parts.append(f"{len(momentum_failures)} momentum failure(s) detected.")
    result["summary"] = " ".join(parts)

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# TOOL 3: PRECIOUS METALS REGIME
# ═══════════════════════════════════════════════════════════════════════

def protrader_precious_metals_regime() -> str:
    """Analyze the precious metals regime: gold classification, silver beta,
    parabolic detection, correction risk, and seasonal calendar.

    Classifies gold into one of four regimes:
    - structural_bid: gold rising despite dollar/yield strength (central bank
      buying, dedollarization). Correlation breakdown.
    - macro_driven: gold following yields/dollar inversely (normal regime).
    - risk_asset: gold falling with risk assets (liquidation/margin call).
    - transitioning: correlations breaking down, regime unclear.

    Key insight: when gold-DXY correlation turns positive, price-insensitive
    demand (central banks) is overriding traditional macro drivers.

    Returns:
        JSON string with gold_regime, silver_analysis, parabolic_detection,
        correction_risk, seasonal, signals, and summary.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Load Data ──
    gold_df = _load_daily_close("gold.csv", "gold_price")
    silver_df = _load_daily_close("silver.csv", "silver_price")
    dxy_df = _load_daily_close("dxy.csv", "dxy")
    spx_df = _load_daily_close("es_futures.csv", "es_price")

    # ── Gold Regime Classification ──
    gold_regime = {}

    if gold_df is not None and len(gold_df) >= 30:
        gold_close = gold_df["close"]
        gold_current = float(gold_close.iloc[-1])

        # Gold-DXY 20d correlation
        gold_dxy_corr = None
        if dxy_df is not None and len(dxy_df) >= 30:
            merged = _align_by_date(gold_df, dxy_df)
            if len(merged) >= 20:
                ret_g = merged["close_0"].pct_change().tail(20).dropna()
                ret_d = merged["close_1"].pct_change().tail(20).dropna()
                if len(ret_g) >= 15:
                    c = ret_g.corr(ret_d)
                    gold_dxy_corr = round(float(c), 2) if not np.isnan(c) else None

        # Gold-10Y yield 20d correlation (via FRED)
        gold_10y_corr = None
        try:
            obs_10y = _fetch_series_raw("DGS10", limit=30, sort_order="desc")
            if obs_10y and len(obs_10y) >= 20:
                yield_df = pd.DataFrame(obs_10y)
                yield_df["date"] = pd.to_datetime(yield_df["date"])
                yield_df = yield_df.rename(columns={"value": "close"})
                yield_df = yield_df.sort_values("date", ascending=True).reset_index(drop=True)
                merged_y = _align_by_date(gold_df, yield_df)
                if len(merged_y) >= 20:
                    ret_gy = merged_y["close_0"].pct_change().tail(20).dropna()
                    ret_yy = merged_y["close_1"].pct_change().tail(20).dropna()
                    if len(ret_gy) >= 15:
                        c = ret_gy.corr(ret_yy)
                        gold_10y_corr = round(float(c), 2) if not np.isnan(c) else None
        except Exception:
            pass

        # Gold-SPX 20d correlation (for risk-asset mode detection)
        gold_spx_corr = None
        gold_spx_both_falling = False
        if spx_df is not None and len(spx_df) >= 30:
            merged_s = _align_by_date(gold_df, spx_df)
            if len(merged_s) >= 20:
                ret_gs = merged_s["close_0"].pct_change().tail(20).dropna()
                ret_ss = merged_s["close_1"].pct_change().tail(20).dropna()
                if len(ret_gs) >= 15:
                    c = ret_gs.corr(ret_ss)
                    gold_spx_corr = round(float(c), 2) if not np.isnan(c) else None

                # Check if both are falling (liquidation regime)
                gold_20d_ret = ((float(merged_s["close_0"].iloc[-1]) -
                                 float(merged_s["close_0"].iloc[-21])) /
                                float(merged_s["close_0"].iloc[-21]) * 100) if len(merged_s) >= 21 else 0
                spx_20d_ret = ((float(merged_s["close_1"].iloc[-1]) -
                                float(merged_s["close_1"].iloc[-21])) /
                                float(merged_s["close_1"].iloc[-21]) * 100) if len(merged_s) >= 21 else 0
                gold_spx_both_falling = gold_20d_ret < -3 and spx_20d_ret < -3

        # Classification logic
        if gold_spx_both_falling and (gold_spx_corr is not None and gold_spx_corr > 0.4):
            classification = "risk_asset"
            evidence = (
                "Gold falling alongside equities — liquidation/margin call regime. "
                "Traditional safe-haven status temporarily suspended."
            )
            signals.append("GOLD_RISK_ASSET_MODE")
        elif gold_dxy_corr is not None and gold_dxy_corr > -0.1:
            classification = "structural_bid"
            evidence = (
                f"Gold-DXY 20d correlation at {gold_dxy_corr} (normally -0.4 to -0.6). "
                "Traditional inverse relationship broken — price-insensitive demand "
                "(central banks, dedollarization) overriding macro drivers."
            )
            signals.append("STRUCTURAL_BID_REGIME")
        elif gold_dxy_corr is not None and gold_dxy_corr < -0.3:
            classification = "macro_driven"
            evidence = (
                f"Gold-DXY 20d correlation at {gold_dxy_corr} — normal inverse relationship intact. "
                "Gold following traditional macro drivers (yields, dollar)."
            )
        else:
            classification = "transitioning"
            evidence = (
                "Gold-DXY correlation in ambiguous zone — regime transitioning. "
                "Monitor for breakout in either direction."
            )

        gold_regime = {
            "classification": classification,
            "gold_dxy_20d_corr": gold_dxy_corr,
            "gold_10y_20d_corr": gold_10y_corr,
            "gold_spx_20d_corr": gold_spx_corr,
            "gold_price": round(gold_current, 1),
            "evidence": evidence,
        }
    else:
        gold_regime = {"error": "Insufficient gold data"}

    result["gold_regime"] = gold_regime

    # ── Silver Analysis ──
    silver_analysis = {}

    if (silver_df is not None and gold_df is not None
            and len(silver_df) >= 30 and len(gold_df) >= 30):
        merged_sg = _align_by_date(silver_df, gold_df)
        if len(merged_sg) >= 21:
            silver_price = float(merged_sg["close_0"].iloc[-1])
            gold_price = float(merged_sg["close_1"].iloc[-1])

            # Silver/gold ratio
            sg_ratio = silver_price / gold_price
            # 1Y percentile of ratio
            ratios_all = merged_sg["close_0"] / merged_sg["close_1"]
            last_252 = ratios_all.tail(252)
            ratio_pctile = _percentile_rank(last_252, sg_ratio)

            # Silver beta: 20d window regression of silver returns on gold returns
            sg_ret_s = merged_sg["close_0"].pct_change().tail(20).dropna()
            sg_ret_g = merged_sg["close_1"].pct_change().tail(20).dropna()
            silver_beta = None
            if len(sg_ret_s) >= 15 and len(sg_ret_g) >= 15:
                # Simple beta: cov(s,g) / var(g)
                cov = sg_ret_s.cov(sg_ret_g)
                var_g = sg_ret_g.var()
                if var_g > 0:
                    silver_beta = round(float(cov / var_g), 2)

            # Speculative overlay classification
            if silver_beta is not None:
                if silver_beta > 2.0:
                    spec_overlay = "high"
                    signals.append("SILVER_HIGH_BETA")
                elif silver_beta > 1.3:
                    spec_overlay = "moderate"
                else:
                    spec_overlay = "low"
            else:
                spec_overlay = "unknown"

            interp_parts = []
            if silver_beta is not None:
                interp_parts.append(f"Silver running {silver_beta:.1f}x gold's moves")
            if spec_overlay == "high":
                interp_parts.append("speculative positioning elevated. Vulnerable to hawkish Fed.")
            elif spec_overlay == "moderate":
                interp_parts.append("moderate speculative overlay.")
            else:
                interp_parts.append("limited speculative overlay.")

            silver_analysis = {
                "silver_price": round(silver_price, 2),
                "gold_price": round(gold_price, 1),
                "silver_gold_ratio": round(sg_ratio, 5),
                "ratio_percentile_1y": ratio_pctile,
                "silver_beta_20d": silver_beta,
                "speculative_overlay": spec_overlay,
                "interpretation": " — ".join(interp_parts),
            }
    else:
        silver_analysis = {"error": "Insufficient silver/gold data"}

    result["silver_analysis"] = silver_analysis

    # ── Parabolic Detection ──
    parabolic = {}

    if gold_df is not None and len(gold_df) >= 60:
        closes = gold_df["close"]

        # Rate of change (20d)
        roc_20 = _compute_roc(closes, 20)
        current_roc = float(roc_20.iloc[-1]) if not np.isnan(roc_20.iloc[-1]) else 0

        # RoC acceleration (RoC of RoC) — compare current RoC to RoC 10 days ago
        roc_10d_ago = float(roc_20.iloc[-11]) if len(roc_20) >= 11 and not np.isnan(roc_20.iloc[-11]) else 0
        acceleration = current_roc - roc_10d_ago

        # RSI
        rsi = _compute_rsi(closes)
        current_rsi = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50

        # Parabolic: RoC > 15% AND acceleration > 3
        is_parabolic = current_roc > 15 and acceleration > 3

        if is_parabolic:
            signals.append("GOLD_PARABOLIC_ADVANCE")
        if current_rsi > 80:
            signals.append("GOLD_RSI_EXTREME")

        parabolic = {
            "gold_roc_20d": round(current_roc, 1),
            "gold_roc_acceleration": round(acceleration, 1),
            "is_parabolic": is_parabolic,
            "rsi_14d": round(current_rsi, 1),
            "rsi_extreme": current_rsi > 80,
        }
    else:
        parabolic = {"error": "Insufficient gold data for parabolic detection"}

    result["parabolic_detection"] = parabolic

    # ── Correction Risk Score (0-10) ──
    correction_risk = {}

    if gold_df is not None and len(gold_df) >= 60:
        closes = gold_df["close"]
        current_price = float(closes.iloc[-1])

        # Drawdown from high
        high_60d = float(closes.tail(60).max())
        drawdown_pct = ((current_price - high_60d) / high_60d) * 100

        # Days since high
        high_idx = closes.tail(60).idxmax()
        high_date = gold_df.loc[high_idx, "date"]
        latest_date = gold_df["date"].iloc[-1]
        days_since_high = max(0, (latest_date - high_date).days)

        # SMA distance
        sma_50 = float(_compute_sma(closes, 50).iloc[-1]) if len(closes) >= 50 else current_price
        sma_200 = float(_compute_sma(closes, 200).iloc[-1]) if len(closes) >= 200 else current_price
        pct_above_50sma = ((current_price - sma_50) / sma_50) * 100

        # Score components (each 0-10, then weighted)
        rsi_score = 0
        rsi_val = parabolic.get("rsi_14d", 50)
        if rsi_val > 80:
            rsi_score = 10
        elif rsi_val > 70:
            rsi_score = 7
        elif rsi_val > 60:
            rsi_score = 4
        else:
            rsi_score = 1

        roc_score = 0
        roc_val = abs(parabolic.get("gold_roc_20d", 0))
        if roc_val > 15:
            roc_score = 10
        elif roc_val > 10:
            roc_score = 7
        elif roc_val > 5:
            roc_score = 4
        else:
            roc_score = 1

        accel_score = 0
        accel_val = parabolic.get("gold_roc_acceleration", 0)
        if accel_val > 5:
            accel_score = 10
        elif accel_val > 3:
            accel_score = 7
        elif accel_val > 1:
            accel_score = 4
        else:
            accel_score = 1

        distance_score = 0
        if pct_above_50sma > 15:
            distance_score = 10
        elif pct_above_50sma > 10:
            distance_score = 7
        elif pct_above_50sma > 5:
            distance_score = 4
        else:
            distance_score = 1

        # Weighted: RSI (0.3), RoC (0.25), acceleration (0.25), SMA distance (0.2)
        corr_score = round(
            rsi_score * 0.3 + roc_score * 0.25 + accel_score * 0.25 + distance_score * 0.2, 1
        )

        factors = []
        if rsi_val > 70:
            factors.append(f"RSI elevated at {rsi_val:.0f}")
        elif rsi_val < 40:
            factors.append(f"RSI oversold at {rsi_val:.0f}")
        else:
            factors.append(f"RSI neutral at {rsi_val:.0f}")

        if roc_val > 10:
            factors.append(f"Strong momentum (RoC {roc_val:.1f}%)")
        if accel_val > 3:
            factors.append(f"Acceleration elevated ({accel_val:.1f})")
        if pct_above_50sma > 10:
            factors.append(f"Extended above 50SMA ({pct_above_50sma:.1f}%)")

        if corr_score >= 7:
            signals.append("HIGH_CORRECTION_RISK")

        correction_risk = {
            "score": corr_score,
            "drawdown_from_high_pct": round(drawdown_pct, 1),
            "days_since_high": days_since_high,
            "pct_above_50sma": round(pct_above_50sma, 1),
            "factors": factors,
        }
    else:
        correction_risk = {"error": "Insufficient data for correction risk"}

    result["correction_risk"] = correction_risk

    # ── Seasonal Calendar ──
    now = datetime.utcnow()
    month, day = now.month, now.day

    china_golden_week = (month == 10 and 1 <= day <= 7)
    # Chinese New Year approximate range: late Jan to mid Feb
    chinese_new_year = (month == 1 and day >= 20) or (month == 2 and day <= 15)
    # Indian wedding season (Oct-Dec)
    indian_wedding = month in (10, 11, 12)

    if china_golden_week:
        seasonal_bias = "positive"
        seasonal_note = "China Golden Week (Oct 1-7) — elevated physical gold demand from Chinese consumers."
    elif chinese_new_year:
        seasonal_bias = "positive"
        seasonal_note = "Chinese New Year period — traditionally strong physical gold demand."
    elif indian_wedding:
        seasonal_bias = "mildly_positive"
        seasonal_note = "Indian wedding season (Oct-Dec) — elevated jewellery demand supports gold."
    elif month in (6, 7):
        seasonal_bias = "mildly_negative"
        seasonal_note = "Summer doldrums — typically quieter period for gold. Lower physical demand."
    else:
        seasonal_bias = "neutral"
        seasonal_note = "No major seasonal effects currently active."

    result["seasonal"] = {
        "china_golden_week": china_golden_week,
        "chinese_new_year": chinese_new_year,
        "indian_wedding_season": indian_wedding,
        "current_seasonal_bias": seasonal_bias,
        "note": seasonal_note,
    }

    result["signals"] = signals

    # ── Summary ──
    parts = []
    classification = gold_regime.get("classification", "unknown")
    parts.append(f"Gold in {classification.replace('_', ' ')} regime.")

    gold_dxy_c = gold_regime.get("gold_dxy_20d_corr")
    if gold_dxy_c is not None:
        parts.append(f"Gold-DXY correlation: {gold_dxy_c}.")

    s_beta = silver_analysis.get("silver_beta_20d")
    if s_beta is not None:
        parts.append(f"Silver beta: {s_beta}x.")

    corr_s = correction_risk.get("score")
    if corr_s is not None:
        parts.append(f"Correction risk: {corr_s}/10.")

    if parabolic.get("is_parabolic"):
        parts.append("PARABOLIC ADVANCE DETECTED — elevated correction risk.")

    if seasonal_bias != "neutral":
        parts.append(f"Seasonal bias: {seasonal_bias}.")

    result["summary"] = " ".join(parts)

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# TOOL 4: USD REGIME / AMERICAN EXODUS ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def protrader_usd_regime_analysis() -> str:
    """Analyze the USD structural regime and 'American exodus' basket signals.

    Assesses DXY structural trend (SMA 50/200, death cross), 30Y yield
    proximity to 5% ceiling, MOVE index (bond volatility), 'American
    exodus' basket coherence (gold up + DXY down + 30Y yields up), and
    bond-equity correlation regime.

    Key insight: when DXY is in structural bear (below both MAs + death
    cross) AND the exodus basket is confirmed (gold rising, USD falling,
    long bonds selling off), conditions favor long gold + short USD +
    short treasuries as a thematic basket.  When 30Y yields approach 5%,
    progress to downside stalls and market squeezes short-sellers.

    Returns:
        JSON string with dxy_regime, yield_30y, bond_volatility,
        exodus_basket, bond_equity_correlation, usd_regime, signals,
        and summary.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── DXY Regime ──
    dxy_df = _load_daily_close("dxy.csv", "dxy")
    dxy_regime: dict = {}
    dxy_level = None
    dxy_classification = "unknown"

    if dxy_df is not None and len(dxy_df) >= 50:
        dxy_level = float(dxy_df["close"].iloc[-1])

        # Moving averages
        sma_50 = float(_compute_sma(dxy_df["close"], 50).iloc[-1]) if len(dxy_df) >= 50 else None
        sma_200 = (
            float(_compute_sma(dxy_df["close"], 200).iloc[-1])
            if len(dxy_df) >= 200
            else None
        )

        pct_vs_50 = ((dxy_level - sma_50) / sma_50 * 100) if sma_50 else None
        pct_vs_200 = ((dxy_level - sma_200) / sma_200 * 100) if sma_200 else None

        # Death cross / golden cross
        death_cross = (sma_50 < sma_200) if (sma_50 is not None and sma_200 is not None) else None

        # 20-day direction
        if len(dxy_df) >= 21:
            dxy_20d_ago = float(dxy_df["close"].iloc[-21])
            dxy_20d_change = ((dxy_level - dxy_20d_ago) / dxy_20d_ago) * 100
            if dxy_20d_change < -1.0:
                direction_20d = "falling"
            elif dxy_20d_change > 1.0:
                direction_20d = "rising"
            else:
                direction_20d = "ranging"
        else:
            direction_20d = "unknown"
            dxy_20d_change = 0

        # Classification
        below_50 = pct_vs_50 is not None and pct_vs_50 < 0
        below_200 = pct_vs_200 is not None and pct_vs_200 < 0
        above_50 = pct_vs_50 is not None and pct_vs_50 > 0
        above_200 = pct_vs_200 is not None and pct_vs_200 > 0

        if below_50 and below_200 and death_cross and direction_20d == "falling":
            dxy_classification = "structural_bear"
            signals.append("USD_STRUCTURAL_BEAR")
        elif below_50 and below_200:
            dxy_classification = "cyclical_weakness"
            signals.append("USD_CYCLICAL_WEAK")
        elif above_50 and above_200 and (death_cross is False) and direction_20d == "rising":
            dxy_classification = "structural_bull"
            signals.append("USD_STRUCTURAL_BULL")
        elif above_50 and above_200 and death_cross:
            # Price above both SMAs but SMA50 < SMA200 (death cross still active)
            dxy_classification = "recovering"
        elif above_50 and above_200:
            dxy_classification = "cyclical_strength"
        elif below_50 and above_200:
            dxy_classification = "cyclical_weakness"
        elif above_50 and below_200 and death_cross:
            dxy_classification = "recovering"
        elif above_50 and below_200:
            dxy_classification = "cyclical_strength"
        else:
            dxy_classification = "neutral_range"

        dxy_regime = {
            "level": round(dxy_level, 2),
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "sma_200": round(sma_200, 2) if sma_200 else None,
            "pct_vs_50sma": round(pct_vs_50, 1) if pct_vs_50 is not None else None,
            "pct_vs_200sma": round(pct_vs_200, 1) if pct_vs_200 is not None else None,
            "direction_20d": direction_20d,
            "death_cross": death_cross,
            "classification": dxy_classification,
        }
    else:
        dxy_regime = {"error": "Insufficient DXY data (need >= 50 rows)"}

    result["dxy_regime"] = dxy_regime

    # ── 30Y Yield Analysis ──
    yield_30y_result: dict = {}
    yield_30y_level = None
    yield_30y_df = _load_30y_yield()

    if yield_30y_df is not None and len(yield_30y_df) >= 21:
        yield_30y_level = float(yield_30y_df["close"].iloc[-1])
        yield_30y_20d_ago = float(yield_30y_df["close"].iloc[-21])
        yield_30y_change_bps = (yield_30y_level - yield_30y_20d_ago) * 100  # basis points

        # Direction
        if yield_30y_change_bps > 10:
            y30_direction = "rising"
        elif yield_30y_change_bps < -10:
            y30_direction = "falling"
        else:
            y30_direction = "stable"

        near_5pct = yield_30y_level >= 4.80

        if near_5pct:
            y30_interp = (
                f"30Y yield at {yield_30y_level:.2f}% — approaching 5% ceiling. "
                "Historical resistance zone where progress stalls and squeezes occur."
            )
            signals.append("30Y_NEAR_5PCT_CEILING")
        elif yield_30y_level >= 4.50:
            y30_interp = (
                f"30Y yield at {yield_30y_level:.2f}% — elevated but below 5% ceiling. "
                "Fiscal concerns reflected in term premium."
            )
        else:
            y30_interp = f"30Y yield at {yield_30y_level:.2f}% — within normal range."

        yield_30y_result = {
            "level": round(yield_30y_level, 2),
            "change_20d_bps": round(yield_30y_change_bps, 1),
            "near_5pct_ceiling": near_5pct,
            "direction_20d": y30_direction,
            "interpretation": y30_interp,
        }
    else:
        yield_30y_result = {"error": "Insufficient 30Y yield data"}

    result["yield_30y"] = yield_30y_result

    # ── Bond Volatility (MOVE Index) ──
    move_result: dict = {}
    move_df = _load_daily_close("vix_move.csv", "move")

    if move_df is not None and len(move_df) >= 20:
        move_level = float(move_df["close"].iloc[-1])
        last_252 = move_df["close"].tail(252)
        move_pctile = _percentile_rank(last_252, move_level)

        if move_level > 130:
            move_interp = "MOVE very elevated — extreme bond market stress."
            signals.append("MOVE_EXTREME")
        elif move_level > 110:
            move_interp = "MOVE elevated — moderately high bond market stress."
        elif move_level > 90:
            move_interp = "MOVE in normal range."
        else:
            move_interp = "MOVE subdued — low bond market volatility."

        move_result = {
            "move_level": round(move_level, 1),
            "move_percentile_1y": round(move_pctile, 0),
            "interpretation": move_interp,
        }
    else:
        move_result = {"error": "Insufficient MOVE data"}

    result["bond_volatility"] = move_result

    # ── American Exodus Basket Detection ──
    # Basket confirmed when: gold rising (>2%) + DXY falling (<-1%) + 30Y yields rising (>10bp)
    exodus_result: dict = {}

    gold_df = _load_daily_close("gold.csv", "gold_price")
    gold_20d_ret = None
    dxy_20d_ret = None

    if gold_df is not None and len(gold_df) >= 21:
        g_current = float(gold_df["close"].iloc[-1])
        g_20d_ago = float(gold_df["close"].iloc[-21])
        gold_20d_ret = ((g_current - g_20d_ago) / g_20d_ago) * 100

    if dxy_df is not None and len(dxy_df) >= 21:
        d_current = float(dxy_df["close"].iloc[-1])
        d_20d_ago = float(dxy_df["close"].iloc[-21])
        dxy_20d_ret = ((d_current - d_20d_ago) / d_20d_ago) * 100

    yield_30y_20d_chg_bps = yield_30y_result.get("change_20d_bps")

    # Determine basket coherence
    gold_leg = gold_20d_ret is not None and gold_20d_ret > 2
    dxy_leg = dxy_20d_ret is not None and dxy_20d_ret < -1
    bond_leg = yield_30y_20d_chg_bps is not None and yield_30y_20d_chg_bps > 10

    legs_confirmed = sum([gold_leg, dxy_leg, bond_leg])

    if legs_confirmed == 3:
        coherence = "strong"
        basket_confirmed = True
        signals.append("EXODUS_BASKET_CONFIRMED")
        exodus_interp = (
            "American exodus basket confirmed: gold rising, USD falling, long bonds "
            "selling off. Pattern consistent with fiscal-driven capital rotation away "
            "from US assets."
        )
    elif legs_confirmed == 2:
        coherence = "partial"
        basket_confirmed = False
        signals.append("EXODUS_BASKET_PARTIAL")
        active_legs = []
        if gold_leg:
            active_legs.append("gold bid")
        if dxy_leg:
            active_legs.append("USD weak")
        if bond_leg:
            active_legs.append("bonds selling")
        exodus_interp = (
            f"Exodus basket partially confirmed ({', '.join(active_legs)}). "
            "Monitor for third leg to confirm."
        )
    else:
        coherence = "absent"
        basket_confirmed = False
        exodus_interp = "No exodus basket signal — fewer than 2 legs active."

    exodus_result = {
        "gold_20d_return": round(gold_20d_ret, 1) if gold_20d_ret is not None else None,
        "dxy_20d_return": round(dxy_20d_ret, 1) if dxy_20d_ret is not None else None,
        "yield_30y_20d_change_bps": (
            round(yield_30y_20d_chg_bps, 1) if yield_30y_20d_chg_bps is not None else None
        ),
        "basket_confirmed": basket_confirmed,
        "coherence": coherence,
        "legs_active": legs_confirmed,
        "interpretation": exodus_interp,
    }

    result["exodus_basket"] = exodus_result

    # ── Bond-Equity Correlation ──
    # Normally negative (risk-off = bonds rally, equities fall)
    # Positive = bonds trading like risk assets (fiscal stress)
    bond_eq_result: dict = {}
    es_df = _load_daily_close("es_futures.csv", "es_price")

    if es_df is not None and yield_30y_df is not None:
        merged = _align_by_date(es_df, yield_30y_df)
        if len(merged) >= 20:
            ret_spx = merged["close_0"].pct_change().tail(20).dropna()
            # For yields: use daily changes (not pct returns)
            ret_30y = merged["close_1"].diff().tail(20).dropna()

            if len(ret_spx) >= 15 and len(ret_30y) >= 15:
                corr_val = float(ret_spx.corr(ret_30y))

                if not np.isnan(corr_val):
                    if corr_val > 0.3:
                        be_regime = "fiscal_stress"
                        be_interp = (
                            f"SPX-30Y yield 20d correlation: {corr_val:.2f} (positive). "
                            "Bonds and equities moving together — treasuries trading like "
                            "risk assets. Fiscal concerns dominate."
                        )
                        signals.append("FISCAL_STRESS_CORRELATION")
                    elif corr_val < -0.3:
                        be_regime = "normal"
                        be_interp = (
                            f"SPX-30Y yield 20d correlation: {corr_val:.2f} (negative). "
                            "Normal risk-on/risk-off relationship — bonds providing "
                            "diversification."
                        )
                    else:
                        be_regime = "transitioning"
                        be_interp = (
                            f"SPX-30Y yield 20d correlation: {corr_val:.2f} (near zero). "
                            "Bond-equity relationship in transition."
                        )

                    bond_eq_result = {
                        "spx_30y_20d_corr": round(corr_val, 2),
                        "regime": be_regime,
                        "interpretation": be_interp,
                    }
                else:
                    bond_eq_result = {"error": "Correlation computation returned NaN"}
            else:
                bond_eq_result = {"error": "Insufficient aligned data for correlation"}
        else:
            bond_eq_result = {"error": "Insufficient overlapping ES/30Y data"}
    else:
        bond_eq_result = {"error": "Missing ES or 30Y yield data"}

    result["bond_equity_correlation"] = bond_eq_result

    # ── Overall USD Regime Classification ──
    be_regime_val = bond_eq_result.get("regime", "unknown")

    if dxy_classification == "structural_bear" and basket_confirmed:
        usd_regime = "exodus"
    elif dxy_classification == "structural_bear":
        usd_regime = "structural_bear"
    elif dxy_classification in ("cyclical_weakness",) and coherence == "partial":
        usd_regime = "weakening"
    elif dxy_classification == "structural_bull":
        usd_regime = "structural_bull"
    elif dxy_classification in ("cyclical_strength",):
        usd_regime = "cyclical_strength"
    elif dxy_classification == "recovering":
        usd_regime = "recovering"
    else:
        usd_regime = "neutral"

    result["usd_regime"] = usd_regime
    result["signals"] = signals

    # ── Summary ──
    parts = [f"USD regime: {usd_regime.replace('_', ' ')}."]

    if dxy_level is not None:
        parts.append(f"DXY at {dxy_level:.1f} ({dxy_classification.replace('_', ' ')}).")

    if yield_30y_level is not None:
        parts.append(f"30Y yield at {yield_30y_level:.2f}%.")
        if yield_30y_result.get("near_5pct_ceiling"):
            parts.append("WARNING: Near 5% ceiling — squeeze risk elevated.")

    if basket_confirmed:
        parts.append("EXODUS BASKET CONFIRMED — gold bid, USD falling, bonds selling.")
    elif coherence == "partial":
        parts.append(f"Exodus basket partial ({legs_confirmed}/3 legs).")

    if be_regime_val == "fiscal_stress":
        parts.append("Bonds trading like risk assets — fiscal stress regime.")

    result["summary"] = " ".join(parts)

    return json.dumps(result, indent=2)