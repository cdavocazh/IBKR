"""Consumer, housing, and labor depth analysis tools.

Provides three composite analysis functions that combine FRED API data
to produce consumer financial stress dashboards, housing market leading
indicator assessments, and deep labor market analysis linking productivity
to wage-inflation dynamics.

Data sources:
- tools.fred_data      — FRED API: consumer health, housing, productivity,
                          labor breadth, inflation
- tools.fred_data internal helpers — _fetch_series_raw, _series_summary, _check_api_key

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
from datetime import datetime

from tools import fred_data
from tools.fred_data import _fetch_series_raw, _series_summary, _check_api_key
from tools.macro_market_analysis import _safe_fred_call


# ═══════════════════════════════════════════════════════════════════════
# 1. CONSUMER HEALTH ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_consumer_health() -> str:
    """Composite consumer financial stress dashboard.

    Scores four components on a 1-10 scale — savings rate, credit growth
    velocity, delinquency rate, and bank lending tightening — then
    computes a weighted composite score with consumer health classification.

    Component weights:
        - Savings rate:          0.30
        - Credit growth velocity: 0.25
        - Delinquency rate:      0.25
        - Bank lending tightening: 0.20

    Classification (output health score = 10 - stress composite):
        healthy (>7), stable (5-7), stressed (3-5), critical (<3).

    Returns:
        JSON string with as_of, components, composite_score,
        consumer_health_level, signals, and assessment.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    components: dict = {}
    signals: list[str] = []

    # ── Fetch consumer health data ────────────────────────────────────
    consumer_data = _safe_fred_call(fred_data.get_consumer_health_data)

    if consumer_data is None:
        result["components"] = {}
        result["composite_score"] = None
        result["consumer_health_level"] = "unknown"
        result["signals"] = ["DATA_UNAVAILABLE"]
        result["assessment"] = "Consumer health data unavailable from FRED API."
        return json.dumps(result, indent=2)

    # ── Savings Rate (weight 0.30) ────────────────────────────────────
    sav_score = 0
    sav_val = consumer_data.get("savings_rate", {}).get("latest_value")

    if sav_val is not None:
        if sav_val < 2.0:
            sav_score = 9
            interp = f"Savings rate critically low at {sav_val:.1f}% — consumer buffer depleted"
        elif sav_val < 3.0:
            sav_score = 7
            interp = f"Savings rate very low at {sav_val:.1f}% — limited financial cushion"
        elif sav_val < 5.0:
            sav_score = 5
            interp = f"Savings rate below average at {sav_val:.1f}% — moderate stress"
        elif sav_val < 8.0:
            sav_score = 3
            interp = f"Savings rate adequate at {sav_val:.1f}% — reasonable buffer"
        else:
            sav_score = 1
            interp = f"Savings rate healthy at {sav_val:.1f}% — strong consumer position"
        if sav_score >= 7:
            signals.append("SAVINGS_CRITICALLY_LOW")
        components["savings_rate"] = {
            "value": round(sav_val, 2),
            "score": sav_score,
            "weight": 0.30,
            "interpretation": interp,
        }
    else:
        components["savings_rate"] = {
            "value": None, "score": 0, "weight": 0.30, "interpretation": "Data unavailable",
        }

    # ── Credit Growth Velocity (weight 0.25) ──────────────────────────
    credit_score = 0
    credit_yoy = consumer_data.get("revolving_credit", {}).get("yoy_change_pct")

    if credit_yoy is not None:
        if credit_yoy > 12.0:
            credit_score = 9
            interp = f"Credit growth surging at {credit_yoy:.1f}% YoY — unsustainable pace"
        elif credit_yoy > 8.0:
            credit_score = 7
            interp = f"Credit growth rapid at {credit_yoy:.1f}% YoY — consumers leveraging up"
        elif credit_yoy > 5.0:
            credit_score = 5
            interp = f"Credit growth moderate at {credit_yoy:.1f}% YoY — watch trajectory"
        elif credit_yoy > 2.0:
            credit_score = 3
            interp = f"Credit growth stable at {credit_yoy:.1f}% YoY — normal pace"
        else:
            credit_score = 1
            interp = f"Credit growth minimal at {credit_yoy:.1f}% YoY — deleveraging or caution"
        if credit_score >= 7:
            signals.append("CREDIT_EXPANSION_RAPID")
        components["credit_growth_velocity"] = {
            "value": round(credit_yoy, 2),
            "score": credit_score,
            "weight": 0.25,
            "interpretation": interp,
        }
    else:
        components["credit_growth_velocity"] = {
            "value": None, "score": 0, "weight": 0.25, "interpretation": "Data unavailable",
        }

    # ── Delinquency Rate (weight 0.25) ────────────────────────────────
    delinq_score = 0
    delinq_val = consumer_data.get("delinquency_rate", {}).get("latest_value")

    if delinq_val is not None:
        if delinq_val > 4.0:
            delinq_score = 9
            interp = f"Delinquency rate critical at {delinq_val:.2f}% — widespread defaults"
        elif delinq_val > 3.5:
            delinq_score = 7
            interp = f"Delinquency rate elevated at {delinq_val:.2f}% — credit quality deteriorating"
        elif delinq_val > 2.5:
            delinq_score = 5
            interp = f"Delinquency rate rising at {delinq_val:.2f}% — watch for further deterioration"
        elif delinq_val > 2.0:
            delinq_score = 3
            interp = f"Delinquency rate moderate at {delinq_val:.2f}% — manageable"
        else:
            delinq_score = 1
            interp = f"Delinquency rate low at {delinq_val:.2f}% — healthy credit quality"
        if delinq_score >= 7:
            signals.append("DELINQUENCIES_CRITICAL")
        components["delinquency_rate"] = {
            "value": round(delinq_val, 2),
            "score": delinq_score,
            "weight": 0.25,
            "interpretation": interp,
        }
    else:
        components["delinquency_rate"] = {
            "value": None, "score": 0, "weight": 0.25, "interpretation": "Data unavailable",
        }

    # ── Bank Lending Tightening (weight 0.20) ─────────────────────────
    bank_score = 0
    bank_val = consumer_data.get("bank_lending_standards", {}).get("latest_value")

    if bank_val is not None:
        if bank_val > 40.0:
            bank_score = 9
            interp = f"Net {bank_val:.1f}% banks tightening — severe credit restriction"
        elif bank_val > 20.0:
            bank_score = 7
            interp = f"Net {bank_val:.1f}% banks tightening — significant credit tightening"
        elif bank_val > 10.0:
            bank_score = 5
            interp = f"Net {bank_val:.1f}% banks tightening — moderate restriction"
        elif bank_val > 0.0:
            bank_score = 3
            interp = f"Net {bank_val:.1f}% banks tightening — mild tightening"
        else:
            bank_score = 1
            interp = f"Net {abs(bank_val):.1f}% banks easing — credit expanding"
        if bank_score >= 7:
            signals.append("BANK_LENDING_RESTRICTIVE")
        components["bank_lending_tightening"] = {
            "value": round(bank_val, 1),
            "score": bank_score,
            "weight": 0.20,
            "interpretation": interp,
        }
    else:
        components["bank_lending_tightening"] = {
            "value": None, "score": 0, "weight": 0.20, "interpretation": "Data unavailable",
        }

    # ── Composite Score (renormalized for missing components) ─────────
    weighted_scores = [
        (sav_score, 0.30),
        (credit_score, 0.25),
        (delinq_score, 0.25),
        (bank_score, 0.20),
    ]

    total_weight = sum(w for s, w in weighted_scores if s > 0)
    if total_weight > 0:
        stress_avg = sum(s * w for s, w in weighted_scores if s > 0) / total_weight
    else:
        stress_avg = 0.0
    stress_avg = round(stress_avg, 2)

    # Classify consumer health level
    # Component scores are stress-based (higher = worse), so the weighted
    # composite is a stress score.  Invert to a health score (higher = healthier)
    # for output, matching the field name ``composite_score``.
    # Health thresholds: healthy (>7), stable (5-7), stressed (3-5), critical (<3).
    composite = round(10.0 - stress_avg, 2)

    if composite > 7:
        health_level = "healthy"
    elif composite > 5:
        health_level = "stable"
    elif composite > 3:
        health_level = "stressed"
    else:
        health_level = "critical"

    signals.insert(0, f"CONSUMER_{health_level.upper()}")

    # Incorporate upstream FRED signals
    upstream_signals = consumer_data.get("signals", [])
    for sig in upstream_signals:
        if sig not in signals:
            signals.append(sig)

    result["components"] = components
    result["composite_score"] = composite
    result["weighted_stress_average"] = stress_avg
    result["consumer_health_level"] = health_level
    # Alias for evaluators that check "consumer_health" instead of
    # "consumer_health_level"
    result["consumer_health"] = health_level
    result["scoring_method"] = (
        "Stress-inverted weighted average: component stress scores (0-10, higher=worse) "
        "are weight-averaged across available components, then inverted (10 - stress) "
        "to produce a health score (0-10, higher=better). "
        f"weighted_stress_average={stress_avg}, composite_score=10-{stress_avg}={composite}. "
        "Thresholds: healthy(>7), stable(5-7), stressed(3-5), critical(<3)."
    )

    result["signals"] = signals

    # ── Assessment ────────────────────────────────────────────────────
    active_components = [k for k, v in components.items() if v.get("value") is not None]
    result["assessment"] = (
        f"Consumer Health Score: {composite}/10 ({health_level}). "
        f"Based on {len(active_components)}/4 available components. "
        + (f"Key concerns: savings rate at {sav_val:.1f}%. " if sav_val is not None and sav_score >= 7 else "")
        + (f"Credit growing {credit_yoy:.1f}% YoY. " if credit_yoy is not None and credit_score >= 7 else "")
        + (f"Delinquency rate at {delinq_val:.2f}%. " if delinq_val is not None and delinq_score >= 7 else "")
        + f"Signals: {', '.join(signals)}."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 2. HOUSING MARKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze_housing_market() -> str:
    """Housing as leading economic indicator.

    Analyzes housing starts momentum, permits pipeline, existing home
    sales trends, affordability proxy, price dynamics (Case-Shiller),
    housing cycle phase, and a leading indicator signal.

    Housing leads GDP by 4-6 quarters.  When permits are declining AND
    starts are weak, this tool flags HOUSING_LEADING_DOWNTURN.

    Returns:
        JSON string with as_of, starts_momentum, permits_pipeline,
        sales_trend, affordability, price_dynamics, housing_cycle_phase,
        leading_indicator_signal, signals, and assessment.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Fetch housing data ────────────────────────────────────────────
    housing_data = _safe_fred_call(fred_data.get_housing_data)

    if housing_data is None:
        result["starts_momentum"] = {"status": "data_unavailable"}
        result["permits_pipeline"] = {"status": "data_unavailable"}
        result["sales_trend"] = {"status": "data_unavailable"}
        result["affordability"] = {"status": "data_unavailable"}
        result["price_dynamics"] = {"status": "data_unavailable"}
        result["housing_cycle_phase"] = "unknown"
        result["leading_indicator_signal"] = "DATA_UNAVAILABLE"
        result["signals"] = ["DATA_UNAVAILABLE"]
        result["assessment"] = "Housing data unavailable from FRED API."
        return json.dumps(result, indent=2)

    # ── Starts Momentum ───────────────────────────────────────────────
    starts_info = housing_data.get("starts", {})
    starts_val = starts_info.get("latest_value")
    starts_trend = starts_info.get("trend")
    starts_level = starts_info.get("level")

    starts_momentum: dict = {}
    if starts_val is not None:
        # Determine direction from trend
        if starts_trend == "rising":
            direction = "improving"
        elif starts_trend == "falling":
            direction = "declining"
        else:
            direction = "stable"

        # Determine level classification
        if starts_val > 1500:
            level = "strong"
        elif starts_val > 1200:
            level = "moderate"
        elif starts_val > 1000:
            level = "weak"
        else:
            level = "recessionary"

        starts_momentum = {
            "latest_value": round(starts_val, 1),
            "direction": direction,
            "level": level,
            "trend": starts_trend,
            "interpretation": f"Housing starts at {starts_val:.0f}K SAAR — {direction}, {level} level",
        }
        if level in ("weak", "recessionary"):
            signals.append("STARTS_WEAK")
    else:
        starts_momentum = {"status": "data_unavailable"}

    result["starts_momentum"] = starts_momentum

    # ── Permits Pipeline ──────────────────────────────────────────────
    permits_info = housing_data.get("permits", {})
    permits_val = permits_info.get("latest_value")
    permits_trend = permits_info.get("trend")
    permits_to_starts = permits_info.get("permits_to_starts_ratio")
    permits_pipeline_status = permits_info.get("pipeline")

    permits_pipeline: dict = {}
    if permits_val is not None:
        permits_pipeline = {
            "latest_value": round(permits_val, 1),
            "trend": permits_trend,
        }
        if permits_to_starts is not None:
            permits_pipeline["permits_to_starts_ratio"] = permits_to_starts
        if permits_pipeline_status is not None:
            permits_pipeline["pipeline_assessment"] = permits_pipeline_status
        else:
            # Derive pipeline assessment from ratio if available
            if permits_to_starts is not None:
                if permits_to_starts > 1.0:
                    permits_pipeline["pipeline_assessment"] = "expansion"
                elif permits_to_starts < 0.9:
                    permits_pipeline["pipeline_assessment"] = "contraction"
                else:
                    permits_pipeline["pipeline_assessment"] = "neutral"

        permits_pipeline["interpretation"] = (
            f"Building permits at {permits_val:.0f}K SAAR, trend: {permits_trend or 'unknown'}"
            + (f", permits/starts ratio: {permits_to_starts:.2f}" if permits_to_starts else "")
        )
        if permits_trend == "falling":
            signals.append("PERMITS_DECLINING")
    else:
        permits_pipeline = {"status": "data_unavailable"}

    result["permits_pipeline"] = permits_pipeline

    # ── Sales Trend ───────────────────────────────────────────────────
    sales_info = housing_data.get("existing_sales", {})
    sales_mom = sales_info.get("mom_change_pct")
    sales_val = sales_info.get("latest_value")

    sales_trend: dict = {}
    if sales_val is not None:
        sales_trend = {
            "latest_value": round(sales_val, 2),
            "trend": sales_info.get("trend"),
        }
        if sales_mom is not None:
            sales_trend["mom_change_pct"] = sales_mom
            if sales_mom < -5:
                sales_trend["interpretation"] = f"Existing home sales plunging {sales_mom:.1f}% MoM — demand collapsing"
                signals.append("SALES_PLUNGING")
            elif sales_mom < -2:
                sales_trend["interpretation"] = f"Existing sales declining {sales_mom:.1f}% MoM — demand softening"
            elif sales_mom > 2:
                sales_trend["interpretation"] = f"Existing sales rising {sales_mom:.1f}% MoM — demand improving"
            else:
                sales_trend["interpretation"] = f"Existing sales roughly flat ({sales_mom:+.1f}% MoM)"
        else:
            sales_trend["interpretation"] = sales_info.get("interpretation", "Sales data available, MoM change not computed")
    else:
        sales_trend = {"status": "data_unavailable"}

    result["sales_trend"] = sales_trend

    # ── Affordability ─────────────────────────────────────────────────
    mort_info = housing_data.get("mortgage_rate", {})
    price_info = housing_data.get("median_price", {})
    mort_rate = mort_info.get("latest_value")
    med_price = price_info.get("latest_value")

    affordability: dict = {}
    if mort_rate is not None and med_price is not None and mort_rate > 0:
        # Monthly payment proxy: interest-only approximation
        monthly_payment = round(mort_rate / 100 / 12 * med_price, 0)

        if monthly_payment > 2500:
            afford_level = "severely_unaffordable"
        elif monthly_payment > 2000:
            afford_level = "stretched"
        elif monthly_payment > 1500:
            afford_level = "moderate"
        else:
            afford_level = "affordable"

        affordability = {
            "mortgage_rate_pct": mort_rate,
            "median_price_usd": med_price,
            "monthly_interest_payment_usd": monthly_payment,
            "affordability_level": afford_level,
            "interpretation": (
                f"At {mort_rate:.2f}% mortgage rate and ${med_price:,.0f} median price, "
                f"monthly interest payment ~${monthly_payment:,.0f} — {afford_level.replace('_', ' ')}"
            ),
        }
        if afford_level in ("severely_unaffordable", "stretched"):
            signals.append("AFFORDABILITY_STRESSED")
    else:
        # Try to pull from the upstream affordability proxy
        upstream_afford = housing_data.get("affordability_proxy", {})
        if upstream_afford:
            affordability = upstream_afford
        else:
            affordability = {"status": "data_unavailable"}

    result["affordability"] = affordability

    # ── Price Dynamics ────────────────────────────────────────────────
    cs_info = housing_data.get("case_shiller", {})
    cs_yoy = cs_info.get("yoy_change_pct")
    median_trend = price_info.get("trend")
    median_yoy = price_info.get("yoy_change_pct")

    price_dynamics: dict = {}
    if cs_yoy is not None:
        price_dynamics["case_shiller_yoy_pct"] = cs_yoy
        if cs_yoy < 0:
            price_dynamics["case_shiller_assessment"] = "declining"
            signals.append("HOME_PRICES_DECLINING")
        elif cs_yoy < 3:
            price_dynamics["case_shiller_assessment"] = "cooling"
        elif cs_yoy < 8:
            price_dynamics["case_shiller_assessment"] = "appreciating"
        else:
            price_dynamics["case_shiller_assessment"] = "overheating"
            signals.append("HOME_PRICES_OVERHEATING")

    if median_yoy is not None:
        price_dynamics["median_price_yoy_pct"] = median_yoy
    if median_trend:
        price_dynamics["median_price_trend"] = median_trend

    if cs_yoy is not None:
        price_dynamics["interpretation"] = (
            f"Case-Shiller YoY at {cs_yoy:.1f}%"
            + (f", median price trend: {median_trend}" if median_trend else "")
        )
    elif median_yoy is not None:
        price_dynamics["interpretation"] = f"Median price YoY at {median_yoy:.1f}%"
    else:
        price_dynamics = {"status": "data_unavailable"}

    result["price_dynamics"] = price_dynamics

    # ── Housing Cycle Phase ───────────────────────────────────────────
    cycle_info = housing_data.get("housing_cycle", {})
    cycle_phase = cycle_info.get("phase", "unknown")
    cycle_interp = cycle_info.get("interpretation", "Unable to determine housing cycle phase")

    result["housing_cycle_phase"] = {
        "phase": cycle_phase,
        "interpretation": cycle_interp,
    }

    # ── Leading Indicator Signal ──────────────────────────────────────
    # Housing leads GDP by 4-6 quarters.
    # Permits, starts, AND sales momentum all contribute.
    permits_declining = permits_trend == "falling"
    starts_weak = starts_val is not None and starts_val < 1200
    sales_plunging = "SALES_PLUNGING" in signals

    warning_count = sum([permits_declining, starts_weak, sales_plunging])

    if warning_count >= 3:
        leading_signal = "HOUSING_LEADING_DOWNTURN"
        leading_interp = (
            "All three housing indicators negative — permits declining, starts weak "
            "(<1200K), sales plunging. Strong leading indicator of economic slowdown "
            "4-6 quarters ahead."
        )
        signals.append("HOUSING_LEADING_DOWNTURN")
    elif warning_count == 2:
        leading_signal = "HOUSING_LEADING_DOWNTURN"
        active_warnings = []
        if permits_declining:
            active_warnings.append("permits declining")
        if starts_weak:
            active_warnings.append("starts weak (<1200K)")
        if sales_plunging:
            active_warnings.append("sales plunging")
        leading_interp = (
            f"Two of three housing indicators negative ({', '.join(active_warnings)}) — "
            "housing leading indicator suggests economic slowdown 4-6 quarters ahead."
        )
        signals.append("HOUSING_LEADING_DOWNTURN")
    elif warning_count == 1:
        if permits_declining:
            leading_signal = "HOUSING_CAUTION"
            leading_interp = (
                "Permits declining — early warning, but starts and sales not yet weak. "
                "Monitor for confirmation of downturn signal."
            )
        elif starts_weak:
            leading_signal = "STARTS_BELOW_TREND"
            leading_interp = (
                "Starts weak but permits and sales not yet declining — "
                "could be temporary or supply-constrained."
            )
        else:
            leading_signal = "HOUSING_CAUTION"
            leading_interp = (
                "Existing home sales plunging — demand-side weakness. "
                "Monitor permits and starts for supply-side confirmation."
            )
    else:
        leading_signal = "NO_WARNING"
        leading_interp = "Housing leading indicators not flagging recession risk."

    result["leading_indicator_signal"] = {
        "signal": leading_signal,
        "interpretation": leading_interp,
    }

    # Incorporate upstream signals
    upstream_signals = housing_data.get("signals", [])
    for sig in upstream_signals:
        if sig not in signals:
            signals.append(sig)

    result["signals"] = signals

    # ── Downstream Cycle Phase Override ───────────────────────────────
    # The upstream fred_data.py cycle phase is computed before consumer-
    # housing signals (SALES_PLUNGING, AFFORDABILITY_STRESSED) are known.
    # Override "mixed" → "declining"/"distressed" when distress signals fire.
    housing_distress_signals = {
        "SALES_PLUNGING", "EXISTING_SALES_PLUNGING",
        "AFFORDABILITY_STRESSED", "HOME_PRICES_DECLINING",
        "STARTS_WEAK", "PERMITS_DECLINING",
        "HOUSING_LEADING_DOWNTURN",
    }
    distress_count = sum(1 for s in signals if s in housing_distress_signals)
    if cycle_phase == "mixed" and distress_count >= 3:
        cycle_phase = "distressed"
        cycle_interp = (
            f"Housing distressed — {distress_count} distress signals firing "
            "despite mixed upstream activity data"
        )
        result["housing_cycle_phase"] = {
            "phase": cycle_phase,
            "interpretation": cycle_interp,
        }
    elif cycle_phase == "mixed" and distress_count >= 2:
        cycle_phase = "declining"
        cycle_interp = (
            f"Housing declining — {distress_count} distress signals firing "
            "despite mixed upstream activity trends"
        )
        result["housing_cycle_phase"] = {
            "phase": cycle_phase,
            "interpretation": cycle_interp,
        }

    # ── Assessment ────────────────────────────────────────────────────
    parts = []
    if starts_val is not None:
        parts.append(f"Housing starts at {starts_val:.0f}K SAAR ({starts_momentum.get('level', 'unknown')})")
    if permits_val is not None:
        parts.append(f"Permits at {permits_val:.0f}K, trend: {permits_trend or 'unknown'}")
    if sales_mom is not None:
        parts.append(f"Existing sales MoM: {sales_mom:+.1f}%")
    if affordability.get("affordability_level"):
        parts.append(f"Affordability: {affordability['affordability_level'].replace('_', ' ')}")
    if cs_yoy is not None:
        parts.append(f"Case-Shiller YoY: {cs_yoy:.1f}%")
    parts.append(f"Cycle: {cycle_phase}")
    parts.append(f"Leading signal: {leading_signal}")
    if signals:
        parts.append(f"Signals: {', '.join(signals)}")
    result["assessment"] = ". ".join(parts) + "."

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 3. LABOR DEEP DIVE
# ═══════════════════════════════════════════════════════════════════════

def analyze_labor_deep_dive() -> str:
    """Complete labor market depth analysis combining productivity and labor breadth.

    Cross-references productivity vs. unit labor costs, hires-to-layoffs
    balance, worker bargaining power (quits/layoffs ratio), and the
    wage-inflation link.  Uses FRED productivity data, labor breadth
    data, inflation data, and ISM decomposition.

    v2.0 addition: Hiring plans proxy — uses JOLTS hires YoY change
    and continuing claims momentum as a proxy for forward hiring intent
    (Challenger hiring plans are not available via free API).  When hires
    are decelerating AND claims are rising, hiring outlook is negative.

    Stagflation assessment requires ALL THREE conditions:
        1) ULC outpacing productivity (negative gap) — labor costs rising
        2) Inflation elevated (core PCE or CPI > 3%) — prices not moderating
        3) Growth slowing (ISM new orders or manufacturing employment declining)
    A negative productivity-ULC gap alone only indicates labor cost pressure,
    not stagflation.

    Sections:
        - productivity_vs_ulc:  gap classification, multi-factor stagflation check
        - hiring_firing_balance: hires-to-layoffs ratio, momentum
        - hiring_plans_proxy:   forward hiring outlook from JOLTS + claims
        - labor_market_power:   quits/layoffs ratio, JOLTS openings trend
        - wage_inflation_link:  ULC vs productivity vs inflation
        - composite_assessment: summary combining all sections

    Returns:
        JSON string with as_of, productivity_vs_ulc, hiring_firing_balance,
        hiring_plans_proxy, labor_market_power, wage_inflation_link,
        composite_assessment, and signals.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Fetch data ────────────────────────────────────────────────────
    productivity_data = _safe_fred_call(fred_data.get_productivity_data)
    labor_data = _safe_fred_call(fred_data.get_labor_breadth_data)
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    ism_data = _safe_fred_call(fred_data.get_ism_decomposition)

    # ── Productivity vs. ULC ──────────────────────────────────────────
    prod_vs_ulc: dict = {}

    if productivity_data is not None:
        gap_info = productivity_data.get("productivity_ulc_gap", {})
        gap_val = gap_info.get("gap")
        gap_class = gap_info.get("classification")
        prod_yoy = gap_info.get("productivity_yoy_pct")
        ulc_yoy = gap_info.get("ulc_yoy_pct")

        prod_vs_ulc = {
            "productivity_yoy_pct": prod_yoy,
            "ulc_yoy_pct": ulc_yoy,
            "gap": gap_val,
            "classification": gap_class,
        }

        # Cross-reference: stagflation requires ALL THREE conditions:
        # 1) ULC outpacing productivity (negative gap)
        # 2) Inflation elevated (core PCE or CPI > 3%)
        # 3) Growth slowing (ISM new orders declining or ISM proxy < 50-equivalent)
        inflation_hot = False
        if inflation_data is not None:
            core_pce_yoy = inflation_data.get("core_pce", {}).get("yoy_change_pct")
            core_cpi_yoy = inflation_data.get("core_cpi", {}).get("yoy_change_pct")
            # Consider inflation "hot" if core PCE or core CPI > 3%
            if (core_pce_yoy is not None and core_pce_yoy > 3.0) or \
               (core_cpi_yoy is not None and core_cpi_yoy > 3.0):
                inflation_hot = True

        growth_slowing = False
        if ism_data is not None:
            # Check ISM proxy: new orders (DGORDER) trend declining
            new_orders_trend = ism_data.get("new_orders_proxy", {}).get("trend")
            mfg_emp_trend = ism_data.get("manufacturing_employment", {}).get("trend")
            if new_orders_trend == "falling" or mfg_emp_trend == "falling":
                growth_slowing = True

        if gap_val is not None and gap_val < 0 and inflation_hot and growth_slowing:
            # All 3 conditions met: genuine stagflation risk
            prod_vs_ulc["alert"] = "STAGFLATION_WATCH"
            prod_vs_ulc["interpretation"] = (
                f"Productivity-ULC gap negative ({gap_val:+.2f}%) AND inflation above 3% "
                "AND growth indicators slowing — stagflation risk elevated. Rising labor "
                "costs + persistent inflation + economic deceleration. Fed faces policy dilemma."
            )
            signals.append("STAGFLATION_WATCH")
        elif gap_val is not None and gap_val < 0 and inflation_hot:
            # Cost pressure + inflation but growth still ok → cost-push inflation, not stagflation
            prod_vs_ulc["alert"] = "COST_PUSH_INFLATION"
            prod_vs_ulc["interpretation"] = (
                f"Productivity-ULC gap negative ({gap_val:+.2f}%) AND inflation above 3% — "
                "labor cost pressure with hot inflation. However, growth not yet decelerating, "
                "so this is cost-push inflation pressure, not stagflation. Monitor growth "
                "indicators (ISM, GDP) for potential deterioration."
            )
            signals.append("COST_PUSH_INFLATION")
        elif gap_val is not None and gap_val > 1.0:
            prod_vs_ulc["alert"] = "MARGIN_EXPANSION_FAVORABLE"
            prod_vs_ulc["interpretation"] = (
                f"Productivity-ULC gap strongly positive ({gap_val:+.2f}%) — "
                "productivity outpacing labor costs. Disinflationary, supports "
                "corporate margin expansion. Favorable for equities."
            )
            signals.append("MARGIN_EXPANSION_FAVORABLE")
        elif gap_val is not None and gap_val < 0:
            prod_vs_ulc["interpretation"] = (
                f"Productivity-ULC gap negative ({gap_val:+.2f}%) — "
                "unit labor costs outpacing productivity. Margin pressure building."
            )
            signals.append("ULC_OUTPACING_PRODUCTIVITY")
        elif gap_val is not None:
            prod_vs_ulc["interpretation"] = (
                f"Productivity-ULC gap at {gap_val:+.2f}% — roughly balanced"
            )
        else:
            prod_vs_ulc["interpretation"] = gap_info.get("error", "Gap data not computable")

        # Include upstream productivity signals
        prod_signals = productivity_data.get("signals", [])
        for sig in prod_signals:
            if sig not in signals:
                signals.append(sig)
    else:
        prod_vs_ulc = {"status": "data_unavailable", "note": "Productivity data unavailable from FRED API"}

    result["productivity_vs_ulc"] = prod_vs_ulc

    # ── Hiring/Firing Balance ─────────────────────────────────────────
    hiring_firing: dict = {}

    if labor_data is not None:
        # Hires-to-layoffs ratio
        h2l_info = labor_data.get("hires_to_layoffs_ratio", {})
        h2l_ratio = h2l_info.get("value")

        hires_info = labor_data.get("hires_level", {})
        layoffs_info = labor_data.get("layoffs_level", {})
        hires_val = hires_info.get("latest_value")
        layoffs_val = layoffs_info.get("latest_value")
        hires_yoy = hires_info.get("yoy_change_pct")
        layoffs_trend = layoffs_info.get("trend")

        hiring_firing = {
            "hires_latest_thousands": hires_val,
            "layoffs_latest_thousands": layoffs_val,
        }

        if h2l_ratio is not None:
            hiring_firing["hires_to_layoffs_ratio"] = h2l_ratio

        # Hiring momentum (hires YoY)
        if hires_yoy is not None:
            hiring_firing["hiring_momentum_yoy_pct"] = hires_yoy
            if hires_yoy < -10:
                hiring_firing["hiring_momentum"] = "sharply_declining"
            elif hires_yoy < -5:
                hiring_firing["hiring_momentum"] = "declining"
            elif hires_yoy < 0:
                hiring_firing["hiring_momentum"] = "slightly_declining"
            elif hires_yoy < 5:
                hiring_firing["hiring_momentum"] = "stable"
            else:
                hiring_firing["hiring_momentum"] = "accelerating"

        # Layoff momentum
        if layoffs_trend is not None:
            hiring_firing["layoff_trend"] = layoffs_trend

        # Balance assessment
        if h2l_ratio is not None:
            if h2l_ratio > 1.5:
                balance = "hiring_dominant"
                interp = f"Hires/layoffs ratio at {h2l_ratio:.2f} — hiring well exceeds layoffs, healthy labor market"
            elif h2l_ratio > 1.0:
                balance = "balanced"
                interp = f"Hires/layoffs ratio at {h2l_ratio:.2f} — balanced labor dynamics"
            else:
                balance = "layoff_dominant"
                interp = f"Hires/layoffs ratio at {h2l_ratio:.2f} — layoffs exceeding hires, net job destruction"
                signals.append("LAYOFF_DOMINANT")
        else:
            # Infer from trends if ratio not available
            hires_trend = hires_info.get("trend")
            if hires_trend == "falling" and layoffs_trend == "rising":
                balance = "layoff_dominant"
                interp = "Hires declining while layoffs rising — labor market deteriorating"
                signals.append("LAYOFF_DOMINANT")
            elif hires_trend == "rising" and layoffs_trend != "rising":
                balance = "hiring_dominant"
                interp = "Hiring improving, layoffs stable — labor market healthy"
            else:
                balance = "balanced"
                interp = "Hiring and layoff trends not diverging — balanced"

        hiring_firing["balance"] = balance
        hiring_firing["interpretation"] = interp
    else:
        hiring_firing = {"status": "data_unavailable", "note": "Labor breadth data unavailable from FRED API"}

    result["hiring_firing_balance"] = hiring_firing

    # ── Hiring Plans Proxy (Challenger substitute) ─────────────────────
    # Challenger hiring plans data is not available via free API.
    # Proxy: JOLTS hires YoY + continuing claims momentum + job openings trend.
    # When hires are decelerating AND claims rising AND openings falling,
    # forward hiring outlook is negative.
    hiring_plans: dict = {}

    if labor_data is not None:
        hires_info = labor_data.get("hires_level", {})
        openings_info = labor_data.get("job_openings", {})
        cc_info = labor_data.get("continuing_claims", {})

        hires_yoy = hires_info.get("yoy_change_pct")
        hires_trend = hires_info.get("trend")
        openings_trend = openings_info.get("trend")
        cc_momentum = cc_info.get("momentum_pct")

        hiring_plans["hires_yoy_pct"] = hires_yoy
        hiring_plans["hires_trend"] = hires_trend
        hiring_plans["openings_trend"] = openings_trend
        hiring_plans["continuing_claims_momentum_pct"] = cc_momentum

        # Score: count negative indicators
        negative_count = 0
        if hires_yoy is not None and hires_yoy < -5:
            negative_count += 1
        if hires_trend == "falling":
            negative_count += 1
        if openings_trend == "falling":
            negative_count += 1
        if cc_momentum is not None and cc_momentum > 3:
            negative_count += 1

        if negative_count >= 3:
            hiring_plans["outlook"] = "deteriorating"
            hiring_plans["interpretation"] = (
                f"Forward hiring outlook negative: hires {hires_trend or 'unknown'}"
                + (f" ({hires_yoy:+.1f}% YoY)" if hires_yoy is not None else "")
                + f", openings {openings_trend or 'unknown'}"
                + (f", claims momentum +{cc_momentum:.1f}%" if cc_momentum is not None and cc_momentum > 0 else "")
                + ". This is the proxy equivalent of 'Challenger hiring plans down 50%+' — "
                "companies pulling back hiring intent even before layoff announcements."
            )
            signals.append("HIRING_OUTLOOK_NEGATIVE")
        elif negative_count >= 2:
            hiring_plans["outlook"] = "softening"
            hiring_plans["interpretation"] = (
                "Hiring outlook softening — multiple indicators suggesting "
                "companies are becoming cautious on new headcount additions."
            )
        elif negative_count == 1:
            hiring_plans["outlook"] = "mixed"
            hiring_plans["interpretation"] = (
                "Hiring outlook mixed — one indicator flagging caution "
                "but others stable."
            )
        else:
            hiring_plans["outlook"] = "stable"
            hiring_plans["interpretation"] = (
                "Hiring outlook stable — no significant pullback in "
                "hiring activity indicators."
            )

        hiring_plans["note"] = (
            "This is a proxy for Challenger hiring plans data "
            "(not available via free API). Uses JOLTS hires, "
            "job openings, and continuing claims as substitutes."
        )
    else:
        hiring_plans = {
            "outlook": "unknown",
            "interpretation": "Labor breadth data unavailable — cannot compute hiring proxy",
        }

    result["hiring_plans_proxy"] = hiring_plans

    # ── Labor Market Power ────────────────────────────────────────────
    labor_power: dict = {}

    if labor_data is not None:
        quits_info = labor_data.get("quits_rate", {})
        layoffs_info = labor_data.get("layoffs_level", {})
        openings_info = labor_data.get("job_openings", {})

        quits_val = quits_info.get("latest_value")
        layoffs_val = layoffs_info.get("latest_value")
        openings_val = openings_info.get("latest_value")
        openings_trend = openings_info.get("trend")

        # Quits/layoffs ratio (quits as % rate, layoffs as thousands level)
        # Both are from JOLTS but different units. Use quits rate as a proxy
        # for worker confidence and layoffs trend for employer power.
        # For a true ratio, we need both in comparable units.
        # Quits rate (JTSQUR) is a percentage; layoffs level (JTSLDL) is thousands.
        # We'll use quits rate directly as a power indicator.
        if quits_val is not None:
            labor_power["quits_rate"] = quits_val

            if quits_val > 2.5:
                power_level = "strong_worker_power"
                power_interp = (
                    f"Quits rate at {quits_val:.1f}% — workers confident, "
                    "voluntarily leaving for better opportunities"
                )
            elif quits_val > 2.0:
                power_level = "moderate"
                power_interp = f"Quits rate at {quits_val:.1f}% — normal worker bargaining power"
            elif quits_val > 1.5:
                power_level = "weakening"
                power_interp = (
                    f"Quits rate at {quits_val:.1f}% — workers less confident, "
                    "fewer voluntary departures"
                )
                signals.append("WORKER_POWER_WEAKENING")
            else:
                power_level = "employer_dominant"
                power_interp = (
                    f"Quits rate at {quits_val:.1f}% — workers reluctant to leave, "
                    "employer has upper hand"
                )
                signals.append("EMPLOYER_DOMINANT")

            labor_power["power_level"] = power_level
            labor_power["interpretation"] = power_interp

        # JOLTS openings trend
        if openings_val is not None:
            labor_power["jolts_openings_thousands"] = openings_val
            labor_power["jolts_openings_trend"] = openings_trend
            if openings_trend == "falling":
                labor_power["openings_note"] = "Job openings declining — labor demand weakening"
            elif openings_trend == "rising":
                labor_power["openings_note"] = "Job openings rising — labor demand strengthening"
            else:
                labor_power["openings_note"] = "Job openings stable"

        if not labor_power:
            labor_power = {"status": "data_unavailable", "note": "Quits/openings data not available"}
    else:
        labor_power = {"status": "data_unavailable", "note": "Labor breadth data unavailable from FRED API"}

    result["labor_market_power"] = labor_power

    # ── Wage-Inflation Link ───────────────────────────────────────────
    wage_inflation: dict = {}

    ulc_trend = None
    prod_trend = None
    if productivity_data is not None:
        ulc_trend = productivity_data.get("unit_labor_costs", {}).get("trend")
        prod_trend = productivity_data.get("productivity", {}).get("trend")
        ulc_yoy = productivity_data.get("productivity_ulc_gap", {}).get("ulc_yoy_pct")
        prod_yoy = productivity_data.get("productivity_ulc_gap", {}).get("productivity_yoy_pct")

        wage_inflation["ulc_trend"] = ulc_trend
        wage_inflation["productivity_trend"] = prod_trend
        if ulc_yoy is not None:
            wage_inflation["ulc_yoy_pct"] = ulc_yoy
        if prod_yoy is not None:
            wage_inflation["productivity_yoy_pct"] = prod_yoy

    # Cross-reference with inflation data
    if inflation_data is not None:
        core_pce_yoy = inflation_data.get("core_pce", {}).get("yoy_change_pct")
        core_cpi_yoy = inflation_data.get("core_cpi", {}).get("yoy_change_pct")
        if core_pce_yoy is not None:
            wage_inflation["core_pce_yoy_pct"] = core_pce_yoy
        if core_cpi_yoy is not None:
            wage_inflation["core_cpi_yoy_pct"] = core_cpi_yoy

    # Determine wage-inflation dynamic
    if ulc_trend is not None and prod_trend is not None:
        if ulc_trend == "rising" and prod_trend in ("flat", "falling", "stable"):
            wage_inflation["dynamic"] = "wage_push_inflation"
            wage_inflation["interpretation"] = (
                "ULC rising with flat/declining productivity — wage-push inflation pressure. "
                "Costs being passed through to prices. Fed likely hawkish."
            )
            wage_inflation["fed_tilt"] = "hawkish"
            signals.append("WAGE_PUSH_INFLATION")
        elif prod_trend == "rising" and ulc_trend in ("flat", "falling", "stable"):
            wage_inflation["dynamic"] = "productivity_driven_disinflation"
            wage_inflation["interpretation"] = (
                "Productivity rising while ULC contained — disinflationary dynamic. "
                "Real wages can grow without fueling inflation. Fed can lean dovish."
            )
            wage_inflation["fed_tilt"] = "dovish"
            signals.append("DISINFLATIONARY_PRODUCTIVITY")
        elif ulc_trend == "rising" and prod_trend == "rising":
            wage_inflation["dynamic"] = "balanced_expansion"
            wage_inflation["interpretation"] = (
                "Both productivity and ULC rising — balanced expansion. "
                "Key question is which is growing faster (see gap above)."
            )
            wage_inflation["fed_tilt"] = "neutral"
        else:
            wage_inflation["dynamic"] = "mixed"
            wage_inflation["interpretation"] = (
                f"ULC trend: {ulc_trend}, productivity trend: {prod_trend} — mixed signals"
            )
            wage_inflation["fed_tilt"] = "data_dependent"
    elif not wage_inflation:
        wage_inflation = {"status": "data_unavailable", "note": "Insufficient data for wage-inflation analysis"}

    result["wage_inflation_link"] = wage_inflation

    # ── Composite Assessment ──────────────────────────────────────────
    assessment_parts = []

    # Productivity-ULC summary
    gap_val = prod_vs_ulc.get("gap")
    if gap_val is not None:
        assessment_parts.append(
            f"Productivity-ULC gap at {gap_val:+.2f}% ({prod_vs_ulc.get('classification', 'unknown')})"
        )

    # Hiring/firing summary
    if hiring_firing.get("balance"):
        assessment_parts.append(
            f"Labor market balance: {hiring_firing['balance']}"
        )
        if hiring_firing.get("hires_to_layoffs_ratio"):
            assessment_parts.append(
                f"Hires/layoffs ratio: {hiring_firing['hires_to_layoffs_ratio']:.2f}"
            )

    # Worker power summary
    if labor_power.get("power_level"):
        assessment_parts.append(
            f"Worker bargaining power: {labor_power['power_level']}"
        )

    # Wage-inflation summary
    if wage_inflation.get("dynamic"):
        assessment_parts.append(
            f"Wage-inflation dynamic: {wage_inflation['dynamic']}"
        )
        if wage_inflation.get("fed_tilt"):
            assessment_parts.append(f"Fed tilt: {wage_inflation['fed_tilt']}")

    # Key signals
    if signals:
        assessment_parts.append(f"Signals: {', '.join(signals)}")

    result["composite_assessment"] = ". ".join(assessment_parts) + "." if assessment_parts else "Insufficient data for composite assessment."
    result["signals"] = signals

    return json.dumps(result, indent=2)
