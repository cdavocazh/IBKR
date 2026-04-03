"""Commodity analysis tools.

Combines local macro CSV data (prices, COT positioning) with optional FRED API
data (inventories, supply/demand) to produce comprehensive commodity analysis
including seasonal patterns, support/resistance levels, cross-asset correlations,
and positioning signals.

Supported commodities: crude_oil, gold, silver, copper.

Data sources:
- /macro_2/historical_data/*.csv  — price history, COT positioning, DXY, yields, VIX
- tools.fred_data (optional)      — oil inventories, supply/demand fundamentals
- tools.macro_data                — existing indicator analysis (z-scores, anomalies)
"""

import os
import json
from datetime import datetime

import numpy as np
import pandas as pd

from tools.config import HISTORICAL_DATA_DIR
from tools import macro_data

# ═══════════════════════════════════════════════════════════════════════
# COMMODITY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

COMMODITY_CONFIG = {
    "crude_oil": {
        "csv": "crude_oil.csv",
        "price_col": "crude_oil_price",
        "indicator_key": "crude_oil",
        "cot_key": None,
    },
    "gold": {
        "csv": "gold.csv",
        "price_col": "gold_price",
        "indicator_key": "gold",
        "cot_key": "cot_gold",
    },
    "silver": {
        "csv": "silver.csv",
        "price_col": "silver_price",
        "indicator_key": "silver",
        "cot_key": "cot_silver",
    },
    "copper": {
        "csv": "copper.csv",
        "price_col": "copper_price",
        "indicator_key": "copper",
        "cot_key": None,
    },
}

# Correlation targets — other indicators to correlate against
CORRELATION_TARGETS = {
    "dxy": {"csv": "dxy.csv", "price_col": "dxy"},
    "10y_yield": {"csv": "10y_treasury_yield.csv", "price_col": "10y_yield"},
    "vix": {"csv": "vix_move.csv", "price_col": "vix"},
    "gold": {"csv": "gold.csv", "price_col": "gold_price"},
    "silver": {"csv": "silver.csv", "price_col": "silver_price"},
    "crude_oil": {"csv": "crude_oil.csv", "price_col": "crude_oil_price"},
    "copper": {"csv": "copper.csv", "price_col": "copper_price"},
}

# Month names for seasonal pattern output
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _load_csv(filename: str) -> pd.DataFrame | None:
    """Load a CSV from HISTORICAL_DATA_DIR, return None on failure."""
    path = os.path.join(HISTORICAL_DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        return df
    except Exception:
        return None


def _validate_commodity(commodity: str) -> dict | None:
    """Return config dict if valid commodity, else None."""
    return COMMODITY_CONFIG.get(commodity.lower())


def _interpret_correlation(r: float) -> str:
    """Interpret a correlation coefficient as a human-readable string."""
    abs_r = abs(r)
    if abs_r >= 0.6:
        strength = "strong"
    elif abs_r >= 0.3:
        strength = "moderate"
    elif abs_r >= 0.1:
        strength = "weak"
    else:
        return "near zero"
    direction = "positive" if r > 0 else "inverse"
    return f"{strength} {direction}"


def _compute_cot_analysis(cot_key: str) -> dict | None:
    """Load COT CSV and compute positioning metrics."""
    df = _load_csv(f"{cot_key}.csv")
    if df is None or len(df) < 4:
        return None

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    net_series = df["managed_money_net"].dropna()
    if len(net_series) < 4:
        return None

    latest_net = float(net_series.iloc[-1])
    prev_net = float(net_series.iloc[-2]) if len(net_series) >= 2 else None

    # Percentile rank of latest position vs all history
    pctile = float((net_series < latest_net).sum() / len(net_series) * 100)

    # WoW position change
    wow_change = None
    wow_change_pct = None
    if prev_net is not None and prev_net != 0:
        wow_change = round(latest_net - prev_net, 0)
        wow_change_pct = round((latest_net - prev_net) / abs(prev_net) * 100, 2)

    # 4-week position trend
    if len(net_series) >= 4:
        last_4 = net_series.tail(4).values
        increases = sum(1 for i in range(1, len(last_4)) if last_4[i] > last_4[i - 1])
        trend = "improving" if increases >= 2 else "reducing"
    else:
        trend = "insufficient_data"

    latest_oi = None
    if "open_interest" in df.columns:
        oi_series = df["open_interest"].dropna()
        if len(oi_series) > 0:
            latest_oi = float(oi_series.iloc[-1])

    return {
        "latest_managed_money_net": latest_net,
        "percentile_rank": round(pctile, 1),
        "wow_change": wow_change,
        "wow_change_pct": wow_change_pct,
        "four_week_trend": trend,
        "open_interest": latest_oi,
    }


def _compute_seasonal(df: pd.DataFrame, price_col: str) -> dict:
    """Compute seasonal monthly return patterns."""
    df = df.copy()
    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    df["daily_return"] = df[price_col].pct_change() * 100

    # Check if we have enough history
    date_range = (df["date"].max() - df["date"].min()).days
    if date_range < 180:
        return {"status": "insufficient_history", "days_available": date_range}

    df["month"] = df["date"].dt.month
    monthly_stats = {}
    for month_num in range(1, 13):
        month_data = df[df["month"] == month_num]["daily_return"].dropna()
        if len(month_data) < 5:
            monthly_stats[MONTH_NAMES[month_num]] = {
                "mean_return_pct": None,
                "median_return_pct": None,
                "positive_pct": None,
                "sample_size": int(len(month_data)),
            }
        else:
            monthly_stats[MONTH_NAMES[month_num]] = {
                "mean_return_pct": round(float(month_data.mean()), 4),
                "median_return_pct": round(float(month_data.median()), 4),
                "positive_pct": round(float((month_data > 0).sum() / len(month_data) * 100), 1),
                "sample_size": int(len(month_data)),
            }

    # Identify strongest and weakest months (by mean return)
    valid_months = {
        k: v for k, v in monthly_stats.items()
        if v.get("mean_return_pct") is not None
    }
    strongest = max(valid_months, key=lambda k: valid_months[k]["mean_return_pct"]) if valid_months else None
    weakest = min(valid_months, key=lambda k: valid_months[k]["mean_return_pct"]) if valid_months else None

    # Current month tendency
    current_month = MONTH_NAMES[datetime.now().month]
    current_stats = monthly_stats.get(current_month, {})
    avg_return = current_stats.get("mean_return_pct")
    if avg_return is not None:
        if avg_return > 0.05:
            tendency = "bullish"
        elif avg_return > 0.01:
            tendency = "slightly bullish"
        elif avg_return > -0.01:
            tendency = "neutral"
        elif avg_return > -0.05:
            tendency = "slightly bearish"
        else:
            tendency = "bearish"
    else:
        tendency = "unknown"

    # Quarterly aggregation
    quarter_map = {1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
                   7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4"}
    df["quarter"] = df["date"].dt.month.map(quarter_map)
    quarterly_stats = {}
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        q_data = df[df["quarter"] == q]["daily_return"].dropna()
        if len(q_data) >= 10:
            quarterly_stats[q] = {
                "mean_return_pct": round(float(q_data.mean()), 4),
                "positive_pct": round(float((q_data > 0).sum() / len(q_data) * 100), 1),
                "sample_size": int(len(q_data)),
            }

    # Seasonality strength (std of monthly means — higher = more seasonal)
    monthly_means = [v["mean_return_pct"] for v in valid_months.values()
                     if v["mean_return_pct"] is not None]
    seasonality_score = round(float(pd.Series(monthly_means).std()), 4) if len(monthly_means) >= 4 else None

    return {
        "current_month": current_month,
        "avg_monthly_return_pct": avg_return,
        "historical_tendency": tendency,
        "strongest_month": strongest,
        "weakest_month": weakest,
        "months_with_data": len(valid_months),
        "seasonality_strength": seasonality_score,
        "seasonality_note": (
            "High seasonality" if seasonality_score and seasonality_score > 0.05
            else "Moderate seasonality" if seasonality_score and seasonality_score > 0.02
            else "Low seasonality" if seasonality_score
            else "Insufficient data"
        ),
        "quarterly_patterns": quarterly_stats,
        "date_range_days": date_range,
        "all_months": monthly_stats,
    }


def _round_number_step(price: float) -> float:
    """Return a sensible round-number step for synthetic S/R levels."""
    if price > 500:
        return 50
    if price > 100:
        return 10
    if price > 50:
        return 5
    if price > 10:
        return 2
    return 1


def _compute_support_resistance(
    df: pd.DataFrame, price_col: str, lookback_days: int = 120, window: int = 5,
) -> dict:
    """Find support and resistance levels from local minima/maxima."""
    df = df.copy()
    df = df.sort_values("date", ascending=True).reset_index(drop=True)

    # Take the last lookback_days rows
    df = df.tail(lookback_days).reset_index(drop=True)
    prices = df[price_col].dropna().values
    current_price = float(prices[-1]) if len(prices) > 0 else None

    if len(prices) < window * 2 + 1:
        return {
            "supports": [],
            "resistances": [],
            "current_price": current_price,
            "error": "insufficient data for support/resistance calculation",
        }

    supports = []
    resistances = []
    half_w = window // 2

    for i in range(half_w, len(prices) - half_w):
        local_window = prices[i - half_w: i + half_w + 1]
        val = prices[i]
        if val == min(local_window):
            supports.append(round(float(val), 2))
        if val == max(local_window):
            resistances.append(round(float(val), 2))

    # Cluster nearby levels (within 1.5% of each other)
    supports = _cluster_levels(supports, tolerance_pct=1.5)
    resistances = _cluster_levels(resistances, tolerance_pct=1.5)

    # Filter: supports must be below current price, resistances above
    if current_price is not None:
        supports = [s for s in supports if s < current_price]
        resistances = [r for r in resistances if r > current_price]

        # If all historical levels are below price (e.g., price spike), add
        # round-number levels as synthetic resistance
        if not resistances:
            step = _round_number_step(current_price)
            base = (current_price // step + 1) * step
            resistances = [round(base + i * step, 2) for i in range(3)]

        # If all historical levels are above price (e.g., crash), add
        # round-number levels as synthetic support
        if not supports:
            step = _round_number_step(current_price)
            base = (current_price // step) * step
            supports = [round(base - i * step, 2) for i in range(3)
                        if base - i * step > 0]

    return {
        "supports": supports,
        "resistances": resistances,
        "current_price": round(current_price, 2) if current_price is not None else None,
    }


def _cluster_levels(levels: list[float], tolerance_pct: float = 1.5) -> list[float]:
    """Cluster nearby price levels and return representative values.

    Groups levels within tolerance_pct of each other, returns the mean of
    each cluster sorted by frequency (most touched first), limited to top 5.
    """
    if not levels:
        return []

    sorted_levels = sorted(levels)
    clusters: list[list[float]] = []
    current_cluster = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        cluster_mean = np.mean(current_cluster)
        if abs(level - cluster_mean) / cluster_mean * 100 <= tolerance_pct:
            current_cluster.append(level)
        else:
            clusters.append(current_cluster)
            current_cluster = [level]
    clusters.append(current_cluster)

    # Sort clusters by number of touches (descending), then by recency
    cluster_means = [
        (round(float(np.mean(c)), 2), len(c)) for c in clusters
    ]
    cluster_means.sort(key=lambda x: x[1], reverse=True)

    return [cm[0] for cm in cluster_means[:5]]


def _compute_dxy_correlation(df: pd.DataFrame, price_col: str) -> dict | None:
    """Compute rolling correlation between commodity and DXY."""
    dxy_df = _load_csv("dxy.csv")
    if dxy_df is None:
        return None

    # Prepare commodity series
    comm = df[["date", price_col]].copy()
    comm = comm.dropna(subset=[price_col])
    comm["date"] = pd.to_datetime(comm["date"], errors="coerce")
    comm = comm.dropna(subset=["date"])

    # Prepare DXY series
    dxy = dxy_df[["date", "dxy"]].copy()
    dxy = dxy.dropna(subset=["dxy"])
    dxy["date"] = pd.to_datetime(dxy["date"], errors="coerce")
    dxy = dxy.dropna(subset=["date"])

    # Merge on date
    merged = comm.merge(dxy, on="date", how="inner")
    if len(merged) < 25:
        return None

    merged = merged.sort_values("date", ascending=True).reset_index(drop=True)
    merged["comm_ret"] = merged[price_col].pct_change()
    merged["dxy_ret"] = merged["dxy"].pct_change()
    merged = merged.dropna(subset=["comm_ret", "dxy_ret"])

    if len(merged) < 20:
        return None

    rolling_corr = merged["comm_ret"].rolling(20).corr(merged["dxy_ret"])
    latest_corr = float(rolling_corr.iloc[-1]) if not pd.isna(rolling_corr.iloc[-1]) else None

    if latest_corr is None:
        return None

    return {
        "dxy_20d_correlation": round(latest_corr, 2),
        "interpretation": _interpret_correlation(latest_corr),
    }


def _generate_signals(
    commodity: str,
    cot_data: dict | None,
    oil_fundamentals: dict | None,
    dxy_corr: dict | None,
    df: pd.DataFrame,
    price_col: str,
) -> list[str]:
    """Generate supply/demand and positioning signal strings."""
    signals = []

    # Oil-specific FRED signals
    if commodity == "crude_oil" and oil_fundamentals is not None:
        inv = oil_fundamentals.get("inventory_data", {})
        if inv:
            four_week_trend = inv.get("four_week_trend")
            if four_week_trend == "building":
                signals.append("INVENTORY_BUILDING")
            elif four_week_trend == "drawing":
                signals.append("INVENTORY_DRAWING")

        spread = oil_fundamentals.get("brent_wti_spread", {})
        if spread:
            spread_trend = spread.get("trend")
            if spread_trend == "widening":
                signals.append("BRENT_PREMIUM_WIDENING")
            elif spread_trend == "narrowing":
                signals.append("BRENT_PREMIUM_NARROWING")

    # COT signals (gold/silver)
    if cot_data is not None:
        pctile = cot_data.get("percentile_rank")
        if pctile is not None:
            if pctile > 80:
                signals.append("COT_CROWDED_LONG")
            elif pctile < 20:
                signals.append("COT_CROWDED_SHORT")

        wow_pct = cot_data.get("wow_change_pct")
        if wow_pct is not None and abs(wow_pct) > 15:
            signals.append("LARGE_POSITION_SHIFT")

    # DXY signals (applicable to all commodities)
    if dxy_corr is not None:
        # Check DXY direction from recent data
        dxy_df = _load_csv("dxy.csv")
        if dxy_df is not None and len(dxy_df) >= 6:
            dxy_df = dxy_df.sort_values("date", ascending=True)
            dxy_latest = float(dxy_df["dxy"].dropna().iloc[-1])
            dxy_week_ago = float(dxy_df["dxy"].dropna().iloc[-6]) if len(dxy_df["dxy"].dropna()) >= 6 else None
            if dxy_week_ago is not None and dxy_week_ago != 0:
                dxy_change = (dxy_latest - dxy_week_ago) / dxy_week_ago * 100
                if dxy_change < -0.3:
                    signals.append("DXY_TAILWIND")
                elif dxy_change > 0.3:
                    signals.append("DXY_HEADWIND")

    return signals


def _generate_summary(
    commodity: str,
    current_price: float | None,
    price_analysis: dict,
    cot_data: dict | None,
    signals: list[str],
    seasonal: dict,
) -> str:
    """Generate a brief human-readable summary."""
    name = commodity.replace("_", " ").title()
    parts = []

    if current_price is not None:
        parts.append(f"{name} at ${current_price:,.2f}")

    # 52-week context from price_analysis
    metrics = price_analysis.get("metrics", {})
    for col, metric in metrics.items():
        pct_high = metric.get("pct_from_52w_high")
        pct_low = metric.get("pct_from_52w_low")
        if pct_high is not None and abs(pct_high) < 3:
            parts.append("near 52-week high")
        elif pct_low is not None and abs(pct_low) < 3:
            parts.append("near 52-week low")

        wow_pct = metric.get("wow_change_pct")
        if wow_pct is not None:
            direction = "up" if wow_pct > 0 else "down"
            parts.append(f"{direction} {abs(wow_pct):.1f}% WoW")
        break  # Only first metric

    # COT summary
    if cot_data:
        pctile = cot_data.get("percentile_rank")
        if pctile is not None:
            if pctile > 80:
                parts.append(f"speculative positioning crowded long ({pctile:.0f}th pctile)")
            elif pctile < 20:
                parts.append(f"speculative positioning crowded short ({pctile:.0f}th pctile)")
            else:
                parts.append(f"speculative positioning moderate ({pctile:.0f}th pctile)")

    # Seasonal
    tendency = seasonal.get("historical_tendency", "unknown")
    current_month = seasonal.get("current_month", "")
    if tendency != "unknown":
        parts.append(f"seasonally {tendency} in {current_month}")

    # Key signals
    if signals:
        parts.append(f"signals: {', '.join(signals)}")

    return ". ".join(parts) + "." if parts else f"{name} analysis complete."


def _compute_energy_divergence() -> dict | None:
    """Compute XLE vs XOP divergence signal for crude oil.

    XLE (Energy Select Sector SPDR) = integrated majors (Exxon, Chevron).
    XOP (SPDR Oil & Gas Exploration & Production) = independent E&Ps.

    When XLE is flat while XOP rallies → market sees oil spike as temporary
    (majors hedge, independents benefit from spot).
    When both rally → market expects sustained higher oil.
    When XOP underperforms XLE → independents under pressure, bearish oil.

    Returns dict with XLE/XOP prices, spread, and signal, or None on failure.
    """
    try:
        from tools.fred_data import _fetch_etf_prices
    except ImportError:
        return None

    xle = _fetch_etf_prices("XLE")
    xop = _fetch_etf_prices("XOP")

    if not xle or not xop:
        return {"status": "unavailable", "note": "ETF data requires yfinance (pip install yfinance)"}

    result = {
        "xle": xle,
        "xop": xop,
    }

    xle_1w = xle.get("pct_change_1w")
    xop_1w = xop.get("pct_change_1w")
    xle_1m = xle.get("pct_change_1m")
    xop_1m = xop.get("pct_change_1m")

    # Compute spread (XOP - XLE performance)
    if xle_1w is not None and xop_1w is not None:
        spread_1w = round(xop_1w - xle_1w, 2)
        result["spread_1w_pp"] = spread_1w
    else:
        spread_1w = None

    if xle_1m is not None and xop_1m is not None:
        spread_1m = round(xop_1m - xle_1m, 2)
        result["spread_1m_pp"] = spread_1m
    else:
        spread_1m = None

    # Interpret divergence
    if spread_1w is not None:
        if spread_1w > 3.0:
            result["signal"] = "OIL_SPIKE_TEMPORARY"
            result["interpretation"] = (
                f"XOP outperforming XLE by {spread_1w:+.1f}pp this week — "
                "independents leading while majors lag. Market sees oil spike "
                "as temporary (majors are hedged, not repricing higher for long)."
            )
        elif spread_1w < -3.0:
            result["signal"] = "OIL_INDEPENDENTS_WEAK"
            result["interpretation"] = (
                f"XLE outperforming XOP by {abs(spread_1w):.1f}pp this week — "
                "independents underperforming. Bearish for sustained oil rally; "
                "market favoring diversified majors over pure-play E&Ps."
            )
        elif xle_1w is not None and xop_1w is not None and xle_1w > 2 and xop_1w > 2:
            result["signal"] = "OIL_BROAD_ENERGY_RALLY"
            result["interpretation"] = (
                f"Both XLE ({xle_1w:+.1f}%) and XOP ({xop_1w:+.1f}%) rallying — "
                "broad energy strength. Market expects sustained higher oil prices."
            )
        elif xle_1w is not None and abs(xle_1w) < 1 and xop_1w is not None and abs(xop_1w) < 1:
            result["interpretation"] = (
                f"XLE ({xle_1w:+.1f}%) and XOP ({xop_1w:+.1f}%) both flat — "
                "no divergence signal this week."
            )
        else:
            result["interpretation"] = (
                f"XLE {xle_1w:+.1f}%, XOP {xop_1w:+.1f}% — "
                "modest divergence, no strong signal."
            )

    return result


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def analyze_commodity_outlook(commodity: str) -> str:
    """Comprehensive commodity analysis combining price data, positioning, fundamentals, and technicals.

    Produces a full outlook including price analysis, COT positioning (gold/silver),
    FRED inventory data (crude oil), seasonal patterns, support/resistance levels,
    DXY correlation, and actionable signals.

    Args:
        commodity: One of 'crude_oil', 'gold', 'silver', 'copper'.

    Returns:
        JSON string with all analysis sections.
    """
    config = _validate_commodity(commodity)
    if config is None:
        return json.dumps({
            "error": f"Unknown commodity '{commodity}'. Supported: {list(COMMODITY_CONFIG.keys())}",
        })

    commodity = commodity.lower()
    csv_file = config["csv"]
    price_col = config["price_col"]
    indicator_key = config["indicator_key"]
    cot_key = config["cot_key"]

    # 1. Load price CSV
    df = _load_csv(csv_file)
    if df is None:
        return json.dumps({"error": f"Price data not found: {csv_file}"})

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    df = df.dropna(subset=[price_col])

    if len(df) < 10:
        return json.dumps({"error": "Insufficient price data", "rows": len(df)})

    current_price = round(float(df[price_col].iloc[-1]), 2)

    # 2. Get existing macro analysis
    price_analysis = {}
    try:
        raw = macro_data.analyze_indicator_changes(indicator_key)
        price_analysis = json.loads(raw)
    except Exception:
        price_analysis = {"error": "macro_data analysis unavailable"}

    # 3. COT positioning (gold/silver)
    cot_data = None
    if cot_key:
        cot_data = _compute_cot_analysis(cot_key)

    # 4. FRED fundamentals (crude oil)
    oil_fundamentals = None
    if commodity == "crude_oil":
        try:
            from tools import fred_data
            raw_oil = fred_data.get_oil_fundamentals()
            oil_fundamentals = json.loads(raw_oil) if isinstance(raw_oil, str) else raw_oil
        except Exception:
            oil_fundamentals = None

    # 5. Seasonal pattern
    seasonal = _compute_seasonal(df, price_col)

    # 6. Support / resistance (60-day lookback for outlook)
    sr = _compute_support_resistance(df, price_col, lookback_days=60, window=5)

    # 7. DXY correlation
    dxy_corr = _compute_dxy_correlation(df, price_col)

    # 8. Generate signals
    signals = _generate_signals(commodity, cot_data, oil_fundamentals, dxy_corr, df, price_col)

    # 9. Build summary
    summary = _generate_summary(commodity, current_price, price_analysis, cot_data, signals, seasonal)

    # Assemble result
    result: dict = {
        "commodity": commodity,
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "price_analysis": price_analysis,
    }

    if cot_data is not None:
        result["cot_positioning"] = cot_data

    if oil_fundamentals is not None:
        result["inventory_data"] = oil_fundamentals
    elif commodity == "crude_oil":
        result["inventory_data"] = {"status": "fred_data_unavailable"}

    result["seasonal_pattern"] = seasonal

    result["support_resistance"] = {
        "supports": sr.get("supports", [])[:3],
        "resistances": sr.get("resistances", [])[:3],
        "current_price": current_price,
    }

    if dxy_corr:
        result["correlations"] = dxy_corr
    else:
        # Diagnose why DXY correlation failed
        dxy_df = _load_csv("dxy.csv")
        if dxy_df is None:
            result["correlations"] = {"status": "dxy_csv_not_found"}
        else:
            dxy_rows = len(dxy_df.dropna(subset=["dxy"])) if "dxy" in dxy_df.columns else 0
            result["correlations"] = {
                "status": "dxy_correlation_unavailable",
                "dxy_rows": dxy_rows,
                "commodity_rows": len(df),
                "note": "Insufficient overlapping dates for 20-day rolling correlation (need ≥25 merged rows)",
            }

    # 10. XLE vs XOP divergence (crude oil only)
    if commodity == "crude_oil":
        energy_div = _compute_energy_divergence()
        if energy_div:
            result["energy_etf_divergence"] = energy_div
            # Add any divergence signals
            div_signal = energy_div.get("signal")
            if div_signal:
                signals.append(div_signal)

    result["signals"] = signals
    result["summary"] = summary

    return json.dumps(result)


def get_seasonal_pattern(commodity: str) -> str:
    """Compute seasonal monthly return patterns for a commodity.

    Groups daily returns by calendar month and reports mean, median, and
    positive-day percentage for each month. Identifies strongest and weakest
    months historically.

    Args:
        commodity: One of 'crude_oil', 'gold', 'silver', 'copper'.

    Returns:
        JSON string with monthly breakdown and highlights.
    """
    config = _validate_commodity(commodity)
    if config is None:
        return json.dumps({
            "error": f"Unknown commodity '{commodity}'. Supported: {list(COMMODITY_CONFIG.keys())}",
        })

    df = _load_csv(config["csv"])
    if df is None:
        return json.dumps({"error": f"Price data not found: {config['csv']}"})

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    df = df.dropna(subset=[config["price_col"]])

    seasonal = _compute_seasonal(df, config["price_col"])

    result = {
        "commodity": commodity.lower(),
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "data_points": len(df),
        "date_range": {
            "start": df["date"].min().strftime("%Y-%m-%d") if len(df) > 0 else None,
            "end": df["date"].max().strftime("%Y-%m-%d") if len(df) > 0 else None,
        },
        "seasonal": seasonal,
    }

    return json.dumps(result)


def get_support_resistance(commodity: str, lookback_days: int = 120) -> str:
    """Compute support and resistance levels for a commodity.

    Finds local minima (support) and maxima (resistance) using a 5-day window,
    clusters nearby levels within 1.5% of each other, and returns the top 5
    of each sorted by significance (touch frequency).

    Args:
        commodity: One of 'crude_oil', 'gold', 'silver', 'copper'.
        lookback_days: Number of trading days to analyze (default 120).

    Returns:
        JSON string with support levels, resistance levels, and current price.
    """
    config = _validate_commodity(commodity)
    if config is None:
        return json.dumps({
            "error": f"Unknown commodity '{commodity}'. Supported: {list(COMMODITY_CONFIG.keys())}",
        })

    df = _load_csv(config["csv"])
    if df is None:
        return json.dumps({"error": f"Price data not found: {config['csv']}"})

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    df = df.dropna(subset=[config["price_col"]])

    sr = _compute_support_resistance(df, config["price_col"], lookback_days=lookback_days, window=5)

    result = {
        "commodity": commodity.lower(),
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "lookback_days": lookback_days,
        "current_price": sr.get("current_price"),
        "supports": sr.get("supports", []),
        "resistances": sr.get("resistances", []),
    }

    if "error" in sr:
        result["warning"] = sr["error"]

    return json.dumps(result)


def get_commodity_correlations(commodity: str) -> str:
    """Compute cross-asset correlations for a commodity.

    Loads the commodity's price CSV alongside DXY, 10Y yield, VIX, and other
    commodity prices. Computes daily returns, then calculates 20-day rolling
    correlation and 60-day average correlation for each pair.

    Args:
        commodity: One of 'crude_oil', 'gold', 'silver', 'copper'.

    Returns:
        JSON string with correlation matrix and interpretations.
    """
    config = _validate_commodity(commodity)
    if config is None:
        return json.dumps({
            "error": f"Unknown commodity '{commodity}'. Supported: {list(COMMODITY_CONFIG.keys())}",
        })

    commodity = commodity.lower()
    csv_file = config["csv"]
    price_col = config["price_col"]

    # Load commodity price data
    df = _load_csv(csv_file)
    if df is None:
        return json.dumps({"error": f"Price data not found: {csv_file}"})

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    df = df.dropna(subset=[price_col])
    comm_df = df[["date", price_col]].copy()
    comm_df["date"] = pd.to_datetime(comm_df["date"], errors="coerce")
    comm_df = comm_df.dropna(subset=["date"])
    comm_df["comm_ret"] = comm_df[price_col].pct_change()

    correlations = {}

    for target_key, target_cfg in CORRELATION_TARGETS.items():
        # Skip self-correlation
        if target_key == commodity:
            continue

        target_df = _load_csv(target_cfg["csv"])
        if target_df is None:
            continue

        t_price_col = target_cfg["price_col"]
        if t_price_col not in target_df.columns:
            continue

        target_df = target_df[["date", t_price_col]].copy()
        target_df["date"] = pd.to_datetime(target_df["date"], errors="coerce")
        target_df = target_df.dropna(subset=["date", t_price_col])
        target_df["target_ret"] = target_df[t_price_col].pct_change()

        # Merge on date
        merged = comm_df[["date", "comm_ret"]].merge(
            target_df[["date", "target_ret"]], on="date", how="inner",
        )
        merged = merged.dropna(subset=["comm_ret", "target_ret"])
        merged = merged.sort_values("date", ascending=True).reset_index(drop=True)

        if len(merged) < 20:
            continue

        # 20-day rolling correlation (latest)
        rolling_20 = merged["comm_ret"].rolling(20).corr(merged["target_ret"])
        latest_20d = float(rolling_20.iloc[-1]) if not pd.isna(rolling_20.iloc[-1]) else None

        # 60-day average correlation
        if len(merged) >= 60:
            last_60 = rolling_20.tail(60).dropna()
            avg_60d = round(float(last_60.mean()), 2) if len(last_60) > 0 else None
        else:
            avg_60d = latest_20d  # Fall back to what we have

        if latest_20d is not None:
            correlations[target_key] = {
                "latest_20d": round(latest_20d, 2),
                "avg_60d": avg_60d,
                "interpretation": _interpret_correlation(latest_20d),
            }

    result = {
        "commodity": commodity,
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "correlations": correlations,
    }

    return json.dumps(result)
