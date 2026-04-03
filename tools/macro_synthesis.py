"""Cross-tool macro synthesis, contradiction detection, and actionable recommendations.

Combines outputs from multiple analysis tools into a unified macro view with:
- Contradiction detection: flags inconsistencies across tools
- Actionable recommendations: sector tilts, duration calls, risk sizing
- Historical analogues: references similar macro periods
- Cause-effect reasoning: explains WHY metrics matter, not just WHAT they show

v2.7 — 2026-03-11
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from tools import fred_data
from tools.macro_market_analysis import (
    analyze_bond_market,
    analyze_equity_drivers,
    analyze_macro_regime,
)
from tools.market_regime_enhanced import (
    analyze_financial_stress,
    detect_late_cycle_signals,
)
from tools.consumer_housing_analysis import analyze_consumer_health

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# HISTORICAL ANALOGUES DATABASE
# ═══════════════════════════════════════════════════════════════════════
# Simplified regime fingerprints from notable market periods.
# Each entry has key metrics and what followed.

_HISTORICAL_ANALOGUES = [
    {
        "period": "Q4 2018 (Fed overtightening)",
        "conditions": {
            "vix_range": (15, 35), "hy_oas_range": (3.0, 5.5),
            "curve": "flattening_or_inverted", "fed": "hiking",
            "unemployment": "low", "inflation": "moderate",
        },
        "what_followed": "20% SPX drawdown (Sep-Dec 2018), Fed pivot to cuts in 2019",
        "lesson": "Tight labor + Fed hiking + credit widening = equity correction. Fed pivot was the catalyst for recovery.",
    },
    {
        "period": "Q1 2020 (COVID crash)",
        "conditions": {
            "vix_range": (30, 82), "hy_oas_range": (5.0, 11.0),
            "curve": "steepening", "fed": "emergency_cutting",
            "unemployment": "spiking", "inflation": "collapsing",
        },
        "what_followed": "34% drawdown in 23 trading days, V-shaped recovery, massive fiscal/monetary response",
        "lesson": "Exogenous shocks create maximum fear but fastest recoveries when policy responds aggressively.",
    },
    {
        "period": "H2 2021 (peak euphoria)",
        "conditions": {
            "vix_range": (15, 22), "hy_oas_range": (2.5, 3.5),
            "curve": "normal", "fed": "still_accommodative",
            "unemployment": "falling_fast", "inflation": "rising",
        },
        "what_followed": "2022 bear market (-25% SPX), worst bond year in decades, Fed hiked aggressively",
        "lesson": "Ultra-tight spreads + rising inflation + accommodative Fed = mispriced risk. Inflation was not transitory.",
    },
    {
        "period": "Q3 2022 (peak hawkishness)",
        "conditions": {
            "vix_range": (20, 35), "hy_oas_range": (4.5, 6.0),
            "curve": "deeply_inverted", "fed": "aggressive_hiking",
            "unemployment": "low", "inflation": "peaking",
        },
        "what_followed": "SPX bottomed Oct 2022, rallied 25%+ over next 12 months as inflation peaked",
        "lesson": "Peak hawkishness = peak pessimism. When inflation peaks and Fed signals pace change, equities rally ahead of cuts.",
    },
    {
        "period": "2024-2025 (higher-for-longer)",
        "conditions": {
            "vix_range": (12, 20), "hy_oas_range": (2.8, 4.0),
            "curve": "inverted_then_normalizing", "fed": "on_hold_high",
            "unemployment": "low_but_rising", "inflation": "sticky_above_target",
        },
        "what_followed": "Narrow AI-driven rally, broadening concerns, rate cut debate, carry trade unwind (Aug 2024)",
        "lesson": "Narrow markets with sticky inflation and high rates are fragile. Concentration risk + vol compression = sharp corrections on catalysts.",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# CONTRADICTION DETECTION
# ═══════════════════════════════════════════════════════════════════════

def _detect_contradictions(
    regime_data: dict,
    equity_data: dict,
    bond_data: dict,
    stress_data: dict,
    consumer_data: dict,
) -> list[dict]:
    """Scan analysis outputs for internal contradictions.

    Returns a list of contradiction dicts with severity, description,
    and which tools disagree.
    """
    contradictions: list[dict] = []

    # ── 1. Credit spreads vs equity assessment ──
    credit_regime = regime_data.get("regimes", {}).get("credit", {})
    credit_stress = credit_regime.get("stress_level", "")
    equity_signals = equity_data.get("signals", [])

    if credit_stress in ("stressed", "elevated", "crisis", "severe_stress"):
        if "CREDIT_TAILWIND" in equity_signals:
            contradictions.append({
                "severity": "CRITICAL",
                "type": "credit_equity_mismatch",
                "description": (
                    f"Credit regime shows {credit_stress} (HY OAS "
                    f"{credit_regime.get('value_bps', '?')}bps) but equity "
                    f"analysis signals CREDIT_TAILWIND. These are contradictory."
                ),
                "tools": ["analyze_macro_regime", "analyze_equity_drivers"],
                "recommendation": "Trust credit market signal — credit leads equity by 2-3 months",
            })

    if credit_stress in ("tight", "below_average"):
        if "CREDIT_STRESS" in equity_signals:
            contradictions.append({
                "severity": "HIGH",
                "type": "credit_equity_mismatch",
                "description": (
                    f"Credit regime shows {credit_stress} but equity "
                    f"analysis signals CREDIT_STRESS. Possible data lag."
                ),
                "tools": ["analyze_macro_regime", "analyze_equity_drivers"],
                "recommendation": "Check if credit data is stale; verify spread direction",
            })

    # ── 2. Consumer health vs macro regime ──
    consumer_score = None
    consumer_level = None
    if isinstance(consumer_data, dict):
        consumer_score = consumer_data.get("composite_score")
        consumer_level = consumer_data.get("health_level")

    growth_regime = regime_data.get("regimes", {}).get("growth", {})
    growth_cls = growth_regime.get("classification", "")

    if consumer_level == "stressed" and growth_cls == "expansion":
        contradictions.append({
            "severity": "HIGH",
            "type": "consumer_growth_mismatch",
            "description": (
                f"Consumer health is {consumer_level} (score {consumer_score}/10) "
                f"but growth regime is '{growth_cls}'. Consumer weakness may not yet "
                f"show in GDP but is a leading indicator of slowdown."
            ),
            "tools": ["analyze_consumer_health", "analyze_macro_regime"],
            "recommendation": "Monitor consumer spending data closely; defensive positioning warranted",
        })

    # ── 3. VIX vs credit spreads divergence ──
    vix_regime = regime_data.get("regimes", {}).get("volatility", {})
    vix_val = vix_regime.get("value")

    if vix_val is not None and credit_stress:
        if vix_val < 15 and credit_stress in ("stressed", "elevated"):
            contradictions.append({
                "severity": "HIGH",
                "type": "vix_credit_divergence",
                "description": (
                    f"VIX is complacent at {vix_val} but credit spreads are "
                    f"{credit_stress}. VIX may be under-pricing risk (underVIX)."
                ),
                "tools": ["analyze_macro_regime", "analyze_financial_stress"],
                "recommendation": "VIX underpricing = cheap downside protection. Consider buying puts.",
            })
        elif vix_val > 25 and credit_stress in ("tight", "below_average"):
            contradictions.append({
                "severity": "MEDIUM",
                "type": "vix_credit_divergence",
                "description": (
                    f"VIX is elevated at {vix_val} but credit spreads are "
                    f"{credit_stress}. Equity fear without credit stress often "
                    f"resolves bullishly (panic attack, not systemic risk)."
                ),
                "tools": ["analyze_macro_regime", "analyze_financial_stress"],
                "recommendation": "Likely a panic attack. Look for buying opportunities if credit stays contained.",
            })

    # ── 4. Late-cycle signals vs growth regime ──
    stress_signals = stress_data.get("signals_firing", []) if isinstance(stress_data, dict) else []
    late_cycle_count = stress_data.get("count", 0) if isinstance(stress_data, dict) else 0

    if late_cycle_count >= 6 and growth_cls in ("expansion", "strong_expansion"):
        contradictions.append({
            "severity": "MEDIUM",
            "type": "late_cycle_growth_mismatch",
            "description": (
                f"{late_cycle_count}/13 late-cycle signals firing but growth "
                f"regime is '{growth_cls}'. Economy may be in late-cycle expansion — "
                f"growth looks strong but cracks are forming beneath the surface."
            ),
            "tools": ["detect_late_cycle_signals", "analyze_macro_regime"],
            "recommendation": "Reduce cyclical exposure, increase quality tilt. Late-cycle expansions end abruptly.",
        })

    # ── 5. Bond market vs equity signals ──
    bond_signals = bond_data.get("signals", []) if isinstance(bond_data, dict) else []
    if "CREDIT_WIDENING" in bond_signals and "CREDIT_TAILWIND" in equity_signals:
        contradictions.append({
            "severity": "HIGH",
            "type": "bond_equity_credit_mismatch",
            "description": "Bond analysis shows credit widening but equity analysis shows credit tailwind.",
            "tools": ["analyze_bond_market", "analyze_equity_drivers"],
            "recommendation": "Bond market is likely right. Reduce equity risk until credit stabilizes.",
        })

    return contradictions


# ═══════════════════════════════════════════════════════════════════════
# HISTORICAL ANALOGUE MATCHING
# ═══════════════════════════════════════════════════════════════════════

def _find_analogues(
    vix: float | None,
    hy_oas: float | None,
    curve_shape: str | None,
    fed_stance: str | None,
) -> list[dict]:
    """Find historical periods most similar to current conditions."""
    matches = []

    for analogue in _HISTORICAL_ANALOGUES:
        conds = analogue["conditions"]
        score = 0
        total = 0

        # VIX range match
        if vix is not None:
            total += 1
            vix_lo, vix_hi = conds["vix_range"]
            if vix_lo <= vix <= vix_hi:
                score += 1
            elif abs(vix - vix_lo) < 5 or abs(vix - vix_hi) < 5:
                score += 0.5

        # HY OAS range match
        if hy_oas is not None:
            total += 1
            oas_lo, oas_hi = conds["hy_oas_range"]
            if oas_lo <= hy_oas <= oas_hi:
                score += 1
            elif abs(hy_oas - oas_lo) < 0.5 or abs(hy_oas - oas_hi) < 0.5:
                score += 0.5

        # Curve shape match (fuzzy)
        if curve_shape:
            total += 1
            c = conds["curve"]
            if curve_shape == "inverted" and "inverted" in c:
                score += 1
            elif curve_shape == "normal" and c == "normal":
                score += 1
            elif curve_shape == "flat" and "flat" in c:
                score += 0.5

        if total > 0:
            match_pct = score / total * 100
            if match_pct >= 50:
                matches.append({
                    "period": analogue["period"],
                    "match_pct": round(match_pct, 0),
                    "what_followed": analogue["what_followed"],
                    "lesson": analogue["lesson"],
                })

    # Sort by match quality
    matches.sort(key=lambda x: x["match_pct"], reverse=True)
    return matches[:3]  # top 3


# ═══════════════════════════════════════════════════════════════════════
# ACTIONABLE RECOMMENDATIONS ENGINE
# ═══════════════════════════════════════════════════════════════════════

def _generate_recommendations(
    regime_data: dict,
    equity_data: dict,
    bond_data: dict,
    stress_data: dict,
    consumer_data: dict,
    contradictions: list[dict],
) -> dict:
    """Generate actionable portfolio recommendations from analysis outputs."""

    recs: dict = {
        "equity_positioning": [],
        "fixed_income": [],
        "sector_tilts": [],
        "risk_management": [],
        "conviction": "LOW",  # default
    }

    # Extract key inputs
    regimes = regime_data.get("regimes", {})
    growth_cls = regimes.get("growth", {}).get("classification", "")
    inflation_cls = regimes.get("inflation", {}).get("classification", "")
    credit_cls = regimes.get("credit", {}).get("classification", "")
    vol_cls = regimes.get("volatility", {}).get("classification", "")

    stress_score = stress_data.get("composite_score", 5) if isinstance(stress_data, dict) else 5
    late_cycle_count = stress_data.get("count", 0) if isinstance(stress_data, dict) else 0

    erp = equity_data.get("erp_pct")
    equity_signals = equity_data.get("signals", [])
    bond_signals = bond_data.get("signals", []) if isinstance(bond_data, dict) else []

    # ── Equity positioning ──
    if stress_score > 7:
        recs["equity_positioning"].append("REDUCE gross equity exposure by 20-30% — stress score elevated")
    elif stress_score > 5:
        recs["equity_positioning"].append("CAUTIOUS — maintain exposure but tighten stops and reduce leverage")
    elif stress_score < 3:
        recs["equity_positioning"].append("CONSTRUCTIVE — stress low, consider adding risk on pullbacks")

    if erp is not None:
        if erp < 1.5:
            recs["equity_positioning"].append(f"ERP at {erp}% — equities expensive vs bonds. Reduce overweight.")
        elif erp > 4.0:
            recs["equity_positioning"].append(f"ERP at {erp}% — equities attractive vs bonds. Increase equity allocation.")

    if late_cycle_count >= 8:
        recs["equity_positioning"].append(f"LATE CYCLE WARNING: {late_cycle_count}/13 signals firing — reduce cyclical exposure")
    elif late_cycle_count >= 5:
        recs["equity_positioning"].append(f"Late-cycle watch: {late_cycle_count}/13 signals — shift to quality factor")

    # ── Fixed income ──
    if "YIELD_CURVE_STEEPENING" in bond_signals:
        recs["fixed_income"].append("Curve steepening — reduce duration, favor short-end")
    elif "YIELD_CURVE_FLATTENING" in bond_signals:
        recs["fixed_income"].append("Curve flattening — add duration on dips, front-end less attractive")

    if credit_cls in ("elevated", "crisis"):
        recs["fixed_income"].append("Credit spreads elevated — avoid HY, favor IG or Treasuries")
    elif credit_cls == "tight":
        recs["fixed_income"].append("Spreads tight — HY carry attractive but limited upside; be selective")

    if inflation_cls in ("elevated", "hot"):
        recs["fixed_income"].append("Inflation elevated — favor TIPS over nominals, short duration")
    elif inflation_cls in ("falling", "low"):
        recs["fixed_income"].append("Inflation falling — extend duration, nominal bonds attractive")

    # ── Sector tilts ──
    if inflation_cls in ("elevated", "hot") and growth_cls in ("expansion", "strong_expansion"):
        recs["sector_tilts"].append("OVERWEIGHT: Energy, Materials, Financials (inflation + growth)")
        recs["sector_tilts"].append("UNDERWEIGHT: Utilities, Long-duration Tech (rate-sensitive)")
    elif inflation_cls in ("falling", "low") and growth_cls in ("contraction", "slowing"):
        recs["sector_tilts"].append("OVERWEIGHT: Utilities, Healthcare, Consumer Staples (defensive)")
        recs["sector_tilts"].append("UNDERWEIGHT: Cyclicals, Industrials, Materials")
    elif growth_cls in ("expansion",) and inflation_cls in ("moderate", "falling"):
        recs["sector_tilts"].append("OVERWEIGHT: Tech, Consumer Discretionary, Industrials (Goldilocks)")
        recs["sector_tilts"].append("UNDERWEIGHT: Defensive sectors (Utilities, Staples)")

    if "DOLLAR_WEAKENING" in equity_signals or "DXY_FALLING" in equity_signals:
        recs["sector_tilts"].append("Weak dollar — favor EM-exposed multinationals, commodity producers")

    # ── Risk management ──
    if contradictions:
        critical_count = sum(1 for c in contradictions if c["severity"] == "CRITICAL")
        if critical_count > 0:
            recs["risk_management"].append(
                f"{critical_count} CRITICAL contradiction(s) detected — reduce position sizes until resolved"
            )
        recs["risk_management"].append(
            f"Total {len(contradictions)} contradiction(s) across tools — higher uncertainty = smaller positions"
        )

    vol_value = regimes.get("volatility", {}).get("value")
    if vol_value is not None:
        if vol_value < 14:
            recs["risk_management"].append(
                f"VIX at {vol_value} — vol compression. Cheap to buy protection. Consider 5% of book in downside hedges."
            )
        elif vol_value > 30:
            recs["risk_management"].append(
                f"VIX at {vol_value} — elevated fear. Selling premium is attractive but size small. "
                f"This is NOT the time to add new directional risk."
            )

    if stress_score > 6:
        recs["risk_management"].append("Financial stress elevated — max 1% risk per trade, no leverage")
    elif stress_score < 3:
        recs["risk_management"].append("Financial stress low — normal risk budget (1.5-2% per trade)")

    # ── Overall conviction ──
    # High conviction = clear regime + no contradictions + strong signals
    critical_contradictions = sum(1 for c in contradictions if c["severity"] in ("CRITICAL", "HIGH"))
    if critical_contradictions == 0 and stress_score < 4:
        recs["conviction"] = "HIGH"
    elif critical_contradictions <= 1 and stress_score < 6:
        recs["conviction"] = "MODERATE"
    else:
        recs["conviction"] = "LOW"

    recs["conviction_note"] = {
        "HIGH": "Clear regime, no major contradictions. Size positions normally.",
        "MODERATE": "Some uncertainty. Reduce position sizes by 30-50%.",
        "LOW": "Contradictions or elevated stress. Minimum position sizes, cash buffer up.",
    }[recs["conviction"]]

    return recs


# ═══════════════════════════════════════════════════════════════════════
# SO-WHAT CAUSE-EFFECT CHAINS
# ═══════════════════════════════════════════════════════════════════════

def _build_so_what(regime_data: dict, stress_data: dict) -> list[dict]:
    """Build cause-effect reasoning chains from current regime state."""
    chains: list[dict] = []
    regimes = regime_data.get("regimes", {})

    # Inflation chain
    inflation = regimes.get("inflation", {})
    inf_cls = inflation.get("classification", "")
    if inf_cls in ("elevated", "hot"):
        chains.append({
            "observation": f"Inflation regime: {inf_cls}",
            "because": "Sticky services inflation + potential commodity passthrough from energy prices",
            "so_what": "Fed stays hawkish → real yields stay elevated → P/E compression risk for growth stocks",
            "portfolio_action": "Favor value over growth, add inflation hedges (TIPS, commodities), reduce duration",
        })
    elif inf_cls in ("falling", "low"):
        chains.append({
            "observation": f"Inflation regime: {inf_cls}",
            "because": "Base effects + demand moderation + goods deflation",
            "so_what": "Fed can ease → real yields decline → duration assets and growth stocks benefit",
            "portfolio_action": "Extend bond duration, add long-duration growth, reduce commodity overweight",
        })

    # Credit chain
    credit = regimes.get("credit", {})
    credit_stress = credit.get("stress_level", "")
    if credit_stress in ("stressed", "elevated", "crisis", "severe_stress"):
        chains.append({
            "observation": f"Credit spreads: {credit_stress} ({credit.get('value_bps', '?')}bps)",
            "because": "Risk repricing — either fundamental deterioration or liquidity withdrawal",
            "so_what": "Credit leads equity by 2-3 months. Widening spreads precede earnings downgrades and equity selloffs.",
            "portfolio_action": "Reduce HY and leveraged loan exposure. Move up in quality. Add Treasury allocation.",
        })
    elif credit_stress in ("tight", "below_average"):
        chains.append({
            "observation": f"Credit spreads: {credit_stress} ({credit.get('value_bps', '?')}bps)",
            "because": "Strong demand for credit + limited defaults + carry-seeking in risk assets",
            "so_what": "Tight spreads support equities near-term but leave no cushion for shocks. Complacency risk.",
            "portfolio_action": "Carry is attractive but upside limited. Avoid reaching for yield in lowest-quality tranches.",
        })

    # Growth chain
    growth = regimes.get("growth", {})
    growth_cls = growth.get("classification", "")
    if growth_cls in ("contraction", "slowing"):
        chains.append({
            "observation": f"Growth regime: {growth_cls}",
            "because": "ISM decomposition suggests weakening new orders and/or rising inventories",
            "so_what": "Earnings growth will decelerate. Forward guidance likely to disappoint. Cyclicals most exposed.",
            "portfolio_action": "Defensive rotation: Healthcare > Discretionary, Staples > Cyclicals, Quality > Momentum",
        })

    # Stress chain
    stress_score = stress_data.get("composite_score", 0) if isinstance(stress_data, dict) else 0
    if stress_score > 6:
        chains.append({
            "observation": f"Financial stress score: {stress_score:.1f}/10",
            "because": "Multiple stress components elevated simultaneously (credit, volatility, labor, sentiment)",
            "so_what": "Elevated stress is a regime indicator, not a trade signal. It persists — conditions worsen before improving.",
            "portfolio_action": "Capital preservation mode. Raise cash to 15-25% of portfolio. No new leveraged positions.",
        })

    return chains


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC: SYNTHESIZE MACRO VIEW
# ═══════════════════════════════════════════════════════════════════════

def synthesize_macro_view() -> str:
    """Run all major analysis tools and produce a unified macro synthesis.

    Combines: macro regime, equity drivers, bond market, financial stress,
    late-cycle signals, and consumer health into one coherent view with:
    - Cross-tool contradiction detection
    - Actionable recommendations (sector tilts, duration, risk sizing)
    - Historical analogue matching
    - Cause-effect reasoning chains

    This is the agent's highest-level analytical function.
    """
    result: dict = {"as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

    # ── Run analyses (with error handling) ──
    def _safe_json(func, name: str) -> dict:
        try:
            raw = func()
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            logger.warning("synthesize_macro_view: %s failed: %s", name, e)
            return {"error": str(e)}

    regime_data = _safe_json(analyze_macro_regime, "macro_regime")
    equity_data = _safe_json(lambda: analyze_equity_drivers("sp500"), "equity_drivers")
    bond_data = _safe_json(analyze_bond_market, "bond_market")
    stress_data = _safe_json(analyze_financial_stress, "financial_stress")
    late_cycle = _safe_json(detect_late_cycle_signals, "late_cycle")
    consumer = _safe_json(analyze_consumer_health, "consumer_health")

    # Merge late-cycle into stress for convenience
    if "error" not in late_cycle:
        stress_data["late_cycle_count"] = late_cycle.get("count", 0)
        stress_data["late_cycle_signals"] = late_cycle.get("signals_firing", [])
        stress_data["count"] = late_cycle.get("count", 0)

    # ── Regime summary ──
    regimes = regime_data.get("regimes", {})
    result["regime_summary"] = {
        "growth": regimes.get("growth", {}).get("classification", "?"),
        "inflation": regimes.get("inflation", {}).get("classification", "?"),
        "employment": regimes.get("employment", {}).get("classification", "?"),
        "rates": regimes.get("rates", {}).get("classification", "?"),
        "credit": regimes.get("credit", {}).get("classification", "?"),
        "credit_stress_level": regimes.get("credit", {}).get("stress_level", "?"),
        "housing": regimes.get("housing", {}).get("classification", "?"),
        "financial_stress_score": stress_data.get("composite_score", "?"),
        "late_cycle_signals": f"{late_cycle.get('count', '?')}/13",
        "consumer_health": consumer.get("health_level", "?"),
    }

    # ── Contradiction detection ──
    contradictions = _detect_contradictions(
        regime_data, equity_data, bond_data, stress_data, consumer,
    )
    result["contradictions"] = contradictions
    result["contradiction_count"] = len(contradictions)
    result["coherence_status"] = "CLEAN" if not contradictions else (
        "CRITICAL_ISSUES" if any(c["severity"] == "CRITICAL" for c in contradictions) else "WARNINGS"
    )

    # ── Historical analogues ──
    vix_val = regimes.get("volatility", {}).get("value")
    hy_oas_val = regimes.get("credit", {}).get("value")
    curve_shape = bond_data.get("yield_curve", {}).get("shape") if isinstance(bond_data, dict) else None
    fed_stance = bond_data.get("fed_policy", {}).get("stance") if isinstance(bond_data, dict) else None

    analogues = _find_analogues(vix_val, hy_oas_val, curve_shape, fed_stance)
    result["historical_analogues"] = analogues

    # ── Cause-effect chains ──
    so_what = _build_so_what(regime_data, stress_data)
    result["so_what_chains"] = so_what

    # ── Actionable recommendations ──
    recommendations = _generate_recommendations(
        regime_data, equity_data, bond_data, stress_data, consumer, contradictions,
    )
    result["recommendations"] = recommendations

    # ── Executive summary (narrative) ──
    parts = []
    growth = result["regime_summary"]["growth"]
    inflation = result["regime_summary"]["inflation"]
    credit = result["regime_summary"]["credit_stress_level"]
    stress = result["regime_summary"]["financial_stress_score"]
    lc = result["regime_summary"]["late_cycle_signals"]

    parts.append(f"Growth: {growth}, Inflation: {inflation}, Credit: {credit}")
    parts.append(f"Stress: {stress}/10, Late-cycle: {lc}")

    if contradictions:
        crit = sum(1 for c in contradictions if c["severity"] == "CRITICAL")
        parts.append(f"ALERT: {len(contradictions)} contradictions detected ({crit} critical)")

    if analogues:
        parts.append(f"Closest analogue: {analogues[0]['period']} ({analogues[0]['match_pct']:.0f}% match)")

    parts.append(f"Conviction: {recommendations['conviction']}")
    result["executive_summary"] = ". ".join(parts) + "."

    return json.dumps(result, indent=2, default=str)
