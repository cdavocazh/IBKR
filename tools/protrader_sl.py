"""Pro Trader Stop-Loss Framework.

Stop-loss logic extracted from 200+ professional macro trader emails.
Provides asset-class-specific stop placement, position sizing rules,
trailing stop methodology, and the Fidenza risk management framework.

Supports: FX, gold, silver, copper, oil, BTC, ES/equities, rates/SOFR,
ETFs, and a generic fallback.

No external dependencies beyond the standard library.
"""

import json
import math


# ---------------------------------------------------------------------------
# Asset-class stop profiles
# ---------------------------------------------------------------------------
# Each profile captures the typical stop width range, the default percentage
# used for percent-based stops, and asset-specific guidance notes distilled
# from institutional trade logs.

_STOP_PROFILES = {
    "fx": {
        "typical_range": "50-100 pips (0.4-0.9%)",
        "default_pct": 0.7,
        "method": "Below/above 1-3 day swing",
        "notes": (
            "FX: 50-100 pip stops typical. Stops placed below/above "
            "1-3 day swing lows/highs."
        ),
    },
    "eurusd": {
        "typical_range": "50-100 pips (0.4-0.9%)",
        "default_pct": 0.7,
        "method": "Below/above 1-3 day swing",
        "notes": (
            "FX: 50-100 pip stops typical. Stops placed below/above "
            "1-3 day swing lows/highs."
        ),
    },
    "gold": {
        "typical_range": "30-160 points (0.9-4.8%)",
        "default_pct": 1.5,
        "method": "Below swing low",
        "notes": (
            "Gold: 4H RSI oversold is historically a strong buy signal. "
            "Avoid buying when 4H RSI overbought. Stops typically 30-160 "
            "points below entry. Half size on wide stops."
        ),
    },
    "silver": {
        "typical_range": "3-5 points (3-6%)",
        "default_pct": 4.0,
        "method": "Below swing low; half size on wide stops",
        "notes": (
            "Silver: Highly volatile -- always use half position size if "
            "stop is wider than 4 points. Front-running resistance breaks "
            "can work. Parabolic rallies need trailing stops."
        ),
    },
    "copper": {
        "typical_range": "10-30 cents (2-5%)",
        "default_pct": 3.0,
        "method": "Below range support",
        "notes": (
            "Copper: Stops placed below range support. Watch for "
            "China demand signals and inventory drawdowns."
        ),
    },
    "oil": {
        "typical_range": "$1.50-3.50 (2-5%)",
        "default_pct": 3.0,
        "method": "Below support for longs, above resistance for shorts",
        "notes": (
            "Oil: Geopolitical events create temporary vs sustained "
            "spikes. XOP outperforming XLE = temporary. Ceasefire "
            "risk = rapid unwind."
        ),
    },
    "crude_oil": {
        "typical_range": "$1.50-3.50 (2-5%)",
        "default_pct": 3.0,
        "method": "Below support for longs, above resistance for shorts",
        "notes": (
            "Oil: Geopolitical events create temporary vs sustained "
            "spikes. XOP outperforming XLE = temporary. Ceasefire "
            "risk = rapid unwind."
        ),
    },
    "btc": {
        "typical_range": "$3K-8K (3-7%)",
        "default_pct": 5.0,
        "method": "Wide stop, scale-in plan on confirmation",
        "notes": (
            "BTC: Wide stops required. Scale-in plan: if price moves "
            "3-5% in favor, add to position and tighten stop. Negative "
            "funding = short squeeze fuel."
        ),
    },
    "bitcoin": {
        "typical_range": "$3K-8K (3-7%)",
        "default_pct": 5.0,
        "method": "Wide stop, scale-in plan on confirmation",
        "notes": (
            "BTC: Wide stops required. Scale-in plan: if price moves "
            "3-5% in favor, add to position and tighten stop. Negative "
            "funding = short squeeze fuel."
        ),
    },
    "es": {
        "typical_range": "30-60 points (0.4-0.8%)",
        "default_pct": 0.6,
        "method": "1:1 trailing stop rule",
        "notes": (
            "ES/Equities: Size trades at 0.7-1.0% of capital. Use "
            "1:1 trailing stop rule. Don't chase extended moves on Mondays."
        ),
    },
    "spx": {
        "typical_range": "30-60 points (0.4-0.8%)",
        "default_pct": 0.6,
        "method": "1:1 trailing stop rule",
        "notes": (
            "ES/Equities: Size trades at 0.7-1.0% of capital. Use "
            "1:1 trailing stop rule. Don't chase extended moves on Mondays."
        ),
    },
    "equities": {
        "typical_range": "30-60 points (0.4-0.8%)",
        "default_pct": 0.6,
        "method": "1:1 trailing stop rule",
        "notes": (
            "ES/Equities: Size trades at 0.7-1.0% of capital. Use "
            "1:1 trailing stop rule. Don't chase extended moves on Mondays."
        ),
    },
    "rates": {
        "typical_range": "5-10 bps (0.05-0.1%)",
        "default_pct": 0.08,
        "method": "Tight asymmetric bets",
        "notes": (
            "Rates/SOFR: Very tight stops (5-10 bps). Asymmetric "
            "bets: small risk, large potential reward."
        ),
    },
    "sofr": {
        "typical_range": "5-10 bps (0.05-0.1%)",
        "default_pct": 0.08,
        "method": "Tight asymmetric bets",
        "notes": (
            "Rates/SOFR: Very tight stops (5-10 bps). Asymmetric "
            "bets: small risk, large potential reward."
        ),
    },
    "etf": {
        "typical_range": "5-10%",
        "default_pct": 7.0,
        "method": "Below breakout or key support",
        "notes": (
            "ETFs: 5-10% stops. Thematic conviction required. Half "
            "size if stop is wider than 10%."
        ),
    },
    "general": {
        "typical_range": "varies",
        "default_pct": 2.0,
        "method": "Generic default",
        "notes": (
            "General: Apply Fidenza framework rules. Risk 0.75-2.0% "
            "of capital per trade. Use swing-based stops when available."
        ),
    },
}

# Swing buffer: a small cushion placed beyond the swing point so the
# stop is not sitting exactly at the level where a wick is likely.
_SWING_BUFFER_PCT = 0.005  # 0.5%


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------

def protrader_stop_loss_framework(
    asset_class: str = "general",
    entry_price: float = 0,
    direction: str = "long",
    current_price: float = 0,
    recent_swing_low: float = 0,
    recent_swing_high: float = 0,
    atr_14: float = 0,
) -> str:
    """Pro trader stop-loss framework.

    Computes stop-loss levels using three methods (swing-based, ATR-based,
    percent-based) and recommends the best one based on available inputs.
    Includes position-sizing guidance, trailing-stop rules, and the full
    Fidenza risk-management framework distilled from 200+ professional
    macro trader emails.

    Parameters
    ----------
    asset_class : str
        One of: fx, eurusd, gold, silver, copper, oil, crude_oil, btc,
        bitcoin, es, spx, equities, rates, sofr, etf, general.
    entry_price : float
        Trade entry price.
    direction : str
        "long" or "short".
    current_price : float
        Current market price (informational; 0 if unavailable).
    recent_swing_low : float
        Recent swing low for long stop placement (0 if unavailable).
    recent_swing_high : float
        Recent swing high for short stop placement (0 if unavailable).
    atr_14 : float
        14-period ATR value (0 if unavailable).

    Returns
    -------
    str
        JSON string containing stop levels, recommendation, position
        sizing guidance, trailing rules, and the Fidenza framework.
    """
    asset_key = asset_class.lower().strip()
    profile = _STOP_PROFILES.get(asset_key, _STOP_PROFILES["general"])
    default_pct = profile["default_pct"]
    direction = direction.lower().strip()
    is_long = direction == "long"

    # Fallback: if no entry_price provided, return framework-only output.
    if entry_price <= 0:
        return _framework_only_output(asset_key, direction, profile)

    # If current_price not supplied, assume it equals entry_price.
    price_is_estimated = False
    if current_price <= 0:
        current_price = entry_price
        price_is_estimated = True

    # -----------------------------------------------------------------
    # 1. Swing-based stop
    # -----------------------------------------------------------------
    swing_stop = None
    if is_long and recent_swing_low > 0:
        swing_level = round(recent_swing_low * (1 - _SWING_BUFFER_PCT), 2)
        swing_risk_pct = round(
            abs(entry_price - swing_level) / entry_price * 100, 2
        )
        swing_stop = {
            "level": swing_level,
            "method": "Below recent swing low (with 0.5% buffer)",
            "risk_pct": swing_risk_pct,
        }
    elif not is_long and recent_swing_high > 0:
        swing_level = round(recent_swing_high * (1 + _SWING_BUFFER_PCT), 2)
        swing_risk_pct = round(
            abs(swing_level - entry_price) / entry_price * 100, 2
        )
        swing_stop = {
            "level": swing_level,
            "method": "Above recent swing high (with 0.5% buffer)",
            "risk_pct": swing_risk_pct,
        }

    # -----------------------------------------------------------------
    # 2. ATR-based stop
    # -----------------------------------------------------------------
    atr_stop = None
    if atr_14 > 0:
        atr_multiplier = 1.5
        if is_long:
            atr_level = round(entry_price - atr_multiplier * atr_14, 2)
        else:
            atr_level = round(entry_price + atr_multiplier * atr_14, 2)
        atr_risk_pct = round(
            abs(entry_price - atr_level) / entry_price * 100, 2
        )
        dir_label = "Entry - 1.5xATR(14)" if is_long else "Entry + 1.5xATR(14)"
        atr_stop = {
            "level": atr_level,
            "method": dir_label,
            "risk_pct": atr_risk_pct,
        }

    # -----------------------------------------------------------------
    # 3. Percent-based stop (always computed)
    # -----------------------------------------------------------------
    if is_long:
        pct_level = round(entry_price * (1 - default_pct / 100), 2)
    else:
        pct_level = round(entry_price * (1 + default_pct / 100), 2)
    pct_risk_pct = round(default_pct, 2)
    pct_label = (
        f"{default_pct}% {'below' if is_long else 'above'} entry "
        f"({asset_key} default)"
    )
    pct_stop = {
        "level": pct_level,
        "method": pct_label,
        "risk_pct": pct_risk_pct,
    }

    # -----------------------------------------------------------------
    # Build stop_levels dict
    # -----------------------------------------------------------------
    stop_levels = {}
    if swing_stop is not None:
        stop_levels["swing_based"] = swing_stop
    if atr_stop is not None:
        stop_levels["atr_based"] = atr_stop
    stop_levels["percent_based"] = pct_stop

    # -----------------------------------------------------------------
    # Recommendation logic
    # -----------------------------------------------------------------
    if swing_stop is not None:
        recommended_stop = swing_stop["level"]
        recommended_method = "swing_based"
    elif atr_stop is not None:
        recommended_stop = atr_stop["level"]
        recommended_method = "atr_based"
    else:
        recommended_stop = pct_stop["level"]
        recommended_method = "percent_based"

    # Risk per unit (distance from entry to stop)
    capital_at_risk_per_unit = round(abs(entry_price - recommended_stop), 2)
    recommended_risk_pct = stop_levels[recommended_method]["risk_pct"]

    # -----------------------------------------------------------------
    # Position sizing
    # -----------------------------------------------------------------
    position_sizing = {
        "risk_per_trade_pct": default_pct,
        "capital_at_risk_per_unit": capital_at_risk_per_unit,
        "sizing_rule": (
            "Wider stop -> reduce position size. "
            "Tighter stop -> can size up."
        ),
    }

    # -----------------------------------------------------------------
    # Trailing rules
    # -----------------------------------------------------------------
    one_r = capital_at_risk_per_unit
    if is_long:
        breakeven_target = round(entry_price + one_r, 2)
    else:
        breakeven_target = round(entry_price - one_r, 2)

    trailing_rules = {
        "trail_to_breakeven_after": (
            f"1R profit (${one_r} {'above' if is_long else 'below'} "
            f"entry = ${breakeven_target})"
        ),
        "trailing_method": (
            "1:1 trailing -- trail stop by 1 unit for every 1 unit "
            "of profit above breakeven"
        ),
    }

    # -----------------------------------------------------------------
    # Risk management rules
    # -----------------------------------------------------------------
    risk_management_rules = [
        "Cut before stop if thesis deteriorates",
        "Tighten all stops if macro regime shifts to risk-off",
        "Re-enter at different level if stopped out but thesis intact",
        "Manage correlated positions -- don't double up on same factor",
    ]

    # -----------------------------------------------------------------
    # Fidenza framework
    # -----------------------------------------------------------------
    fidenza_framework = {
        "rule_1": (
            "Risk 0.75-2.0% of capital per trade "
            "(0.7-1.0% for ES swings)"
        ),
        "rule_2": "Stop = recent swing low/high (1-3 days prior)",
        "rule_3": "Position size inversely proportional to stop width",
        "rule_4": "Trail stop to breakeven after 1R profit",
        "rule_5": "Cut before stop when thesis deteriorates",
        "rule_6": "Tighten all stops during regime shift to risk-off",
        "rule_7": "Manage correlation -- close overlapping positions",
        "rule_8": "Use uncorrelated positions as hedges",
        "rule_9": "Re-enter after stops if thesis intact",
        "rule_10": (
            "Adapt sizing to volatility regime -- "
            "higher vol = wider stop + smaller size"
        ),
    }

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------
    asset_display = asset_key.upper() if asset_key in (
        "btc", "fx", "es", "spx", "etf",
    ) else asset_key.capitalize()
    dir_display = direction.capitalize()
    summary = (
        f"{asset_display} {dir_display.lower()} at ${entry_price:,.2f}. "
        f"Recommended stop: ${recommended_stop:,.2f} "
        f"({recommended_method.replace('_', '-')}, "
        f"{recommended_risk_pct}% risk). "
        f"Trail to breakeven after ${one_r:,.2f} profit. "
        f"Risk {default_pct}% of capital per trade."
    )

    # -----------------------------------------------------------------
    # Warnings
    # -----------------------------------------------------------------
    warnings = []
    if price_is_estimated:
        warnings.append(
            "current_price was not provided — using entry_price as proxy. "
            "Stop levels are approximate; re-run with live price for accuracy."
        )
    if swing_stop is None:
        warnings.append(
            "Swing-based stop unavailable — no recent swing "
            f"{'low' if is_long else 'high'} provided. "
            "For best results, supply the nearest swing level."
        )
    if atr_stop is None:
        warnings.append(
            "ATR-based stop unavailable — ATR(14) not provided. "
            "For best results, supply the 14-period ATR value."
        )

    # -----------------------------------------------------------------
    # Assemble result
    # -----------------------------------------------------------------
    result = {
        "asset_class": asset_key,
        "direction": direction,
        "entry_price": entry_price,
        "current_price": current_price,
        "price_is_estimated": price_is_estimated,
        "stop_levels": stop_levels,
        "recommended_stop": recommended_stop,
        "recommended_method": recommended_method,
        "position_sizing": position_sizing,
        "trailing_rules": trailing_rules,
        "risk_management_rules": risk_management_rules,
        "asset_specific_notes": profile["notes"],
        "fidenza_framework": fidenza_framework,
        "summary": summary,
    }
    if warnings:
        result["warnings"] = warnings

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Helper: framework-only output when no entry price is given
# ---------------------------------------------------------------------------

def _framework_only_output(
    asset_key: str,
    direction: str,
    profile: dict,
) -> str:
    """Return the Fidenza framework and asset-specific guidance without
    computing concrete stop levels (no entry price provided)."""

    result = {
        "asset_class": asset_key,
        "direction": direction,
        "entry_price": None,
        "current_price": None,
        "stop_levels": {},
        "recommended_stop": None,
        "recommended_method": None,
        "position_sizing": {
            "risk_per_trade_pct": profile["default_pct"],
            "capital_at_risk_per_unit": None,
            "sizing_rule": (
                "Wider stop -> reduce position size. "
                "Tighter stop -> can size up."
            ),
        },
        "trailing_rules": {
            "trail_to_breakeven_after": "1R profit above entry",
            "trailing_method": (
                "1:1 trailing -- trail stop by 1 unit for every 1 unit "
                "of profit above breakeven"
            ),
        },
        "risk_management_rules": [
            "Cut before stop if thesis deteriorates",
            "Tighten all stops if macro regime shifts to risk-off",
            "Re-enter at different level if stopped out but thesis intact",
            "Manage correlated positions -- don't double up on same factor",
        ],
        "asset_specific_notes": profile["notes"],
        "fidenza_framework": {
            "rule_1": (
                "Risk 0.75-2.0% of capital per trade "
                "(0.7-1.0% for ES swings)"
            ),
            "rule_2": "Stop = recent swing low/high (1-3 days prior)",
            "rule_3": "Position size inversely proportional to stop width",
            "rule_4": "Trail stop to breakeven after 1R profit",
            "rule_5": "Cut before stop when thesis deteriorates",
            "rule_6": "Tighten all stops during regime shift to risk-off",
            "rule_7": "Manage correlation -- close overlapping positions",
            "rule_8": "Use uncorrelated positions as hedges",
            "rule_9": "Re-enter after stops if thesis intact",
            "rule_10": (
                "Adapt sizing to volatility regime -- "
                "higher vol = wider stop + smaller size"
            ),
        },
        "summary": (
            f"No entry price provided. Use the {asset_key} default stop "
            f"of {profile['default_pct']}% with the Fidenza framework. "
            f"Typical stop range: {profile['typical_range']}. "
            f"Method: {profile['method']}."
        ),
    }

    return json.dumps(result, indent=2)
