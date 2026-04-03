"""Yardeni Research-inspired analytical frameworks.

Implements several key frameworks from Dr. Ed Yardeni's research methodology:

1. Boom-Bust Barometer (BBB) — CRB Raw Industrials / Initial Claims
2. FSMI (Fundamental Stock Market Indicator) — CRB Industrials avg + Consumer Sentiment
3. Bond Vigilantes Model — 10Y Treasury yield vs. Nominal GDP growth
4. Rule of 20 valuation — Forward P/E + CPI inflation = 20 is fair value
5. Market Decline Classification — Panic attack / correction / bear market

Data sources:
- /macro_2/historical_data/ — macro CSV files (copper as CRB proxy, S&P 500)
- tools.fred_data           — FRED API for yields, GDP, CPI, claims, sentiment
- tools.macro_market_analysis — _load_csv helper

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tools import fred_data
from tools.fred_data import _fetch_series_raw, _series_summary, _check_api_key
from tools.macro_market_analysis import _load_csv, _safe_fred_call


# ═══════════════════════════════════════════════════════════════════════
# 1. BOOM-BUST BAROMETER
# ═══════════════════════════════════════════════════════════════════════

def get_boom_bust_barometer() -> str:
    """Compute Yardeni's Boom-Bust Barometer: commodity prices / initial claims.

    Uses copper price as a CRB Raw Industrials proxy (copper is Yardeni's
    favourite single component of the CRB index). Divides by weekly initial
    unemployment claims. The ratio rises in expansions and falls into
    recessions.

    Returns:
        JSON string with current_ratio, 1Y_change, interpretation, and
        historical context.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # Copper price (CRB proxy)
    copper_df = _load_csv("copper.csv")
    copper_val = None
    if copper_df is not None:
        price_cols = [c for c in copper_df.columns if "price" in c.lower() or "copper" in c.lower()]
        if price_cols:
            copper_series = copper_df[price_cols[0]].dropna()
            if len(copper_series) > 0:
                copper_val = float(copper_series.iloc[-1])

    # Initial claims from FRED
    employment_data = _safe_fred_call(fred_data.get_employment_data)
    claims_val = None
    if employment_data:
        claims_val = employment_data.get("initial_claims", {}).get("latest_value")

    if copper_val is None or claims_val is None or claims_val == 0:
        result["error"] = "Could not compute BBB — missing copper or claims data"
        result["copper_price"] = copper_val
        result["initial_claims"] = claims_val
        return json.dumps(result, indent=2)

    # Normalize claims to thousands (FRED ICSA is raw count, e.g. 213000)
    claims_k = claims_val / 1000 if claims_val > 1000 else claims_val

    # Compute BBB ratio: copper price / claims (thousands)
    bbb_ratio = round(copper_val / claims_k, 4)

    result["copper_price"] = round(copper_val, 2)
    result["initial_claims_thousands"] = round(claims_k, 0)
    result["bbb_ratio"] = bbb_ratio

    # Interpretation
    # Higher = expansion (commodity demand up, layoffs low)
    # Lower = contraction (commodity demand down, layoffs rising)
    if bbb_ratio > 2.0:
        interp = "strong_expansion — commodity demand robust, labor market tight"
    elif bbb_ratio > 1.5:
        interp = "expansion — positive economic momentum"
    elif bbb_ratio > 1.0:
        interp = "moderate — economy growing but decelerating"
    elif bbb_ratio > 0.5:
        interp = "slowing — rising claims and/or falling commodity demand"
    else:
        interp = "contraction_signal — recessionary dynamics"

    result["interpretation"] = interp

    # Signals — actionable flags based on BBB level and dynamics
    signals = []
    if bbb_ratio < 0.5:
        signals.append("RECESSION_WARNING")
    elif bbb_ratio < 1.0:
        signals.append("DECELERATION")
    if bbb_ratio > 2.0:
        signals.append("STRONG_EXPANSION")
    if claims_k and claims_k > 300:
        signals.append("ELEVATED_CLAIMS")
    elif claims_k and claims_k < 200:
        signals.append("TIGHT_LABOR")
    result["signals"] = signals

    # Historical context from copper series
    if copper_df is not None and price_cols:
        copper_series = copper_df[price_cols[0]].dropna()
        if len(copper_series) > 250:
            copper_1y = float(copper_series.iloc[-252]) if len(copper_series) >= 252 else float(copper_series.iloc[0])
            result["copper_1y_change_pct"] = round((copper_val - copper_1y) / copper_1y * 100, 1)

    result["methodology"] = (
        "Yardeni Boom-Bust Barometer: CRB Raw Industrials (copper proxy) / "
        "Initial Claims. Peaks at end of booms, troughs at end of recessions. "
        "Unlike monthly CEI, this is available weekly with minimal lag."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 2. FUNDAMENTAL STOCK MARKET INDICATOR (FSMI)
# ═══════════════════════════════════════════════════════════════════════

def get_fsmi() -> str:
    """Compute Yardeni's FSMI: average of CRB industrials + consumer sentiment.

    FSMI is highly correlated with the S&P 500 since 2000. Not a leading
    indicator but a confirmation/divergence signal.

    Uses copper (CRB proxy, normalized) and U of Michigan Consumer Sentiment
    (UMCSENT). Both are z-scored and averaged.

    Returns:
        JSON string with fsmi_zscore, components, divergence_signal, and
        interpretation.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # Copper z-score (proxy for CRB industrials economic activity)
    copper_df = _load_csv("copper.csv")
    copper_z = None
    copper_val = None
    if copper_df is not None:
        price_cols = [c for c in copper_df.columns if "price" in c.lower() or "copper" in c.lower()]
        if price_cols:
            copper_series = copper_df[price_cols[0]].dropna()
            if len(copper_series) >= 50:
                copper_val = float(copper_series.iloc[-1])
                mean = float(copper_series.tail(252).mean())
                std = float(copper_series.tail(252).std())
                if std > 0:
                    copper_z = round((copper_val - mean) / std, 2)

    # Consumer sentiment z-score
    umcsent_obs = _fetch_series_raw("UMCSENT", limit=60, sort_order="desc")
    sent_z = None
    sent_val = None
    if umcsent_obs and len(umcsent_obs) >= 6:
        values = [o["value"] for o in umcsent_obs if o.get("value") is not None]
        if values:
            sent_val = values[0]
            mean = np.mean(values)
            std = np.std(values)
            if std > 0:
                sent_z = round((sent_val - mean) / std, 2)

    # S&P 500 z-score for divergence check
    sp_df = _load_csv("es_futures.csv")
    sp_z = None
    sp_val = None
    if sp_df is not None:
        price_cols = [c for c in sp_df.columns if "close" in c.lower() or "price" in c.lower() or c.lower().startswith("es")]
        if price_cols:
            sp_series = sp_df[price_cols[0]].dropna()
            if len(sp_series) >= 50:
                sp_val = float(sp_series.iloc[-1])
                mean = float(sp_series.tail(252).mean())
                std = float(sp_series.tail(252).std())
                if std > 0:
                    sp_z = round((sp_val - mean) / std, 2)

    result["components"] = {
        "copper_crb_proxy": {"value": copper_val, "zscore": copper_z},
        "consumer_sentiment": {"value": sent_val, "zscore": sent_z},
        "sp500": {"value": sp_val, "zscore": sp_z},
    }

    # FSMI composite z-score
    zscores = [z for z in [copper_z, sent_z] if z is not None]
    if zscores:
        fsmi_z = round(np.mean(zscores), 2)
        result["fsmi_zscore"] = fsmi_z

        # Divergence with S&P 500
        if sp_z is not None:
            gap = round(sp_z - fsmi_z, 2)
            result["sp500_vs_fsmi_gap"] = gap
            if gap > 1.0:
                result["divergence_signal"] = "SP500_overbought_vs_fundamentals — FSMI lagging equity rally"
            elif gap < -1.0:
                result["divergence_signal"] = "SP500_undervalued_vs_fundamentals — FSMI stronger than prices"
            else:
                result["divergence_signal"] = "confirmed — FSMI aligned with equities"

        # Interpretation
        if fsmi_z > 1.0:
            result["interpretation"] = "strong_economy — commodity demand + consumer confidence elevated"
        elif fsmi_z > 0:
            result["interpretation"] = "positive — economy expanding normally"
        elif fsmi_z > -1.0:
            result["interpretation"] = "softening — below average economic momentum"
        else:
            result["interpretation"] = "weak — recession risk elevated"
    else:
        result["fsmi_zscore"] = None
        result["interpretation"] = "insufficient_data"

    result["methodology"] = (
        "Yardeni FSMI: average of CRB Raw Industrials (copper proxy) z-score + "
        "U of Michigan Consumer Sentiment z-score. Highly correlated with S&P 500. "
        "When FSMI diverges from equities, it signals a potential correction or catch-up."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 3. BOND VIGILANTES MODEL
# ═══════════════════════════════════════════════════════════════════════

def analyze_bond_vigilantes() -> str:
    """Yardeni's Bond Vigilantes Model: 10Y yield vs. nominal GDP growth.

    Since 1953, the 10Y Treasury yield has fluctuated around the YoY
    growth rate of nominal GDP. Sustained divergence signals:
    - Yield > GDP growth: vigilantes demanding fiscal discipline
    - Yield < GDP growth: central bank suppression (QE, etc.)

    Returns:
        JSON string with yield_10y, nominal_gdp_growth, gap, regime, and
        historical context.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # 10Y Treasury yield
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)
    yield_10y = None
    if yield_data:
        nominal = yield_data.get("nominal_yields", {})
        # Try both "10Y" and "10y" keys for robustness
        y10 = nominal.get("10y") or nominal.get("10Y") or {}
        yield_10y = y10.get("latest_value")

    # Nominal GDP growth (use GDP series from FRED)
    # Need 2+ years for YoY on quarterly data
    gdp_start = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
    gdp_obs = _fetch_series_raw("GDP", limit=10, sort_order="desc", observation_start=gdp_start)
    nominal_gdp_yoy = None
    if gdp_obs and len(gdp_obs) >= 5:
        values = [(o["date"], o["value"]) for o in gdp_obs if o.get("value") is not None]
        if len(values) >= 5:
            latest_gdp = values[0][1]
            # GDP is quarterly — YoY is 4 quarters ago
            yoy_gdp = values[4][1] if len(values) > 4 else values[-1][1]
            if yoy_gdp > 0:
                nominal_gdp_yoy = round((latest_gdp - yoy_gdp) / yoy_gdp * 100, 2)

    result["yield_10y"] = round(yield_10y, 2) if yield_10y is not None else None
    result["nominal_gdp_yoy_pct"] = nominal_gdp_yoy

    if yield_10y is not None and nominal_gdp_yoy is not None:
        gap = round(yield_10y - nominal_gdp_yoy, 2)
        result["gap_pct"] = gap

        if gap > 1.0:
            regime = "vigilante_regime — bond market demanding higher compensation than growth justifies"
        elif gap > 0:
            regime = "mildly_tight — yields slightly above GDP growth, mild vigilante pressure"
        elif gap > -1.0:
            regime = "accommodative — yields below GDP growth, policy supportive"
        elif gap > -2.0:
            regime = "suppressed — significant central bank influence keeping yields low"
        else:
            regime = "deeply_suppressed — financial repression (QE/YCC era dynamics)"

        result["regime"] = regime

        # Investment implications
        implications = []
        if gap > 0.5:
            implications.append("Bond vigilantes active — fiscal concerns may constrain risk assets")
            implications.append("Duration risk elevated — bonds pricing higher-for-longer")
        elif gap < -1.0:
            implications.append("Financial repression — negative real returns on safe assets favor equities")
            implications.append("Credit markets benefit from yield suppression")
        result["implications"] = implications
    else:
        result["regime"] = "insufficient_data"

    result["methodology"] = (
        "Yardeni Bond Vigilantes Model (coined 1983): 10Y Treasury yield vs. "
        "Nominal GDP YoY growth. When yield exceeds GDP growth, bond vigilantes "
        "are enforcing fiscal discipline. When yield is suppressed below GDP growth, "
        "central bank policy dominates."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 4. RULE OF 20 / RULE OF 24 VALUATION
# ═══════════════════════════════════════════════════════════════════════

def analyze_yardeni_valuation() -> str:
    """Rule of 20 and Rule of 24 (Misery-Adjusted P/E) valuation framework.

    Rule of 20: Forward P/E + YoY CPI = 20 is fair value.
    Rule of 24: Forward P/E + Misery Index (unemployment + CPI) ≈ 23.9 avg.

    Uses Shiller CAPE as a P/E proxy (since forward P/E requires I/B/E/S
    data not currently available). Notes the limitation.

    Returns:
        JSON string with rule_of_20, rule_of_24, valuation_assessment.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # P/E ratio — use S&P 500 P/E from macro CSVs if available
    pe_val = None
    sp_fund = _load_csv("sp500_fundamentals.csv")
    if sp_fund is not None:
        pe_cols = [c for c in sp_fund.columns if "pe" in c.lower() or "p_e" in c.lower() or "p/e" in c.lower()]
        if pe_cols:
            pe_series = sp_fund[pe_cols[0]].dropna()
            if len(pe_series) > 0:
                pe_val = float(pe_series.iloc[-1])

    # Fallback to Shiller CAPE
    cape_val = None
    cape_df = _load_csv("shiller_cape.csv")
    if cape_df is not None:
        cape_cols = [c for c in cape_df.columns if "cape" in c.lower() or "shiller" in c.lower()]
        if cape_cols:
            cape_series = cape_df[cape_cols[0]].dropna()
            if len(cape_series) > 0:
                cape_val = float(cape_series.iloc[-1])

    effective_pe = pe_val if pe_val is not None else cape_val
    pe_source = "trailing_PE" if pe_val is not None else "Shiller_CAPE"

    # CPI YoY
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    cpi_yoy = None
    if inflation_data:
        # Try multiple key/field names for robustness
        cpi_block = (inflation_data.get("cpi")
                     or inflation_data.get("cpi_headline")
                     or {})
        cpi_yoy = (cpi_block.get("yoy_change_pct")
                   or cpi_block.get("yoy_change"))

    # Unemployment rate
    employment_data = _safe_fred_call(fred_data.get_employment_data)
    unemployment = None
    if employment_data:
        unemployment = employment_data.get("unemployment_rate", {}).get("latest_value")

    result["inputs"] = {
        "pe_ratio": round(effective_pe, 1) if effective_pe else None,
        "pe_source": pe_source,
        "cpi_yoy_pct": round(cpi_yoy, 1) if cpi_yoy is not None else None,
        "unemployment_rate": round(unemployment, 1) if unemployment is not None else None,
    }

    # Rule of 20
    if effective_pe is not None and cpi_yoy is not None:
        rule20_sum = round(effective_pe + cpi_yoy, 1)
        fair_pe_20 = round(20 - cpi_yoy, 1)
        result["rule_of_20"] = {
            "sum": rule20_sum,
            "fair_value_threshold": 20,
            "implied_fair_pe": fair_pe_20,
            "valuation": "overvalued" if rule20_sum > 20 else "undervalued" if rule20_sum < 20 else "fair",
            "gap_pct": round((rule20_sum - 20) / 20 * 100, 1),
        }

    # Rule of 24 (Misery Index)
    if effective_pe is not None and cpi_yoy is not None and unemployment is not None:
        misery_index = round(cpi_yoy + unemployment, 1)
        rule24_sum = round(effective_pe + misery_index, 1)
        fair_pe_24 = round(23.9 - misery_index, 1)
        result["rule_of_24"] = {
            "sum": rule24_sum,
            "misery_index": misery_index,
            "historical_avg": 23.9,
            "implied_fair_pe": fair_pe_24,
            "valuation": "overvalued" if rule24_sum > 23.9 else "undervalued",
            "gap_pct": round((rule24_sum - 23.9) / 23.9 * 100, 1),
        }
        # Low misery = high fair PE (Nirvana scenario)
        if misery_index < 7:
            result["rule_of_24"]["note"] = "Low Misery Index (<7%) — 'Nirvana' scenario justifies higher P/E"
        elif misery_index > 12:
            result["rule_of_24"]["note"] = "High Misery Index (>12%) — depressed fair P/E"

    # Real Earnings Yield
    if effective_pe is not None and effective_pe > 0 and cpi_yoy is not None:
        earnings_yield = round(100.0 / effective_pe, 2)
        real_ey = round(earnings_yield - cpi_yoy, 2)
        result["real_earnings_yield"] = {
            "nominal_earnings_yield_pct": earnings_yield,
            "real_earnings_yield_pct": real_ey,
            "interpretation": (
                "positive (stocks cheap in real terms)" if real_ey > 2
                else "adequate" if real_ey > 0
                else "negative (stocks expensive vs inflation)"
            ),
        }

    # Overall assessment
    assessments = []
    if "rule_of_20" in result:
        r20 = result["rule_of_20"]
        assessments.append(f"Rule of 20: {r20['valuation']} ({r20['sum']} vs 20)")
    if "rule_of_24" in result:
        r24 = result["rule_of_24"]
        assessments.append(f"Rule of 24: {r24['valuation']} ({r24['sum']} vs 23.9 avg)")
    if "real_earnings_yield" in result:
        rey = result["real_earnings_yield"]
        assessments.append(f"Real Earnings Yield: {rey['real_earnings_yield_pct']}%")

    result["assessment"] = "; ".join(assessments) if assessments else "insufficient_data"

    note = (
        "NOTE: Using " + pe_source + " instead of forward P/E (I/B/E/S data not available). "
    )
    if pe_source == "Shiller_CAPE":
        note += (
            "CAPE is a 10-year cyclically adjusted P/E and will read higher than forward P/E. "
            "Interpret directionally, not at face value against Rule of 20/24 thresholds."
        )
    result["data_note"] = note

    result["methodology"] = (
        "Rule of 20 (Jim Moltz / Yardeni): P/E + CPI = 20 is fair value. "
        "Rule of 24 (Yardeni extension): P/E + Misery Index (unemployment + CPI) avg = 23.9 since 1979. "
        "Real Earnings Yield: 1/PE - CPI YoY — mean-reverting valuation signal."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 5. MARKET DECLINE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def classify_market_decline() -> str:
    """Classify current S&P 500 drawdown using Yardeni's framework.

    Categories:
    - Panic attack: <10% from peak (66 counted 2009-2020, short-lived)
    - Correction: 10-20% from peak
    - Bear market: >20% from peak, typically recession-linked

    Returns:
        JSON string with current_drawdown, classification, peak_date,
        and forward_earnings_signal (if available).
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}

    # S&P 500 price data
    sp_df = _load_csv("es_futures.csv")
    if sp_df is None:
        sp_df = _load_csv("sp500_ma200.csv")
    if sp_df is None:
        return json.dumps({"error": "S&P 500 data not found in macro CSVs"})

    # Find price column
    price_col = None
    for col in sp_df.columns:
        if col.lower() in ("close", "price", "es_price", "sp500_price", "sp500"):
            price_col = col
            break
    if price_col is None:
        # Try first numeric column after date
        for col in sp_df.columns:
            if col != "date" and sp_df[col].dtype in [np.float64, np.int64, float, int]:
                price_col = col
                break
    if price_col is None:
        return json.dumps({"error": f"Could not identify price column. Columns: {list(sp_df.columns)}"})

    sp_series = sp_df[price_col].dropna()
    if len(sp_series) < 20:
        return json.dumps({"error": "Insufficient S&P 500 data"})

    current_price = float(sp_series.iloc[-1])
    peak = float(sp_series.max())
    peak_idx = sp_series.idxmax()

    # Find peak date
    peak_date = None
    if "date" in sp_df.columns:
        peak_date = str(sp_df.loc[peak_idx, "date"])

    drawdown_pct = round((current_price - peak) / peak * 100, 2)

    result["current_price"] = round(current_price, 1)
    result["all_time_high"] = round(peak, 1)
    result["peak_date"] = peak_date
    result["drawdown_pct"] = drawdown_pct

    # Classification
    if drawdown_pct > -3:
        classification = "at_or_near_highs"
        description = "Market near all-time high — no drawdown concern"
    elif drawdown_pct > -10:
        classification = "panic_attack"
        description = (
            f"{abs(drawdown_pct):.1f}% pullback — Yardeni 'panic attack'. "
            "66 such events occurred 2009-2020. Typically short-lived within bull markets."
        )
    elif drawdown_pct > -20:
        classification = "correction"
        description = (
            f"{abs(drawdown_pct):.1f}% correction. Key question: will it turn into a bear market? "
            "Watch forward earnings direction — if forward EPS keeps rising, bear risk is low."
        )
    else:
        classification = "bear_market"
        description = (
            f"{abs(drawdown_pct):.1f}% decline — bear market territory. "
            "Historically accompanied by recession. Check late-cycle signals and forward earnings."
        )

    result["classification"] = classification
    result["description"] = description

    # 52-week range context
    if len(sp_series) >= 252:
        yr_high = float(sp_series.tail(252).max())
        yr_low = float(sp_series.tail(252).min())
        result["52wk_high"] = round(yr_high, 1)
        result["52wk_low"] = round(yr_low, 1)
        result["pct_from_52wk_high"] = round((current_price - yr_high) / yr_high * 100, 2)

    result["methodology"] = (
        "Yardeni Market Decline Classification: <10% = panic attack (short-lived dip within "
        "a bull market), 10-20% = correction, >20% = bear market (typically recession-linked). "
        "Key differentiator: if forward EPS continues rising during the drawdown, it's more "
        "likely a correction. If forward EPS is falling, bear market risk is elevated."
    )

    return json.dumps(result, indent=2)
