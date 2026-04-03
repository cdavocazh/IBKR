"""Enhanced market regime analysis tools.

Provides five advanced analysis functions that combine FRED API data,
local CSV macro data, and cross-asset signals to produce composite
financial stress scores, late-cycle detection, term premium dynamics,
energy-to-inflation passthrough estimates, and a full VIX opportunity
framework.

v2.0 additions (Twitter-derived frameworks):
- Private credit stress proxy (HY OAS + bank lending as private credit proxy)
- Bank equity vs credit stress distinction (KBE vs credit spreads)
- Labor share of income as late-cycle tell (W270RE1A156NBEA)
- Manufacturing recession decomposition (DGORDER + AWHMAN + OPHNFB + ULCNFB)

Data sources:
- tools.fred_data      — FRED API: credit spreads, yields, inflation,
                          employment, ISM, labor breadth, oil fundamentals,
                          labor share (W270RE1A156NBEA), mfg hours (AWHMAN)
- tools.fred_data internal helpers — _fetch_series_raw for NFCI, SAHMREALTIME, UMCSENT
- tools.fred_data._fetch_etf_prices — yfinance for KBE bank ETF
- /macro_2/historical_data/vix_move.csv — VIX and MOVE index history

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd

from tools import fred_data
from tools.fred_data import _fetch_series_raw, _series_summary, _check_api_key, _fetch_etf_prices, classify_hy_oas
from tools.macro_market_analysis import _load_csv, _safe_fred_call


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _score_bracket(value: float | None, brackets: list[tuple]) -> int:
    """Score a value against ordered brackets.

    Each bracket is (threshold, score).  Brackets are evaluated in order;
    the first one whose threshold is *exceeded* by value wins.  The last
    bracket acts as the default/floor.

    Example::

        _score_bracket(25, [(40, 9), (30, 7), (20, 5), (15, 3), (0, 1)])
        # returns 5  (25 >= 20)
    """
    if value is None:
        return 0
    for threshold, score in brackets:
        if value >= threshold:
            return score
    # Fallback — return the last score if nothing matched
    return brackets[-1][1] if brackets else 0


def _percentile_rank(series: pd.Series, current: float) -> float:
    """Compute percentile rank of *current* within *series*."""
    valid = series.dropna()
    if len(valid) == 0:
        return 50.0
    count_below = (valid < current).sum()
    return round(float(count_below) / len(valid) * 100, 1)


# ═══════════════════════════════════════════════════════════════════════
# 1. FINANCIAL STRESS SCORE
# ═══════════════════════════════════════════════════════════════════════

def analyze_financial_stress() -> str:
    """Compute a composite Financial Stress Score (0-10).

    Combines eight weighted components — NFCI, HY OAS, VIX, 2s10s spread,
    initial claims, Sahm Rule indicator, consumer sentiment, and consumer
    credit stress (delinquency rate) — into a single weighted score with
    stress-level classification.

    Also includes two supplemental sections (not in composite score):
    - **Private credit stress proxy**: When HY OAS is widening AND bank
      lending standards are tightening, private credit is under pressure
      (par-to-zero events become more likely).
    - **Bank equity vs credit stress**: When bank equities (KBE) are
      falling but credit spreads are stable, stress is equity-only
      (not systemic). When both deteriorate, systemic risk is rising.

    Returns:
        JSON string with as_of, composite_score, stress_level,
        components, supplemental (private_credit_proxy, bank_equity_vs_credit),
        signals, and summary.
    """
    key_err = _check_api_key()
    if key_err:
        return key_err

    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    components: dict = {}
    signals: list[str] = []

    # ── NFCI (Chicago Fed National Financial Conditions Index) ────────
    nfci_obs = _fetch_series_raw("NFCI", limit=10, sort_order="desc")
    nfci_val = nfci_obs[0]["value"] if nfci_obs and len(nfci_obs) >= 1 else None

    if nfci_val is not None:
        if nfci_val > 1.0:
            nfci_score = 9
        elif nfci_val > 0.5:
            nfci_score = 7
        elif nfci_val > 0.0:
            nfci_score = 5
        elif nfci_val > -0.5:
            nfci_score = 3
        else:
            nfci_score = 1
        interp = "tighter" if nfci_val > 0 else "looser"
        components["nfci"] = {
            "value": round(nfci_val, 3),
            "score": nfci_score,
            "weight": 0.18,
            "interpretation": f"NFCI at {nfci_val:.3f} — {interp} than average",
        }
    else:
        nfci_score = 0
        components["nfci"] = {"value": None, "score": 0, "weight": 0.18, "interpretation": "Data unavailable"}

    # ── HY OAS ────────────────────────────────────────────────────────
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    hy_val = None
    if credit_data:
        hy_val = credit_data.get("high_yield_oas", {}).get("latest_value")

    if hy_val is not None:
        # Use regime-aware classification from fred_data
        hy_stress = credit_data.get("high_yield_oas", {}).get("stress_level") if credit_data else None
        hy_score = fred_data._hy_stress_score(hy_stress) if hy_stress else 3
        hy_interp = credit_data.get("high_yield_oas", {}).get("interpretation", f"HY OAS at {round(hy_val * 100)}bps") if credit_data else f"HY OAS at {round(hy_val * 100)}bps"
        components["hy_oas"] = {
            "value": round(hy_val, 2),
            "value_bps": int(round(hy_val * 100)),
            "score": hy_score,
            "weight": 0.18,
            "interpretation": hy_interp,
            "stress_level": hy_stress or "unknown",
        }
    else:
        hy_stress = None
        hy_score = 0
        components["hy_oas"] = {"value": None, "score": 0, "weight": 0.18, "interpretation": "Data unavailable"}

    # Regime-aware stressed flag — used by private credit proxy & bank equity analysis
    hy_is_stressed = hy_stress in ("stressed", "severe_stress", "crisis", "elevated")

    # ── VIX ───────────────────────────────────────────────────────────
    vix_df = _load_csv("vix_move.csv")
    vix_val = None
    if vix_df is not None and "vix" in vix_df.columns:
        vix_df = vix_df.sort_values("date", ascending=True)
        vix_series = vix_df["vix"].dropna()
        if len(vix_series) > 0:
            vix_val = float(vix_series.iloc[-1])

    if vix_val is not None:
        if vix_val > 40:
            vix_score = 9
        elif vix_val > 30:
            vix_score = 7
        elif vix_val > 20:
            vix_score = 5
        elif vix_val > 15:
            vix_score = 3
        else:
            vix_score = 1
        components["vix"] = {
            "value": round(vix_val, 1),
            "score": vix_score,
            "weight": 0.14,
            "interpretation": f"VIX at {vix_val:.1f}",
        }
    else:
        vix_score = 0
        components["vix"] = {"value": None, "score": 0, "weight": 0.14, "interpretation": "Data unavailable"}

    # ── 2s10s Spread ──────────────────────────────────────────────────
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)
    spread_val = None
    if yield_data:
        spread_val = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("latest_value")

    if spread_val is not None:
        if spread_val < -0.5:
            spread_score = 9
        elif spread_val < 0:
            spread_score = 7
        elif spread_val < 0.5:
            spread_score = 4
        elif spread_val < 1.0:
            spread_score = 2
        else:
            spread_score = 1
        status = "inverted" if spread_val < 0 else "normal"
        components["yield_curve_2s10s"] = {
            "value": round(spread_val, 2),
            "score": spread_score,
            "weight": 0.14,
            "interpretation": f"2s10s at {spread_val:.2f}% — {status}",
        }
    else:
        spread_score = 0
        components["yield_curve_2s10s"] = {
            "value": None, "score": 0, "weight": 0.14, "interpretation": "Data unavailable",
        }

    # ── Initial Claims ────────────────────────────────────────────────
    employment_data = _safe_fred_call(fred_data.get_employment_data)
    claims_val = None
    if employment_data:
        claims_val = employment_data.get("initial_claims", {}).get("latest_value")

    if claims_val is not None:
        # Normalize to thousands if raw value (FRED ICSA is in "Number" units)
        claims_k = claims_val / 1000 if claims_val > 1000 else claims_val
        if claims_k > 400:
            claims_score = 9
        elif claims_k > 300:
            claims_score = 7
        elif claims_k > 260:
            claims_score = 5
        elif claims_k > 220:
            claims_score = 3
        else:
            claims_score = 1
        components["initial_claims"] = {
            "value": round(claims_k, 0),
            "score": claims_score,
            "weight": 0.10,
            "interpretation": f"Initial claims at {claims_k:.0f}K",
        }
    else:
        claims_score = 0
        components["initial_claims"] = {
            "value": None, "score": 0, "weight": 0.10, "interpretation": "Data unavailable",
        }

    # ── Sahm Rule Recession Indicator ─────────────────────────────────
    sahm_obs = _fetch_series_raw("SAHMREALTIME", limit=10, sort_order="desc")
    sahm_val = sahm_obs[0]["value"] if sahm_obs and len(sahm_obs) >= 1 else None

    if sahm_val is not None:
        if sahm_val > 0.8:
            sahm_score = 10
        elif sahm_val > 0.5:
            sahm_score = 8
        elif sahm_val > 0.3:
            sahm_score = 5
        elif sahm_val > 0.2:
            sahm_score = 3
        else:
            sahm_score = 1
        if sahm_val > 0.5:
            signals.append("SAHM_RULE_TRIGGERED")
        components["sahm_rule"] = {
            "value": round(sahm_val, 2),
            "score": sahm_score,
            "weight": 0.10,
            "interpretation": f"Sahm Rule at {sahm_val:.2f}" + (" — RECESSION SIGNAL" if sahm_val > 0.5 else ""),
        }
    else:
        sahm_score = 0
        components["sahm_rule"] = {
            "value": None, "score": 0, "weight": 0.10, "interpretation": "Data unavailable",
        }

    # ── Consumer Sentiment ────────────────────────────────────────────
    umcsent_obs = _fetch_series_raw("UMCSENT", limit=10, sort_order="desc")
    umcsent_val = umcsent_obs[0]["value"] if umcsent_obs and len(umcsent_obs) >= 1 else None

    if umcsent_val is not None:
        if umcsent_val < 50:
            sent_score = 9
        elif umcsent_val < 60:
            sent_score = 7
        elif umcsent_val < 70:
            sent_score = 5
        elif umcsent_val < 80:
            sent_score = 3
        else:
            sent_score = 1
        components["consumer_sentiment"] = {
            "value": round(umcsent_val, 1),
            "score": sent_score,
            "weight": 0.08,
            "interpretation": f"U of Michigan Sentiment at {umcsent_val:.1f}",
        }
    else:
        sent_score = 0
        components["consumer_sentiment"] = {
            "value": None, "score": 0, "weight": 0.08, "interpretation": "Data unavailable",
        }

    # ── Consumer Credit Stress ─────────────────────────────────────
    consumer_data = _safe_fred_call(fred_data.get_consumer_health_data)
    consumer_credit_val = None
    if consumer_data:
        consumer_credit_val = consumer_data.get("delinquency_rate", {}).get("latest_value")

    if consumer_credit_val is not None:
        if consumer_credit_val > 4.0:
            cc_score = 9
        elif consumer_credit_val > 3.5:
            cc_score = 7
        elif consumer_credit_val > 3.0:
            cc_score = 5
        elif consumer_credit_val > 2.5:
            cc_score = 3
        else:
            cc_score = 1
        components["consumer_credit"] = {
            "value": round(consumer_credit_val, 2),
            "score": cc_score,
            "weight": 0.08,
            "interpretation": f"All-loan delinquency rate at {consumer_credit_val:.2f}%",
        }
        if consumer_credit_val > 3.5:
            signals.append("CONSUMER_CREDIT_STRESS")
    else:
        cc_score = 0
        components["consumer_credit"] = {
            "value": None, "score": 0, "weight": 0.08, "interpretation": "Data unavailable",
        }

    # ── Composite Score ───────────────────────────────────────────────
    weighted_scores = [
        (nfci_score, 0.18),
        (hy_score, 0.18),
        (vix_score, 0.14),
        (spread_score, 0.14),
        (claims_score, 0.10),
        (sahm_score, 0.10),
        (sent_score, 0.08),
        (cc_score, 0.08),
    ]

    total_weight = sum(w for s, w in weighted_scores if s > 0)
    if total_weight > 0:
        composite = sum(s * w for s, w in weighted_scores if s > 0) / total_weight
    else:
        composite = 0.0
    composite = round(composite, 2)

    # Breadth floor: when stress is broad-based (≥3 components scoring ≥5),
    # the composite should be at least "elevated" (4.0).  A 3.9 average from
    # many mildly-stressed components is more concerning than a single stressed
    # component diluted by calm ones — broad stress warrants the "elevated" tag.
    elevated_components = sum(1 for s, _ in weighted_scores if s >= 5)
    if elevated_components >= 3 and composite < 4.0:
        composite = 4.0

    # Classify stress level
    if composite >= 8:
        stress_level = "extreme"
    elif composite >= 6:
        stress_level = "high"
    elif composite >= 4:
        stress_level = "elevated"
    elif composite >= 2:
        stress_level = "moderate"
    else:
        stress_level = "low"

    # Build signal
    stress_signal = f"STRESS_{stress_level.upper()}"
    signals.insert(0, stress_signal)

    result["composite_score"] = composite
    result["weighted_average"] = round(
        sum(s * w for s, w in weighted_scores if s > 0) / total_weight, 2
    ) if total_weight > 0 else 0.0
    result["breadth_floor_applied"] = (elevated_components >= 3 and result["weighted_average"] < 4.0)
    if result["breadth_floor_applied"]:
        result["breadth_floor_note"] = (
            f"Weighted average was {result['weighted_average']} but {elevated_components} of 8 "
            f"components score >= 5. Broad-based stress floored composite to 4.0 (elevated)."
        )
    result["stress_level"] = stress_level
    result["scoring_method"] = (
        "Weighted average of 8 components (0-10 each). "
        "Breadth floor: if >= 3 components score >= 5, composite floors at 4.0 (elevated). "
        "Levels: extreme(>=8), high(>=6), elevated(>=4), moderate(>=2), low(<2)."
    )
    result["components"] = components

    # ── Supplemental: Private Credit Stress Proxy ──────────────────────
    # When HY OAS is widening AND banks are tightening, private credit is
    # under pressure (par-to-zero events become more likely).
    supplemental: dict = {}
    private_credit: dict = {}

    hy_direction = None
    if credit_data:
        hy_direction = credit_data.get("high_yield_oas", {}).get("spread_direction")

    bank_lending_val = None
    if consumer_data:
        bank_lending_val = consumer_data.get("bank_lending_standards", {}).get("latest_value")

    if hy_val is not None and bank_lending_val is not None:
        hy_wide = hy_direction == "widening" or hy_is_stressed
        bank_tight = bank_lending_val > 10

        if hy_wide and bank_tight:
            private_credit["stress_level"] = "elevated"
            private_credit["interpretation"] = (
                f"HY OAS {hy_direction or 'elevated'} at {round(hy_val * 100)}bps AND "
                f"net {bank_lending_val:.0f}% of banks tightening — private credit under "
                "pressure. Par-to-zero markdowns likely spreading across business models "
                "that only worked when money was cheap."
            )
            signals.append("PRIVATE_CREDIT_STRESS")
        elif hy_wide:
            private_credit["stress_level"] = "watch"
            private_credit["interpretation"] = (
                f"HY OAS elevated/widening at {round(hy_val * 100)}bps but bank lending "
                "not yet tightening sharply. Monitor for confirmation."
            )
        elif bank_tight:
            private_credit["stress_level"] = "watch"
            private_credit["interpretation"] = (
                f"Banks tightening (net {bank_lending_val:.0f}%) but HY OAS not yet "
                "widening. Credit pipeline contracting but market hasn't repriced yet."
            )
        else:
            private_credit["stress_level"] = "low"
            private_credit["interpretation"] = (
                "HY OAS contained and bank lending not restrictive — "
                "private credit environment benign."
            )
        private_credit["hy_oas_bps"] = round(hy_val * 100) if hy_val else None
        private_credit["hy_direction"] = hy_direction
        private_credit["hy_regime_classification"] = hy_stress or "unknown"
        private_credit["bank_tightening_net_pct"] = round(bank_lending_val, 1) if bank_lending_val else None
    else:
        private_credit["stress_level"] = "unknown"
        private_credit["interpretation"] = "Insufficient data for private credit proxy"

    supplemental["private_credit_proxy"] = private_credit

    # ── Supplemental: Bank Equity vs Credit Stress ─────────────────────
    # When bank equities (KBE) fall but credit spreads are stable →
    # equity-only issue, not systemic.  When both deteriorate → systemic.
    bank_eq_credit: dict = {}
    kbe_data = _fetch_etf_prices("KBE")

    if kbe_data and hy_val is not None:
        kbe_1w = kbe_data.get("pct_change_1w")
        kbe_1m = kbe_data.get("pct_change_1m")
        kbe_falling = (kbe_1w is not None and kbe_1w < -2) or (kbe_1m is not None and kbe_1m < -5)
        credit_stressed = hy_is_stressed or hy_direction == "widening"

        bank_eq_credit["kbe_latest"] = kbe_data.get("latest_price")
        bank_eq_credit["kbe_1w_pct"] = kbe_1w
        bank_eq_credit["kbe_1m_pct"] = kbe_1m
        bank_eq_credit["hy_oas_bps"] = round(hy_val * 100) if hy_val else None
        bank_eq_credit["hy_regime_classification"] = hy_stress or "unknown"

        if kbe_falling and credit_stressed:
            bank_eq_credit["diagnosis"] = "systemic_risk"
            bank_eq_credit["interpretation"] = (
                f"Bank equities falling (KBE {kbe_1w:+.1f}% 1W) AND credit spreads "
                f"stressed ({round(hy_val * 100)}bps HY OAS) — SYSTEMIC risk. "
                "Both equity and credit markets pricing bank deterioration."
            )
            signals.append("BANK_SYSTEMIC_STRESS")
        elif kbe_falling and not credit_stressed:
            bank_eq_credit["diagnosis"] = "equity_only"
            bank_eq_credit["interpretation"] = (
                f"Bank equities falling (KBE {kbe_1w:+.1f}% 1W) but credit spreads "
                f"contained ({round(hy_val * 100)}bps HY OAS) — equity issue, not "
                "systemic. Market views bank stress as earnings/valuation problem, "
                "not solvency threat."
            )
            signals.append("BANK_EQUITY_ONLY_STRESS")
        elif not kbe_falling and credit_stressed:
            bank_eq_credit["diagnosis"] = "credit_warning"
            bank_eq_credit["interpretation"] = (
                "Credit spreads widening but bank equities holding — credit market "
                "may be leading. Watch for equity confirmation."
            )
        else:
            bank_eq_credit["diagnosis"] = "no_stress"
            bank_eq_credit["interpretation"] = (
                "Bank equities and credit spreads both stable — no bank stress signal."
            )
    else:
        bank_eq_credit["diagnosis"] = "data_unavailable"
        bank_eq_credit["interpretation"] = (
            "KBE ETF data unavailable (requires yfinance). "
            "Install with: pip install yfinance"
        )

    supplemental["bank_equity_vs_credit"] = bank_eq_credit
    result["supplemental"] = supplemental

    result["signals"] = signals

    # Summary
    active_components = [k for k, v in components.items() if v.get("value") is not None]
    supp_notes = []
    if private_credit.get("stress_level") == "elevated":
        supp_notes.append("private credit stress elevated")
    if bank_eq_credit.get("diagnosis") == "systemic_risk":
        supp_notes.append("bank systemic risk detected")
    elif bank_eq_credit.get("diagnosis") == "equity_only":
        supp_notes.append("bank stress is equity-only (not systemic)")

    result["summary"] = (
        f"Financial Stress Score: {composite}/10 ({stress_level}). "
        f"Based on {len(active_components)}/8 available components. "
        + (f"Key concerns: Sahm Rule triggered at {sahm_val:.2f}. " if "SAHM_RULE_TRIGGERED" in signals else "")
        + (f"Supplemental: {'; '.join(supp_notes)}. " if supp_notes else "")
        + f"Signals: {', '.join(signals)}."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 2. LATE-CYCLE SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════

def detect_late_cycle_signals() -> str:
    """Detect late-cycle economic signals using a 13-indicator framework.

    Original 11 signals plus two Twitter-derived additions:
    12. Labor share near record lows — profit margins peaked, wage
        pressure building (W270RE1A156NBEA).
    13. Manufacturing recession — when durable goods output falls but
        hours are flat/rising, it signals labor hoarding and margin
        compression (DGORDER + AWHMAN + OPHNFB + ULCNFB).

    Returns:
        JSON string with as_of, signals_firing, count, total,
        confidence_level, interpretation, and assessment.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals_firing: list[dict] = []

    # ── 1. ISM Manufacturing contraction (<50) ────────────────────────
    ism_data = _safe_fred_call(fred_data.get_ism_decomposition)
    headline_pmi = ism_data.get("headline_pmi") if ism_data else None

    if headline_pmi is not None:
        firing = headline_pmi < 50
        signals_firing.append({
            "name": "ISM Manufacturing contraction",
            "status": "firing" if firing else "not_firing",
            "evidence": f"Headline PMI at {headline_pmi:.1f}" + (" — below 50 contraction threshold" if firing else ""),
        })
    else:
        signals_firing.append({
            "name": "ISM Manufacturing contraction",
            "status": "data_unavailable",
            "evidence": "ISM data not available",
        })

    # ── 2. ISM New Orders declining ───────────────────────────────────
    ism_signals = ism_data.get("signals", []) if ism_data else []
    no_declining = "ISM_NEW_ORDERS_DECLINING" in ism_signals
    signals_firing.append({
        "name": "ISM New Orders declining",
        "status": "firing" if no_declining else "not_firing",
        "evidence": "New orders trend declining" if no_declining else "New orders stable or rising",
    })

    # ── 3. NFP deceleration ───────────────────────────────────────────
    labor_data = _safe_fred_call(fred_data.get_labor_breadth_data)
    labor_signals = labor_data.get("signals", []) if labor_data else []
    nfp_decel = "NFP_TREND_DECELERATING" in labor_signals

    nfp_evidence = "NFP trend stable or accelerating"
    if labor_data and "nfp_trend" in labor_data:
        nfp_info = labor_data["nfp_trend"]
        three_m = nfp_info.get("three_month_avg_thousands")
        prior_m = nfp_info.get("prior_three_month_avg_thousands")
        if three_m is not None and prior_m is not None:
            nfp_evidence = f"3M avg {three_m}K vs prior 3M avg {prior_m}K" + (" — decelerating" if nfp_decel else "")

    signals_firing.append({
        "name": "NFP deceleration",
        "status": "firing" if nfp_decel else "not_firing",
        "evidence": nfp_evidence,
    })

    # ── 4. Rising continuing claims ───────────────────────────────────
    cc_rising = "CONTINUING_CLAIMS_RISING" in labor_signals
    cc_evidence = "Continuing claims stable or improving"
    if labor_data and "continuing_claims" in labor_data:
        cc_info = labor_data["continuing_claims"]
        momentum = cc_info.get("momentum_pct")
        if momentum is not None:
            cc_evidence = f"Continuing claims momentum {momentum:.1f}%" + (" — rising" if cc_rising else "")

    signals_firing.append({
        "name": "Rising continuing claims",
        "status": "firing" if cc_rising else "not_firing",
        "evidence": cc_evidence,
    })

    # ── 5. Credit spreads widening ────────────────────────────────────
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
    hy_widening = False
    credit_evidence = "Credit spread data unavailable"
    if credit_data:
        hy_direction = credit_data.get("high_yield_oas", {}).get("spread_direction")
        hy_widening = hy_direction == "widening"
        hy_val = credit_data.get("high_yield_oas", {}).get("latest_value")
        if hy_val is not None:
            credit_evidence = f"HY OAS at {round(hy_val * 100)}bps, direction: {hy_direction or 'unknown'}"

    signals_firing.append({
        "name": "Credit spreads widening",
        "status": "firing" if hy_widening else "not_firing",
        "evidence": credit_evidence,
    })

    # ── 6. Term premium rising ────────────────────────────────────────
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)

    tp_rising = False
    tp_evidence = "Term premium data unavailable"

    nominal_10y = None
    real_10y = None
    breakeven_10y = None

    if yield_data:
        nominal_10y = yield_data.get("nominal_yields", {}).get("10y", {}).get("latest_value")
        real_10y = yield_data.get("real_yields", {}).get("10y_real", {}).get("latest_value")
    if inflation_data:
        breakeven_10y = inflation_data.get("breakevens", {}).get("t10yie", {}).get("latest_value")

    if nominal_10y is not None and real_10y is not None and breakeven_10y is not None:
        term_premium = round(nominal_10y - real_10y - breakeven_10y, 3)
        # Check if 10y nominal trend is rising (proxy for term premium rising)
        nom_10y_trend = yield_data.get("nominal_yields", {}).get("10y", {}).get("trend")
        real_10y_trend = yield_data.get("real_yields", {}).get("10y_real", {}).get("trend")
        tp_rising = nom_10y_trend == "rising" and real_10y_trend != "rising"
        tp_evidence = f"Term premium proxy: {term_premium:.3f}% (10Y nom {nominal_10y}% - real {real_10y}% - BE {breakeven_10y}%)"
        if tp_rising:
            tp_evidence += " — rising"

    signals_firing.append({
        "name": "Term premium rising",
        "status": "firing" if tp_rising else "not_firing",
        "evidence": tp_evidence,
    })

    # ── 7. JOLTS quits declining ──────────────────────────────────────
    quits_declining = "QUITS_RATE_DECLINING" in labor_signals
    quits_evidence = "Quits rate stable or rising"
    if labor_data and "quits_rate" in labor_data:
        qr = labor_data["quits_rate"]
        qr_val = qr.get("latest_value")
        qr_trend = qr.get("trend")
        if qr_val is not None:
            quits_evidence = f"Quits rate at {qr_val}%, trend: {qr_trend or 'unknown'}"

    signals_firing.append({
        "name": "JOLTS quits declining",
        "status": "firing" if quits_declining else "not_firing",
        "evidence": quits_evidence,
    })

    # ── 8. Yield curve inversion ──────────────────────────────────────
    curve_inverted = False
    curve_evidence = "Yield curve data unavailable"
    if yield_data:
        curve_status = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("curve_status")
        curve_inverted = curve_status == "inverted"
        spread_val = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("latest_value")
        if spread_val is not None:
            curve_evidence = f"2s10s spread at {spread_val:.2f}% — {curve_status or 'unknown'}"

    signals_firing.append({
        "name": "Yield curve inversion",
        "status": "firing" if curve_inverted else "not_firing",
        "evidence": curve_evidence,
    })

    # ── 9. Housing permits declining ───────────────────────────────────
    housing_data = _safe_fred_call(fred_data.get_housing_data)
    permits_declining = False
    permits_evidence = "Housing permit data unavailable"
    if housing_data:
        permits_trend = housing_data.get("permits", {}).get("trend")
        permits_val = housing_data.get("permits", {}).get("latest_value")
        permits_declining = permits_trend == "falling"
        if permits_val is not None:
            permits_evidence = (
                f"Building permits at {permits_val:.0f}K SAAR, trend: {permits_trend or 'unknown'}"
                + (" — declining (housing leading indicator)" if permits_declining else "")
            )
    signals_firing.append({"name": "Housing permits declining", "status": "firing" if permits_declining else "not_firing", "evidence": permits_evidence})

    # ── 10. Delinquencies rising ───────────────────────────────────────
    consumer_data = _safe_fred_call(fred_data.get_consumer_health_data)
    delinq_rising = False
    delinq_evidence = "Delinquency data unavailable"
    if consumer_data:
        delinq_section = consumer_data.get("delinquency_rate", {})
        delinq_val = delinq_section.get("latest_value")
        delinq_trend = delinq_section.get("trend")
        if delinq_val is not None:
            delinq_rising = delinq_trend == "rising" and delinq_val > 2.5
            delinq_evidence = (
                f"Delinquency rate at {delinq_val:.2f}%, trend: {delinq_trend or 'unknown'}"
                + (" — rising above 2.5% threshold" if delinq_rising else "")
            )
    signals_firing.append({"name": "Delinquencies rising", "status": "firing" if delinq_rising else "not_firing", "evidence": delinq_evidence})

    # ── 11. Bank lending tightening ────────────────────────────────────
    bank_tightening = False
    bank_evidence = "Bank lending standards data unavailable"
    if consumer_data:
        bank_section = consumer_data.get("bank_lending_standards", {})
        bank_val = bank_section.get("latest_value")
        if bank_val is not None:
            bank_tightening = bank_val > 10
            bank_evidence = (
                f"Net {bank_val:.1f}% of banks tightening lending standards"
                + (" — credit access contracting" if bank_tightening else "")
            )
    signals_firing.append({"name": "Bank lending tightening", "status": "firing" if bank_tightening else "not_firing", "evidence": bank_evidence})

    # ── 12. Labor share near record lows ────────────────────────────────
    labor_share_data = _safe_fred_call(fred_data.get_labor_share_data)
    ls_firing = False
    ls_evidence = "Labor share data unavailable"
    if labor_share_data:
        ls_val = labor_share_data.get("latest_value")
        ls_pctile = labor_share_data.get("percentile_rank")
        ls_signals = labor_share_data.get("signals", [])
        if ls_val is not None:
            # Fires when labor share is in bottom 15th percentile (near record lows)
            ls_firing = (ls_pctile is not None and ls_pctile < 15) or "LABOR_SHARE_NEAR_RECORD_LOW" in ls_signals
            ls_evidence = (
                f"Labor share at {ls_val:.1f}%"
                + (f", {ls_pctile:.0f}th percentile" if ls_pctile is not None else "")
                + (" — near historical lows, late-cycle tell" if ls_firing else "")
            )
    signals_firing.append({"name": "Labor share near record lows", "status": "firing" if ls_firing else "not_firing", "evidence": ls_evidence})

    # ── 13. Manufacturing recession (labor hoarding) ────────────────────
    mfg_hours_data = _safe_fred_call(fred_data.get_manufacturing_hours_data)
    productivity_data = _safe_fred_call(fred_data.get_productivity_data)

    mfg_recession = False
    mfg_evidence = "Manufacturing decomposition data unavailable"

    # Check durable goods from ISM data (DGORDER trend)
    dgorder_trend = None
    if ism_data:
        dgorder_trend = ism_data.get("new_orders_proxy", {}).get("trend")

    # Check manufacturing hours
    mfg_hours_trend = None
    mfg_hours_val = None
    if mfg_hours_data:
        mfg_hours_trend = mfg_hours_data.get("trend")
        mfg_hours_val = mfg_hours_data.get("latest_value")

    # Check productivity vs ULC
    prod_gap = None
    if productivity_data:
        prod_gap = productivity_data.get("productivity_ulc_gap", {}).get("gap")

    # Manufacturing recession: output (DGORDER) falling while hours flat/rising
    # AND ULC outpacing productivity = labor hoarding + margin compression
    if dgorder_trend == "falling" and mfg_hours_trend in ("stable", "rising"):
        mfg_recession = True
        mfg_evidence = (
            f"Durable goods orders declining, mfg hours {mfg_hours_trend} at {mfg_hours_val:.1f}h"
            + (f", productivity-ULC gap {prod_gap:+.1f}%" if prod_gap is not None else "")
            + " — labor hoarding and margin compression"
        )
    elif dgorder_trend == "falling":
        mfg_evidence = (
            f"Durable goods orders declining, mfg hours {mfg_hours_trend or 'unknown'}"
            + (f" at {mfg_hours_val:.1f}h" if mfg_hours_val else "")
            + " — output weakening but not classic labor hoarding pattern"
        )
    elif mfg_hours_val is not None:
        mfg_evidence = (
            f"Durable goods orders {dgorder_trend or 'unknown'}, mfg hours {mfg_hours_val:.1f}h"
            + " — no manufacturing recession signal"
        )
    # Also fire if hours below 40 (recessionary territory) regardless
    if mfg_hours_data and "MFG_HOURS_BELOW_40" in mfg_hours_data.get("signals", []):
        mfg_recession = True
        mfg_evidence = (
            f"Manufacturing hours at {mfg_hours_val:.1f}h — below 40-hour recessionary threshold"
        )

    signals_firing.append({"name": "Manufacturing recession (labor hoarding)", "status": "firing" if mfg_recession else "not_firing", "evidence": mfg_evidence})

    # ── Confidence assessment ─────────────────────────────────────────
    count = sum(1 for s in signals_firing if s["status"] == "firing")
    total = len(signals_firing)

    if count >= 10:
        confidence_level = "pre-recessionary"
        interpretation = f"{count}/{total} signals firing — economy likely entering or in recession"
    elif count >= 8:
        confidence_level = "late cycle confirmed"
        interpretation = f"{count}/{total} signals firing — late-cycle dynamics dominant, defensive positioning warranted"
    elif count >= 6:
        confidence_level = "transitioning"
        interpretation = f"{count}/{total} signals firing — economy transitioning from mid to late cycle"
    elif count >= 3:
        confidence_level = "early warning"
        interpretation = f"{count}/{total} signals firing — early warning signs of late-cycle dynamics emerging"
    else:
        confidence_level = "early/mid cycle"
        interpretation = f"{count}/{total} signals firing — early or mid-cycle dynamics, no late-cycle concern"

    result["signals_firing"] = signals_firing
    result["count"] = count
    result["total"] = total
    result["confidence_level"] = confidence_level
    result["interpretation"] = interpretation
    result["assessment"] = (
        f"{count}/{total} late-cycle signals firing. "
        f"Confidence: {confidence_level}. {interpretation}."
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 3. TERM PREMIUM DYNAMICS
# ═══════════════════════════════════════════════════════════════════════

def analyze_term_premium_dynamics() -> str:
    """Deep analysis of the term premium in the 10-Year Treasury.

    Computes a term premium proxy (10Y nominal - 10Y real - 10Y breakeven)
    and layers in credit spread and breakeven trend context to identify
    global discount rate adjustments and flight-to-safety dynamics.

    Returns:
        JSON string with as_of, term_premium, breakeven_context,
        credit_context, signals, and assessment.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Fetch data ────────────────────────────────────────────────────
    yield_data = _safe_fred_call(fred_data.get_yield_curve_data)
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)
    credit_data = _safe_fred_call(fred_data.get_credit_spread_data)

    # ── Term premium proxy ────────────────────────────────────────────
    nominal_10y = None
    real_10y = None
    breakeven_10y = None
    nom_10y_trend = None
    real_10y_trend = None

    if yield_data:
        nom_section = yield_data.get("nominal_yields", {}).get("10y", {})
        nominal_10y = nom_section.get("latest_value")
        nom_10y_trend = nom_section.get("trend")

        real_section = yield_data.get("real_yields", {}).get("10y_real", {})
        real_10y = real_section.get("latest_value")
        real_10y_trend = real_section.get("trend")

    if inflation_data:
        be_section = inflation_data.get("breakevens", {}).get("t10yie", {})
        breakeven_10y = be_section.get("latest_value")

    term_premium_section: dict = {}

    if nominal_10y is not None and real_10y is not None and breakeven_10y is not None:
        tp_value = round(nominal_10y - real_10y - breakeven_10y, 3)
        term_premium_section = {
            "value": tp_value,
            "components": {
                "nominal_10y": round(nominal_10y, 3),
                "real_10y_tips": round(real_10y, 3),
                "breakeven_10y": round(breakeven_10y, 3),
            },
        }

        # Interpretation
        if tp_value > 0.5:
            term_premium_section["interpretation"] = (
                f"Term premium elevated at {tp_value:.3f}% — investors demanding extra compensation "
                "for duration risk, fiscal concerns, or supply uncertainty"
            )
        elif tp_value > 0:
            term_premium_section["interpretation"] = (
                f"Term premium modestly positive at {tp_value:.3f}% — normal compensation for duration"
            )
        elif tp_value > -0.5:
            term_premium_section["interpretation"] = (
                f"Term premium slightly negative at {tp_value:.3f}% — some flight-to-safety premium"
            )
        else:
            term_premium_section["interpretation"] = (
                f"Term premium deeply negative at {tp_value:.3f}% — strong flight-to-safety / "
                "foreign demand compressing long-end"
            )
            signals.append("FLIGHT_TO_SAFETY")

        if tp_value < 0:
            signals.append("TERM_PREMIUM_NEGATIVE")
        elif tp_value > 0.5:
            signals.append("TERM_PREMIUM_ELEVATED")

    else:
        term_premium_section = {"value": None, "interpretation": "Insufficient data to compute term premium proxy"}

    result["term_premium"] = term_premium_section

    # ── Breakeven context ─────────────────────────────────────────────
    breakeven_context: dict = {}
    if inflation_data and "breakevens" in inflation_data:
        be = inflation_data["breakevens"]
        t5yie_info = be.get("t5yie", {})
        t10yie_info = be.get("t10yie", {})
        breakeven_context = {
            "breakeven_5y": t5yie_info.get("latest_value"),
            "breakeven_5y_trend": t5yie_info.get("trend"),
            "breakeven_10y": t10yie_info.get("latest_value"),
            "breakeven_10y_trend": t10yie_info.get("trend"),
        }

        be_10y_trend = t10yie_info.get("trend")
        tp_value = term_premium_section.get("value")

        if tp_value is not None and tp_value > 0 and be_10y_trend == "rising":
            signals.append("GLOBAL_DISCOUNT_RATE_ADJUSTMENT")
            breakeven_context["interpretation"] = (
                "Positive term premium with rising breakevens — "
                "global discount rate adjusting higher, headwind for long-duration assets"
            )
        elif be_10y_trend == "falling":
            breakeven_context["interpretation"] = "Falling breakevens — disinflation expectations"
        else:
            breakeven_context["interpretation"] = "Breakevens stable"

    result["breakeven_context"] = breakeven_context if breakeven_context else {"status": "data_unavailable"}

    # ── Credit context ────────────────────────────────────────────────
    credit_context: dict = {}
    if credit_data:
        hy_info = credit_data.get("high_yield_oas", {})
        credit_context = {
            "hy_oas": hy_info.get("latest_value"),
            "hy_spread_direction": hy_info.get("spread_direction"),
            "hy_stress_level": hy_info.get("stress_level"),
        }
        if hy_info.get("spread_direction") == "widening":
            credit_context["interpretation"] = "Credit spreads widening — risk sentiment deteriorating"
        elif hy_info.get("spread_direction") == "tightening":
            credit_context["interpretation"] = "Credit spreads tightening — risk appetite intact"
        else:
            credit_context["interpretation"] = "Credit spreads stable"

    result["credit_context"] = credit_context if credit_context else {"status": "data_unavailable"}
    result["signals"] = signals

    # ── Assessment ────────────────────────────────────────────────────
    parts = []
    tp_val = term_premium_section.get("value")
    if tp_val is not None:
        parts.append(f"Term premium proxy at {tp_val:.3f}%")
    if breakeven_context.get("breakeven_10y"):
        parts.append(f"10Y breakeven at {breakeven_context['breakeven_10y']}%")
    if credit_context.get("hy_oas"):
        parts.append(f"HY OAS at {credit_context['hy_oas']}%")
    if signals:
        parts.append(f"Signals: {', '.join(signals)}")
    result["assessment"] = ". ".join(parts) + "." if parts else "Insufficient data for assessment."

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 4. ENERGY-INFLATION PASSTHROUGH
# ═══════════════════════════════════════════════════════════════════════

def analyze_energy_inflation_passthrough() -> str:
    """Estimate the passthrough from energy prices to CPI.

    Computes the direct CPI impact from gasoline price changes (2.91%
    energy CPI weight), applies the BofA model ($10/bbl WTI rise ->
    +0.1% inflation / -0.1% GDP), and compares to market breakeven
    pricing.

    Returns:
        JSON string with as_of, gasoline, crude_oil, bofa_model,
        market_pricing, signals, and assessment.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Fetch data ────────────────────────────────────────────────────
    oil_data = _safe_fred_call(fred_data.get_oil_fundamentals)
    inflation_data = _safe_fred_call(fred_data.get_inflation_data)

    # ── Gasoline section ──────────────────────────────────────────────
    gasoline_section: dict = {}
    gas_price = None
    gas_mom_change_pct = None

    if oil_data and "gasoline_price" in oil_data:
        gp = oil_data["gasoline_price"]
        gas_price = gp.get("latest_price_per_gallon")

    # For MoM change we need the raw FRED series
    gas_obs = _fetch_series_raw("GASREGW", limit=10, sort_order="desc")
    if gas_obs and len(gas_obs) >= 5:
        gas_price = gas_price or gas_obs[0]["value"]
        # Compare latest to ~4 weeks ago for MoM proxy
        prior_gas = gas_obs[4]["value"]
        if prior_gas and prior_gas != 0:
            gas_mom_change_pct = round((gas_obs[0]["value"] - prior_gas) / prior_gas * 100, 2)

    if gas_price is not None:
        # Direct CPI impact: gas MoM change * energy CPI weight (2.91%)
        cpi_impact = None
        if gas_mom_change_pct is not None:
            cpi_impact = round(gas_mom_change_pct * 0.0291, 4)

        gasoline_section = {
            "price_per_gallon": round(gas_price, 3),
            "mom_change_pct": gas_mom_change_pct,
            "cpi_impact_pct": cpi_impact,
            "energy_cpi_weight": 0.0291,
        }
        if cpi_impact is not None:
            gasoline_section["interpretation"] = (
                f"Gasoline at ${gas_price:.2f}/gal, MoM {gas_mom_change_pct:+.2f}% — "
                f"direct CPI impact: {cpi_impact:+.4f}%"
            )
    else:
        gasoline_section = {"status": "data_unavailable"}

    result["gasoline"] = gasoline_section

    # ── Crude oil section ─────────────────────────────────────────────
    crude_section: dict = {}
    wti_price = None
    wti_wow_change = None

    if oil_data and "wti" in oil_data:
        wti_info = oil_data["wti"]
        wti_price = wti_info.get("latest_price")
        wti_wow_change = wti_info.get("wow_change")
        crude_section = {
            "price": wti_price,
            "wow_change": wti_wow_change,
            "wow_change_pct": wti_info.get("wow_change_pct"),
        }
        if wti_price is not None:
            crude_section["context"] = f"WTI at ${wti_price:.2f}/bbl"
    else:
        crude_section = {"status": "data_unavailable"}

    result["crude_oil"] = crude_section

    # ── BofA model ────────────────────────────────────────────────────
    bofa_section: dict = {}
    if wti_price is not None and wti_wow_change is not None:
        # BofA rule of thumb: $10/bbl rise -> +0.1% inflation, -0.1% GDP
        # Scale by actual WoW change
        implied_inflation_impact = round(wti_wow_change / 10.0 * 0.1, 4)
        implied_gdp_impact = round(wti_wow_change / 10.0 * -0.1, 4)
        bofa_section = {
            "oil_wow_change_dollars": round(wti_wow_change, 2),
            "implied_inflation_impact_pct": implied_inflation_impact,
            "implied_gdp_impact_pct": implied_gdp_impact,
            "model_note": "BofA rule: $10/bbl WTI rise -> +0.1% inflation, -0.1% GDP",
        }
        if abs(implied_inflation_impact) > 0.05:
            if implied_inflation_impact > 0:
                signals.append("ENERGY_INFLATION_UPSIDE")
            else:
                signals.append("ENERGY_INFLATION_DOWNSIDE")
    else:
        bofa_section = {"status": "data_unavailable"}

    result["bofa_model"] = bofa_section

    # ── Market pricing (breakevens) ───────────────────────────────────
    market_pricing: dict = {}
    if inflation_data and "breakevens" in inflation_data:
        be = inflation_data["breakevens"]
        t5yie = be.get("t5yie", {})
        t10yie = be.get("t10yie", {})
        market_pricing = {
            "breakeven_5y": t5yie.get("latest_value"),
            "breakeven_5y_trend": t5yie.get("trend"),
            "breakeven_10y": t10yie.get("latest_value"),
            "breakeven_10y_trend": t10yie.get("trend"),
        }

        # Compare energy-implied inflation impact to breakeven moves
        be_5y_val = t5yie.get("latest_value")
        if be_5y_val is not None:
            if be_5y_val > 2.5:
                market_pricing["interpretation"] = (
                    f"5Y breakeven at {be_5y_val}% — market pricing above-target inflation"
                )
                signals.append("BREAKEVEN_ABOVE_TARGET")
            elif be_5y_val < 2.0:
                market_pricing["interpretation"] = (
                    f"5Y breakeven at {be_5y_val}% — market pricing below-target inflation"
                )
                signals.append("BREAKEVEN_BELOW_TARGET")
            else:
                market_pricing["interpretation"] = (
                    f"5Y breakeven at {be_5y_val}% — well-anchored near target"
                )
    else:
        market_pricing = {"status": "data_unavailable"}

    result["market_pricing"] = market_pricing
    result["signals"] = signals

    # ── Assessment ────────────────────────────────────────────────────
    parts = []
    if gasoline_section.get("price_per_gallon"):
        parts.append(f"Gasoline at ${gasoline_section['price_per_gallon']:.2f}/gal")
    if gasoline_section.get("cpi_impact_pct") is not None:
        parts.append(f"Direct CPI impact: {gasoline_section['cpi_impact_pct']:+.4f}%")
    if bofa_section.get("implied_inflation_impact_pct") is not None:
        parts.append(f"BofA model inflation impact: {bofa_section['implied_inflation_impact_pct']:+.4f}%")
    if market_pricing.get("breakeven_5y"):
        parts.append(f"5Y breakeven: {market_pricing['breakeven_5y']}%")
    if signals:
        parts.append(f"Signals: {', '.join(signals)}")
    result["assessment"] = ". ".join(parts) + "." if parts else "Insufficient data for assessment."

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# 5. ENHANCED VIX ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def get_enhanced_vix_analysis() -> str:
    """Full VIX opportunity framework with 7-tier classification.

    Computes 1-year percentile rank, classifies VIX into seven tiers
    (complacency through home-run territory), checks MOVE/VIX ratio
    for bond-equity vol divergence, and detects UnderVIX conditions
    where VIX is low but credit or curve signals indicate hidden risk.

    Returns:
        JSON string with as_of, vix, move, under_vix,
        opportunity_assessment, and signals.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d")}
    signals: list[str] = []

    # ── Load VIX/MOVE from local CSV ──────────────────────────────────
    vix_df = _load_csv("vix_move.csv")
    if vix_df is None or "vix" not in vix_df.columns:
        return json.dumps({"error": "vix_move.csv not available or missing vix column"}, indent=2)

    vix_df = vix_df.sort_values("date", ascending=True).reset_index(drop=True)
    vix_series = vix_df["vix"].dropna()

    if len(vix_series) == 0:
        return json.dumps({"error": "No VIX data available"}, indent=2)

    latest_vix = float(vix_series.iloc[-1])

    # ── 1-year percentile rank (252 trading days) ─────────────────────
    lookback = min(252, len(vix_series))
    vix_1y = vix_series.tail(lookback)
    percentile_1y = _percentile_rank(vix_1y, latest_vix)

    # ── 7-tier classification ─────────────────────────────────────────
    if latest_vix >= 50:
        tier = 7
        tier_description = "Home run territory"
        tier_detail = "Extreme fear — historically rare, massive mean-reversion opportunity"
        signals.append("VIX_HOME_RUN")
    elif latest_vix >= 40:
        tier = 6
        tier_description = "Career P&L opportunity"
        tier_detail = "Panic selling — vol sellers and systematic strategies capitulating"
        signals.append("VIX_CAREER_PNL")
    elif latest_vix >= 30:
        tier = 5
        tier_description = "Opportunity set unlocks"
        tier_detail = "Vol control funds stepping in, RV traders adding — actionable dislocations"
        signals.append("VIX_OPPORTUNITY")
    elif latest_vix >= 25:
        tier = 4
        tier_description = "Risk-off — hedging demand rising"
        tier_detail = "Institutional hedging demand elevating premiums"
        signals.append("VIX_ELEVATED")
    elif latest_vix >= 20:
        tier = 3
        tier_description = "Elevated caution"
        tier_detail = "Above-average uncertainty, monitor for escalation"
    elif latest_vix >= 14:
        tier = 2
        tier_description = "Normal range"
        tier_detail = "Typical market conditions, balanced risk-reward"
    else:
        tier = 1
        tier_description = "Complacency zone"
        tier_detail = "Low vol often precedes spikes — tail hedging cheap here"
        signals.append("VIX_COMPLACENCY")

    vix_section = {
        "latest": round(latest_vix, 2),
        "percentile_1y": percentile_1y,
        "tier": tier,
        "tier_description": tier_description,
        "tier_detail": tier_detail,
    }

    result["vix"] = vix_section

    # ── MOVE index and MOVE/VIX ratio ─────────────────────────────────
    move_section: dict = {}
    if "move" in vix_df.columns:
        move_series = vix_df["move"].dropna()
        if len(move_series) > 0:
            latest_move = float(move_series.iloc[-1])
            move_section["latest"] = round(latest_move, 1)

            if latest_vix > 0:
                move_vix_ratio = round(latest_move / latest_vix, 2)
                move_section["move_vix_ratio"] = move_vix_ratio

                if move_vix_ratio > 6:
                    move_section["interpretation"] = (
                        f"MOVE/VIX ratio at {move_vix_ratio} — bond vol elevated relative to equity vol. "
                        "Rate uncertainty driving markets more than equity-specific risk."
                    )
                    signals.append("MOVE_VIX_DIVERGENCE")
                elif move_vix_ratio < 3:
                    move_section["interpretation"] = (
                        f"MOVE/VIX ratio at {move_vix_ratio} — equity vol elevated relative to bond vol. "
                        "Equity-specific risk (earnings, positioning) driving over rates."
                    )
                else:
                    move_section["interpretation"] = (
                        f"MOVE/VIX ratio at {move_vix_ratio} — balanced equity and rate vol"
                    )

    result["move"] = move_section if move_section else {"status": "data_unavailable"}

    # ── UnderVIX detection ────────────────────────────────────────────
    under_vix: dict = {"detected": False, "evidence": []}

    if latest_vix < 18:
        # Check for hidden stress via credit spreads
        credit_data = _safe_fred_call(fred_data.get_credit_spread_data)
        yield_data = _safe_fred_call(fred_data.get_yield_curve_data)

        credit_stress = False
        if credit_data:
            hy_stress = credit_data.get("high_yield_oas", {}).get("stress_level")
            if hy_stress in ("stress", "elevated", "crisis"):
                credit_stress = True
                under_vix["evidence"].append(
                    f"HY OAS stress level: {hy_stress} (spread at "
                    f"{credit_data.get('high_yield_oas', {}).get('latest_value', 'N/A')}%)"
                )

        curve_inverted = False
        if yield_data:
            curve_status = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("curve_status")
            if curve_status == "inverted":
                curve_inverted = True
                spread_val = yield_data.get("yield_curve_spreads", {}).get("2s10s", {}).get("latest_value")
                under_vix["evidence"].append(f"Yield curve inverted (2s10s at {spread_val}%)")

        if credit_stress or curve_inverted:
            under_vix["detected"] = True
            under_vix["interpretation"] = (
                f"VIX at {latest_vix:.1f} appears low given underlying stress signals. "
                "Market may be underpricing risk — watch for vol repricing."
            )
            signals.append("UNDER_VIX_DETECTED")
        else:
            under_vix["interpretation"] = "No hidden stress detected — low VIX consistent with conditions"
    else:
        under_vix["interpretation"] = f"VIX at {latest_vix:.1f} — above 18, UnderVIX check not applicable"

    result["under_vix"] = under_vix

    # ── Opportunity assessment ────────────────────────────────────────
    if tier >= 5:
        opportunity = (
            f"VIX at {latest_vix:.1f} ({tier_description}) — historically strong forward returns "
            "for equity longs. Vol selling and mean-reversion strategies favored."
        )
    elif tier == 4:
        opportunity = (
            f"VIX at {latest_vix:.1f} — risk-off environment. "
            "Selective opportunities emerging but caution warranted."
        )
    elif tier <= 1:
        opportunity = (
            f"VIX at {latest_vix:.1f} — complacency zone. "
            "Tail hedging is historically cheap here. Consider protective puts."
        )
    else:
        opportunity = f"VIX at {latest_vix:.1f} — {tier_description}. No extreme opportunity signal."

    result["opportunity_assessment"] = opportunity
    result["signals"] = signals

    return json.dumps(result, indent=2)
