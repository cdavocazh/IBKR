"""Macro-to-market analysis tools.

Connects macroeconomic signals (inflation, employment, yields, credit spreads)
to equity index movements and bond market dynamics. Combines local macro CSV
data with FRED API data to produce regime classification, equity driver analysis,
bond market analysis, and cross-asset correlations.

Data sources:
- /macro_2/historical_data/*.csv  — price/yield/index history
- tools.fred_data                 — inflation, employment, yield curve, credit spreads
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
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

INDEX_CONFIG = {
    "sp500": {
        "csv": "es_futures.csv",
        "price_col": "es_price",
        "valuation_csv": "sp500_fundamentals.csv",
        "pe_col": "sp500_pe",
    },
    "russell_2000": {
        "csv": "rty_futures.csv",
        "price_col": "rty_price",
    },
}

# Macro factors available from local CSVs for correlation computation
MACRO_FACTOR_CSV = {
    "dxy": {"csv": "dxy.csv", "col": "dxy"},
    "10y_yield": {"csv": "10y_treasury_yield.csv", "col": "10y_yield"},
    "2y_yield": {"csv": "us_2y_yield.csv", "col": "us_2y_yield"},
    "vix": {"csv": "vix_move.csv", "col": "vix"},
    "move": {"csv": "vix_move.csv", "col": "move"},
    "gold": {"csv": "gold.csv", "col": "gold_price"},
    "crude_oil": {"csv": "crude_oil.csv", "col": "crude_oil_price"},
    "copper": {"csv": "copper.csv", "col": "copper_price"},
}


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


def _compute_rolling_corr(
    df_a: pd.DataFrame,
    col_a: str,
    df_b: pd.DataFrame,
    col_b: str,
    window: int = 20,
) -> dict | None:
    """Compute rolling correlation between two series aligned by date.

    Returns dict with latest_20d, avg_60d, interpretation, or None if
    insufficient data.
    """
    a = df_a[["date", col_a]].copy().dropna(subset=[col_a])
    a["date"] = pd.to_datetime(a["date"], errors="coerce")
    a = a.dropna(subset=["date"])

    b = df_b[["date", col_b]].copy().dropna(subset=[col_b])
    b["date"] = pd.to_datetime(b["date"], errors="coerce")
    b = b.dropna(subset=["date"])

    merged = a.merge(b, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if len(merged) < window + 5:
        return None

    merged["ret_a"] = merged[col_a].pct_change()
    merged["ret_b"] = merged[col_b].pct_change()
    merged = merged.dropna(subset=["ret_a", "ret_b"])

    if len(merged) < window:
        return None

    rolling = merged["ret_a"].rolling(window).corr(merged["ret_b"])
    latest = float(rolling.iloc[-1]) if not pd.isna(rolling.iloc[-1]) else None
    if latest is None:
        return None

    avg_60d = None
    if len(merged) >= 60:
        last_60 = rolling.tail(60).dropna()
        avg_60d = round(float(last_60.mean()), 2) if len(last_60) > 0 else None

    return {
        "latest_20d": round(latest, 2),
        "avg_60d": avg_60d if avg_60d is not None else round(latest, 2),
        "interpretation": _interpret_correlation(latest),
    }


def _safe_fred_call(func, *args, **kwargs) -> dict | None:
    """Call a fred_data function and return parsed JSON, or None on failure."""
    try:
        from tools import fred_data
        raw = func(*args, **kwargs)
        if isinstance(raw, str):
            data = json.loads(raw)
            if "error" in data:
                return None
            return data
        return None
    except Exception:
        return None


def _classify_regime(label: str, value: float | None, thresholds: dict) -> dict:
    """Classify a macro regime based on thresholds.

    thresholds is a dict like:
      {"hot": (">", 3.0), "cooling": ("range", 2.0, 3.0), "stable": ("<", 2.0)}
    """
    if value is None:
        return {"classification": "unknown", "value": None, "evidence": "Data unavailable"}

    for cls_name, condition in thresholds.items():
        op = condition[0]
        if op == ">" and value > condition[1]:
            return {"classification": cls_name, "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}
        elif op == "<" and value < condition[1]:
            return {"classification": cls_name, "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}
        elif op == ">=" and value >= condition[1]:
            return {"classification": cls_name, "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}
        elif op == "<=" and value <= condition[1]:
            return {"classification": cls_name, "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}
        elif op == "range" and condition[1] <= value <= condition[2]:
            return {"classification": cls_name, "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}

    return {"classification": "unknown", "value": round(value, 2), "evidence": f"{label} = {value:.2f}"}


def _compute_energy_cpi_passthrough() -> dict | None:
    """Compute energy → CPI passthrough estimates.

    Uses gasoline retail price from FRED oil fundamentals and computes:
    - Direct CPI impact: gas price MoM change × 2.91% (CPI energy weight)
    - BofA model: $10/bbl WTI rise → +0.1% inflation, −0.1% GDP

    Returns dict with gasoline_price, mom_change_pct, cpi_impact_pct,
    wti_price, bofa_implied_inflation, bofa_implied_gdp, or None on failure.
    """
    from tools import fred_data
    oil_data = _safe_fred_call(fred_data.get_oil_fundamentals)
    if not oil_data:
        return None

    result: dict = {}

    # Gasoline retail price
    gas_section = oil_data.get("gasoline", {})
    gas_retail = gas_section.get("retail_price", {})
    gas_price = gas_retail.get("latest_value")
    if gas_price is not None:
        result["gasoline_price"] = round(gas_price, 3)
        # MoM change from trend data
        gas_trend = gas_retail.get("trend")
        gas_wow = gas_retail.get("wow_change_pct")
        if gas_wow is not None:
            # Approximate MoM from weekly change × 4
            mom_approx = round(gas_wow * 4, 2)
            result["gas_mom_change_pct_approx"] = mom_approx
            # Direct CPI impact: MoM change × energy weight (2.91%)
            cpi_impact = round(mom_approx * 0.0291, 4)
            result["direct_cpi_impact_pct"] = cpi_impact
            result["cpi_formula"] = "gas_mom_change × 2.91% (CPI energy weight)"

    # WTI crude
    wti_section = oil_data.get("wti", {})
    wti_price = wti_section.get("latest_value")
    if wti_price is not None:
        result["wti_price"] = round(wti_price, 2)
        # BofA model: $10 change → +0.1% inflation, −0.1% GDP
        wti_wow = wti_section.get("wow_change_pct")
        if wti_wow is not None:
            wti_dollar_change = round(wti_price * wti_wow / 100, 2)
            implied_inflation = round(wti_dollar_change / 10 * 0.1, 3)
            implied_gdp = round(wti_dollar_change / 10 * -0.1, 3)
            result["bofa_model"] = {
                "wti_weekly_change_usd": wti_dollar_change,
                "implied_inflation_impact_pct": implied_inflation,
                "implied_gdp_impact_pct": implied_gdp,
                "note": "BofA: $10/bbl oil rise → +0.1% inflation, −0.1% GDP",
            }

    return result if result else None


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def analyze_macro_regime() -> str:
    """Classify current macro regime across 6 dimensions.

    Dimensions: inflation, employment, growth, rate environment, credit conditions,
    and housing. Each dimension is classified into one of several states with
    supporting evidence.

    Returns:
        JSON string with regimes, composite_outlook, and signals.
    """
    from tools import fred_data

    result: dict = {"timestamp": datetime.now().strftime("%Y-%m-%d")}
    regimes: dict = {}
    signals: list[str] = []

    # ── 1. Inflation Regime ──────────────────────────────────────────
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    cpi_yoy = None
    core_pce_yoy = None
    if inflation_data:
        cpi_section = inflation_data.get("cpi", {})
        cpi_yoy = cpi_section.get("yoy_change_pct")
        core_pce_section = inflation_data.get("core_pce", {})
        core_pce_yoy = core_pce_section.get("yoy_change_pct")

    # Use core PCE as primary (Fed's preferred), CPI as fallback
    inflation_val = core_pce_yoy if core_pce_yoy is not None else cpi_yoy
    inflation_regime = _classify_regime(
        "Core PCE YoY" if core_pce_yoy is not None else "CPI YoY",
        inflation_val,
        {"hot": (">", 3.0), "elevated": ("range", 2.5, 3.0), "stable": ("range", 1.5, 2.5), "cooling": ("<", 1.5)},
    )

    # Add trend info and resolve classification-vs-trend contradictions
    inflation_trend = None
    if inflation_data:
        cpi_trend = inflation_data.get("cpi", {}).get("trend")
        pce_trend = inflation_data.get("core_pce", {}).get("trend")
        inflation_trend = pce_trend or cpi_trend
        inflation_regime["trend"] = inflation_trend
        if inflation_trend == "rising" and inflation_val is not None:
            # Prevent "cooling" + "rising" contradiction
            if inflation_val > 2.5:
                inflation_regime["classification"] = "hot"
            elif inflation_val > 1.5:
                inflation_regime["classification"] = "elevated"
            else:
                # Value is low but rising — not "cooling"
                inflation_regime["classification"] = "rising_from_low_base"
        elif inflation_trend == "falling" and inflation_val is not None:
            # Prevent "hot" + "falling" contradiction
            if inflation_val > 3.0:
                inflation_regime["classification"] = "elevated"  # high but declining

    regimes["inflation"] = inflation_regime
    cls = inflation_regime["classification"]
    if cls == "hot":
        signals.append("INFLATION_HOT")
    elif cls == "cooling":
        signals.append("INFLATION_COOLING")
    else:
        signals.append("INFLATION_STABLE")

    # Breakeven info
    if inflation_data and "breakevens" in inflation_data:
        be = inflation_data["breakevens"]
        t5yie = be.get("t5yie", {}).get("latest_value")
        if t5yie is not None:
            regimes["inflation"]["breakeven_5y"] = round(t5yie, 2)

    # ── 2. Employment Regime ─────────────────────────────────────────
    employment_data = _safe_fred_call(fred_data.get_employment_data)
    unemp_rate = None
    claims_trend = None
    if employment_data:
        unemp_rate = employment_data.get("unemployment_rate", {}).get("latest_value")
        claims_trend = employment_data.get("initial_claims", {}).get("trend")

    employment_regime = _classify_regime(
        "Unemployment Rate",
        unemp_rate,
        {"tight": ("<", 4.0), "moderate": ("range", 4.0, 5.0), "loosening": ("range", 5.0, 6.0), "weak": (">=", 6.0)},
    )
    if claims_trend:
        employment_regime["claims_trend"] = claims_trend
    if employment_data:
        nfp = employment_data.get("nonfarm_payrolls", {}).get("nfp_monthly_change_thousands")
        if nfp is not None:
            employment_regime["latest_nfp_thousands"] = nfp

    # Labor Breadth (JOLTS, Quits, Continuing Claims momentum, NFP trend)
    labor_breadth = _safe_fred_call(fred_data.get_labor_breadth_data)
    if labor_breadth:
        employment_regime["labor_breadth"] = {
            "job_openings_thousands": labor_breadth.get("job_openings", {}).get("latest_value"),
            "job_openings_interpretation": labor_breadth.get("job_openings", {}).get("interpretation"),
            "quits_rate_pct": labor_breadth.get("quits_rate", {}).get("latest_value"),
            "quits_rate_interpretation": labor_breadth.get("quits_rate", {}).get("interpretation"),
            "continuing_claims_momentum_pct": labor_breadth.get("continuing_claims", {}).get("momentum_pct"),
            "nfp_3m_avg_thousands": labor_breadth.get("nfp_trend", {}).get("three_month_avg_thousands"),
            "nfp_decelerating": labor_breadth.get("nfp_trend", {}).get("decelerating", False),
        }
        # Propagate labor breadth signals
        for sig in labor_breadth.get("signals", []):
            signals.append(sig)

    regimes["employment"] = employment_regime
    cls = employment_regime["classification"]
    if cls == "tight":
        signals.append("LABOR_TIGHT")
    elif cls in ("loosening", "weak"):
        signals.append("LABOR_LOOSENING")
    else:
        signals.append("LABOR_MODERATE")

    # ── 3. Growth Regime ─────────────────────────────────────────────
    pmi_val = None
    try:
        pmi_raw = macro_data.analyze_indicator_changes("ism_pmi")
        pmi_data = json.loads(pmi_raw)
        metrics = pmi_data.get("metrics", {})
        for col, m in metrics.items():
            pmi_val = m.get("latest_value")
            break
    except Exception:
        pass

    growth_regime = _classify_regime(
        "ISM Manufacturing PMI",
        pmi_val,
        {"expansion": (">", 52.0), "slowing": ("range", 50.0, 52.0), "contraction": ("<", 50.0)},
    )
    # ISM Decomposition (sub-component analysis)
    ism_decomp = _safe_fred_call(fred_data.get_ism_decomposition)
    if ism_decomp:
        growth_regime["ism_decomposition"] = {
            "new_orders": ism_decomp.get("new_orders", {}).get("latest_value"),
            "new_orders_interpretation": ism_decomp.get("new_orders", {}).get("interpretation"),
            "employment": ism_decomp.get("employment", {}).get("latest_value"),
            "employment_breadth": ism_decomp.get("decomposition", {}).get("employment_breadth"),
            "inventories": ism_decomp.get("inventories", {}).get("latest_value"),
            "inventory_flip": ism_decomp.get("decomposition", {}).get("inventory_flip", False),
            "inventories_too_high": ism_decomp.get("decomposition", {}).get("inventories_too_high", False),
            "pull_forward_detected": ism_decomp.get("decomposition", {}).get("pull_forward_detected", False),
        }
        # Propagate ISM sub-component signals
        for sig in ism_decomp.get("signals", []):
            signals.append(sig)

    regimes["growth"] = growth_regime
    cls = growth_regime["classification"]
    if cls == "expansion":
        signals.append("GROWTH_EXPANSION")
    elif cls == "slowing":
        signals.append("GROWTH_SLOWING")
    elif cls == "contraction":
        signals.append("GROWTH_CONTRACTION")

    # ── 4. Rate Environment ──────────────────────────────────────────
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)
    ff_rate = None
    ff_trend = None
    if yield_data:
        fp = yield_data.get("fed_policy", {})
        ff_rate = fp.get("effective_rate", {}).get("latest_value")
        ff_trend = fp.get("effective_rate", {}).get("trend")

    rate_regime: dict = {"value": ff_rate}
    if ff_trend == "rising":
        rate_regime["classification"] = "tightening"
        signals.append("FED_TIGHTENING")
    elif ff_trend == "falling":
        rate_regime["classification"] = "easing"
        signals.append("FED_EASING")
    else:
        rate_regime["classification"] = "neutral"
        signals.append("FED_NEUTRAL")
    rate_regime["evidence"] = f"Fed funds = {ff_rate}%, trend = {ff_trend}" if ff_rate else "Data unavailable"

    if yield_data:
        rate_regime["curve_shape"] = yield_data.get("curve_shape", "unknown")
        stance = yield_data.get("fed_policy", {}).get("stance")
        if stance:
            rate_regime["stance"] = stance

    regimes["rates"] = rate_regime

    # ── 5. Credit Conditions ─────────────────────────────────────────
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    hy_oas = None
    hy_stress = None
    if credit_data:
        hy_info = credit_data.get("high_yield_oas", {})
        hy_oas = hy_info.get("latest_value")
        hy_stress = hy_info.get("stress_level")

    # Use regime-aware stress_level from fred_data (percentile-based)
    stress_to_regime = {
        "crisis": "crisis", "severe_stress": "crisis",
        "stressed": "elevated", "elevated": "elevated",
        "normal": "neutral", "below_average": "neutral",
        "tight": "tight",
    }
    regime_cls = stress_to_regime.get(hy_stress, "neutral") if hy_stress else "data_unavailable"
    hy_bps = int(round(hy_oas * 100)) if hy_oas else None
    credit_regime = {
        "metric": "HY OAS",
        "value": hy_oas,
        "value_bps": hy_bps,
        "classification": regime_cls,
        "stress_level": hy_stress or "data_unavailable",
        "evidence": credit_data.get("high_yield_oas", {}).get("interpretation", "Data unavailable") if credit_data else "Data unavailable",
    }
    if credit_data:
        hy_direction = credit_data.get("high_yield_oas", {}).get("spread_direction")
        if hy_direction:
            credit_regime["spread_direction"] = hy_direction
        pctile = credit_data.get("high_yield_oas", {}).get("one_year_percentile")
        if pctile is not None:
            credit_regime["one_year_percentile"] = pctile
    regimes["credit"] = credit_regime

    if regime_cls == "tight":
        signals.append("CREDIT_LOOSE")
    elif regime_cls in ("elevated", "crisis"):
        signals.append("CREDIT_TIGHT")
    else:
        signals.append("CREDIT_NEUTRAL")

    # ── 6. Housing Regime ─────────────────────────────────────────────
    housing_data = _safe_fred_call(fred_data.get_housing_data)
    housing_regime: dict = {"classification": "data_unavailable", "evidence": "Housing data unavailable"}

    if housing_data:
        starts_val = housing_data.get("housing_starts", {}).get("latest_value")
        permits_trend = housing_data.get("permits", {}).get("trend")
        existing_sales_trend = housing_data.get("existing_home_sales", {}).get("trend")
        mortgage_rate = housing_data.get("mortgage_rate", {}).get("latest_value") if "mortgage_rate" in housing_data else None

        if starts_val is not None:
            if starts_val > 1500:
                housing_cls = "strong"
            elif starts_val >= 1200:
                housing_cls = "moderate"
            elif starts_val >= 1000:
                housing_cls = "weak"
            else:
                housing_cls = "recessionary"

            housing_regime = {
                "classification": housing_cls,
                "value": starts_val,
                "evidence": f"Housing starts at {starts_val:.0f}K SAAR — {housing_cls}",
            }
        else:
            housing_regime = {"classification": "data_unavailable", "evidence": "Housing starts data unavailable"}

        if permits_trend:
            housing_regime["permits_trend"] = permits_trend
        if existing_sales_trend:
            housing_regime["existing_sales_trend"] = existing_sales_trend
        if mortgage_rate is not None:
            housing_regime["mortgage_rate"] = mortgage_rate

        # Propagate housing signals
        for sig in housing_data.get("signals", []):
            signals.append(sig)

    regimes["housing"] = housing_regime
    housing_cls = housing_regime["classification"]
    if housing_cls in ("weak", "recessionary"):
        signals.append("HOUSING_WEAK")

    # ── Composite Outlook ────────────────────────────────────────────
    parts = []
    inf_cls = regimes.get("inflation", {}).get("classification", "unknown")
    emp_cls = regimes.get("employment", {}).get("classification", "unknown")
    grow_cls = regimes.get("growth", {}).get("classification", "unknown")
    rate_cls = regimes.get("rates", {}).get("classification", "unknown")
    cred_cls = regimes.get("credit", {}).get("classification", "unknown")
    hous_cls = regimes.get("housing", {}).get("classification", "unknown")

    if inf_cls in ("stable",) and grow_cls == "expansion" and cred_cls == "tight":
        parts.append("Goldilocks environment — moderate inflation with solid growth and loose credit")
    elif inf_cls == "hot" and rate_cls == "tightening":
        parts.append("Stagflation risk — hot inflation with tightening policy")
    elif grow_cls == "contraction" and cred_cls in ("elevated", "crisis"):
        parts.append("Recessionary — contracting growth with tight credit conditions")
    elif inf_cls == "cooling" and rate_cls == "easing":
        parts.append("Reflationary — falling inflation allowing policy easing")
    else:
        parts.append(f"Mixed — inflation {inf_cls}, growth {grow_cls}, credit {cred_cls}")

    if emp_cls == "tight":
        parts.append("Labor market remains tight")
    elif emp_cls in ("loosening", "weak"):
        parts.append("Labor market showing cracks")

    if hous_cls == "strong":
        parts.append("Housing sector strong — supportive of growth")
    elif hous_cls == "weak":
        parts.append("Housing sector weakening — potential drag on economy")
    elif hous_cls == "recessionary":
        parts.append("Housing in recessionary territory — significant headwind")

    result["regimes"] = regimes
    result["composite_outlook"] = ". ".join(parts) + "."
    result["signals"] = signals

    # Include raw data summaries for LLM context
    if inflation_data:
        result["inflation_detail"] = {
            k: {kk: vv for kk, vv in v.items() if kk in ("latest_value", "yoy_change_pct", "trend", "interpretation")}
            for k, v in inflation_data.items()
            if isinstance(v, dict) and "latest_value" in v
        }

    return json.dumps(result)


def analyze_equity_drivers(index: str = "both") -> str:
    """Analyze how macro factors are driving equity index movements.

    Computes equity risk premium, real yield impact, credit-equity correlation,
    DXY impact, inflation rotation signals, and VIX/MOVE regime.

    Args:
        index: 'sp500', 'russell_2000', or 'both'.

    Returns:
        JSON string with equity driver analysis and signals.
    """
    from tools import fred_data

    index = index.strip().lower()
    if index not in ("sp500", "russell_2000", "both"):
        index = "both"

    result: dict = {"timestamp": datetime.now().strftime("%Y-%m-%d"), "index": index}
    signals: list[str] = []

    indices_to_analyze = []
    if index in ("sp500", "both"):
        indices_to_analyze.append("sp500")
    if index in ("russell_2000", "both"):
        indices_to_analyze.append("russell_2000")

    # ── 1. Equity Risk Premium (S&P 500 only) ───────────────────────
    erp_result: dict = {}
    sp_pe_data = _load_csv("sp500_fundamentals.csv")
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)

    # CSV column may be "sp500_pe" or "pe_ratio_trailing" depending on data source
    pe_col = None
    if sp_pe_data is not None:
        for candidate in ("sp500_pe", "pe_ratio_trailing", "pe_ratio"):
            if candidate in sp_pe_data.columns:
                pe_col = candidate
                break
    if pe_col is not None:
        sp_pe_data = sp_pe_data.sort_values("date", ascending=True).dropna(subset=[pe_col])
        if len(sp_pe_data) > 0:
            latest_pe = float(sp_pe_data[pe_col].iloc[-1])
            earnings_yield = round(100.0 / latest_pe, 2) if latest_pe > 0 else None

            real_yield_10y = None
            if yield_data:
                real_yield_10y = yield_data.get("real_yields", {}).get("10y_real", {}).get("latest_value")

            if earnings_yield is not None and real_yield_10y is not None:
                erp = round(earnings_yield - real_yield_10y, 2)
                erp_result = {
                    "equity_risk_premium_pct": erp,
                    "sp500_pe": round(latest_pe, 1),
                    "earnings_yield_pct": earnings_yield,
                    "real_yield_10y_pct": round(real_yield_10y, 2),
                    "interpretation": (
                        f"ERP at {erp}% — equities expensive vs bonds"
                        if erp < 2 else
                        f"ERP at {erp}% — fair value"
                        if erp < 4 else
                        f"ERP at {erp}% — equities attractive vs bonds"
                    ),
                }
                if erp < 2:
                    signals.append("EQUITY_RISK_PREMIUM_LOW")
                elif erp > 5:
                    signals.append("EQUITY_RISK_PREMIUM_HIGH")

    result["equity_risk_premium"] = erp_result if erp_result else {"status": "data_unavailable"}
    # Flat top-level ERP value for programmatic access
    result["erp_pct"] = erp_result.get("equity_risk_premium_pct") if erp_result else None

    # ── 2. Real Yield Impact ─────────────────────────────────────────
    real_yield_impact: dict = {}
    if yield_data:
        ry = yield_data.get("real_yields", {})
        ry_10y = ry.get("10y_real", {})
        ry_val = ry_10y.get("latest_value")
        ry_trend = ry_10y.get("trend")
        ry_daily_bps = ry_10y.get("daily_change_bps")

        if ry_val is not None:
            real_yield_impact = {
                "real_yield_10y": round(ry_val, 2),
                "trend": ry_trend,
                "daily_change_bps": ry_daily_bps,
            }
            if ry_val > 2.0 and ry_trend == "rising":
                real_yield_impact["interpretation"] = "Rising real yields — headwind for growth/tech, tailwind for value"
                signals.append("REAL_YIELD_HEADWIND")
            elif ry_val < 1.0 or ry_trend == "falling":
                real_yield_impact["interpretation"] = "Low/falling real yields — supportive for growth/tech"
                signals.append("REAL_YIELD_TAILWIND")
            else:
                real_yield_impact["interpretation"] = f"Real yields at {ry_val}% — moderate level"

    result["real_yield_impact"] = real_yield_impact if real_yield_impact else {"status": "data_unavailable"}

    # ── 3. Credit-Equity Link ────────────────────────────────────────
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    credit_equity: dict = {}
    if credit_data:
        hy = credit_data.get("high_yield_oas", {})
        hy_val = hy.get("latest_value")
        hy_direction = hy.get("spread_direction")
        hy_wow = hy.get("wow_change_bps")

        if hy_val is not None:
            # FRED OAS is in pct points (3.08 = 308bps)
            hy_bps = int(round(hy_val * 100))
            credit_equity = {
                "hy_oas_pct": round(hy_val, 2),
                "hy_oas_bps": hy_bps,
                "spread_direction": hy_direction,
                "wow_change_bps": hy_wow,
            }
            # Use regime-aware classification from fred_data
            hy_stress = hy.get("stress_level", "normal")
            hy_interp = hy.get("interpretation", f"HY OAS at {hy_bps}bps")
            credit_equity["stress_level"] = hy_stress
            credit_equity["interpretation"] = hy_interp
            if hy_stress in ("crisis", "severe_stress", "stressed"):
                signals.append("CREDIT_STRESS")
            elif hy_stress in ("tight", "below_average"):
                signals.append("CREDIT_TAILWIND")

    result["credit_equity_link"] = credit_equity if credit_equity else {"status": "data_unavailable"}

    # ── 4. DXY Impact ────────────────────────────────────────────────
    dxy_impact: dict = {}
    dxy_df = _load_csv("dxy.csv")
    if dxy_df is not None and "dxy" in dxy_df.columns:
        dxy_df = dxy_df.sort_values("date", ascending=True).dropna(subset=["dxy"])
        if len(dxy_df) >= 6:
            latest_dxy = float(dxy_df["dxy"].iloc[-1])
            week_ago = float(dxy_df["dxy"].iloc[-6]) if len(dxy_df) >= 6 else None
            dxy_impact = {
                "latest_dxy": round(latest_dxy, 2),
            }
            if week_ago and week_ago != 0:
                wow_chg = round((latest_dxy - week_ago) / week_ago * 100, 2)
                dxy_impact["wow_change_pct"] = wow_chg

            wow_chg_val = dxy_impact.get("wow_change_pct", 0)
            if latest_dxy > 105:
                dxy_impact["interpretation"] = "Strong dollar — headwind for multinational earnings"
                if dxy_df["dxy"].iloc[-1] > dxy_df["dxy"].iloc[-6]:
                    signals.append("DOLLAR_HEADWIND")
            elif latest_dxy < 100:
                if wow_chg_val > 0.3:
                    dxy_impact["interpretation"] = (
                        f"DXY at {latest_dxy} (rising {wow_chg_val:+.2f}%) — "
                        "dollar strengthening from low base"
                    )
                elif wow_chg_val < -0.3:
                    dxy_impact["interpretation"] = "Weak dollar — tailwind for multinationals, EM"
                    signals.append("DOLLAR_TAILWIND")
                else:
                    dxy_impact["interpretation"] = f"DXY at {latest_dxy} — weak range, stable"
            else:
                dxy_impact["interpretation"] = f"DXY at {latest_dxy} — neutral range"

    result["dxy_impact"] = dxy_impact if dxy_impact else {"status": "data_unavailable"}

    # ── 5. Inflation-Rotation Signal ─────────────────────────────────
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    inflation_rotation: dict = {}
    if inflation_data:
        cpi_yoy = inflation_data.get("cpi", {}).get("yoy_change_pct")
        cpi_trend = inflation_data.get("cpi", {}).get("trend")
        if cpi_yoy is not None:
            inflation_rotation = {
                "cpi_yoy_pct": cpi_yoy,
                "cpi_trend": cpi_trend,
            }
            if cpi_yoy > 3.0 and cpi_trend == "rising":
                inflation_rotation["rotation_signal"] = "Favor value, energy, materials over growth/tech"
                signals.append("INFLATION_ROTATION_VALUE")
            elif cpi_yoy < 2.5 and cpi_trend == "falling":
                inflation_rotation["rotation_signal"] = "Favor growth/tech over value/cyclicals"
                signals.append("INFLATION_ROTATION_GROWTH")
            else:
                inflation_rotation["rotation_signal"] = "No strong rotation signal"

    result["inflation_rotation"] = inflation_rotation if inflation_rotation else {"status": "data_unavailable"}

    # ── 6. Volatility Regime (7-Tier Framework) ─────────────────────
    vol_regime: dict = {}
    vix_df = _load_csv("vix_move.csv")
    if vix_df is not None:
        vix_df = vix_df.sort_values("date", ascending=True)
        if "vix" in vix_df.columns and len(vix_df) > 0:
            latest_vix = float(vix_df["vix"].dropna().iloc[-1])
            vol_regime["vix"] = round(latest_vix, 1)
        if "move" in vix_df.columns and len(vix_df) > 0:
            latest_move = float(vix_df["move"].dropna().iloc[-1])
            vol_regime["move"] = round(latest_move, 1)

        vix_val = vol_regime.get("vix", 0)
        move_val = vol_regime.get("move", 0)

        # 7-tier VIX opportunity framework (Ksidiii framework)
        if vix_val >= 50:
            vol_regime["tier"] = 7
            vol_regime["regime"] = "Home run territory — extreme dislocation, generational opportunity"
            signals.append("VIX_HOME_RUN")
        elif vix_val >= 40:
            vol_regime["tier"] = 6
            vol_regime["regime"] = "Career P&L opportunity — vol sellers rewarded handsomely"
            signals.append("VIX_CAREER_PNL")
        elif vix_val >= 30:
            vol_regime["tier"] = 5
            vol_regime["regime"] = "Opportunity set unlocks — vol control funds step in, RV traders add"
            signals.append("VIX_OPPORTUNITY")
        elif vix_val >= 25:
            vol_regime["tier"] = 4
            vol_regime["regime"] = "Risk-off — hedging demand rising, position de-risking"
            signals.append("RISK_OFF_REGIME")
        elif vix_val >= 20:
            vol_regime["tier"] = 3
            vol_regime["regime"] = "Elevated caution — protection costs rising"
        elif vix_val >= 14:
            vol_regime["tier"] = 2
            vol_regime["regime"] = "Normal range"
        else:
            vol_regime["tier"] = 1
            vol_regime["regime"] = "Complacency zone — low vol often precedes spikes"
            signals.append("VIX_COMPLACENCY")

        # Dual vol spike detection (equity + bond)
        if vix_val > 25 and move_val > 120:
            vol_regime["dual_vol_spike"] = True
            if "RISK_OFF_REGIME" not in signals:
                signals.append("RISK_OFF_REGIME")

        # UnderVIX detection: VIX low but credit/curve stress present
        if vix_val < 18:
            under_vix_evidence = []
            if credit_data:
                hy_info_uv = credit_data.get("high_yield_oas", {})
                hy_stress_uv = hy_info_uv.get("stress_level", "")
                if hy_stress_uv in ("stressed", "severe_stress", "crisis", "elevated"):
                    hy_val_uv = hy_info_uv.get("latest_value", "N/A")
                    under_vix_evidence.append(f"HY OAS {hy_stress_uv} at {hy_val_uv}%")
            if yield_data:
                curve_status = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("curve_status")
                if curve_status == "inverted":
                    under_vix_evidence.append("2s10s curve inverted")
            if under_vix_evidence:
                vol_regime["under_vix_detected"] = True
                vol_regime["under_vix_evidence"] = under_vix_evidence
                vol_regime["under_vix_warning"] = "Market may be underpricing risk — VIX low despite stress signals"
                signals.append("UNDER_VIX_DETECTED")

    result["volatility_regime"] = vol_regime if vol_regime else {"status": "data_unavailable"}

    # ── 7. Rolling Correlations (macro factors vs indices) ───────────
    correlations: dict = {}
    for idx_key in indices_to_analyze:
        idx_cfg = INDEX_CONFIG.get(idx_key)
        if not idx_cfg:
            continue
        idx_df = _load_csv(idx_cfg["csv"])
        if idx_df is None:
            continue
        idx_df = idx_df.sort_values("date", ascending=True).dropna(subset=[idx_cfg["price_col"]])

        idx_corrs: dict = {}
        for factor_key, factor_cfg in MACRO_FACTOR_CSV.items():
            factor_df = _load_csv(factor_cfg["csv"])
            if factor_df is None:
                continue
            corr = _compute_rolling_corr(idx_df, idx_cfg["price_col"], factor_df, factor_cfg["col"])
            if corr:
                idx_corrs[factor_key] = corr

        if idx_corrs:
            correlations[idx_key] = idx_corrs

    result["rolling_correlations"] = correlations

    # ── Small-cap headwind check ─────────────────────────────────────
    if "REAL_YIELD_HEADWIND" in signals and "CREDIT_STRESS" in signals:
        signals.append("SMALL_CAP_HEADWIND")

    result["signals"] = signals

    # ── Summary ──────────────────────────────────────────────────────
    parts = []
    if erp_result and "equity_risk_premium_pct" in erp_result:
        parts.append(f"ERP at {erp_result['equity_risk_premium_pct']}%")
    if real_yield_impact and "real_yield_10y" in real_yield_impact:
        parts.append(f"10Y real yield {real_yield_impact['real_yield_10y']}%")
    if credit_equity and "hy_oas_bps" in credit_equity:
        parts.append(f"HY spreads {credit_equity['hy_oas_bps']}bps")
    if dxy_impact and "latest_dxy" in dxy_impact:
        parts.append(f"DXY at {dxy_impact['latest_dxy']}")
    if signals:
        parts.append(f"Signals: {', '.join(signals)}")
    result["summary"] = ". ".join(parts) + "." if parts else "Analysis complete."

    return json.dumps(result)


def analyze_bond_market() -> str:
    """Comprehensive bond market analysis.

    Analyzes yield curve shape and slope, real yields, breakeven inflation,
    credit spreads, Fed policy stance, and duration risk.

    Returns:
        JSON string with yield_curve, real_yields, breakevens, credit_spreads,
        fed_policy, duration_risk, signals, and summary.
    """
    from tools import fred_data

    result: dict = {"timestamp": datetime.now().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── 1. Yield Curve ───────────────────────────────────────────────
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)

    yield_curve: dict = {}
    if yield_data:
        # Nominal yields
        nom = yield_data.get("nominal_yields", {})
        yield_curve["nominal_yields"] = {
            k: {kk: vv for kk, vv in v.items() if kk in ("latest_value", "daily_change_bps", "wow_change_bps", "trend")}
            for k, v in nom.items() if isinstance(v, dict)
        }

        # Spreads
        spreads = yield_data.get("yield_curve_spreads", {})
        yield_curve["spreads"] = {}
        for k, v in spreads.items():
            if isinstance(v, dict):
                yield_curve["spreads"][k] = {
                    kk: vv for kk, vv in v.items()
                    if kk in ("latest_value", "curve_status", "slope_trend", "interpretation")
                }
                if v.get("curve_status") == "inverted":
                    signals.append("CURVE_INVERSION_WARNING")
                slope = v.get("slope_trend")
                if slope == "steepening":
                    signals.append("CURVE_STEEPENING")
                elif slope == "flattening":
                    signals.append("CURVE_FLATTENING")

        yield_curve["shape"] = yield_data.get("curve_shape", "unknown")

    result["yield_curve"] = yield_curve if yield_curve else {"status": "data_unavailable"}

    # ── 2. Real Yields ───────────────────────────────────────────────
    real_yields: dict = {}
    if yield_data:
        ry = yield_data.get("real_yields", {})
        for k, v in ry.items():
            if isinstance(v, dict):
                real_yields[k] = {
                    kk: vv for kk, vv in v.items()
                    if kk in ("latest_value", "daily_change_bps", "trend", "interpretation")
                }
                val = v.get("latest_value")
                daily_bps = v.get("daily_change_bps")
                if val is not None and val > 2.5:
                    signals.append("REAL_YIELD_SPIKE")
                if daily_bps is not None and abs(daily_bps) > 10:
                    signals.append("REAL_YIELD_SPIKE")

    result["real_yields"] = real_yields if real_yields else {"status": "data_unavailable"}

    # ── 3. Breakevens ────────────────────────────────────────────────
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    breakevens: dict = {}
    if inflation_data and "breakevens" in inflation_data:
        be = inflation_data["breakevens"]
        be_rising = 0
        be_falling = 0
        for k, v in be.items():
            if isinstance(v, dict):
                breakevens[k] = {
                    kk: vv for kk, vv in v.items()
                    if kk in ("latest_value", "trend", "interpretation")
                }
                trend = v.get("trend")
                if trend == "rising":
                    be_rising += 1
                elif trend == "falling":
                    be_falling += 1

        # Net direction signal (majority vote across series)
        if be_rising > be_falling:
            signals.append("BREAKEVEN_RISING")
        elif be_falling > be_rising:
            signals.append("BREAKEVEN_FALLING")

        # Flag split signal when series disagree
        if be_rising > 0 and be_falling > 0:
            signals.append("BREAKEVEN_MIXED")

        # Divergence check: 5Y vs 10Y breakeven
        t5 = be.get("t5yie", {}).get("latest_value")
        t10 = be.get("t10yie", {}).get("latest_value")
        if t5 is not None and t10 is not None and abs(t5 - t10) > 0.5:
            signals.append("BREAKEVEN_DIVERGENCE")
            breakevens["divergence"] = {
                "t5yie": round(t5, 2),
                "t10yie": round(t10, 2),
                "gap": round(abs(t5 - t10), 2),
                "interpretation": "Unusual divergence between 5Y and 10Y breakevens",
            }

    result["breakevens"] = breakevens if breakevens else {"status": "data_unavailable"}

    # ── 4. Credit Spreads ────────────────────────────────────────────
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    credit_spreads: dict = {}
    if credit_data:
        for key in ("high_yield_oas", "ig_corporate_oas", "bbb_oas", "hy_ig_differential"):
            v = credit_data.get(key)
            if isinstance(v, dict):
                credit_spreads[key] = {
                    kk: vv for kk, vv in v.items()
                    if kk in ("latest_value", "latest_value_bps", "value_bps", "wow_change_bps", "stress_level", "spread_direction", "interpretation", "one_year_percentile")
                }

        hy_wow = credit_data.get("high_yield_oas", {}).get("wow_change_bps")
        if hy_wow is not None:
            if hy_wow > 30:
                signals.append("CREDIT_WIDENING")
            elif hy_wow < -30:
                signals.append("CREDIT_TIGHTENING")

    if credit_spreads:
        result["credit_spreads"] = credit_spreads
    else:
        result["credit_spreads"] = {
            "status": "data_unavailable",
            "note": (
                "Credit spread data unavailable from get_credit_spread_data(). "
                "Check FRED_API_KEY in .env and local CSV files "
                "(hy_oas.csv, ig_oas.csv, bbb_oas.csv)."
            ),
        }

    # ── 5. Fed Policy ────────────────────────────────────────────────
    fed_policy: dict = {}
    if yield_data:
        fp = yield_data.get("fed_policy", {})
        fed_policy["effective_rate"] = fp.get("effective_rate", {}).get("latest_value")
        fed_policy["target_upper"] = fp.get("target_upper", {}).get("latest_value")
        fed_policy["stance"] = fp.get("stance", "unknown")
        fed_policy["rate_trend"] = fp.get("effective_rate", {}).get("trend")

        if "Restrictive" in str(fed_policy.get("stance", "")):
            signals.append("FED_RESTRICTIVE")

    result["fed_policy"] = fed_policy if fed_policy else {"status": "data_unavailable"}

    # ── 6. Duration Risk ─────────────────────────────────────────────
    duration_risk: dict = {"level": "moderate"}
    curve_shape = yield_curve.get("shape", "")
    ry_10y_trend = real_yields.get("10y_real", {}).get("trend")

    if ("flat" in curve_shape or "inverted" in curve_shape) and ry_10y_trend == "rising":
        duration_risk = {
            "level": "elevated",
            "interpretation": "Flat/inverted curve with rising real yields — duration risk is high",
        }
        signals.append("DURATION_RISK_HIGH")
    elif ry_10y_trend == "rising":
        duration_risk = {
            "level": "moderate-high",
            "interpretation": "Rising real yields increase mark-to-market risk for long-duration bonds",
        }
    elif ry_10y_trend == "falling":
        duration_risk = {
            "level": "low",
            "interpretation": "Falling real yields — favorable for duration exposure",
        }

    result["duration_risk"] = duration_risk

    # ── 7. Term Premium Proxy ─────────────────────────────────────────
    term_premium_section: dict = {}
    nominal_10y_val = None
    real_10y_val = None
    breakeven_10y_val = None

    if yield_data:
        nominal_10y_val = yield_data.get("nominal_yields", {}).get("10y", {}).get("latest_value")
        real_10y_val = yield_data.get("real_yields", {}).get("10y_real", {}).get("latest_value")
    if inflation_data and "breakevens" in inflation_data:
        breakeven_10y_val = inflation_data["breakevens"].get("t10yie", {}).get("latest_value")

    if nominal_10y_val is not None and real_10y_val is not None and breakeven_10y_val is not None:
        # Term premium ≈ nominal - real - breakeven
        tp = round(nominal_10y_val - real_10y_val - breakeven_10y_val, 3)
        term_premium_section = {
            "term_premium_pct": tp,
            "components": {
                "nominal_10y": round(nominal_10y_val, 3),
                "real_10y": round(real_10y_val, 3),
                "breakeven_10y": round(breakeven_10y_val, 3),
            },
        }
        # Interpretation
        be_trend = inflation_data.get("breakevens", {}).get("t10yie", {}).get("trend") if inflation_data else None
        if tp > 0 and be_trend == "rising":
            term_premium_section["interpretation"] = (
                f"Term premium positive ({tp}%) with rising breakevens — global discount rate adjustment signal"
            )
            signals.append("GLOBAL_DISCOUNT_RATE_ADJUSTMENT")
        elif tp < 0:
            term_premium_section["interpretation"] = (
                f"Negative term premium ({tp}%) — flight to safety / duration demand exceeds supply"
            )
            signals.append("FLIGHT_TO_SAFETY")
        elif tp > 0.5:
            term_premium_section["interpretation"] = (
                f"Elevated term premium ({tp}%) — investors demanding compensation for holding duration"
            )
        else:
            term_premium_section["interpretation"] = f"Term premium at {tp}% — within normal range"

    result["term_premium"] = term_premium_section if term_premium_section else {"status": "data_unavailable"}

    # Deduplicate signals
    result["signals"] = list(dict.fromkeys(signals))

    # ── Summary ──────────────────────────────────────────────────────
    parts = []
    if yield_curve.get("shape"):
        parts.append(f"Curve: {yield_curve['shape']}")
    if real_yields.get("10y_real", {}).get("latest_value"):
        parts.append(f"10Y real yield: {real_yields['10y_real']['latest_value']}%")
    if credit_spreads.get("high_yield_oas", {}).get("latest_value"):
        parts.append(f"HY OAS: {credit_spreads['high_yield_oas']['latest_value']}bps")
    if fed_policy.get("stance"):
        parts.append(f"Fed: {fed_policy['stance']}")
    parts.append(f"Duration risk: {duration_risk['level']}")
    if term_premium_section and "term_premium_pct" in term_premium_section:
        parts.append(f"Term premium: {term_premium_section['term_premium_pct']}%")
    if result["signals"]:
        parts.append(f"Signals: {', '.join(result['signals'])}")
    result["summary"] = ". ".join(parts) + "."

    return json.dumps(result)


def get_macro_market_correlations(target: str = "all") -> str:
    """Cross-asset correlation matrix between macro factors and markets.

    Loads local CSV data for macro factors (DXY, yields, VIX, MOVE,
    commodities) and equity indices (ES, RTY), then computes 20-day
    rolling correlations.

    Args:
        target: 'equities', 'bonds', or 'all'.

    Returns:
        JSON string with correlation matrix and notable relationships.
    """
    target = target.strip().lower()
    if target not in ("equities", "bonds", "all"):
        target = "all"

    result: dict = {"timestamp": datetime.now().strftime("%Y-%m-%d"), "target": target}
    correlations: dict = {}

    # ── Equity correlations ──────────────────────────────────────────
    if target in ("equities", "all"):
        for idx_key, idx_cfg in INDEX_CONFIG.items():
            idx_df = _load_csv(idx_cfg["csv"])
            if idx_df is None:
                continue
            idx_df = idx_df.sort_values("date", ascending=True).dropna(subset=[idx_cfg["price_col"]])

            idx_corrs: dict = {}
            for factor_key, factor_cfg in MACRO_FACTOR_CSV.items():
                factor_df = _load_csv(factor_cfg["csv"])
                if factor_df is None:
                    continue
                corr = _compute_rolling_corr(idx_df, idx_cfg["price_col"], factor_df, factor_cfg["col"])
                if corr:
                    idx_corrs[factor_key] = corr

            if idx_corrs:
                correlations[f"{idx_key}_vs_macro"] = idx_corrs

    # ── Bond correlations (10Y yield vs macro) ───────────────────────
    if target in ("bonds", "all"):
        bond_df = _load_csv("10y_treasury_yield.csv")
        if bond_df is not None and "10y_yield" in bond_df.columns:
            bond_df = bond_df.sort_values("date", ascending=True).dropna(subset=["10y_yield"])

            bond_corrs: dict = {}
            for factor_key, factor_cfg in MACRO_FACTOR_CSV.items():
                if factor_key == "10y_yield":
                    continue  # Skip self
                factor_df = _load_csv(factor_cfg["csv"])
                if factor_df is None:
                    continue
                corr = _compute_rolling_corr(bond_df, "10y_yield", factor_df, factor_cfg["col"])
                if corr:
                    bond_corrs[factor_key] = corr

            if bond_corrs:
                correlations["10y_yield_vs_macro"] = bond_corrs

    result["correlations"] = correlations

    # ── Find strongest and notable relationships ─────────────────────
    strongest_positive = {"pair": None, "value": -1.0}
    strongest_negative = {"pair": None, "value": 1.0}

    for group_key, group_corrs in correlations.items():
        for factor, corr_data in group_corrs.items():
            val = corr_data.get("latest_20d", 0)
            pair_name = f"{group_key} / {factor}"
            if val > strongest_positive["value"]:
                strongest_positive = {"pair": pair_name, "value": val}
            if val < strongest_negative["value"]:
                strongest_negative = {"pair": pair_name, "value": val}

    result["strongest_positive"] = strongest_positive if strongest_positive["pair"] else None
    result["strongest_negative"] = strongest_negative if strongest_negative["pair"] else None

    return json.dumps(result)
