"""FRED (Federal Reserve Economic Data) API client.

Fetches economic time-series data from the FRED REST API maintained by
the Federal Reserve Bank of St. Louis.

Key FRED series used by this module:

  Crude Oil & Energy:
    DCOILWTICO    — WTI Crude Oil Price (daily)
    DCOILBRENTEU  — Brent Crude Oil Price (daily)
    WCESTUS1      — US Ending Stocks of Crude Oil, thousands of barrels (weekly)
    WGTSTUS1      — US Total Gasoline Stocks, thousands of barrels (weekly)
    WDISTUS1      — US Distillate Fuel Oil Stocks, thousands of barrels (weekly)
    GASREGW       — Regular Gasoline Price, dollars per gallon (weekly)

  Natural Gas:
    DHHNGSP       — Henry Hub Natural Gas Spot Price (daily)

  Metals:
    PCOPPUSDM     — Global Price of Copper, USD per metric ton (monthly, IMF)
    GOLDAMGBD228NLBM — Gold Fixing Price, London Bullion Market (daily)

  Inflation:
    CPIAUCSL      — CPI All Urban Consumers (monthly)
    CPILFESL      — Core CPI ex food/energy (monthly)
    PCEPI         — PCE Price Index (monthly)
    PCEPILFE      — Core PCE ex food/energy (monthly)
    PPIFIS        — PPI Final Demand (monthly)
    T5YIE         — 5-Year Breakeven Inflation Rate (daily)
    T10YIE        — 10-Year Breakeven Inflation Rate (daily)
    T5YIFR        — 5-Year, 5-Year Forward Inflation Expectation (daily)

  Employment:
    UNRATE        — Civilian Unemployment Rate (monthly)
    PAYEMS        — Total Nonfarm Payrolls, thousands (monthly)
    ICSA          — Initial Jobless Claims, thousands (weekly)
    CCSA          — Continuing Claims, thousands (weekly)

  Yields & Rates:
    DGS2          — 2-Year Treasury Yield (daily)
    DGS5          — 5-Year Treasury Yield (daily)
    DGS10         — 10-Year Treasury Yield (daily)
    DGS30         — 30-Year Treasury Yield (daily)
    T10Y2Y        — 10-Year minus 2-Year Spread (daily)
    T10Y3M        — 10-Year minus 3-Month Spread (daily)
    FEDFUNDS      — Effective Federal Funds Rate (monthly)
    DFEDTARU      — Fed Funds Target Upper Bound (event)
    DFII5         — 5-Year TIPS Real Yield (daily)
    DFII10        — 10-Year TIPS Real Yield (daily)

  Credit Spreads:
    BAMLH0A0HYM2  — ICE BofA US High Yield OAS (daily)
    BAMLC0A0CM    — ICE BofA US Corporate Master OAS (daily)
    BAMLC0A4CBBB  — ICE BofA BBB US Corporate OAS (daily)

All public functions return JSON strings.
"""

import json
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

from tools.config import FRED_API_KEY, HISTORICAL_DATA_DIR

# ── Constants ────────────────────────────────────────────────────────────

_FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 15
_MISSING_KEY_MSG = (
    "FRED_API_KEY not set. Get one free at "
    "https://fred.stlouisfed.org/docs/api/api_key.html"
)


# ── Local-first data routing ────────────────────────────────────────────
# Maps FRED series IDs to local CSV files in /macro_2/historical_data/.
# When a mapping exists and the CSV file is present, the agent reads
# local data first (fast) and only falls back to the FRED API if the
# local file is missing or the series has no mapping (None).

FRED_TO_LOCAL_MAP: dict[str, dict | None] = {
    # Commodities & Energy
    "DCOILWTICO":       {"csv": "crude_oil.csv",             "col": "crude_oil_price"},
    "DCOILBRENTEU":     {"csv": "brent_crude.csv",          "col": "brent_crude_price"},
    "WCESTUS1":         None,  # Weekly crude inventories — API only
    "WGTSTUS1":         None,  # Weekly gasoline stocks — API only
    "WDISTUS1":         None,  # Weekly distillate stocks — API only
    "GASREGW":          {"csv": "gasoline_price.csv",        "col": "gasoline_price"},
    "DHHNGSP":          {"csv": "natural_gas_fred.csv",      "col": "natural_gas_price"},
    "PCOPPUSDM":        {"csv": "copper_price_fred.csv",     "col": "copper_price_usd_mt"},
    "GOLDAMGBD228NLBM": {"csv": "gold_price_fred.csv",      "col": "gold_price_fred"},
    # Inflation
    # NOTE: Some local CSVs store pre-computed YoY %, not raw index values.
    # "is_yoy_pct": True means the value column IS the YoY percentage —
    # do NOT recompute YoY on top of it.
    "CPIAUCSL":  {"csv": "cpi_headline.csv",              "col": "cpi",      "is_yoy_pct": True},
    "CPILFESL":  {"csv": "core_cpi.csv",                  "col": "core_cpi", "is_yoy_pct": True},
    "PCEPI":     {"csv": "pce_headline.csv",              "col": "pce"},
    "PCEPILFE":  {"csv": "core_pce.csv",                  "col": "core_pce", "is_yoy_pct": True},
    "PPIFIS":    {"csv": "ppi.csv",                       "col": "ppi",      "is_yoy_pct": True},
    "T5YIE":     {"csv": "breakeven_5y.csv",              "col": "breakeven_5y"},
    "T10YIE":    {"csv": "breakeven_10y.csv",             "col": "breakeven_10y"},
    "T5YIFR":    {"csv": "forward_inflation_5y5y.csv",    "col": "forward_inflation_5y5y"},
    # Employment
    "UNRATE": {"csv": "unemployment_rate.csv",  "col": "unemployment_rate"},
    "PAYEMS": {"csv": "nonfarm_payrolls.csv",   "col": "nonfarm_payrolls"},
    "ICSA":   {"csv": "initial_claims.csv",     "col": "initial_claims"},
    "CCSA":   {"csv": "continuing_claims.csv",  "col": "continuing_claims"},
    # Yields & Rates
    "DGS2":     {"csv": "us_2y_yield.csv",            "col": "us_2y_yield"},
    "DGS5":     {"csv": "us_5y_yield.csv",            "col": "us_5y_yield"},
    "DGS10":    {"csv": "10y_treasury_yield.csv",     "col": "10y_yield"},
    "DGS30":    {"csv": "us_30y_yield.csv",           "col": "us_30y_yield"},
    "T10Y2Y":   None,  # Computed spread — not a single CSV
    "T10Y3M":   {"csv": "spread_10y3m.csv",           "col": "spread_10y3m"},
    "FEDFUNDS": {"csv": "fed_funds_effective.csv",    "col": "fed_funds_effective"},
    "DFEDTARU": {"csv": "fed_target_upper.csv",       "col": "fed_target_upper"},
    "DFII5":    {"csv": "real_yield_5y.csv",          "col": "real_yield_5y"},
    "DFII10":   {"csv": "real_yield_10y.csv",         "col": "real_yield_10y"},
    # Credit Spreads
    "BAMLH0A0HYM2":  {"csv": "hy_oas.csv",   "col": "hy_oas"},
    "BAMLC0A0CM":    {"csv": "ig_oas.csv",   "col": "ig_oas"},
    "BAMLC0A4CBBB":  {"csv": "bbb_oas.csv", "col": "bbb_oas"},
    # ISM / Manufacturing
    "DGORDER": {"csv": "durable_goods_orders.csv",       "col": "durable_goods_orders"},
    "MANEMP":  {"csv": "manufacturing_employment.csv",   "col": "manufacturing_employment"},
    "ISRATIO": {"csv": "inventories_sales_ratio.csv",    "col": "inventories_sales_ratio"},
    # JOLTS
    "JTSJOL": {"csv": "jolts_openings.csv",     "col": "jolts_openings"},
    "JTSQUR": {"csv": "jolts_quits_rate.csv",   "col": "jolts_quits_rate"},
    "JTSHIL": {"csv": "jolts_hires.csv",        "col": "jolts_hires"},
    "JTSLDL": {"csv": "jolts_layoffs.csv",      "col": "jolts_layoffs"},
    # Productivity
    "OPHNFB": {"csv": "productivity.csv",        "col": "output_per_hour"},
    "ULCNFB": {"csv": "unit_labor_costs.csv",   "col": "unit_labor_costs"},
    # Consumer
    "PSAVERT":  {"csv": "savings_rate.csv",             "col": "savings_rate"},
    "REVOLSL":  {"csv": "revolving_credit.csv",         "col": "revolving_credit"},
    "DRALACBS": {"csv": "delinquency_rate.csv",         "col": "delinquency_rate"},
    "DRTSCILM": {"csv": "bank_lending_standards.csv",   "col": "bank_lending_standards"},
    # Housing
    "HOUST":        {"csv": "housing_starts.csv",       "col": "housing_starts"},
    "PERMIT":       {"csv": "building_permits.csv",     "col": "building_permits"},
    "EXHOSLUSM495S": {"csv": "existing_home_sales.csv", "col": "existing_home_sales"},
    "MORTGAGE30US": {"csv": "mortgage_rate_30y.csv",    "col": "mortgage_rate_30y"},
    "MSPUS":        {"csv": "median_home_price.csv",    "col": "median_home_price"},
    "CSUSHPISA":    {"csv": "case_shiller_index.csv",   "col": "case_shiller_index"},
    # Financial Stress / Sentiment
    "NFCI":         {"csv": "nfci.csv",                 "col": "nfci"},
    "SAHMREALTIME": {"csv": "sahm_rule.csv",            "col": "sahm_rule"},
    "UMCSENT":      {"csv": "consumer_sentiment.csv",   "col": "consumer_sentiment"},
    # Labor (v2.0) — no local equivalents
    "W270RE1A156NBEA": None,
    "AWHMAN":          None,
    # GDP
    "GDP": {"csv": "us_gdp.csv", "col": "us_gdp"},
}


# ── ETF price cache (yfinance) ──────────────────────────────────────────
_ETF_CACHE: dict[str, tuple[float, dict]] = {}  # {key: (timestamp, result)}
_ETF_CACHE_TTL = 1800  # 30 minutes


# ── Internal helpers ─────────────────────────────────────────────────────

def _check_api_key() -> str | None:
    """Return a JSON error string if the API key is missing, else None."""
    if not FRED_API_KEY:
        return json.dumps({"error": _MISSING_KEY_MSG})
    return None


def _try_local_csv(
    series_id: str,
    limit: int = 100,
    sort_order: str = "desc",
    observation_start: str = "",
    observation_end: str = "",
) -> list[dict] | None:
    """Try to load FRED series data from a local CSV file.

    Checks FRED_TO_LOCAL_MAP for a matching CSV.  If found, reads the file
    and converts to the same list[dict] format as the FRED API
    ({"date": "YYYY-MM-DD", "value": float}).  Returns None if the series
    has no local mapping or the CSV is missing/unreadable.
    """
    mapping = FRED_TO_LOCAL_MAP.get(series_id)
    if not mapping:
        return None

    csv_path = os.path.join(HISTORICAL_DATA_DIR, mapping["csv"])
    if not os.path.isfile(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path)
        # Identify date column (all macro CSVs use "date" or "timestamp")
        date_col = "date" if "date" in df.columns else "timestamp"
        val_col = mapping["col"]
        if val_col not in df.columns or date_col not in df.columns:
            return None

        # Use utc=True for timestamp columns that may have mixed timezone
        # offsets from DST transitions (e.g. -05:00 EST vs -04:00 EDT).
        # Without utc=True, pd.to_datetime coerces mismatched offsets to
        # NaT, silently dropping the newest data points.
        use_utc = date_col == "timestamp"
        df[date_col] = pd.to_datetime(
            df[date_col], errors="coerce", utc=use_utc
        )
        df = df.dropna(subset=[date_col, val_col])

        # Apply date range filter (mirroring _fetch_series_raw defaults)
        if observation_start:
            df = df[df[date_col] >= observation_start]
        if observation_end:
            df = df[df[date_col] <= observation_end]
        elif not observation_start:
            # Default window: last 2 years.  The original 1-year window was
            # too narrow for quarterly series (productivity, ULC — only ~3
            # observations) and borderline for monthly series (consumer
            # sentiment, Case-Shiller — ~10 observations).  Downstream YoY
            # calculations need ≥5 quarters (productivity) or ≥13 months
            # (Case-Shiller), so 2 years provides a comfortable margin.
            two_years_ago = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
            df = df[df[date_col] >= two_years_ago]

        # Sort (desc = newest first, matching FRED default)
        ascending = sort_order != "desc"
        df = df.sort_values(date_col, ascending=ascending)

        # Apply limit
        if limit and len(df) > limit:
            df = df.head(limit)

        # Convert to FRED-compatible format
        result: list[dict] = []
        for _, row in df.iterrows():
            try:
                result.append({
                    "date": row[date_col].strftime("%Y-%m-%d"),
                    "value": round(float(row[val_col]), 4),
                })
            except (ValueError, TypeError):
                continue

        return result if result else None
    except Exception:
        return None


def _fetch_series_raw(
    series_id: str,
    limit: int = 100,
    sort_order: str = "desc",
    observation_start: str = "",
    observation_end: str = "",
) -> list[dict] | None:
    """Fetch observations for a FRED series, local-first with API fallback.

    Checks local CSV data first (fast, no network).  Falls back to the
    FRED REST API if local data is unavailable.
    Returns a list of {date, value} dicts, or None on failure.
    """
    # 1. Try local CSV first (fast path)
    local = _try_local_csv(series_id, limit, sort_order,
                           observation_start, observation_end)
    if local:
        return local

    # 2. Fall back to FRED API
    if not FRED_API_KEY:
        return None

    today = datetime.utcnow().strftime("%Y-%m-%d")
    one_year_ago = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": observation_start or one_year_ago,
        "observation_end": observation_end or today,
        "limit": limit,
        "sort_order": sort_order,
    }

    try:
        resp = requests.get(_FRED_BASE_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    observations = data.get("observations", [])
    cleaned: list[dict] = []
    for obs in observations:
        val = obs.get("value", ".")
        if val == ".":
            continue
        try:
            cleaned.append({"date": obs["date"], "value": float(val)})
        except (ValueError, KeyError):
            continue

    return cleaned


def _safe_change(current: float, previous: float) -> float:
    """Compute percentage change, returning 0.0 on division-by-zero."""
    if previous == 0:
        return 0.0
    return round((current - previous) / abs(previous) * 100, 4)


def _safe_diff(current: float, previous: float) -> float:
    """Compute absolute difference, rounded."""
    return round(current - previous, 4)


# ── Regime-Aware Credit Spread Classification ─────────────────────────
# Shared across fred_data, macro_market_analysis, market_regime_enhanced,
# and protrader_frameworks. Uses percentile-first approach with absolute
# guardrails so the classification auto-calibrates as the rate environment
# shifts.  Historical reference points (updated 2026-03):
#   - Pre-COVID tight:   ~300 bps (2019)
#   - COVID crisis peak: ~1100 bps (Mar 2020)
#   - Post-COVID QE:     ~250 bps (mid-2021)
#   - Rate-hike cycle:   ~350-500 bps (2022-2023)
#   - Higher-for-longer: ~300-400 bps (2024-2025)

# Absolute guardrails — these NEVER change regardless of regime.
_HY_CRISIS_BPS     = 800   # >800 bps  → crisis (2008 GFC, 2020 COVID)
_HY_SEVERE_BPS     = 600   # >600 bps  → severe stress

# Percentile-based tiers (1-year lookback, auto-calibrating)
_PCTILE_TIGHT      = 20    # <20th  → tight / risk-on
_PCTILE_NORMAL_LO  = 40    # 20-40  → below average / benign
_PCTILE_NORMAL_HI  = 60    # 40-60  → normal
_PCTILE_ELEVATED   = 80    # 60-80  → elevated / cautionary
                            # >80    → stressed / risk-off


def classify_hy_oas(
    hy_oas_pct: float,
    percentile: float | None = None,
) -> dict:
    """Regime-aware HY OAS stress classification.

    Priority order:
    1. Absolute guardrails for extreme values (>600 bps always = severe+)
    2. 1-year percentile ranking (auto-calibrating to current regime)
    3. Fallback absolute thresholds if no percentile available

    Returns dict with stress_level, interpretation, and regime context.
    """
    bps = int(round(hy_oas_pct * 100))
    result: dict = {"hy_oas_bps": bps, "hy_oas_pct": round(hy_oas_pct, 2)}

    # ── Absolute guardrails ──
    if bps >= _HY_CRISIS_BPS:
        result["stress_level"] = "crisis"
        result["interpretation"] = f"HY spread at {bps}bps — credit crisis territory"
        result["regime_note"] = "Absolute guardrail: >800bps is crisis in any regime"
        return result
    if bps >= _HY_SEVERE_BPS:
        result["stress_level"] = "severe_stress"
        result["interpretation"] = f"HY spread at {bps}bps — severe credit stress"
        result["regime_note"] = "Absolute guardrail: >600bps is severe stress in any regime"
        return result

    # ── Percentile-based classification (preferred) ──
    if percentile is not None:
        if percentile > _PCTILE_ELEVATED:
            stress = "stressed"
            desc = "wide relative to recent history — risk-off"
        elif percentile > _PCTILE_NORMAL_HI:
            stress = "elevated"
            desc = "above average — watchful"
        elif percentile > _PCTILE_NORMAL_LO:
            stress = "normal"
            desc = "normal range for current regime"
        elif percentile > _PCTILE_TIGHT:
            stress = "below_average"
            desc = "below average — risk-on leaning"
        else:
            stress = "tight"
            desc = "tight — risk-on, complacency risk possible"

        result["stress_level"] = stress
        result["interpretation"] = f"HY spread at {bps}bps — {desc} ({percentile:.0f}th pctile, 1Y)"
        result["regime_note"] = "Percentile-based: auto-calibrated to 1-year history"
        result["one_year_percentile"] = round(percentile, 1)
        return result

    # ── Fallback: moderate absolute thresholds ──
    # Calibrated for a higher-for-longer regime (Fed Funds ~4-5%)
    if hy_oas_pct > 5.0:
        stress, desc = "stressed", "credit stress — risk-off"
    elif hy_oas_pct > 4.0:
        stress, desc = "elevated", "elevated — watchful"
    elif hy_oas_pct > 3.0:
        stress, desc = "normal", "normal range"
    elif hy_oas_pct > 2.0:
        stress, desc = "below_average", "below average — benign"
    else:
        stress, desc = "tight", "very tight — risk-on, complacency risk"

    result["stress_level"] = stress
    result["interpretation"] = f"HY spread at {bps}bps — {desc}"
    result["regime_note"] = "Fallback absolute thresholds (no percentile data available)"
    return result


def _hy_stress_score(stress_level: str) -> int:
    """Convert HY OAS stress_level to numeric score (0-9) for composite indices."""
    return {
        "crisis": 9,
        "severe_stress": 8,
        "stressed": 7,
        "elevated": 5,
        "normal": 3,
        "below_average": 2,
        "tight": 1,
    }.get(stress_level, 3)


def _find_value_n_ago(observations: list[dict], n: int) -> float | None:
    """Return the value n entries back in a descending-sorted list, or None."""
    if len(observations) > n:
        return observations[n]["value"]
    return None


def _compute_trend(observations: list[dict], n: int = 3) -> str:
    """Determine trend from the last *n* observations (desc order: newest first).

    Returns 'rising', 'falling', or 'flat'.
    """
    if len(observations) < n:
        return "insufficient_data"
    vals = [observations[i]["value"] for i in range(n)]  # newest to oldest
    ups = sum(1 for i in range(len(vals) - 1) if vals[i] > vals[i + 1])
    downs = sum(1 for i in range(len(vals) - 1) if vals[i] < vals[i + 1])
    if ups > downs:
        return "rising"
    if downs > ups:
        return "falling"
    return "flat"


def _series_summary(
    observations: list[dict] | None,
    series_id: str,
    unit: str = "",
    trend_n: int = 3,
) -> dict:
    """Build a standard summary dict from a FRED observations list."""
    if not observations or len(observations) < 1:
        return {"error": f"No data for {series_id}"}
    latest = round(observations[0]["value"], 4) if isinstance(observations[0]["value"], float) else observations[0]["value"]
    prev = _find_value_n_ago(observations, 1)
    result: dict = {
        "latest_value": latest,
        "date": observations[0]["date"],
    }
    if unit:
        result["unit"] = unit
    if prev is not None:
        result["previous_value"] = round(prev, 4) if isinstance(prev, float) else prev
        result["change"] = _safe_diff(latest, prev)
        result["change_pct"] = _safe_change(latest, prev)
    result["trend"] = _compute_trend(observations, n=trend_n)
    return result


# ═════════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════


def get_fred_series(
    series_id: str,
    observation_start: str = "",
    observation_end: str = "",
    limit: int = 100,
    sort_order: str = "desc",
) -> str:
    """Fetch a generic FRED time-series by series ID.

    Args:
        series_id: FRED series identifier (e.g. "DGS10" for 10-year yield).
        observation_start: Start date YYYY-MM-DD. Defaults to 1 year ago.
        observation_end: End date YYYY-MM-DD. Defaults to today.
        limit: Maximum observations to return (default 100).
        sort_order: "desc" (newest first) or "asc" (oldest first).

    Returns:
        JSON string with series_id, count, and observations list.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    observations = _fetch_series_raw(
        series_id,
        limit=limit,
        sort_order=sort_order,
        observation_start=observation_start,
        observation_end=observation_end,
    )

    if observations is None:
        return json.dumps({
            "error": f"Failed to fetch FRED series {series_id}",
            "series_id": series_id,
        })

    return json.dumps({
        "series_id": series_id,
        "count": len(observations),
        "observations": observations,
    })


def get_oil_fundamentals() -> str:
    """Fetch comprehensive oil market data from multiple FRED series.

    Combines WTI/Brent prices, crude oil inventories, gasoline and
    distillate stocks, and retail gasoline prices.  Computes daily and
    week-over-week changes, inventory trends, and the WTI-Brent spread.

    Returns:
        JSON string with wti, brent, wti_brent_spread, crude_inventories,
        gasoline_stocks, distillate_stocks, and gasoline_price sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    series_map = {
        "wti": "DCOILWTICO",
        "brent": "DCOILBRENTEU",
        "crude_inventories": "WCESTUS1",
        "gasoline_stocks": "WGTSTUS1",
        "distillate_stocks": "WDISTUS1",
        "gasoline_price": "GASREGW",
    }

    raw: dict[str, list[dict] | None] = {}
    for key, sid in series_map.items():
        raw[key] = _fetch_series_raw(sid, limit=52, sort_order="desc")

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # ── WTI ──────────────────────────────────────────────────────────
    wti = raw.get("wti")
    if wti and len(wti) >= 1:
        latest = round(wti[0]["value"], 2)
        prev_day = _find_value_n_ago(wti, 1)
        prev_week = _find_value_n_ago(wti, 5)
        result["wti"] = {
            "latest_price": latest,
            "date": wti[0]["date"],
            "daily_change": _safe_diff(latest, prev_day) if prev_day else None,
            "daily_change_pct": _safe_change(latest, prev_day) if prev_day else None,
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
            "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
        }
    else:
        result["wti"] = {"error": "Failed to fetch WTI data"}

    # ── Brent ────────────────────────────────────────────────────────
    brent = raw.get("brent")
    if brent and len(brent) >= 1:
        latest = round(brent[0]["value"], 2)
        prev_day = _find_value_n_ago(brent, 1)
        prev_week = _find_value_n_ago(brent, 5)
        result["brent"] = {
            "latest_price": latest,
            "date": brent[0]["date"],
            "daily_change": _safe_diff(latest, prev_day) if prev_day else None,
            "daily_change_pct": _safe_change(latest, prev_day) if prev_day else None,
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
            "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
        }
    else:
        result["brent"] = {"error": "Failed to fetch Brent data"}

    # ── WTI-Brent Spread ─────────────────────────────────────────────
    if (
        isinstance(result.get("wti"), dict)
        and "latest_price" in result["wti"]
        and isinstance(result.get("brent"), dict)
        and "latest_price" in result["brent"]
    ):
        spread = round(result["wti"]["latest_price"] - result["brent"]["latest_price"], 4)
        result["wti_brent_spread"] = {
            "value": spread,
            "interpretation": (
                "Brent premium (typical)" if spread < 0
                else "WTI premium (unusual)" if spread > 0
                else "At parity"
            ),
        }
    else:
        result["wti_brent_spread"] = {"error": "Cannot compute — missing price data"}

    # ── Crude Oil Inventories ────────────────────────────────────────
    crude_inv = raw.get("crude_inventories")
    if crude_inv and len(crude_inv) >= 1:
        latest = round(crude_inv[0]["value"], 2)
        prev_week = _find_value_n_ago(crude_inv, 1)
        wow_change = _safe_diff(latest, prev_week) if prev_week else None

        # 4-week average change
        four_week_avg = None
        if len(crude_inv) >= 5:
            changes = []
            for i in range(4):
                changes.append(crude_inv[i]["value"] - crude_inv[i + 1]["value"])
            four_week_avg = round(sum(changes) / len(changes), 2)

        # Interpretation
        if wow_change is not None:
            if wow_change > 500:
                interpretation = "building"
            elif wow_change < -500:
                interpretation = "drawing"
            else:
                interpretation = "flat"
        else:
            interpretation = "unknown"

        result["crude_inventories"] = {
            "latest_value_thousand_barrels": latest,
            "date": crude_inv[0]["date"],
            "wow_change": wow_change,
            "four_week_avg_change": four_week_avg,
            "interpretation": interpretation,
        }
    else:
        result["crude_inventories"] = {
            "error": "Failed to fetch crude inventory data (WCESTUS1)",
            "hint": "Check FRED_API_KEY validity and network connectivity",
        }

    # ── Gasoline Stocks ──────────────────────────────────────────────
    gas_stocks = raw.get("gasoline_stocks")
    if gas_stocks and len(gas_stocks) >= 1:
        latest = round(gas_stocks[0]["value"], 2)
        prev_week = _find_value_n_ago(gas_stocks, 1)
        result["gasoline_stocks"] = {
            "latest_value_thousand_barrels": latest,
            "date": gas_stocks[0]["date"],
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
        }
    else:
        result["gasoline_stocks"] = {
            "error": "Failed to fetch gasoline stock data (WGTSTUS1)",
            "hint": "Check FRED_API_KEY validity and network connectivity",
        }

    # ── Distillate Stocks ────────────────────────────────────────────
    dist_stocks = raw.get("distillate_stocks")
    if dist_stocks and len(dist_stocks) >= 1:
        latest = round(dist_stocks[0]["value"], 2)
        prev_week = _find_value_n_ago(dist_stocks, 1)
        result["distillate_stocks"] = {
            "latest_value_thousand_barrels": latest,
            "date": dist_stocks[0]["date"],
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
        }
    else:
        result["distillate_stocks"] = {
            "error": "Failed to fetch distillate stock data (WDISTUS1)",
            "hint": "Check FRED_API_KEY validity and network connectivity",
        }

    # ── Retail Gasoline Price ────────────────────────────────────────
    gas_price = raw.get("gasoline_price")
    if gas_price and len(gas_price) >= 1:
        result["gasoline_price"] = {
            "latest_price_per_gallon": round(gas_price[0]["value"], 3),
            "date": gas_price[0]["date"],
        }
    else:
        result["gasoline_price"] = {"error": "Failed to fetch gasoline price data"}

    return json.dumps(result, indent=2)


def get_commodity_supply_demand(commodity: str) -> str:
    """Fetch FRED data for a specific commodity with supply/demand analysis.

    Supports: crude_oil, natural_gas, copper, gold.

    Args:
        commodity: One of "crude_oil", "natural_gas", "copper", "gold".

    Returns:
        JSON string with commodity, source (FRED series IDs), price_data,
        supply_demand_indicators, and signals.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    commodity = commodity.strip().lower().replace(" ", "_")

    if commodity == "crude_oil":
        return _crude_oil_supply_demand()
    elif commodity == "natural_gas":
        return _natural_gas_supply_demand()
    elif commodity == "copper":
        return _copper_supply_demand()
    elif commodity == "gold":
        return _gold_supply_demand()
    else:
        return json.dumps({
            "error": f"Unsupported commodity: {commodity}",
            "supported": ["crude_oil", "natural_gas", "copper", "gold"],
        })


def get_inflation_data() -> str:
    """Fetch inflation indicators from FRED.

    Returns CPI (headline & core), PCE (headline & core), PPI final demand,
    and market-based breakeven inflation rates (5Y, 10Y, 5Y5Y forward).

    Returns:
        JSON string with cpi, core_cpi, pce, core_pce, ppi, and breakevens sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # ── CPI / PCE / PPI (monthly, last 24 observations = 2 years) ──
    monthly_series = {
        "cpi": ("CPIAUCSL", "index (1982-84=100)"),
        "core_cpi": ("CPILFESL", "index (1982-84=100)"),
        "pce": ("PCEPI", "index (2017=100)"),
        "core_pce": ("PCEPILFE", "index (2017=100)"),
        "ppi": ("PPIFIS", "index (Nov 2009=100)"),
    }

    # Need 2+ years of data for YoY calculations on monthly series
    two_years_ago = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")

    for key, (sid, unit) in monthly_series.items():
        obs = _fetch_series_raw(sid, limit=24, sort_order="desc", observation_start=two_years_ago)
        summary = _series_summary(obs, sid, unit=unit, trend_n=3)

        # Check if local CSV already stores YoY percentages (not raw index).
        # If so, the latest value IS the YoY % — skip recomputation.
        local_mapping = FRED_TO_LOCAL_MAP.get(sid, {}) or {}
        is_yoy_pct = local_mapping.get("is_yoy_pct", False)

        if is_yoy_pct and obs and len(obs) >= 1:
            # Local CSV value is already YoY % — use directly
            yoy_pct = round(obs[0]["value"], 2)
            summary["yoy_change_pct"] = yoy_pct
            summary["data_format"] = "local_csv_yoy_pct"
        elif obs and len(obs) >= 13:
            # Raw index values (e.g., FRED API or PCE headline index) —
            # compute YoY using date-based 12-month lookback.
            latest_date_str = obs[0].get("date", "")
            year_ago_value = None
            if latest_date_str:
                try:
                    latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d")
                    target_dt = latest_dt.replace(year=latest_dt.year - 1)
                except ValueError:
                    # Handle Feb 29 → Feb 28 for leap years
                    target_dt = latest_dt.replace(year=latest_dt.year - 1, day=28)
                # Find the observation closest to 12 months ago
                best_match = None
                best_delta = timedelta(days=999)
                for o in obs[1:]:
                    o_date_str = o.get("date", "")
                    if not o_date_str:
                        continue
                    try:
                        o_dt = datetime.strptime(o_date_str, "%Y-%m-%d")
                    except ValueError:
                        continue
                    delta = abs(o_dt - target_dt)
                    if delta < best_delta:
                        best_delta = delta
                        best_match = o
                # Only use if within 45 days of target (handles monthly data gaps)
                if best_match and best_delta <= timedelta(days=45):
                    year_ago_value = best_match.get("value")
            year_ago = year_ago_value
            if year_ago and year_ago != 0:
                yoy_pct = round((obs[0]["value"] - year_ago) / year_ago * 100, 2)
                summary["yoy_change_pct"] = yoy_pct

        # Interpretation for CPI/PCE
        yoy_pct = summary.get("yoy_change_pct")
        if yoy_pct is not None and key in ("cpi", "core_cpi", "pce", "core_pce"):
            if yoy_pct > 3.0:
                summary["interpretation"] = f"Above Fed 2% target at {yoy_pct}% — elevated"
            elif yoy_pct > 2.5:
                summary["interpretation"] = f"Moderately above target at {yoy_pct}%"
            elif yoy_pct >= 1.5:
                summary["interpretation"] = f"Near target at {yoy_pct}%"
            else:
                summary["interpretation"] = f"Below target at {yoy_pct}% — disinflation risk"

        result[key] = summary

    # ── Breakeven Inflation Rates (daily, last 60 observations) ──
    breakeven_series = {
        "t5yie": ("T5YIE", "5Y Breakeven Inflation"),
        "t10yie": ("T10YIE", "10Y Breakeven Inflation"),
        "t5yifr": ("T5YIFR", "5Y5Y Forward Inflation Expectation"),
    }

    breakevens: dict = {}
    for key, (sid, label) in breakeven_series.items():
        obs = _fetch_series_raw(sid, limit=60, sort_order="desc")
        summary = _series_summary(obs, sid, unit="percent", trend_n=5)
        if "latest_value" in summary:
            val = summary["latest_value"]
            if val > 2.5:
                summary["interpretation"] = f"{label} at {val}% — above Fed target, inflation risk"
            elif val >= 2.0:
                summary["interpretation"] = f"{label} at {val}% — well-anchored near target"
            else:
                summary["interpretation"] = f"{label} at {val}% — below target, disinflation expectation"
        breakevens[key] = summary

    result["breakevens"] = breakevens

    return json.dumps(result, indent=2)


def get_employment_data() -> str:
    """Fetch employment indicators from FRED.

    Returns unemployment rate, nonfarm payrolls (with MoM change = NFP number),
    initial jobless claims, and continuing claims.

    Returns:
        JSON string with unemployment_rate, nonfarm_payrolls, initial_claims,
        and continuing_claims sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # ── Unemployment Rate (monthly) ──
    unrate = _fetch_series_raw("UNRATE", limit=24, sort_order="desc")
    ur_summary = _series_summary(unrate, "UNRATE", unit="percent", trend_n=3)
    if "latest_value" in ur_summary:
        val = ur_summary["latest_value"]
        if val < 4.0:
            ur_summary["interpretation"] = f"Tight labor market at {val}%"
        elif val < 5.0:
            ur_summary["interpretation"] = f"Moderate at {val}%"
        elif val < 6.0:
            ur_summary["interpretation"] = f"Loosening labor market at {val}%"
        else:
            ur_summary["interpretation"] = f"Weak labor market at {val}%"
    result["unemployment_rate"] = ur_summary

    # ── Nonfarm Payrolls (monthly, thousands) ──
    payems = _fetch_series_raw("PAYEMS", limit=24, sort_order="desc")
    nfp_summary = _series_summary(payems, "PAYEMS", unit="thousands", trend_n=3)
    if payems and len(payems) >= 2:
        nfp_change = round(payems[0]["value"] - payems[1]["value"], 1)
        nfp_summary["nfp_monthly_change_thousands"] = nfp_change
        if nfp_change > 200:
            nfp_summary["interpretation"] = f"Strong job growth: +{nfp_change}K"
        elif nfp_change > 100:
            nfp_summary["interpretation"] = f"Solid job growth: +{nfp_change}K"
        elif nfp_change > 0:
            nfp_summary["interpretation"] = f"Modest job growth: +{nfp_change}K"
        else:
            nfp_summary["interpretation"] = f"Job losses: {nfp_change}K"
        # 3-month average
        if len(payems) >= 4:
            changes_3m = [payems[i]["value"] - payems[i + 1]["value"] for i in range(3)]
            nfp_summary["three_month_avg_change"] = round(sum(changes_3m) / 3, 1)
    result["nonfarm_payrolls"] = nfp_summary

    # ── Initial Claims (weekly) ──
    icsa = _fetch_series_raw("ICSA", limit=20, sort_order="desc")
    ic_summary = _series_summary(icsa, "ICSA", unit="thousands", trend_n=4)
    if icsa and len(icsa) >= 4:
        four_week_avg = round(sum(o["value"] for o in icsa[:4]) / 4, 1)
        ic_summary["four_week_avg"] = four_week_avg
        if four_week_avg < 225:
            ic_summary["interpretation"] = f"Low claims ({four_week_avg}K avg) — healthy labor market"
        elif four_week_avg < 300:
            ic_summary["interpretation"] = f"Moderate claims ({four_week_avg}K avg)"
        else:
            ic_summary["interpretation"] = f"Elevated claims ({four_week_avg}K avg) — labor market stress"
    result["initial_claims"] = ic_summary

    # ── Continuing Claims (weekly) ──
    ccsa = _fetch_series_raw("CCSA", limit=20, sort_order="desc")
    cc_summary = _series_summary(ccsa, "CCSA", unit="thousands", trend_n=4)
    if ccsa and len(ccsa) >= 4:
        four_week_avg = round(sum(o["value"] for o in ccsa[:4]) / 4, 1)
        cc_summary["four_week_avg"] = four_week_avg
    result["continuing_claims"] = cc_summary

    return json.dumps(result, indent=2)


def get_yield_curve_data() -> str:
    """Fetch yield curve data from FRED.

    Returns nominal Treasury yields (2Y, 5Y, 10Y, 30Y), yield curve spreads
    (10Y-2Y, 10Y-3M), Fed funds rate, and real yields (5Y/10Y TIPS).

    Returns:
        JSON string with nominal_yields, yield_curve_spreads, fed_policy,
        and real_yields sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # ── Nominal Yields (daily) ──
    yield_series = {
        "2y": "DGS2",
        "5y": "DGS5",
        "10y": "DGS10",
        "30y": "DGS30",
    }

    nominal_yields: dict = {}
    for label, sid in yield_series.items():
        obs = _fetch_series_raw(sid, limit=60, sort_order="desc")
        summary = _series_summary(obs, sid, unit="percent", trend_n=5)
        if obs and len(obs) >= 2:
            summary["daily_change_bps"] = round((obs[0]["value"] - obs[1]["value"]) * 100, 1)
        if obs and len(obs) >= 6:
            summary["wow_change_bps"] = round((obs[0]["value"] - obs[5]["value"]) * 100, 1)
        nominal_yields[label] = summary

    result["nominal_yields"] = nominal_yields

    # ── Yield Curve Spreads (daily, pre-computed by FRED) ──
    spread_series = {
        "2s10s": "T10Y2Y",
        "3m10s": "T10Y3M",
    }

    spreads: dict = {}
    for label, sid in spread_series.items():
        obs = _fetch_series_raw(sid, limit=60, sort_order="desc")
        summary = _series_summary(obs, sid, unit="percent", trend_n=5)
        if "latest_value" in summary:
            val = summary["latest_value"]
            if val < -0.25:
                summary["curve_status"] = "inverted"
                summary["interpretation"] = f"{label} at {val:.2f}% — inverted (recession signal)"
            elif val < 0.25:
                summary["curve_status"] = "flat"
                summary["interpretation"] = f"{label} at {val:.2f}% — flat"
            else:
                summary["curve_status"] = "normal"
                summary["interpretation"] = f"{label} at {val:.2f}% — normal"
            # Slope trend (steepening vs flattening)
            if summary.get("trend") == "rising":
                summary["slope_trend"] = "steepening"
            elif summary.get("trend") == "falling":
                summary["slope_trend"] = "flattening"
            else:
                summary["slope_trend"] = "stable"
        spreads[label] = summary

    result["yield_curve_spreads"] = spreads

    # ── Yield curve shape summary ──
    s2s10s = spreads.get("2s10s", {})
    s3m10s = spreads.get("3m10s", {})
    if s2s10s.get("curve_status") == "inverted" and s3m10s.get("curve_status") == "inverted":
        result["curve_shape"] = "fully inverted — strong recession signal"
    elif s2s10s.get("curve_status") == "inverted" or s3m10s.get("curve_status") == "inverted":
        result["curve_shape"] = "partially inverted — watch closely"
    elif s2s10s.get("curve_status") == "flat" or s3m10s.get("curve_status") == "flat":
        result["curve_shape"] = "flattening — late-cycle indicator"
    else:
        result["curve_shape"] = "normal — no recession signal"

    # ── Fed Policy ──
    fed_policy: dict = {}

    fedfunds = _fetch_series_raw("FEDFUNDS", limit=12, sort_order="desc")
    fed_policy["effective_rate"] = _series_summary(fedfunds, "FEDFUNDS", unit="percent", trend_n=3)

    target_upper = _fetch_series_raw("DFEDTARU", limit=10, sort_order="desc")
    fed_policy["target_upper"] = _series_summary(target_upper, "DFEDTARU", unit="percent", trend_n=3)

    # Restrictive assessment: compare Fed funds to 10Y
    ten_y = nominal_yields.get("10y", {})
    ff = fed_policy.get("effective_rate", {})
    if "latest_value" in ten_y and "latest_value" in ff:
        ff_val = ff["latest_value"]
        ten_y_val = ten_y["latest_value"]
        if ff_val > ten_y_val:
            fed_policy["stance"] = f"Restrictive — Fed funds ({ff_val}%) above 10Y ({ten_y_val}%)"
        elif ff_val > ten_y_val - 0.5:
            fed_policy["stance"] = f"Tight — Fed funds ({ff_val}%) near 10Y ({ten_y_val}%)"
        else:
            fed_policy["stance"] = f"Neutral-to-accommodative — Fed funds ({ff_val}%) below 10Y ({ten_y_val}%)"

    result["fed_policy"] = fed_policy

    # ── Real Yields (TIPS, daily) ──
    real_yield_series = {
        "5y_real": "DFII5",
        "10y_real": "DFII10",
    }

    real_yields: dict = {}
    for label, sid in real_yield_series.items():
        obs = _fetch_series_raw(sid, limit=60, sort_order="desc")
        summary = _series_summary(obs, sid, unit="percent", trend_n=5)
        if "latest_value" in summary:
            val = summary["latest_value"]
            if val > 2.5:
                summary["interpretation"] = f"Very restrictive real yield at {val}%"
            elif val > 2.0:
                summary["interpretation"] = f"Restrictive real yield at {val}%"
            elif val > 1.0:
                summary["interpretation"] = f"Moderately positive real yield at {val}%"
            elif val > 0:
                summary["interpretation"] = f"Low positive real yield at {val}%"
            else:
                summary["interpretation"] = f"Negative real yield at {val}% — accommodative"
        if obs and len(obs) >= 2:
            summary["daily_change_bps"] = round((obs[0]["value"] - obs[1]["value"]) * 100, 1)
        real_yields[label] = summary

    result["real_yields"] = real_yields

    return json.dumps(result, indent=2)


def get_credit_spread_data() -> str:
    """Fetch credit spread data from FRED.

    Returns ICE BofA US High Yield OAS, US Corporate (IG) OAS, and BBB OAS,
    plus a computed HY-IG differential. Flags stress levels.

    Returns:
        JSON string with high_yield_oas, ig_corporate_oas, bbb_oas,
        and hy_ig_differential sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    spread_series = {
        "high_yield_oas": ("BAMLH0A0HYM2", "ICE BofA US High Yield OAS"),
        "ig_corporate_oas": ("BAMLC0A0CM", "ICE BofA US Corporate Master OAS"),
        "bbb_oas": ("BAMLC0A4CBBB", "ICE BofA BBB US Corporate OAS"),
    }

    raw_data: dict = {}
    for key, (sid, label) in spread_series.items():
        obs = _fetch_series_raw(sid, limit=260, sort_order="desc")
        summary = _series_summary(obs, sid, unit="bps (OAS)", trend_n=5)

        if obs and len(obs) >= 6:
            summary["wow_change_bps"] = round((obs[0]["value"] - obs[5]["value"]) * 100, 1)
        if obs and len(obs) >= 22:
            summary["mom_change_bps"] = round((obs[0]["value"] - obs[21]["value"]) * 100, 1)

        # Stress flags
        # NOTE: FRED OAS series return values in percentage points (e.g. 3.08 = 308 bps)
        if "latest_value" in summary:
            val = summary["latest_value"]
            bps = int(round(val * 100))
            summary["latest_value_bps"] = bps
            if key == "high_yield_oas":
                # Regime-aware classification — uses percentile if available
                pctile = None
                if obs and len(obs) >= 60:
                    all_vals_sorted = sorted(o["value"] for o in obs)
                    pctile = sum(1 for v in all_vals_sorted if v <= val) / len(all_vals_sorted) * 100
                hy_class = classify_hy_oas(val, percentile=pctile)
                summary["stress_level"] = hy_class["stress_level"]
                summary["interpretation"] = hy_class["interpretation"]
                summary["regime_note"] = hy_class.get("regime_note", "")
            elif key == "ig_corporate_oas":
                if val > 2.0:
                    summary["stress_level"] = "stress"
                    summary["interpretation"] = f"IG spread at {bps}bps — elevated stress"
                elif val > 1.5:
                    summary["stress_level"] = "elevated"
                    summary["interpretation"] = f"IG spread at {bps}bps — slightly elevated"
                elif val > 1.0:
                    summary["stress_level"] = "normal"
                    summary["interpretation"] = f"IG spread at {bps}bps — normal range"
                else:
                    summary["stress_level"] = "tight"
                    summary["interpretation"] = f"IG spread at {bps}bps — tight, risk-on"

        # Historical percentile (1-year, using available data)
        if obs and len(obs) >= 60:
            all_vals = sorted(o["value"] for o in obs)
            latest_val = obs[0]["value"]
            pctile = sum(1 for v in all_vals if v <= latest_val) / len(all_vals) * 100
            summary["one_year_percentile"] = round(pctile, 1)

        # Trend interpretation
        trend = summary.get("trend", "flat")
        if trend == "rising":
            summary["spread_direction"] = "widening"
        elif trend == "falling":
            summary["spread_direction"] = "tightening"
        else:
            summary["spread_direction"] = "stable"

        raw_data[key] = obs
        result[key] = summary

    # ── HY-IG Differential ──
    hy = raw_data.get("high_yield_oas")
    ig = raw_data.get("ig_corporate_oas")
    if hy and ig and len(hy) >= 1 and len(ig) >= 1:
        diff_pct = round(hy[0]["value"] - ig[0]["value"], 2)
        diff_bps = int(round(diff_pct * 100))
        result["hy_ig_differential"] = {
            "value_pct": diff_pct,
            "value_bps": diff_bps,
            "interpretation": (
                "Wide differential — risk aversion in lower-quality credit"
                if diff_pct > 4.0 else
                "Normal differential"
                if diff_pct > 2.5 else
                "Tight differential — strong risk appetite"
            ),
        }

    return json.dumps(result, indent=2)


# ═════════════════════════════════════════════════════════════════════════
# COMMODITY-SPECIFIC HELPERS
# ═════════════════════════════════════════════════════════════════════════


def _crude_oil_supply_demand() -> str:
    """Crude oil supply/demand analysis grouped into price, inventories, spreads."""
    wti = _fetch_series_raw("DCOILWTICO", limit=52, sort_order="desc")
    brent = _fetch_series_raw("DCOILBRENTEU", limit=52, sort_order="desc")
    crude_inv = _fetch_series_raw("WCESTUS1", limit=52, sort_order="desc")
    gas_stocks = _fetch_series_raw("WGTSTUS1", limit=52, sort_order="desc")
    dist_stocks = _fetch_series_raw("WDISTUS1", limit=52, sort_order="desc")

    signals: list[str] = []
    result: dict = {
        "commodity": "crude_oil",
        "source": ["DCOILWTICO", "DCOILBRENTEU", "WCESTUS1", "WGTSTUS1", "WDISTUS1"],
    }

    # ── Price section ────────────────────────────────────────────────
    price_data: dict = {}
    if wti and len(wti) >= 1:
        latest = wti[0]["value"]
        prev_week = _find_value_n_ago(wti, 5)
        # Approximate MoM: ~22 trading days
        prev_month = _find_value_n_ago(wti, 22)
        price_data["wti"] = {
            "latest": latest,
            "date": wti[0]["date"],
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
            "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
            "mom_change": _safe_diff(latest, prev_month) if prev_month else None,
            "mom_change_pct": _safe_change(latest, prev_month) if prev_month else None,
        }
        if prev_week and _safe_change(latest, prev_week) > 5:
            signals.append("WTI_PRICE_SURGE_WEEKLY")
        if prev_week and _safe_change(latest, prev_week) < -5:
            signals.append("WTI_PRICE_DROP_WEEKLY")

    if brent and len(brent) >= 1:
        latest = brent[0]["value"]
        prev_week = _find_value_n_ago(brent, 5)
        prev_month = _find_value_n_ago(brent, 22)
        price_data["brent"] = {
            "latest": latest,
            "date": brent[0]["date"],
            "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
            "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
            "mom_change": _safe_diff(latest, prev_month) if prev_month else None,
            "mom_change_pct": _safe_change(latest, prev_month) if prev_month else None,
        }

    result["price_data"] = price_data

    # ── Spreads section ──────────────────────────────────────────────
    spreads: dict = {}
    if (
        wti and brent
        and len(wti) >= 1 and len(brent) >= 1
    ):
        spread_val = round(wti[0]["value"] - brent[0]["value"], 4)
        spreads["wti_brent"] = {
            "value": spread_val,
            "interpretation": (
                "Brent premium (typical)" if spread_val < 0
                else "WTI premium (unusual)" if spread_val > 0
                else "At parity"
            ),
        }
        if spread_val > 2:
            signals.append("WTI_PREMIUM_UNUSUAL")
        if spread_val < -8:
            signals.append("WIDE_BRENT_PREMIUM")
    result["spreads"] = spreads

    # ── Inventories section ──────────────────────────────────────────
    inventories: dict = {}

    if crude_inv and len(crude_inv) >= 2:
        latest = crude_inv[0]["value"]
        prev = crude_inv[1]["value"]
        wow = _safe_diff(latest, prev)
        inventories["crude_oil"] = {
            "latest_thousand_barrels": latest,
            "date": crude_inv[0]["date"],
            "wow_change": wow,
        }
        # 4-week average
        if len(crude_inv) >= 5:
            changes = [crude_inv[i]["value"] - crude_inv[i + 1]["value"] for i in range(4)]
            avg_change = round(sum(changes) / 4, 2)
            inventories["crude_oil"]["four_week_avg_change"] = avg_change
            if avg_change > 1000:
                signals.append("INVENTORY_BUILD")
            elif avg_change < -1000:
                signals.append("INVENTORY_DRAW")
            if len(crude_inv) >= 9:
                prev_4wk = [crude_inv[i]["value"] - crude_inv[i + 1]["value"] for i in range(4, 8)]
                prev_avg = round(sum(prev_4wk) / 4, 2)
                if avg_change < prev_avg and avg_change < -500:
                    signals.append("INVENTORY_DRAW_ACCELERATING")
                if avg_change > prev_avg and avg_change > 500:
                    signals.append("INVENTORY_BUILD_ACCELERATING")

        if wow > 500:
            inventories["crude_oil"]["interpretation"] = "building"
        elif wow < -500:
            inventories["crude_oil"]["interpretation"] = "drawing"
        else:
            inventories["crude_oil"]["interpretation"] = "flat"

    if gas_stocks and len(gas_stocks) >= 2:
        latest = gas_stocks[0]["value"]
        prev = gas_stocks[1]["value"]
        inventories["gasoline"] = {
            "latest_thousand_barrels": latest,
            "date": gas_stocks[0]["date"],
            "wow_change": _safe_diff(latest, prev),
        }

    if dist_stocks and len(dist_stocks) >= 2:
        latest = dist_stocks[0]["value"]
        prev = dist_stocks[1]["value"]
        inventories["distillate"] = {
            "latest_thousand_barrels": latest,
            "date": dist_stocks[0]["date"],
            "wow_change": _safe_diff(latest, prev),
        }

    result["supply_demand_indicators"] = inventories
    result["signals"] = signals

    return json.dumps(result, indent=2)


def _natural_gas_supply_demand() -> str:
    """Natural gas price analysis using Henry Hub spot."""
    obs = _fetch_series_raw("DHHNGSP", limit=52, sort_order="desc")

    if not obs or len(obs) < 1:
        return json.dumps({
            "commodity": "natural_gas",
            "source": ["DHHNGSP"],
            "error": "Failed to fetch Henry Hub natural gas data",
        })

    latest = obs[0]["value"]
    prev_week = _find_value_n_ago(obs, 5)
    prev_month = _find_value_n_ago(obs, 22)

    signals: list[str] = []

    price_data = {
        "latest": latest,
        "date": obs[0]["date"],
        "unit": "dollars_per_mmbtu",
        "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
        "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
        "mom_change": _safe_diff(latest, prev_month) if prev_month else None,
        "mom_change_pct": _safe_change(latest, prev_month) if prev_month else None,
    }

    if prev_week:
        wow_pct = _safe_change(latest, prev_week)
        if wow_pct > 10:
            signals.append("NATGAS_PRICE_SURGE_WEEKLY")
        if wow_pct < -10:
            signals.append("NATGAS_PRICE_DROP_WEEKLY")
    if latest > 5.0:
        signals.append("NATGAS_ELEVATED")
    if latest < 2.0:
        signals.append("NATGAS_DEPRESSED")

    return json.dumps({
        "commodity": "natural_gas",
        "source": ["DHHNGSP"],
        "price_data": price_data,
        "supply_demand_indicators": {},
        "signals": signals,
    }, indent=2)


def _copper_supply_demand() -> str:
    """Copper price analysis using IMF global price (monthly)."""
    obs = _fetch_series_raw("PCOPPUSDM", limit=24, sort_order="desc")

    if not obs or len(obs) < 1:
        return json.dumps({
            "commodity": "copper",
            "source": ["PCOPPUSDM"],
            "error": "Failed to fetch global copper price data",
        })

    latest = obs[0]["value"]
    prev_month = _find_value_n_ago(obs, 1)
    prev_3m = _find_value_n_ago(obs, 3)

    signals: list[str] = []

    price_data = {
        "latest": latest,
        "date": obs[0]["date"],
        "unit": "usd_per_metric_ton",
        "wow_change": None,  # Monthly data — no weekly change
        "wow_change_pct": None,
        "mom_change": _safe_diff(latest, prev_month) if prev_month else None,
        "mom_change_pct": _safe_change(latest, prev_month) if prev_month else None,
    }

    if prev_month:
        mom_pct = _safe_change(latest, prev_month)
        if mom_pct > 5:
            signals.append("COPPER_PRICE_SURGE_MONTHLY")
        if mom_pct < -5:
            signals.append("COPPER_PRICE_DROP_MONTHLY")

    if prev_3m:
        three_m_pct = _safe_change(latest, prev_3m)
        price_data["three_month_change"] = _safe_diff(latest, prev_3m)
        price_data["three_month_change_pct"] = three_m_pct
        if three_m_pct > 15:
            signals.append("COPPER_UPTREND_3M")
        if three_m_pct < -15:
            signals.append("COPPER_DOWNTREND_3M")

    return json.dumps({
        "commodity": "copper",
        "source": ["PCOPPUSDM"],
        "price_data": price_data,
        "supply_demand_indicators": {},
        "signals": signals,
    }, indent=2)


def _gold_supply_demand() -> str:
    """Gold price analysis using London gold fixing."""
    obs = _fetch_series_raw("GOLDAMGBD228NLBM", limit=52, sort_order="desc")

    if not obs or len(obs) < 1:
        return json.dumps({
            "commodity": "gold",
            "source": ["GOLDAMGBD228NLBM"],
            "error": "Failed to fetch gold price data",
        })

    latest = obs[0]["value"]
    prev_week = _find_value_n_ago(obs, 5)
    prev_month = _find_value_n_ago(obs, 22)

    signals: list[str] = []

    price_data = {
        "latest": latest,
        "date": obs[0]["date"],
        "unit": "usd_per_troy_ounce",
        "wow_change": _safe_diff(latest, prev_week) if prev_week else None,
        "wow_change_pct": _safe_change(latest, prev_week) if prev_week else None,
        "mom_change": _safe_diff(latest, prev_month) if prev_month else None,
        "mom_change_pct": _safe_change(latest, prev_month) if prev_month else None,
    }

    if prev_week:
        wow_pct = _safe_change(latest, prev_week)
        if wow_pct > 3:
            signals.append("GOLD_PRICE_SURGE_WEEKLY")
        if wow_pct < -3:
            signals.append("GOLD_PRICE_DROP_WEEKLY")
    if prev_month:
        mom_pct = _safe_change(latest, prev_month)
        if mom_pct > 8:
            signals.append("GOLD_UPTREND_MONTHLY")
        if mom_pct < -8:
            signals.append("GOLD_DOWNTREND_MONTHLY")

    # 52-week high/low from available data
    if len(obs) >= 10:
        all_vals = [o["value"] for o in obs]
        high = max(all_vals)
        low = min(all_vals)
        price_data["period_high"] = high
        price_data["period_low"] = low
        if latest >= high * 0.98:
            signals.append("GOLD_NEAR_PERIOD_HIGH")
        if latest <= low * 1.02:
            signals.append("GOLD_NEAR_PERIOD_LOW")

    return json.dumps({
        "commodity": "gold",
        "source": ["GOLDAMGBD228NLBM"],
        "price_data": price_data,
        "supply_demand_indicators": {},
        "signals": signals,
    }, indent=2)


# ═════════════════════════════════════════════════════════════════════════
# ISM DECOMPOSITION
# ═════════════════════════════════════════════════════════════════════════


def get_ism_decomposition() -> str:
    """Manufacturing sector decomposition using headline ISM PMI + FRED proxy data.

    Combines headline ISM PMI (from local CSV) with FRED manufacturing proxies:
    - DGORDER: Durable Goods New Orders (demand proxy, millions $)
    - MANEMP: Manufacturing Employment (thousands)
    - ISRATIO: Total Business Inventories/Sales Ratio

    Note: ISM sub-component diffusion indices (NAPMNOI, NAPMEI, NAPMII) are
    discontinued on FRED. We use real manufacturing data as proxies instead.

    Returns:
        JSON string with headline_pmi, new_orders, employment, inventories,
        decomposition, and signals sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # ── Headline ISM PMI from local CSV ──
    headline_pmi = None
    try:
        from tools import macro_data
        pmi_raw = macro_data.analyze_indicator_changes("ism_pmi")
        pmi_data = json.loads(pmi_raw)
        metrics = pmi_data.get("metrics", {})
        for col, m in metrics.items():
            headline_pmi = m.get("latest_value")
            break
    except Exception:
        headline_pmi = None
    result["headline_pmi"] = headline_pmi

    # ── FRED proxy: Durable Goods New Orders (demand proxy) ──
    dg_obs = _fetch_series_raw("DGORDER", limit=24, sort_order="desc")
    dg_summary = _series_summary(dg_obs, "DGORDER", unit="millions $", trend_n=3)
    if "latest_value" in dg_summary:
        if dg_summary.get("trend") == "falling":
            dg_summary["interpretation"] = "Manufacturing demand weakening — durable goods orders declining"
        elif dg_summary.get("trend") == "rising":
            dg_summary["interpretation"] = "Manufacturing demand strengthening"
        else:
            dg_summary["interpretation"] = "Manufacturing demand stable"
    result["new_orders"] = dg_summary

    # ── FRED proxy: Manufacturing Employment (MANEMP) ──
    manemp_obs = _fetch_series_raw("MANEMP", limit=24, sort_order="desc")
    manemp_summary = _series_summary(manemp_obs, "MANEMP", unit="thousands", trend_n=3)
    if "latest_value" in manemp_summary:
        trend = manemp_summary.get("trend")
        if trend == "falling":
            manemp_summary["interpretation"] = "Manufacturing shedding workers"
        elif trend == "rising":
            manemp_summary["interpretation"] = "Manufacturing adding workers"
        else:
            manemp_summary["interpretation"] = "Manufacturing employment flat — consistent with barely expansionary ISM"
    result["employment"] = manemp_summary

    # ── FRED proxy: Inventories/Sales Ratio (ISRATIO) ──
    isratio_obs = _fetch_series_raw("ISRATIO", limit=24, sort_order="desc")
    isratio_summary = _series_summary(isratio_obs, "ISRATIO", unit="ratio", trend_n=3)
    if "latest_value" in isratio_summary:
        val = isratio_summary["latest_value"]
        if val > 1.45:
            isratio_summary["interpretation"] = "Inventories elevated relative to sales — potential buildup/late-cycle signal"
        elif val > 1.35:
            isratio_summary["interpretation"] = "Inventory/sales ratio in normal range"
        else:
            isratio_summary["interpretation"] = "Lean inventories relative to sales — potential restocking ahead"
    result["inventories"] = isratio_summary

    # ── Decomposition signals ──
    decomposition: dict = {}
    signals: list[str] = []

    # New orders trend (3-month from durable goods)
    if dg_obs and len(dg_obs) >= 3:
        vals_3m = [dg_obs[i]["value"] for i in range(3)]
        # newest-first, so declining = vals_3m[0] < vals_3m[1] < vals_3m[2]
        declining = vals_3m[0] < vals_3m[1] < vals_3m[2]
        decomposition["new_orders_3m_trend"] = "declining" if declining else "not_declining"
    else:
        decomposition["new_orders_3m_trend"] = "insufficient_data"

    # Pull-forward detection (big jump after prior decline)
    if dg_obs and len(dg_obs) >= 3:
        latest_v = dg_obs[0]["value"]
        prior_v = dg_obs[1]["value"]
        two_ago_v = dg_obs[2]["value"]
        if prior_v > 0:
            jump_pct = (latest_v - prior_v) / prior_v * 100
            prior_declining = prior_v < two_ago_v
            pull_forward = jump_pct > 5 and prior_declining
            decomposition["pull_forward_detected"] = pull_forward
            if pull_forward:
                decomposition["pull_forward_detail"] = (
                    f"Durable goods orders surged {round(jump_pct, 1)}% after prior decline — possible pull-forward"
                )
        else:
            decomposition["pull_forward_detected"] = False
    else:
        decomposition["pull_forward_detected"] = False

    # Employment breadth (based on MoM change)
    if manemp_obs and len(manemp_obs) >= 2:
        emp_chg = manemp_obs[0]["value"] - manemp_obs[1]["value"]
        if emp_chg < -10:
            decomposition["employment_breadth"] = "contracting"
        elif abs(emp_chg) <= 10:
            decomposition["employment_breadth"] = "barely_expansionary"
        else:
            decomposition["employment_breadth"] = "expanding"
    else:
        decomposition["employment_breadth"] = "insufficient_data"

    # Inventory buildup detection (rising I/S ratio)
    inv_buildup = False
    if isratio_obs and len(isratio_obs) >= 4:
        latest_ratio = isratio_obs[0]["value"]
        old_ratio = isratio_obs[3]["value"]
        if latest_ratio > old_ratio and latest_ratio > 1.40:
            inv_buildup = True
    decomposition["inventory_buildup"] = inv_buildup
    if inv_buildup:
        decomposition["inventory_buildup_detail"] = "Inventory/sales ratio rising above 1.40 — potential late-cycle buildup"

    # Inventory too high
    inv_too_high = False
    if isratio_obs and len(isratio_obs) >= 1:
        if isratio_obs[0]["value"] > 1.45:
            inv_too_high = True
    decomposition["inventories_too_high"] = inv_too_high

    result["decomposition"] = decomposition

    # ── Build signals list ──
    if dg_summary.get("trend") == "falling" or decomposition.get("new_orders_3m_trend") == "declining":
        signals.append("ISM_NEW_ORDERS_DECLINING")
    if decomposition.get("inventory_buildup"):
        signals.append("ISM_INVENTORY_FLIP")
    if decomposition.get("inventories_too_high"):
        signals.append("ISM_INVENTORY_TOO_HIGH")
    if decomposition.get("employment_breadth") == "barely_expansionary":
        signals.append("ISM_EMPLOYMENT_BARELY_EXPANSIONARY")
    if decomposition.get("pull_forward_detected"):
        signals.append("ISM_NEW_ORDERS_PULLFORWARD")

    # PMI headline signals
    if headline_pmi is not None:
        if headline_pmi < 50:
            signals.append("ISM_CONTRACTION")

    result["signals"] = signals

    return json.dumps(result, indent=2)


# ═════════════════════════════════════════════════════════════════════════
# LABOR BREADTH DATA
# ═════════════════════════════════════════════════════════════════════════


def get_labor_breadth_data() -> str:
    """Fetch enhanced labor market breadth data from FRED.

    Returns JOLTS job openings (JTSJOL), quits rate (JTSQUR),
    hires level (JTSHIL), layoffs/discharges level (JTSLDL),
    continuing claims momentum, NFP trend analysis.

    Returns:
        JSON string with job_openings, quits_rate, continuing_claims,
        nfp_trend, and signals sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Job Openings (JOLTS, monthly, thousands) ──
    jolts_obs = _fetch_series_raw("JTSJOL", limit=24, sort_order="desc")
    jolts_summary = _series_summary(jolts_obs, "JTSJOL", unit="thousands", trend_n=3)

    if "latest_value" in jolts_summary:
        if jolts_summary.get("trend") == "falling":
            jolts_summary["interpretation"] = "Labor demand weakening — fewer openings"
            signals.append("JOLTS_OPENINGS_DECLINING")
        else:
            jolts_summary["interpretation"] = "Labor demand stable or improving"
        # Year-over-year comparison
        if jolts_obs and len(jolts_obs) >= 13:
            year_ago = jolts_obs[12]["value"]
            if jolts_obs[0]["value"] < year_ago:
                jolts_summary["yoy_note"] = "Job openings below year-ago levels"

    result["job_openings"] = jolts_summary

    # ── Quits Rate (monthly, percent) ──
    quits_obs = _fetch_series_raw("JTSQUR", limit=24, sort_order="desc")
    quits_summary = _series_summary(quits_obs, "JTSQUR", unit="percent", trend_n=3)

    if "latest_value" in quits_summary:
        val = quits_summary["latest_value"]
        if quits_summary.get("trend") == "falling":
            quits_summary["interpretation"] = "Workers losing bargaining power — fewer voluntary quits"
            signals.append("QUITS_RATE_DECLINING")
        elif val < 2.0:
            quits_summary["interpretation"] = "Quits rate below pre-pandemic norm — worker confidence low"
        elif val > 2.5:
            quits_summary["interpretation"] = "Elevated quits — workers confident in finding better jobs"
        else:
            quits_summary["interpretation"] = "Quits rate in normal range"

    result["quits_rate"] = quits_summary

    # ── Hires Level (JOLTS, monthly, thousands) ──
    hires_obs = _fetch_series_raw("JTSHIL", limit=24, sort_order="desc")
    hires_summary = _series_summary(hires_obs, "JTSHIL", unit="thousands", trend_n=3)

    if "latest_value" in hires_summary:
        if hires_summary.get("trend") == "falling":
            hires_summary["interpretation"] = "Hiring pace declining — employers pulling back"
            signals.append("HIRING_DECLINING")
        else:
            hires_summary["interpretation"] = "Hiring pace stable or improving"
        if hires_obs and len(hires_obs) >= 13:
            year_ago = hires_obs[12]["value"]
            current = hires_obs[0]["value"]
            if year_ago and year_ago > 0:
                yoy_change = round((current - year_ago) / year_ago * 100, 1)
                hires_summary["yoy_change_pct"] = yoy_change
                if yoy_change < -10:
                    hires_summary["yoy_note"] = (
                        f"Hires down {abs(yoy_change):.1f}% YoY — significant weakness"
                    )

    result["hires_level"] = hires_summary

    # ── Layoffs/Discharges Level (JOLTS, monthly, thousands) ──
    layoffs_obs = _fetch_series_raw("JTSLDL", limit=24, sort_order="desc")
    layoffs_summary = _series_summary(layoffs_obs, "JTSLDL", unit="thousands", trend_n=3)

    if "latest_value" in layoffs_summary:
        if layoffs_summary.get("trend") == "rising":
            layoffs_summary["interpretation"] = "Layoffs increasing — labor market deteriorating"
            signals.append("LAYOFFS_RISING")
        else:
            layoffs_summary["interpretation"] = "Layoffs stable or declining"

    result["layoffs_level"] = layoffs_summary

    # ── Hires-to-Layoffs Ratio ──
    if ("latest_value" in hires_summary and "latest_value" in layoffs_summary
            and layoffs_summary["latest_value"] > 0):
        h_val = hires_summary["latest_value"]
        l_val = layoffs_summary["latest_value"]
        ratio = round(h_val / l_val, 2)
        result["hires_to_layoffs_ratio"] = {
            "value": ratio,
            "interpretation": (
                "Labor market healthy — hiring well exceeds layoffs" if ratio > 1.5
                else "Balanced hiring-layoff dynamic" if ratio > 1.0
                else "WARNING: Layoffs exceeding hires — net job destruction"
            ),
        }
        if ratio < 1.0:
            signals.append("NET_JOB_DESTRUCTION")

    # ── Continuing Claims momentum (weekly, thousands) ──
    ccsa_obs = _fetch_series_raw("CCSA", limit=52, sort_order="desc")
    ccsa_summary = _series_summary(ccsa_obs, "CCSA", unit="thousands", trend_n=4)

    if ccsa_obs and len(ccsa_obs) >= 12:
        four_week_avg = round(sum(o["value"] for o in ccsa_obs[:4]) / 4, 1)
        twelve_week_avg = round(sum(o["value"] for o in ccsa_obs[:12]) / 12, 1)
        if twelve_week_avg != 0:
            momentum_pct = round((four_week_avg - twelve_week_avg) / twelve_week_avg * 100, 2)
        else:
            momentum_pct = 0.0

        ccsa_summary["four_week_avg"] = four_week_avg
        ccsa_summary["twelve_week_avg"] = twelve_week_avg
        ccsa_summary["momentum_pct"] = momentum_pct

        if momentum_pct > 0:
            ccsa_summary["interpretation"] = "Rising — re-employment becoming harder"
        else:
            ccsa_summary["interpretation"] = "Stable or improving — re-employment conditions steady"

        if momentum_pct > 3:
            signals.append("CONTINUING_CLAIMS_RISING")
    elif ccsa_obs and len(ccsa_obs) >= 4:
        four_week_avg = round(sum(o["value"] for o in ccsa_obs[:4]) / 4, 1)
        ccsa_summary["four_week_avg"] = four_week_avg

    result["continuing_claims"] = ccsa_summary

    # ── NFP Trend Analysis (monthly, thousands) ──
    payems_obs = _fetch_series_raw("PAYEMS", limit=24, sort_order="desc")
    nfp_summary = _series_summary(payems_obs, "PAYEMS", unit="thousands", trend_n=3)

    if payems_obs and len(payems_obs) >= 7:
        # 3 monthly changes: obs[0]-obs[1], obs[1]-obs[2], obs[2]-obs[3]
        recent_changes = [
            payems_obs[i]["value"] - payems_obs[i + 1]["value"] for i in range(3)
        ]
        three_month_avg = round(sum(recent_changes) / 3, 1)

        # Prior 3 monthly changes: obs[3]-obs[4], obs[4]-obs[5], obs[5]-obs[6]
        prior_changes = [
            payems_obs[i]["value"] - payems_obs[i + 1]["value"] for i in range(3, 6)
        ]
        prior_three_month_avg = round(sum(prior_changes) / 3, 1)

        decelerating = three_month_avg < prior_three_month_avg

        nfp_summary["three_month_avg_thousands"] = three_month_avg
        nfp_summary["prior_three_month_avg_thousands"] = prior_three_month_avg
        nfp_summary["decelerating"] = decelerating

        if decelerating:
            nfp_summary["interpretation"] = (
                f"NFP trend decelerating: {three_month_avg}K avg vs prior {prior_three_month_avg}K avg"
            )
            signals.append("NFP_TREND_DECELERATING")
        else:
            nfp_summary["interpretation"] = (
                f"NFP trend stable or accelerating: {three_month_avg}K avg vs prior {prior_three_month_avg}K avg"
            )

    result["nfp_trend"] = nfp_summary

    # ── Signals ──
    result["signals"] = signals

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Productivity & Unit Labor Costs (v1.7)
# ---------------------------------------------------------------------------

def get_productivity_data() -> str:
    """Fetch nonfarm productivity and unit labor cost data from FRED.

    Returns OPHNFB (output per hour, quarterly index) and ULCNFB
    (unit labor costs, quarterly index).  Computes the productivity-ULC
    gap: positive = margin expansion, negative = labor cost pressure.
    Note: a negative gap alone does NOT indicate stagflation — that
    conclusion requires cross-referencing with inflation AND growth data.

    Key FRED series:
        - OPHNFB: Nonfarm Business Sector: Output Per Hour of All Persons
        - ULCNFB: Nonfarm Business Sector: Unit Labor Cost

    Returns:
        JSON string with productivity, unit_labor_costs,
        productivity_ulc_gap, and signals sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Productivity (quarterly index) ──
    prod_obs = _fetch_series_raw("OPHNFB", limit=20, sort_order="desc")
    prod_summary = _series_summary(prod_obs, "OPHNFB", unit="index", trend_n=3)

    prod_yoy = None
    if prod_obs and len(prod_obs) >= 5:
        current = prod_obs[0]["value"]
        year_ago = prod_obs[4]["value"]  # 4 quarters back
        if year_ago and year_ago > 0:
            prod_yoy = round((current - year_ago) / year_ago * 100, 2)
            prod_summary["yoy_change_pct"] = prod_yoy
            if prod_summary.get("trend") == "falling":
                signals.append("PRODUCTIVITY_DECELERATING")

    result["productivity"] = prod_summary

    # ── Unit Labor Costs (quarterly index) ──
    ulc_obs = _fetch_series_raw("ULCNFB", limit=20, sort_order="desc")
    ulc_summary = _series_summary(ulc_obs, "ULCNFB", unit="index", trend_n=3)

    ulc_yoy = None
    if ulc_obs and len(ulc_obs) >= 5:
        current = ulc_obs[0]["value"]
        year_ago = ulc_obs[4]["value"]
        if year_ago and year_ago > 0:
            ulc_yoy = round((current - year_ago) / year_ago * 100, 2)
            ulc_summary["yoy_change_pct"] = ulc_yoy
            if ulc_summary.get("trend") == "rising":
                signals.append("ULC_ACCELERATING")

    result["unit_labor_costs"] = ulc_summary

    # ── Productivity-ULC Gap ──
    gap_section: dict = {}
    if prod_yoy is not None and ulc_yoy is not None:
        gap = round(prod_yoy - ulc_yoy, 2)
        if gap > 1.0:
            classification = "margin_expansion"
            interp = "Productivity growing faster than costs — disinflationary, margin-friendly"
        elif gap > 0:
            classification = "balanced"
            interp = "Productivity roughly keeping pace with costs — neutral"
        elif gap > -1.0:
            classification = "cost_pressure"
            interp = "Unit labor costs mildly outpacing productivity — watch for margin erosion"
        else:
            classification = "elevated_labor_cost_pressure"
            interp = (
                "ULC significantly outpacing productivity — elevated labor cost pressure. "
                "Cross-reference with inflation (core PCE/CPI) and growth (ISM/GDP) data "
                "before assessing stagflation risk."
            )
            signals.append("ELEVATED_LABOR_COST_PRESSURE")

        if gap > 0:
            signals.append("PRODUCTIVITY_GAP_POSITIVE")
        elif gap < 0:
            signals.append("PRODUCTIVITY_GAP_NEGATIVE")

        gap_section = {
            "productivity_yoy_pct": prod_yoy,
            "ulc_yoy_pct": ulc_yoy,
            "gap": gap,
            "classification": classification,
            "interpretation": interp,
        }
    else:
        gap_section = {"error": "Insufficient data for gap computation"}

    result["productivity_ulc_gap"] = gap_section
    result["signals"] = signals

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Consumer Financial Health (v1.7)
# ---------------------------------------------------------------------------

def get_consumer_health_data() -> str:
    """Fetch consumer financial health indicators from FRED.

    Returns personal saving rate (PSAVERT), revolving credit
    outstanding (REVOLSL), delinquency rate on all loans (DRALACBS),
    and bank lending standards (DRTSCILM).

    Key FRED series:
        - PSAVERT:  Personal Saving Rate (monthly, percent)
        - REVOLSL:  Total Revolving Credit Outstanding (monthly, billions $)
        - DRALACBS: Delinquency Rate on All Loans (quarterly, percent)
        - DRTSCILM: Net % of Domestic Banks Tightening Standards for C&I Loans
                    (quarterly, percent; positive = tightening)

    Returns:
        JSON string with savings_rate, revolving_credit,
        delinquency_rate, bank_lending_standards, and signals sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Personal Saving Rate (monthly, percent) ──
    sav_obs = _fetch_series_raw("PSAVERT", limit=24, sort_order="desc")
    sav_summary = _series_summary(sav_obs, "PSAVERT", unit="percent", trend_n=3)

    if "latest_value" in sav_summary:
        val = sav_summary["latest_value"]
        if val > 8.0:
            sav_summary["classification"] = "healthy"
            sav_summary["interpretation"] = "Strong savings buffer — consumer resilient"
        elif val > 5.0:
            sav_summary["classification"] = "adequate"
            sav_summary["interpretation"] = "Reasonable savings rate"
        elif val > 3.0:
            sav_summary["classification"] = "low"
            sav_summary["interpretation"] = "Savings being drawn down — limited buffer"
            signals.append("SAVINGS_RATE_LOW")
        else:
            sav_summary["classification"] = "critically_low"
            sav_summary["interpretation"] = "Critically low savings — consumer under acute pressure"
            signals.append("SAVINGS_RATE_LOW")

    result["savings_rate"] = sav_summary

    # ── Revolving Credit Outstanding (monthly, billions $) ──
    rev_obs = _fetch_series_raw("REVOLSL", limit=24, sort_order="desc")
    rev_summary = _series_summary(rev_obs, "REVOLSL", unit="billions_usd", trend_n=3)

    if rev_obs and len(rev_obs) >= 13:
        current = rev_obs[0]["value"]
        year_ago = rev_obs[12]["value"]
        if year_ago and year_ago > 0:
            yoy_pct = round((current - year_ago) / year_ago * 100, 2)
            rev_summary["yoy_change_pct"] = yoy_pct
            if yoy_pct > 10:
                rev_summary["velocity"] = "rapid_expansion"
                rev_summary["interpretation"] = (
                    f"Credit card debt growing {yoy_pct:.1f}% YoY — consumers leveraging up fast"
                )
                signals.append("CREDIT_GROWTH_RAPID")
            elif yoy_pct > 5:
                rev_summary["velocity"] = "moderate_growth"
                rev_summary["interpretation"] = f"Credit growing {yoy_pct:.1f}% YoY — moderate pace"
            elif yoy_pct > 0:
                rev_summary["velocity"] = "stable"
                rev_summary["interpretation"] = f"Credit growing {yoy_pct:.1f}% YoY — stable"
            else:
                rev_summary["velocity"] = "deleveraging"
                rev_summary["interpretation"] = f"Revolving credit declining {yoy_pct:.1f}% YoY — deleveraging"

    result["revolving_credit"] = rev_summary

    # ── Delinquency Rate on All Loans (quarterly, percent) ──
    delinq_obs = _fetch_series_raw("DRALACBS", limit=12, sort_order="desc")
    delinq_summary = _series_summary(delinq_obs, "DRALACBS", unit="percent", trend_n=3)

    if "latest_value" in delinq_summary:
        val = delinq_summary["latest_value"]
        if val > 3.5:
            delinq_summary["classification"] = "elevated"
            delinq_summary["interpretation"] = "Credit quality deteriorating — elevated delinquencies"
        elif val > 2.5:
            delinq_summary["classification"] = "rising"
            delinq_summary["interpretation"] = "Delinquencies rising — watch for further deterioration"
        elif val > 1.5:
            delinq_summary["classification"] = "normal"
            delinq_summary["interpretation"] = "Delinquency rate in normal range"
        else:
            delinq_summary["classification"] = "low"
            delinq_summary["interpretation"] = "Delinquency rate low — healthy credit quality"

        if delinq_summary.get("trend") == "rising" and val > 2.5:
            signals.append("DELINQUENCIES_RISING")

    result["delinquency_rate"] = delinq_summary

    # ── Bank Lending Standards (quarterly, net % tightening) ──
    bank_obs = _fetch_series_raw("DRTSCILM", limit=12, sort_order="desc")
    bank_summary = _series_summary(bank_obs, "DRTSCILM", unit="net_pct", trend_n=3)

    if "latest_value" in bank_summary:
        val = bank_summary["latest_value"]
        if val > 30:
            bank_summary["classification"] = "aggressive_tightening"
            bank_summary["interpretation"] = (
                f"Net {val:.1f}% of banks tightening — aggressive credit restriction"
            )
            signals.append("BANK_LENDING_TIGHTENING")
        elif val > 10:
            bank_summary["classification"] = "moderate_tightening"
            bank_summary["interpretation"] = (
                f"Net {val:.1f}% of banks tightening — credit becoming less available"
            )
            signals.append("BANK_LENDING_TIGHTENING")
        elif val > -10:
            bank_summary["classification"] = "neutral"
            bank_summary["interpretation"] = f"Bank lending standards roughly neutral ({val:.1f}%)"
        else:
            bank_summary["classification"] = "easing"
            bank_summary["interpretation"] = (
                f"Net {abs(val):.1f}% of banks easing — credit expanding"
            )

    result["bank_lending_standards"] = bank_summary

    # ── Composite consumer stress flag ──
    stress_count = sum(1 for s in signals if s in (
        "SAVINGS_RATE_LOW", "CREDIT_GROWTH_RAPID",
        "DELINQUENCIES_RISING", "BANK_LENDING_TIGHTENING",
    ))
    if stress_count >= 2:
        signals.append("CONSUMER_STRESS")

    result["signals"] = signals

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Housing Market Data (v1.7)
# ---------------------------------------------------------------------------

def get_housing_data() -> str:
    """Fetch housing market indicators from FRED.

    Returns housing starts (HOUST), building permits (PERMIT),
    existing home sales (EXHOSLUSM495S), 30Y mortgage rate
    (MORTGAGE30US), median sales price (MSPUS), and Case-Shiller
    home price index (CSUSHPISA).

    Housing leads GDP by 4-6 quarters. Permits declining 3+ months
    is a confirmed leading recession indicator.

    Key FRED series:
        - HOUST:          Housing Starts (monthly, thousands, SAAR)
        - PERMIT:         Building Permits (monthly, thousands, SAAR)
        - EXHOSLUSM495S:  Existing Home Sales (monthly, millions, SAAR)
        - MORTGAGE30US:   30-Year Fixed Rate Mortgage Average (weekly, %)
        - MSPUS:          Median Sales Price of Houses Sold (quarterly, $)
        - CSUSHPISA:      S&P/Case-Shiller National Home Price Index (monthly)

    Returns:
        JSON string with starts, permits, existing_sales, mortgage_rate,
        median_price, case_shiller, housing_cycle, and signals sections.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Housing Starts (monthly, thousands SAAR) ──
    starts_obs = _fetch_series_raw("HOUST", limit=24, sort_order="desc")
    starts_summary = _series_summary(starts_obs, "HOUST", unit="thousands_saar", trend_n=3)

    starts_val = None
    if "latest_value" in starts_summary:
        starts_val = starts_summary["latest_value"]
        if starts_val > 1500:
            starts_summary["level"] = "strong"
            starts_summary["interpretation"] = "Housing starts robust — construction activity healthy"
        elif starts_val > 1200:
            starts_summary["level"] = "moderate"
            starts_summary["interpretation"] = "Housing starts moderate — baseline activity"
        elif starts_val > 1000:
            starts_summary["level"] = "weak"
            starts_summary["interpretation"] = "Housing starts weak — construction slowing"
            signals.append("HOUSING_STARTS_WEAK")
        else:
            starts_summary["level"] = "recessionary"
            starts_summary["interpretation"] = "Sub-1M starts — historically signals housing bust"
            signals.append("HOUSING_STARTS_WEAK")

    result["starts"] = starts_summary

    # ── Building Permits (monthly, thousands SAAR) ──
    permits_obs = _fetch_series_raw("PERMIT", limit=24, sort_order="desc")
    permits_summary = _series_summary(permits_obs, "PERMIT", unit="thousands_saar", trend_n=3)

    permits_val = None
    if "latest_value" in permits_summary:
        permits_val = permits_summary["latest_value"]
        if permits_summary.get("trend") == "falling":
            permits_summary["interpretation"] = "Permits declining — future construction will slow"
            signals.append("PERMITS_DECLINING")
        elif permits_summary.get("trend") == "rising":
            permits_summary["interpretation"] = "Permits rising — construction pipeline expanding"
        else:
            permits_summary["interpretation"] = "Permits flat — stable construction outlook"

    # Permits-to-starts ratio (leading indicator)
    if starts_val and permits_val and starts_val > 0:
        ratio = round(permits_val / starts_val, 2)
        permits_summary["permits_to_starts_ratio"] = ratio
        if ratio > 1.0:
            permits_summary["pipeline"] = "expansion"
        elif ratio < 0.9:
            permits_summary["pipeline"] = "contraction"
        else:
            permits_summary["pipeline"] = "neutral"

    result["permits"] = permits_summary

    # ── Existing Home Sales (monthly, millions SAAR) ──
    sales_obs = _fetch_series_raw("EXHOSLUSM495S", limit=24, sort_order="desc")
    sales_summary = _series_summary(sales_obs, "EXHOSLUSM495S", unit="millions_saar", trend_n=3)

    if sales_obs and len(sales_obs) >= 2:
        current = sales_obs[0]["value"]
        prior = sales_obs[1]["value"]
        if prior and prior > 0:
            mom_pct = round((current - prior) / prior * 100, 2)
            sales_summary["mom_change_pct"] = mom_pct
            if mom_pct < -5:
                sales_summary["interpretation"] = (
                    f"Existing sales plunging {mom_pct:.1f}% MoM — demand collapsing"
                )
                signals.append("EXISTING_SALES_PLUNGING")
            elif mom_pct < -2:
                sales_summary["interpretation"] = f"Sales declining {mom_pct:.1f}% MoM — demand softening"
            elif mom_pct > 2:
                sales_summary["interpretation"] = f"Sales rising {mom_pct:.1f}% MoM — demand improving"
            else:
                sales_summary["interpretation"] = f"Sales roughly flat ({mom_pct:+.1f}% MoM)"

    result["existing_sales"] = sales_summary

    # ── 30-Year Mortgage Rate (weekly, percent) ──
    mort_obs = _fetch_series_raw("MORTGAGE30US", limit=52, sort_order="desc")
    mort_summary = _series_summary(mort_obs, "MORTGAGE30US", unit="percent", trend_n=4)

    if "latest_value" in mort_summary:
        rate = mort_summary["latest_value"]
        if rate > 7.5:
            mort_summary["interpretation"] = "Mortgage rate very elevated — severe affordability drag"
            signals.append("MORTGAGE_RATE_ELEVATED")
        elif rate > 7.0:
            mort_summary["interpretation"] = "Mortgage rate elevated — significant affordability pressure"
            signals.append("MORTGAGE_RATE_ELEVATED")
        elif rate > 6.0:
            mort_summary["interpretation"] = "Mortgage rate moderately high — some affordability impact"
        elif rate > 5.0:
            mort_summary["interpretation"] = "Mortgage rate moderate — manageable affordability"
        else:
            mort_summary["interpretation"] = "Mortgage rate low — supportive of housing demand"

    result["mortgage_rate"] = mort_summary

    # ── Median Sales Price (quarterly, dollars) ──
    price_obs = _fetch_series_raw("MSPUS", limit=12, sort_order="desc")
    price_summary = _series_summary(price_obs, "MSPUS", unit="usd", trend_n=3)

    if price_obs and len(price_obs) >= 5:
        current = price_obs[0]["value"]
        year_ago = price_obs[4]["value"]  # 4 quarters back
        if year_ago and year_ago > 0:
            yoy_pct = round((current - year_ago) / year_ago * 100, 2)
            price_summary["yoy_change_pct"] = yoy_pct

    result["median_price"] = price_summary

    # ── Case-Shiller National Home Price Index (monthly, SA) ──
    cs_obs = _fetch_series_raw("CSUSHPISA", limit=24, sort_order="desc")
    cs_summary = _series_summary(cs_obs, "CSUSHPISA", unit="index", trend_n=3)

    if cs_obs and len(cs_obs) >= 13:
        current = cs_obs[0]["value"]
        year_ago = cs_obs[12]["value"]
        if year_ago and year_ago > 0:
            yoy_pct = round((current - year_ago) / year_ago * 100, 2)
            cs_summary["yoy_change_pct"] = yoy_pct
            if yoy_pct < 0:
                cs_summary["interpretation"] = f"Home prices declining {yoy_pct:.1f}% YoY"
                signals.append("HOME_PRICES_DECLINING")
            elif yoy_pct < 3:
                cs_summary["interpretation"] = f"Home price appreciation slowing to {yoy_pct:.1f}% YoY"
            else:
                cs_summary["interpretation"] = f"Home prices rising {yoy_pct:.1f}% YoY"

    result["case_shiller"] = cs_summary

    # ── Housing Cycle Classification ──
    starts_trend = starts_summary.get("trend")
    permits_trend = permits_summary.get("trend")
    sales_trend = sales_summary.get("trend")

    declining_count = sum(1 for t in (starts_trend, permits_trend, sales_trend) if t == "falling")
    rising_count = sum(1 for t in (starts_trend, permits_trend, sales_trend) if t == "rising")

    if starts_val and starts_val > 1500 and rising_count >= 2:
        cycle = "boom"
        cycle_interp = "Housing market booming — strong activity across starts, permits, sales"
    elif starts_val and starts_val < 1200 and declining_count >= 2:
        cycle = "contraction"
        cycle_interp = "Housing in contraction — weak starts, declining permits/sales"
        signals.append("HOUSING_LEADING_RECESSION")
    elif rising_count >= 2 and starts_val and starts_val < 1300:
        cycle = "recovery"
        cycle_interp = "Housing recovering from low base — rising activity"
    elif declining_count >= 2:
        cycle = "cooling"
        cycle_interp = "Housing cooling — multiple activity metrics declining"
    else:
        # Check if distress signals are present — "mixed" with distress → "cooling"
        distress_signals = {"EXISTING_SALES_PLUNGING", "HOME_PRICES_DECLINING", "HOUSING_LEADING_RECESSION"}
        if declining_count >= 1 and any(s in signals for s in distress_signals):
            cycle = "cooling"
            cycle_interp = "Housing cooling — declining activity with demand-side distress signals"
        else:
            cycle = "mixed"
            cycle_interp = "Housing signals mixed — no clear directional trend"

    result["housing_cycle"] = {"phase": cycle, "interpretation": cycle_interp}

    # ── Affordability proxy ──
    mort_rate = mort_summary.get("latest_value")
    med_price = price_summary.get("latest_value")
    if mort_rate and med_price and mort_rate > 0:
        # Rough monthly payment proxy (interest-only approximation)
        monthly_payment = round(mort_rate / 100 / 12 * med_price, 0)
        result["affordability_proxy"] = {
            "monthly_interest_payment_usd": monthly_payment,
            "mortgage_rate_pct": mort_rate,
            "median_price_usd": med_price,
            "interpretation": (
                "Severely unaffordable" if monthly_payment > 2500
                else "Stretched affordability" if monthly_payment > 2000
                else "Moderate affordability" if monthly_payment > 1500
                else "Affordable"
            ),
        }

    result["signals"] = signals

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# LABOR SHARE & MANUFACTURING HOURS (v2.0 — Twitter-derived frameworks)
# ═══════════════════════════════════════════════════════════════════════════

def get_labor_share_data() -> str:
    """Get nonfarm business labor share of output from FRED (W270RE1A156NBEA).

    Labor share at historical lows is a late-cycle tell: profit margins
    have peaked and wage pressure is building.  The series is quarterly.

    Returns:
        JSON string with latest_value, yoy_change_pp, historical_context,
        percentile_rank, trend, and signals.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    # Fetch ~10 years of quarterly data for percentile context
    obs = _fetch_series_raw(
        "W270RE1A156NBEA", limit=80, sort_order="desc",
        observation_start=(datetime.utcnow() - timedelta(days=365 * 10)).strftime("%Y-%m-%d"),
    )
    if not obs or len(obs) < 2:
        return json.dumps({"error": "Labor share data unavailable from FRED"})

    result: dict = {"series": "W270RE1A156NBEA", "unit": "percent"}
    signals: list[str] = []

    latest = obs[0]["value"]
    result["latest_value"] = round(latest, 2)
    result["latest_date"] = obs[0]["date"]

    # YoY change (quarterly data, ~4 obs per year)
    if len(obs) >= 5:
        year_ago = obs[4]["value"]
        if year_ago and year_ago > 0:
            yoy = round(latest - year_ago, 2)
            result["yoy_change_pp"] = yoy
            if yoy < -1.0:
                signals.append("LABOR_SHARE_DECLINING_FAST")
            elif yoy < 0:
                signals.append("LABOR_SHARE_DECLINING")

    # Historical context — percentile rank
    all_values = [o["value"] for o in obs if o.get("value") is not None]
    if all_values:
        count_below = sum(1 for v in all_values if v < latest)
        pctile = round(count_below / len(all_values) * 100, 1)
        result["percentile_rank"] = pctile
        if pctile < 10:
            signals.append("LABOR_SHARE_NEAR_RECORD_LOW")
            result["historical_context"] = (
                f"Labor share at {latest:.1f}% — {pctile:.0f}th percentile, "
                "near historical lows. Profit margins likely peaked; "
                "wage pressure building. Late-cycle tell."
            )
        elif pctile < 25:
            result["historical_context"] = (
                f"Labor share at {latest:.1f}% — below 25th percentile. "
                "Profits capturing outsized share of output."
            )
        elif pctile > 75:
            result["historical_context"] = (
                f"Labor share at {latest:.1f}% — above 75th percentile. "
                "Labor capturing larger share — margin pressure for corporates."
            )
        else:
            result["historical_context"] = (
                f"Labor share at {latest:.1f}% — {pctile:.0f}th percentile, "
                "within normal range."
            )

    # Trend (last 3 quarters)
    if len(obs) >= 3:
        recent = [obs[i]["value"] for i in range(3) if obs[i].get("value") is not None]
        if len(recent) == 3:
            if recent[0] < recent[1] < recent[2]:
                result["trend"] = "falling"
            elif recent[0] > recent[1] > recent[2]:
                result["trend"] = "rising"
            else:
                result["trend"] = "mixed"

    result["signals"] = signals
    return json.dumps(result, indent=2)


def get_manufacturing_hours_data() -> str:
    """Get average weekly hours in manufacturing from FRED (AWHMAN).

    Combined with durable goods (DGORDER), productivity (OPHNFB), and
    unit labor costs (ULCNFB), this enables a manufacturing recession
    decomposition: when hours are flat/rising but output is falling,
    it signals labor hoarding and margin compression.

    Returns:
        JSON string with latest_value, mom_change_hours, yoy_change_pct,
        trend, level_assessment, and signals.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    obs = _fetch_series_raw("AWHMAN", limit=24, sort_order="desc")
    if not obs or len(obs) < 2:
        return json.dumps({"error": "Manufacturing hours data unavailable from FRED"})

    result: dict = {"series": "AWHMAN", "unit": "hours_per_week"}
    signals: list[str] = []

    latest = obs[0]["value"]
    prior = obs[1]["value"]
    result["latest_value"] = round(latest, 1)
    result["latest_date"] = obs[0]["date"]

    # MoM change
    if prior and prior > 0:
        mom = round(latest - prior, 1)
        result["mom_change_hours"] = mom
        if mom < -0.3:
            signals.append("MFG_HOURS_DROPPING")

    # YoY change
    if len(obs) >= 13:
        year_ago = obs[12]["value"]
        if year_ago and year_ago > 0:
            yoy_pct = round((latest - year_ago) / year_ago * 100, 2)
            result["yoy_change_pct"] = yoy_pct
            if yoy_pct < -2:
                signals.append("MFG_HOURS_DOWN_YOY")

    # Trend (last 3 months)
    if len(obs) >= 3:
        recent = [obs[i]["value"] for i in range(3) if obs[i].get("value") is not None]
        if len(recent) == 3:
            if recent[0] < recent[1] < recent[2]:
                result["trend"] = "falling"
            elif recent[0] > recent[1] > recent[2]:
                result["trend"] = "rising"
            else:
                result["trend"] = "stable"

    # Threshold check — below 40 hours is recessionary territory historically
    if latest < 40.0:
        signals.append("MFG_HOURS_BELOW_40")
        result["level_assessment"] = "Below 40-hour threshold — recessionary territory"
    elif latest < 40.5:
        result["level_assessment"] = "Near 40-hour level — watch closely"
    else:
        result["level_assessment"] = "Above 40 hours — normal range"

    result["signals"] = signals
    return json.dumps(result, indent=2)


def _fetch_etf_prices(ticker: str, period: str = "3mo") -> dict | None:
    """Fetch ETF price data via yfinance, with in-memory TTL cache.

    Returns dict with latest_price, price_1w_ago, price_1m_ago,
    pct_change_1w, pct_change_1m, or None on failure.

    Results are cached for 30 minutes to avoid repeated yfinance calls
    within the same session.  Gracefully returns None if yfinance is
    unavailable or the fetch fails.
    """
    # Check in-memory cache first
    cache_key = f"{ticker}:{period}"
    now = time.time()
    if cache_key in _ETF_CACHE:
        cached_time, cached_result = _ETF_CACHE[cache_key]
        if now - cached_time < _ETF_CACHE_TTL:
            return cached_result

    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        data = yf.download(ticker, period=period, progress=False, timeout=10)
        if data is None or data.empty:
            return None

        closes = data["Close"].dropna()
        if len(closes) < 2:
            return None

        latest = float(closes.iloc[-1])
        result = {"ticker": ticker, "latest_price": round(latest, 2)}

        # 1-week ago (~5 trading days)
        if len(closes) >= 6:
            week_ago = float(closes.iloc[-6])
            result["price_1w_ago"] = round(week_ago, 2)
            if week_ago > 0:
                result["pct_change_1w"] = round((latest - week_ago) / week_ago * 100, 2)

        # 1-month ago (~22 trading days)
        if len(closes) >= 22:
            month_ago = float(closes.iloc[-22])
            result["price_1m_ago"] = round(month_ago, 2)
            if month_ago > 0:
                result["pct_change_1m"] = round((latest - month_ago) / month_ago * 100, 2)

        # Store in cache
        _ETF_CACHE[cache_key] = (now, result)
        return result

    except Exception:
        return None
