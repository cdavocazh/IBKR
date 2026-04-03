"""Macroeconomic data analysis tools.

Reads historical CSV data from /macro_2/historical_data and performs
daily, week-over-week, and month-over-month comparisons. Detects
abnormalities, trend changes, and critical movements using
indicator-specific thresholds derived from financial research.

Each indicator has custom rules calibrated to its nature:
- VIX: absolute level thresholds (12/20/30/40) + point moves
- Yields: basis-point moves (5/10/15/25 bps)
- SOFR: small bps moves matter (5/10/18/50 bps)
- ISM PMI: 50 expansion/contraction line + 42.3 recession threshold
- TGA: $200B+ monthly swings as liquidity events
- COT: percentile-based extreme positioning
- Gold/Silver ratio: mean-reversion thresholds
- And many more — see INDICATOR_RULES below.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from tools.config import (
    HISTORICAL_DATA_DIR,
    MACRO_INDICATORS,
)


# ═══════════════════════════════════════════════════════════════════════
# INDICATOR-SPECIFIC ANOMALY DETECTION RULES
#
# Each rule set defines thresholds calibrated to what actually matters
# for that indicator. "type" determines the detection strategy:
#
#   "absolute"   — Levels that cross key thresholds (VIX 20/30/40)
#   "bps"        — Basis point moves (yields, SOFR, spreads)
#   "pct"        — Percentage moves (equities, commodities, FX)
#   "level"      — Static level thresholds (PMI 50, CAPE 30)
#   "flow"       — Dollar/unit flow changes (TGA, net liquidity)
#   "ratio"      — Ratio-based thresholds (VIX/MOVE, gold/silver)
#   "positioning" — COT percentile extremes
#
# Each rule maps a CSV column name to its detection config.
# ═══════════════════════════════════════════════════════════════════════

# Common aliases so callers don't need to know exact CSV filenames.
INDICATOR_ALIASES: dict[str, str] = {
    "vix": "vix_move",
    "move": "vix_move",
    "10y_yield": "10y_treasury_yield",
    "10y": "10y_treasury_yield",
    "us_10y": "10y_treasury_yield",
    "treasury_10y": "10y_treasury_yield",
    "2y_yield": "us_2y_yield",
    "2y": "us_2y_yield",
    "us_2y": "us_2y_yield",
    "treasury_2y": "us_2y_yield",
    "cape": "shiller_cape",
    "skew": "cboe_skew",
    "gdp": "us_gdp",
    "pmi": "ism_pmi",
    "tga": "tga_balance",
    "liquidity": "net_liquidity",
    "buffett": "marketcap_to_gdp",
    "buffett_indicator": "marketcap_to_gdp",
    "sp500_pe": "sp500_fundamentals",
    "rty": "rty_futures",
    "russell": "russell_2000",
    "es": "es_futures",
    "usd": "dxy",
    "dollar": "dxy",
    "yen": "jpy",
    "usdjpy": "jpy",
}


def _resolve_indicator_key(key: str) -> str:
    """Resolve indicator aliases to canonical CSV key."""
    return INDICATOR_ALIASES.get(key.lower().strip(), key)


INDICATOR_RULES = {
    # ── VIX / MOVE ───────────────────────────────────────────────────
    "vix_move": {
        "vix": {
            "type": "absolute",
            "label": "VIX",
            "levels": [
                (12, "below", "COMPLACENCY", "VIX below 12 — extreme complacency; vulnerability to shocks"),
                (20, "above", "ELEVATED_FEAR", "VIX above 20 — elevated concern; fear regime"),
                (30, "above", "HIGH_FEAR", "VIX above 30 — high fear; major event underway"),
                (40, "above", "CRISIS", "VIX above 40 — crisis territory; contrarian opportunity zone"),
            ],
            # VIX moves in points, not percent — a 3-point daily move is notable
            "daily_point_thresholds": [
                (3.0, "NOTABLE_VIX_MOVE", "VIX moved {dir} {val:.1f} pts in one day"),
                (5.0, "SIGNIFICANT_VIX_SPIKE", "VIX moved {dir} {val:.1f} pts — significant daily move"),
                (10.0, "EXTREME_VIX_SPIKE", "VIX moved {dir} {val:.1f} pts — extreme (top-20 all-time)"),
            ],
            "weekly_point_threshold": 5.0,
            "monthly_point_threshold": 8.0,
        },
        "move": {
            "type": "absolute",
            "label": "MOVE Index",
            "levels": [
                (80, "below", "CALM_BONDS", "MOVE below 80 — calm bond markets"),
                (120, "above", "BOND_STRESS", "MOVE above 120 — bond market stress; defensive rotation likely"),
                (150, "above", "BOND_CRISIS", "MOVE above 150 — crisis-level bond volatility"),
                (200, "above", "EXTREME_BOND_CRISIS", "MOVE above 200 — extreme (comparable to 2008/2023)"),
            ],
            "daily_point_thresholds": [
                (5.0, "NOTABLE_MOVE_SHIFT", "MOVE changed {dir} {val:.1f} pts"),
                (10.0, "SIGNIFICANT_MOVE_SPIKE", "MOVE changed {dir} {val:.1f} pts — significant"),
            ],
        },
        "vix_move_ratio": {
            "type": "ratio",
            "label": "VIX/MOVE Ratio",
            "description": "Low ratio (MOVE high vs VIX) = bond stress not yet in equities — warning signal",
        },
    },

    # ── DXY ──────────────────────────────────────────────────────────
    "dxy": {
        "dxy": {
            "type": "pct",
            "label": "US Dollar Index",
            "levels": [
                (95, "below", "WEAK_DOLLAR", "DXY below 95 — weak dollar territory; supports commodities and EM"),
                (100, "cross", "DXY_100_CROSS", "DXY crossing 100 — major psychological level"),
                (105, "above", "STRONG_DOLLAR", "DXY above 105 — strong dollar; pressures commodities and EM"),
                (110, "above", "VERY_STRONG_DOLLAR", "DXY above 110 — very strong dollar territory"),
            ],
            "daily_pct_thresholds": [
                (0.5, "NOTABLE_DXY_MOVE", "DXY moved {val:+.2f}% — notable daily move"),
                (1.0, "SIGNIFICANT_DXY_MOVE", "DXY moved {val:+.2f}% — significant for a currency index"),
            ],
            "weekly_pct_threshold": 1.5,
            "monthly_pct_threshold": 3.0,
        },
    },

    # ── USD/JPY ──────────────────────────────────────────────────────
    "jpy": {
        "jpy_rate": {
            "type": "absolute",
            "label": "USD/JPY",
            "levels": [
                (140, "below", "JPY_STRENGTH", "USD/JPY below 140 — significant yen strength; carry trade unwind risk"),
                (145, "below", "JPY_MODERATE_STRENGTH", "USD/JPY below 145 — carry trade attractiveness diminishing"),
                (150, "cross", "JPY_150_CROSS", "USD/JPY crossing 150 — major psychological level"),
                (155, "above", "JPY_WEAK", "USD/JPY above 155 — intervention warning zone"),
                (160, "above", "JPY_INTERVENTION", "USD/JPY above 160 — intervention danger zone (BOJ history)"),
            ],
            # USD/JPY: a 1-yen daily move is notable, 2+ is significant
            "daily_point_thresholds": [
                (1.0, "NOTABLE_JPY_MOVE", "USD/JPY moved {dir} {val:.2f} yen"),
                (2.0, "SIGNIFICANT_JPY_MOVE", "USD/JPY moved {dir} {val:.2f} yen — significant"),
                (3.0, "LARGE_JPY_MOVE", "USD/JPY moved {dir} {val:.2f} yen — carry trade unwind risk"),
            ],
        },
    },

    # ── Treasury Yields (basis-point sensitive) ──────────────────────
    "10y_treasury_yield": {
        "10y_yield": {
            "type": "bps",
            "label": "10-Year Treasury Yield",
            "levels": [
                (3.0, "below", "LOW_YIELD_10Y", "10Y yield below 3% — flight-to-safety/recession pricing"),
                (4.0, "cross", "10Y_4PCT_CROSS", "10Y yield crossing 4% — major psychological level"),
                (4.5, "above", "ELEVATED_10Y", "10Y yield above 4.5% — elevated; pressures equity valuations"),
                (5.0, "above", "HIGH_10Y", "10Y yield above 5% — high; major regime shift from 2010s norms"),
            ],
            # Yields: measured in basis points (0.01% = 1 bps)
            "daily_bps_thresholds": [
                (10, "NOTABLE_YIELD_MOVE", "10Y yield moved {val:+.0f} bps"),
                (15, "SIGNIFICANT_YIELD_MOVE", "10Y yield moved {val:+.0f} bps — significant"),
                (25, "EXTREME_YIELD_MOVE", "10Y yield moved {val:+.0f} bps — extreme daily move"),
            ],
            "weekly_bps_threshold": 20,
            "monthly_bps_threshold": 40,
        },
    },

    "us_2y_yield": {
        "us_2y_yield": {
            "type": "bps",
            "label": "US 2-Year Treasury Yield",
            "levels": [
                (3.0, "below", "LOW_2Y", "2Y yield below 3% — aggressive easing priced"),
                (4.0, "cross", "2Y_4PCT_CROSS", "2Y yield crossing 4% — key level (Fed expectations pivot)"),
                (5.0, "above", "HIGH_2Y", "2Y yield above 5% — tight policy expectations"),
            ],
            "daily_bps_thresholds": [
                (8, "NOTABLE_2Y_MOVE", "2Y yield moved {val:+.0f} bps — notable (Fed-sensitive)"),
                (15, "SIGNIFICANT_2Y_MOVE", "2Y yield moved {val:+.0f} bps — significant repricing"),
                (25, "EXTREME_2Y_MOVE", "2Y yield moved {val:+.0f} bps — extreme; major policy surprise"),
            ],
            "weekly_bps_threshold": 15,
            "monthly_bps_threshold": 30,
        },
    },

    "japan_2y_yield": {
        "japan_2y_yield": {
            "type": "bps",
            "label": "Japan 2Y Yield",
            # Japan yields move in very small increments — 3-5 bps is notable
            "daily_bps_thresholds": [
                (3, "NOTABLE_JP2Y_MOVE", "Japan 2Y yield moved {val:+.1f} bps — notable for JGBs"),
                (5, "SIGNIFICANT_JP2Y_MOVE", "Japan 2Y yield moved {val:+.1f} bps — significant (BOJ policy shift?)"),
                (10, "EXTREME_JP2Y_MOVE", "Japan 2Y yield moved {val:+.1f} bps — extreme for JGBs"),
            ],
            "weekly_bps_threshold": 5,
            "monthly_bps_threshold": 10,
        },
    },

    "us2y_jp2y_spread": {
        "spread": {
            "type": "bps",
            "label": "US 2Y - Japan 2Y Spread",
            "levels": [
                (2.0, "below", "NARROW_CARRY_SPREAD", "US-JP 2Y spread below 200 bps — carry trade unwind risk elevated"),
                (3.0, "below", "DECLINING_CARRY", "US-JP 2Y spread below 300 bps — carry trade attractiveness declining"),
                (4.0, "above", "STRONG_CARRY", "US-JP 2Y spread above 400 bps — strong carry incentive"),
            ],
            "daily_bps_thresholds": [
                (5, "NOTABLE_SPREAD_MOVE", "US-JP spread moved {val:+.0f} bps"),
                (10, "SIGNIFICANT_SPREAD_MOVE", "US-JP spread moved {val:+.0f} bps — significant for carry trade"),
                (20, "EXTREME_SPREAD_MOVE", "US-JP spread moved {val:+.0f} bps — extreme; carry trade disruption"),
            ],
            "weekly_bps_threshold": 15,
            "monthly_bps_threshold": 30,
        },
    },

    # ── SOFR (very small moves matter) ───────────────────────────────
    "sofr": {
        "sofr": {
            "type": "bps",
            "label": "SOFR Rate",
            # SOFR normally moves in 1-2 bps. Even 5 bps is notable.
            "daily_bps_thresholds": [
                (5, "NOTABLE_SOFR_MOVE", "SOFR moved {val:+.0f} bps — above normal daily range"),
                (10, "SIGNIFICANT_SOFR_MOVE", "SOFR moved {val:+.0f} bps — funding stress signal"),
                (18, "HIGH_SOFR_SPIKE", "SOFR moved {val:+.0f} bps — comparable to Sep 2025 spike"),
                (50, "EXTREME_SOFR_SPIKE", "SOFR moved {val:+.0f} bps — major funding crisis (like Sep 2019)"),
            ],
            "weekly_bps_threshold": 10,
            "monthly_bps_threshold": 15,
        },
    },

    # ── Commodities (percentage moves) ───────────────────────────────
    "gold": {
        "gold_price": {
            "type": "pct",
            "label": "Gold Futures",
            "daily_pct_thresholds": [
                (1.5, "NOTABLE_GOLD_MOVE", "Gold moved {val:+.2f}% — notable"),
                (3.0, "SIGNIFICANT_GOLD_MOVE", "Gold moved {val:+.2f}% — significant event-driven move"),
                (5.0, "EXTREME_GOLD_MOVE", "Gold moved {val:+.2f}% — extreme daily move"),
            ],
            "weekly_pct_threshold": 3.0,
            "monthly_pct_threshold": 7.0,
            "distance_from_ma200_pct": 25.0,  # Overbought signal when >25% above 200-day MA
        },
    },

    "silver": {
        "silver_price": {
            "type": "pct",
            "label": "Silver Futures",
            # Silver is ~1.5-2x more volatile than gold
            "daily_pct_thresholds": [
                (2.5, "NOTABLE_SILVER_MOVE", "Silver moved {val:+.2f}% — notable"),
                (5.0, "SIGNIFICANT_SILVER_MOVE", "Silver moved {val:+.2f}% — significant"),
                (7.0, "EXTREME_SILVER_MOVE", "Silver moved {val:+.2f}% — extreme daily move"),
            ],
            "weekly_pct_threshold": 5.0,
            "monthly_pct_threshold": 10.0,
        },
    },

    "crude_oil": {
        "crude_oil_price": {
            "type": "pct",
            "label": "Crude Oil Futures",
            "levels": [
                (50, "below", "OIL_DISTRESSED", "Oil below $50 — distressed; production cuts likely"),
                (55, "below", "OIL_LOW", "Oil below $55 — low; testing major support"),
                (60, "cross", "OIL_60_CROSS", "Oil crossing $60 — key psychological level"),
                (80, "above", "OIL_ELEVATED", "Oil above $80 — elevated; inflationary pressure"),
                (100, "above", "OIL_HIGH", "Oil above $100 — high; stagflation risk"),
            ],
            "daily_pct_thresholds": [
                (2.5, "NOTABLE_OIL_MOVE", "Oil moved {val:+.2f}%"),
                (5.0, "SIGNIFICANT_OIL_MOVE", "Oil moved {val:+.2f}% — significant (geopolitics/OPEC?)"),
                (7.0, "EXTREME_OIL_MOVE", "Oil moved {val:+.2f}% — extreme daily move"),
            ],
            "weekly_pct_threshold": 5.0,
            "monthly_pct_threshold": 10.0,
        },
    },

    "copper": {
        "copper_price": {
            "type": "pct",
            "label": "Copper Futures (Dr. Copper)",
            "levels": [
                (4.0, "below", "COPPER_WEAK", "Copper below $4/lb — weak; global growth concern"),
                (5.0, "cross", "COPPER_5_CROSS", "Copper crossing $5/lb — key breakout/breakdown level"),
                (6.0, "above", "COPPER_STRONG", "Copper above $6/lb — strong; growth and energy transition demand"),
            ],
            "daily_pct_thresholds": [
                (2.0, "NOTABLE_COPPER_MOVE", "Copper moved {val:+.2f}% — Dr. Copper signal"),
                (4.0, "SIGNIFICANT_COPPER_MOVE", "Copper moved {val:+.2f}% — significant global growth signal"),
            ],
            "weekly_pct_threshold": 4.0,
            "monthly_pct_threshold": 8.0,
        },
    },

    # ── COT Positioning ──────────────────────────────────────────────
    "cot_gold": {
        "managed_money_net": {
            "type": "positioning",
            "label": "COT Gold — Managed Money Net Position",
            # We check percentile rank of current position vs history
            "extreme_pct_high": 80,  # Above 80th percentile = crowded long
            "extreme_pct_low": 20,   # Below 20th percentile = crowded short
            "very_extreme_high": 90,
            "very_extreme_low": 10,
            "weekly_change_pct_threshold": 15,  # 15% WoW change in positioning = notable shift
        },
    },

    "cot_silver": {
        "managed_money_net": {
            "type": "positioning",
            "label": "COT Silver — Managed Money Net Position",
            "extreme_pct_high": 80,
            "extreme_pct_low": 20,
            "very_extreme_high": 90,
            "very_extreme_low": 10,
            "weekly_change_pct_threshold": 15,
        },
    },

    # ── Equity Index Metrics ─────────────────────────────────────────
    "sp500_ma200": {
        "price_to_ma200_ratio": {
            "type": "ratio",
            "label": "S&P 500 / 200-Day MA Ratio",
            "levels": [
                (0.90, "below", "DEEPLY_OVERSOLD", "S&P 500 more than 10% below 200-day MA — deeply oversold"),
                (0.95, "below", "BELOW_MA200", "S&P 500 more than 5% below 200-day MA — bearish phase"),
                (0.98, "below", "TESTING_MA200", "S&P 500 testing 200-day MA (within 2%)"),
                (1.00, "cross", "MA200_CROSS", "S&P 500 crossing 200-day MA — trend change signal"),
                (1.10, "above", "EXTENDED_ABOVE_MA", "S&P 500 more than 10% above 200-day MA — extended"),
                (1.25, "above", "OVERBOUGHT_VS_MA", "S&P 500 more than 25% above 200-day MA — historically overbought"),
            ],
        },
    },

    "russell_2000": {
        "value_growth_ratio": {
            "type": "ratio",
            "label": "Russell 2000 Value/Growth Ratio",
            "description": "Rising = value outperforming growth in small caps (reflation signal)",
        },
    },

    "es_futures": {
        "es_price": {
            "type": "pct",
            "label": "ES Futures (S&P 500)",
            "daily_pct_thresholds": [
                (1.0, "NOTABLE_ES_MOVE", "ES moved {val:+.2f}%"),
                (2.0, "SIGNIFICANT_ES_MOVE", "ES moved {val:+.2f}% — significant"),
                (3.0, "LARGE_ES_MOVE", "ES moved {val:+.2f}% — large daily move"),
                (5.0, "EXTREME_ES_MOVE", "ES moved {val:+.2f}% — extreme (circuit-breaker territory)"),
            ],
            "weekly_pct_threshold": 3.0,
            "monthly_pct_threshold": 5.0,
        },
    },

    "rty_futures": {
        "rty_price": {
            "type": "pct",
            "label": "RTY Futures (Russell 2000)",
            # Small caps are ~1.2-1.5x more volatile than large caps
            "daily_pct_thresholds": [
                (1.5, "NOTABLE_RTY_MOVE", "RTY moved {val:+.2f}%"),
                (2.5, "SIGNIFICANT_RTY_MOVE", "RTY moved {val:+.2f}% — significant"),
                (4.0, "LARGE_RTY_MOVE", "RTY moved {val:+.2f}% — large daily move"),
            ],
            "weekly_pct_threshold": 4.0,
            "monthly_pct_threshold": 7.0,
        },
    },

    # ── Valuation Metrics (slow-moving but level-critical) ───────────
    "shiller_cape": {
        "cape_ratio": {
            "type": "level",
            "label": "Shiller CAPE Ratio",
            "levels": [
                (15, "below", "CHEAP_CAPE", "CAPE below 15 — historically cheap; high expected forward returns"),
                (20, "cross", "CAPE_20_CROSS", "CAPE crossing 20 — moving above long-run average"),
                (25, "above", "ELEVATED_CAPE", "CAPE above 25 — only exceeded before 1929, 1999, 2007 peaks"),
                (30, "above", "EXPENSIVE_CAPE", "CAPE above 30 — extreme overvaluation by historical standards"),
                (40, "above", "EXTREME_CAPE", "CAPE above 40 — near all-time record; dot-com peak territory"),
            ],
        },
    },

    "sp500_fundamentals": {
        "pe_ratio_trailing": {
            "type": "level",
            "label": "S&P 500 Trailing P/E",
            "levels": [
                (15, "below", "LOW_PE", "Trailing P/E below 15 — cheap by post-1990 standards"),
                (20, "cross", "PE_20_CROSS", "Trailing P/E crossing 20 — near long-term median (~18)"),
                (25, "above", "ELEVATED_PE", "Trailing P/E above 25 — expensive; associated with market peaks"),
                (30, "above", "HIGH_PE", "Trailing P/E above 30 — very expensive"),
            ],
        },
        "pb_ratio": {
            "type": "level",
            "label": "S&P 500 Price/Book",
            "levels": [
                (2.0, "below", "LOW_PB", "P/B below 2 — cheap"),
                (3.0, "cross", "PB_3_CROSS", "P/B crossing 3 — near historical median (~2.9)"),
                (4.5, "above", "ELEVATED_PB", "P/B above 4.5 — above typical range"),
                (5.5, "above", "EXTREME_PB", "P/B above 5.5 — record territory"),
            ],
        },
    },

    "marketcap_to_gdp": {
        "marketcap_to_gdp_ratio": {
            "type": "level",
            "label": "Market Cap / GDP (Buffett Indicator)",
            "levels": [
                (0.75, "below", "CHEAP_BUFFETT", "Buffett Indicator below 75% — buying zone"),
                (1.0, "cross", "BUFFETT_100_CROSS", "Buffett Indicator crossing 100% — fair value threshold"),
                (1.2, "above", "ELEVATED_BUFFETT", "Buffett Indicator above 120% — critical overvaluation level"),
                (1.5, "above", "HIGH_BUFFETT", "Buffett Indicator above 150% — significantly overvalued"),
                (2.0, "above", "EXTREME_BUFFETT", "Buffett Indicator above 200% — extreme; 'playing with fire' (Buffett)"),
            ],
        },
    },

    # ── Economic Indicators ──────────────────────────────────────────
    "ism_pmi": {
        "ism_pmi": {
            "type": "level",
            "label": "ISM Manufacturing PMI",
            "levels": [
                (42.3, "below", "PMI_RECESSION", "ISM PMI below 42.3 — ~92% historical probability of recession"),
                (47, "below", "PMI_DEEP_CONTRACTION", "ISM PMI below 47 — deep manufacturing contraction"),
                (50, "cross", "PMI_50_CROSS", "ISM PMI crossing 50 — expansion/contraction threshold"),
                (55, "above", "PMI_STRONG_EXPANSION", "ISM PMI above 55 — strong manufacturing expansion"),
            ],
            # PMI is monthly — a 2-point move is notable
            "monthly_point_threshold": 2.0,
            "large_monthly_move": 3.0,
        },
    },

    "us_gdp": {
        "us_gdp": {
            "type": "level",
            "label": "US GDP",
            "description": "GDP is quarterly. Watch for negative growth and deceleration/acceleration patterns.",
        },
    },

    # ── Liquidity Indicators (flow-sensitive) ────────────────────────
    "tga_balance": {
        "tga_balance": {
            "type": "flow",
            "label": "Treasury General Account Balance",
            "levels": [
                (100_000, "below", "TGA_NEAR_EMPTY", "TGA below $100B — near-empty; debt ceiling standoff?"),
                (400_000, "below", "TGA_LOW", "TGA below $400B — below normal operating range"),
                (800_000, "above", "TGA_HIGH", "TGA above $800B — repo tightening risk"),
                (1_000_000, "above", "TGA_VERY_HIGH", "TGA above $1T — significant liquidity drain from private sector"),
            ],
            # TGA: $50B+ weekly swing is notable; $200B+ monthly is a liquidity event
            "weekly_abs_threshold": 50_000,   # $50B
            "monthly_abs_threshold": 200_000,  # $200B
            "direction_matters": True,  # Falling TGA = bullish (liquidity into system)
        },
    },

    "net_liquidity": {
        "net_liquidity": {
            "type": "flow",
            "label": "Fed Net Liquidity",
            # Net liquidity: $100B+ monthly swing matters
            "weekly_abs_threshold": 50_000,   # $50B
            "monthly_abs_threshold": 100_000,  # $100B
            "direction_matters": True,  # Rising = risk-on; Falling = risk-off
        },
    },

    # ── CBOE SKEW ────────────────────────────────────────────────────
    "cboe_skew": {
        "cboe_skew": {
            "type": "level",
            "label": "CBOE SKEW Index",
            "levels": [
                (100, "below", "LOW_SKEW", "SKEW near 100 — negligible tail risk perceived"),
                (115, "cross", "SKEW_ABOVE_AVG", "SKEW crossing 115 — above historical average"),
                (130, "above", "ELEVATED_SKEW", "SKEW above 130 — elevated tail risk; significant hedging activity"),
                (140, "above", "HIGH_SKEW", "SKEW above 140 — extreme tail risk (1998 Russian crisis = 147)"),
            ],
            "daily_point_thresholds": [
                (3.0, "NOTABLE_SKEW_MOVE", "SKEW moved {val:+.1f} pts"),
                (5.0, "SIGNIFICANT_SKEW_MOVE", "SKEW moved {val:+.1f} pts — significant shift in tail risk pricing"),
            ],
        },
    },

    # ── Market Cap (standalone) ──────────────────────────────────────
    "market_cap": {},
}


# ═══════════════════════════════════════════════════════════════════════
# CROSS-ASSET SIGNAL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

CROSS_ASSET_SIGNALS = [
    {
        "name": "VIX_MOVE_DUAL_SPIKE",
        "description": "Both VIX and MOVE elevated simultaneously — high-stress regime. MOVE leading VIX = bond market smells trouble first.",
        "conditions": {"vix_above": 20, "move_above": 120},
    },
    {
        "name": "CARRY_TRADE_UNWIND_RISK",
        "description": "Narrowing US-JP spread + VIX rising = carry trade unwind risk. Can trigger sharp USD/JPY decline.",
        "conditions": {"spread_narrowing_wow_bps": 10, "vix_rising": True},
    },
    {
        "name": "RISK_OFF_TRIFECTA",
        "description": "Gold/silver ratio rising + VIX rising + DXY rising = broad risk-off signal.",
        "conditions": {"gold_silver_ratio_rising": True, "vix_rising": True, "dxy_rising": True},
    },
    {
        "name": "LIQUIDITY_DRAIN",
        "description": "TGA rising (drain) + net liquidity falling = double liquidity squeeze. Historically pressures risk assets.",
        "conditions": {"tga_rising": True, "net_liquidity_falling": True},
    },
    {
        "name": "INDUSTRIAL_SLOWDOWN",
        "description": "Copper + Oil + ISM PMI all declining = manufacturing/industrial slowdown confirmed.",
        "conditions": {"copper_falling": True, "oil_falling": True, "pmi_below_50": True},
    },
    {
        "name": "NARROW_BREADTH_WARNING",
        "description": "ES (large cap) making new highs while RTY (small cap) diverges downward = narrow, fragile rally.",
        "conditions": {"es_near_high": True, "rty_underperforming": True},
    },
]


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def _load_csv(filename: str) -> pd.DataFrame | None:
    """Load a CSV from historical_data, return None on failure."""
    path = os.path.join(HISTORICAL_DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if "timestamp" in df.columns:
            # Use utc=True to handle mixed-timezone timestamps (e.g.
            # -05:00 EST and -04:00 EDT from DST transitions).  Without
            # this, pd.to_datetime coerces mismatched offsets to NaT,
            # silently dropping the newest data points.
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], errors="coerce", utc=True
            )
        return df
    except Exception:
        return None


def _safe_pct(old, new, max_abs_pct: float | None = None) -> float | None:
    """Percentage change, None if incalculable or implausible.

    If *max_abs_pct* is given, absolute percentage changes exceeding
    the cap are returned as None (treated as bad data rather than a
    real move).
    """
    if old is None or new is None or pd.isna(old) or pd.isna(new) or old == 0:
        return None
    pct = round(((new - old) / abs(old)) * 100, 3)
    if max_abs_pct is not None and abs(pct) > max_abs_pct:
        return None
    return pct


def _safe_diff(old, new) -> float | None:
    """Absolute difference, None if incalculable."""
    if old is None or new is None or pd.isna(old) or pd.isna(new):
        return None
    return round(new - old, 4)


# ═══════════════════════════════════════════════════════════════════════
# INDICATOR-SPECIFIC FLAG GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def _check_absolute_levels(value: float, rules: dict) -> list[str]:
    """Check value against absolute level thresholds."""
    flags = []
    for level, direction, code, msg in rules.get("levels", []):
        if direction == "above" and value > level:
            flags.append(f"{code}: {msg}")
        elif direction == "below" and value < level:
            flags.append(f"{code}: {msg}")
        elif direction == "cross":
            pass  # Cross detection needs previous value — handled separately
    return flags


def _check_level_cross(prev_value: float | None, curr_value: float, rules: dict) -> list[str]:
    """Detect if value crossed a key level between prev and curr."""
    if prev_value is None:
        return []
    flags = []
    for level, direction, code, msg in rules.get("levels", []):
        if direction == "cross":
            if (prev_value < level <= curr_value) or (prev_value > level >= curr_value):
                cross_dir = "upward" if curr_value > prev_value else "downward"
                flags.append(f"{code}: {msg} ({cross_dir} cross)")
    return flags


def _check_point_moves(daily_diff, weekly_diff, monthly_diff, rules: dict) -> list[str]:
    """Check absolute point moves against thresholds."""
    flags = []
    if daily_diff is not None:
        direction = "up" if daily_diff > 0 else "down"
        for threshold, code, template in rules.get("daily_point_thresholds", []):
            if abs(daily_diff) >= threshold:
                flags.append(f"{code}: {template.format(dir=direction, val=abs(daily_diff))}")
    if weekly_diff is not None and rules.get("weekly_point_threshold"):
        if abs(weekly_diff) >= rules["weekly_point_threshold"]:
            direction = "up" if weekly_diff > 0 else "down"
            flags.append(f"WEEKLY_POINT_MOVE: Moved {direction} {abs(weekly_diff):.1f} pts WoW")
    if monthly_diff is not None and rules.get("monthly_point_threshold"):
        if abs(monthly_diff) >= rules["monthly_point_threshold"]:
            direction = "up" if monthly_diff > 0 else "down"
            flags.append(f"MONTHLY_POINT_MOVE: Moved {direction} {abs(monthly_diff):.1f} pts MoM")
    return flags


def _check_bps_moves(daily_diff, weekly_diff, monthly_diff, rules: dict) -> list[str]:
    """Check basis-point moves for yield/rate indicators."""
    flags = []
    if daily_diff is not None:
        bps = daily_diff * 100  # Convert from decimal (e.g. 0.05 = 5 bps)
        for threshold, code, template in rules.get("daily_bps_thresholds", []):
            if abs(bps) >= threshold:
                flags.append(f"{code}: {template.format(val=bps)}")
    if weekly_diff is not None and rules.get("weekly_bps_threshold"):
        bps = weekly_diff * 100
        if abs(bps) >= rules["weekly_bps_threshold"]:
            flags.append(f"WEEKLY_BPS_MOVE: {bps:+.0f} bps WoW")
    if monthly_diff is not None and rules.get("monthly_bps_threshold"):
        bps = monthly_diff * 100
        if abs(bps) >= rules["monthly_bps_threshold"]:
            flags.append(f"MONTHLY_BPS_MOVE: {bps:+.0f} bps MoM")
    return flags


def _check_pct_moves(daily_pct, weekly_pct, monthly_pct, rules: dict) -> list[str]:
    """Check percentage moves against indicator-specific thresholds."""
    flags = []
    if daily_pct is not None:
        for threshold, code, template in rules.get("daily_pct_thresholds", []):
            if abs(daily_pct) >= threshold:
                flags.append(f"{code}: {template.format(val=daily_pct)}")
    if weekly_pct is not None and rules.get("weekly_pct_threshold"):
        if abs(weekly_pct) >= rules["weekly_pct_threshold"]:
            flags.append(f"WEEKLY_PCT_MOVE: {weekly_pct:+.2f}% WoW")
    if monthly_pct is not None and rules.get("monthly_pct_threshold"):
        if abs(monthly_pct) >= rules["monthly_pct_threshold"]:
            flags.append(f"MONTHLY_PCT_MOVE: {monthly_pct:+.2f}% MoM")
    return flags


def _check_flow_moves(series: pd.Series, rules: dict) -> list[str]:
    """Check absolute value changes for flow indicators (TGA, net liquidity)."""
    flags = []
    if len(series) < 2:
        return flags

    latest = float(series.iloc[-1])
    prev_1w = float(series.iloc[-6]) if len(series) >= 6 else None
    prev_1m = float(series.iloc[-22]) if len(series) >= 22 else None

    if prev_1w is not None and rules.get("weekly_abs_threshold"):
        diff = latest - prev_1w
        if abs(diff) >= rules["weekly_abs_threshold"]:
            direction = "rising" if diff > 0 else "falling"
            flags.append(f"WEEKLY_FLOW: {rules.get('label', '')} {direction} by ${abs(diff)/1000:.0f}B WoW")
            if rules.get("direction_matters"):
                if "tga" in rules.get("label", "").lower():
                    impact = "liquidity drain" if diff > 0 else "liquidity injection"
                else:
                    impact = "risk-on" if diff > 0 else "risk-off"
                flags.append(f"LIQUIDITY_SIGNAL: {impact}")

    if prev_1m is not None and rules.get("monthly_abs_threshold"):
        diff = latest - prev_1m
        if abs(diff) >= rules["monthly_abs_threshold"]:
            direction = "rising" if diff > 0 else "falling"
            flags.append(f"MONTHLY_FLOW: {rules.get('label', '')} {direction} by ${abs(diff)/1000:.0f}B MoM — liquidity event")

    return flags


def _check_positioning(series: pd.Series, rules: dict) -> list[str]:
    """Check COT positioning for extremes using percentile rank."""
    flags = []
    if len(series) < 10:
        return flags

    latest = float(series.iloc[-1])
    # Use available history for percentile calculation (up to 3 years ~ 156 weekly data points)
    lookback = min(len(series), 156)
    history = series.tail(lookback)
    percentile = (history < latest).sum() / len(history) * 100

    if percentile >= rules.get("very_extreme_high", 95):
        flags.append(f"VERY_EXTREME_LONG: Positioning at {percentile:.0f}th percentile — contrarian bearish signal")
    elif percentile >= rules.get("extreme_pct_high", 80):
        flags.append(f"CROWDED_LONG: Positioning at {percentile:.0f}th percentile — potential for unwinding")
    elif percentile <= rules.get("very_extreme_low", 5):
        flags.append(f"VERY_EXTREME_SHORT: Positioning at {percentile:.0f}th percentile — contrarian bullish signal")
    elif percentile <= rules.get("extreme_pct_low", 20):
        flags.append(f"CROWDED_SHORT: Positioning at {percentile:.0f}th percentile — potential for short squeeze")

    # WoW change in positioning
    if len(series) >= 2:
        prev = float(series.iloc[-2])
        if prev != 0:
            pct_change = abs((latest - prev) / abs(prev)) * 100
            threshold = rules.get("weekly_change_pct_threshold", 15)
            if pct_change >= threshold:
                direction = "increased" if latest > prev else "decreased"
                flags.append(f"LARGE_POSITION_SHIFT: Net position {direction} by {pct_change:.1f}% WoW")

    return flags


# ═══════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def list_available_indicators() -> str:
    """List all macroeconomic indicator CSV files available in historical_data.

    Returns indicator names, file sizes, row counts, and date ranges.
    """
    results = []
    for key, label in MACRO_INDICATORS.items():
        path = os.path.join(HISTORICAL_DATA_DIR, f"{key}.csv")
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                results.append({
                    "key": key,
                    "label": label,
                    "rows": len(df),
                    "columns": list(df.columns),
                })
            except Exception as e:
                results.append({"key": key, "label": label, "error": str(e)})
        else:
            results.append({"key": key, "label": label, "status": "file_not_found"})
    return json.dumps(results, indent=2)


def read_indicator_data(indicator_key: str, rows: int = 30) -> str:
    """Read the most recent N rows from a macro indicator CSV.

    Args:
        indicator_key: CSV filename without extension (e.g. 'vix_move', 'gold').
                       Common aliases supported (e.g. 'vix' → 'vix_move').
        rows: Number of recent rows to return (default 30).

    Returns the data as JSON with column names and values.
    """
    indicator_key = _resolve_indicator_key(indicator_key)
    df = _load_csv(f"{indicator_key}.csv")
    if df is None:
        available = ", ".join(sorted(MACRO_INDICATORS.keys()))
        return json.dumps({"error": f"Indicator '{indicator_key}' not found. Available: {available}"})

    for col in ["timestamp", "date"]:
        if col in df.columns:
            df = df.sort_values(col, ascending=False)
            break

    recent = df.head(int(rows))
    # Round numeric columns to 4dp to avoid float32 precision artifacts
    numeric_cols = recent.select_dtypes(include=["float64", "float32"]).columns
    recent = recent.copy()
    recent[numeric_cols] = recent[numeric_cols].round(4)
    return json.dumps({
        "indicator": MACRO_INDICATORS.get(indicator_key, indicator_key),
        "rows_returned": len(recent),
        "columns": list(recent.columns),
        "data": recent.to_dict(orient="records"),
    }, indent=2, default=str)


def analyze_indicator_changes(indicator_key: str) -> str:
    """Analyze an indicator using indicator-specific rules and thresholds.

    Applies the appropriate detection strategy based on the indicator type:
    - VIX: absolute levels (12/20/30/40) + point moves
    - Yields: basis-point moves + level thresholds
    - Commodities: percentage moves + absolute price levels
    - COT: percentile-based positioning extremes
    - Liquidity: absolute dollar flow changes
    Plus standard z-score and 52-week extreme detection for all.

    Args:
        indicator_key: CSV filename without extension (e.g. 'vix_move', 'gold').
                       Common aliases are supported (e.g. 'vix' → 'vix_move',
                       '10y_yield' → '10y_treasury_yield').
    """
    indicator_key = _resolve_indicator_key(indicator_key)

    df = _load_csv(f"{indicator_key}.csv")
    if df is None:
        available = ", ".join(sorted(MACRO_INDICATORS.keys()))
        return json.dumps({"error": f"Indicator '{indicator_key}' not found. Available: {available}"})

    time_cols = {"timestamp", "date"}
    value_cols = [c for c in df.columns if c not in time_cols and df[c].dtype in [np.float64, np.int64, float, int]]
    if not value_cols:
        return json.dumps({"error": "No numeric columns found", "columns": list(df.columns)})

    for col in ["timestamp", "date"]:
        if col in df.columns:
            df = df.sort_values(col, ascending=True)
            break

    # Get indicator-specific rules
    indicator_rules = INDICATOR_RULES.get(indicator_key, {})

    analysis = {
        "indicator": MACRO_INDICATORS.get(indicator_key, indicator_key),
        "total_rows": len(df),
        "metrics": {},
    }

    for col in value_cols:
        series = df[col].dropna()
        if len(series) < 5:
            continue

        latest = float(series.iloc[-1])
        prev_1d = float(series.iloc[-2]) if len(series) >= 2 else None
        prev_1w = float(series.iloc[-6]) if len(series) >= 6 else None
        prev_1m = float(series.iloc[-22]) if len(series) >= 22 else None
        prev_3m = float(series.iloc[-66]) if len(series) >= 66 else None

        daily_diff = _safe_diff(prev_1d, latest)
        weekly_diff = _safe_diff(prev_1w, latest)
        monthly_diff = _safe_diff(prev_1m, latest)

        daily_pct = _safe_pct(prev_1d, latest, max_abs_pct=50.0)
        weekly_pct = _safe_pct(prev_1w, latest, max_abs_pct=80.0)
        monthly_pct = _safe_pct(prev_1m, latest, max_abs_pct=100.0)

        # Rolling stats for statistical anomaly detection (20-day)
        rolling_mean = series.rolling(20).mean()
        rolling_std = series.rolling(20).std()
        z_score = None
        if len(rolling_mean) >= 20 and not pd.isna(rolling_std.iloc[-1]) and rolling_std.iloc[-1] > 0:
            z_score = round((latest - rolling_mean.iloc[-1]) / rolling_std.iloc[-1], 2)

        # 52-week high/low
        last_252 = series.tail(252)
        high_52w = float(last_252.max())
        low_52w = float(last_252.min())
        pct_from_high = _safe_pct(high_52w, latest)
        pct_from_low = _safe_pct(low_52w, latest)

        def _r2(v):
            """Round to 2 decimal places if not None."""
            return round(v, 2) if v is not None else None

        metric = {
            "latest_value": _r2(latest),
            "daily_change": _r2(daily_diff),
            "daily_change_pct": _r2(daily_pct),
            "wow_change": _r2(weekly_diff),
            "wow_change_pct": _r2(weekly_pct),
            "mom_change": _r2(monthly_diff),
            "mom_change_pct": _r2(monthly_pct),
            "3m_change_pct": _r2(_safe_pct(prev_3m, latest)),
            "z_score_20d": z_score,
            "52w_high": _r2(high_52w),
            "52w_low": _r2(low_52w),
            "pct_from_52w_high": _r2(pct_from_high),
            "pct_from_52w_low": _r2(pct_from_low),
            "flags": [],
        }

        # Get column-specific rules
        col_rules = indicator_rules.get(col, {})
        rule_type = col_rules.get("type", "generic")

        # ── Apply indicator-specific rules ──
        if rule_type in ("absolute", "level"):
            metric["flags"].extend(_check_absolute_levels(latest, col_rules))
            metric["flags"].extend(_check_level_cross(prev_1d, latest, col_rules))

        if rule_type == "absolute" or col_rules.get("daily_point_thresholds"):
            metric["flags"].extend(_check_point_moves(daily_diff, weekly_diff, monthly_diff, col_rules))

        if rule_type == "bps":
            metric["flags"].extend(_check_bps_moves(daily_diff, weekly_diff, monthly_diff, col_rules))
            metric["flags"].extend(_check_absolute_levels(latest, col_rules))
            metric["flags"].extend(_check_level_cross(prev_1d, latest, col_rules))

        if rule_type == "pct" or col_rules.get("daily_pct_thresholds"):
            metric["flags"].extend(_check_pct_moves(daily_pct, weekly_pct, monthly_pct, col_rules))
            metric["flags"].extend(_check_absolute_levels(latest, col_rules))
            metric["flags"].extend(_check_level_cross(prev_1d, latest, col_rules))

        if rule_type == "flow":
            metric["flags"].extend(_check_flow_moves(series, col_rules))
            metric["flags"].extend(_check_absolute_levels(latest, col_rules))

        if rule_type == "positioning":
            metric["flags"].extend(_check_positioning(series, col_rules))

        if rule_type == "ratio":
            metric["flags"].extend(_check_absolute_levels(latest, col_rules))
            metric["flags"].extend(_check_level_cross(prev_1d, latest, col_rules))

        # ── Statistical anomaly (always applied as a backstop) ──
        if z_score is not None and abs(z_score) > 2.0:
            direction = "spike" if z_score > 0 else "plunge"
            metric["flags"].append(f"STATISTICAL_ANOMALY: {col} {direction} (z={z_score}, 20-day)")
        elif z_score is not None and abs(z_score) > 1.5:
            direction = "elevated" if z_score > 0 else "depressed"
            metric["flags"].append(f"STATISTICAL_WATCH: {col} {direction} (z={z_score}, 20-day)")

        # ── 52-week proximity (always applied) ──
        if pct_from_high is not None:
            if abs(pct_from_high) < 1.0:
                metric["flags"].append(f"AT_52W_HIGH: Within 1% of 52-week high ({_r2(high_52w)})")
            elif abs(pct_from_high) < 3.0:
                metric["flags"].append(f"NEAR_52W_HIGH: Within 3% of 52-week high ({_r2(high_52w)})")
        if pct_from_low is not None:
            if abs(pct_from_low) < 1.0:
                metric["flags"].append(f"AT_52W_LOW: Within 1% of 52-week low ({_r2(low_52w)})")
            elif abs(pct_from_low) < 3.0:
                metric["flags"].append(f"NEAR_52W_LOW: Within 3% of 52-week low ({_r2(low_52w)})")

        # ── Fallback: generic large move detection for unconfigured indicators ──
        if rule_type == "generic":
            if daily_pct is not None and abs(daily_pct) > 3.0:
                metric["flags"].append(f"LARGE_DAILY_MOVE: {daily_pct:+.2f}%")
            elif daily_pct is not None and abs(daily_pct) > 1.5:
                metric["flags"].append(f"NOTABLE_DAILY_MOVE: {daily_pct:+.2f}%")
            if weekly_pct is not None and abs(weekly_pct) > 5.0:
                metric["flags"].append(f"LARGE_WEEKLY_MOVE: {weekly_pct:+.2f}% WoW")
            if monthly_pct is not None and abs(monthly_pct) > 10.0:
                metric["flags"].append(f"LARGE_MONTHLY_MOVE: {monthly_pct:+.2f}% MoM")

        # Deduplicate flags (keep highest severity per threshold cascade)
        metric["flags"] = list(dict.fromkeys(metric["flags"]))

        analysis["metrics"][col] = metric

    return json.dumps(analysis, indent=2, default=str)


# ── Flag severity ranking (for short-mode top-flag selection) ────────

_FLAG_SEVERITY_ORDER = [
    "CRISIS", "EXTREME", "HIGH_FEAR", "SIGNIFICANT",
    "LARGE_DAILY", "LARGE_WEEKLY", "LARGE_MONTHLY",
    "STATISTICAL_ANOMALY", "AT_52W_HIGH", "AT_52W_LOW",
    "ELEVATED", "NEAR_52W_HIGH", "NEAR_52W_LOW",
    "NOTABLE", "STATISTICAL_WATCH", "COMPLACENCY",
]


def _rank_flag_severity(flag_str: str) -> int:
    """Return numeric sort priority for a flag string (lower = more severe).

    Flag format: "metric_name: FLAG_PREFIX_REST: description"
    We check which severity keyword the flag text starts with (after the
    metric prefix) and return its rank from _FLAG_SEVERITY_ORDER.
    """
    upper = flag_str.upper()
    for rank, prefix in enumerate(_FLAG_SEVERITY_ORDER):
        if prefix in upper:
            return rank
    return len(_FLAG_SEVERITY_ORDER)  # unknown flags sort last


def _get_top_flags(flags: list[str], max_flags: int = 3) -> list[str]:
    """Sort flags by severity and return the top N."""
    return sorted(flags, key=_rank_flag_severity)[:max_flags]


# ── Follow-up suggestion mapping (indicator key → slash commands) ────

INDICATOR_FOLLOWUP_MAP: dict[str, dict] = {
    "vix_move": {
        "commands": ["/stress", "/vixanalysis"],
        "trigger_label": "VIX/MOVE flagged",
        "reason": "Volatility elevated — check composite stress score and VIX opportunity tier",
    },
    "cboe_skew": {
        "commands": ["/vixanalysis"],
        "trigger_label": "CBOE SKEW flagged",
        "reason": "Options skew abnormal — check vol regime",
    },
    "10y_treasury_yield": {
        "commands": ["/bonds", "/termpremium"],
        "trigger_label": "10Y yield flagged",
        "reason": "Treasury yield move — check yield curve and term premium dynamics",
    },
    "us_2y_yield": {
        "commands": ["/bonds", "/termpremium"],
        "trigger_label": "2Y yield flagged",
        "reason": "Front-end yield move — check curve shape and Fed policy stance",
    },
    "sofr": {
        "commands": ["/bonds"],
        "trigger_label": "SOFR flagged",
        "reason": "Funding rate move — check money market conditions",
    },
    "japan_2y_yield": {
        "commands": ["/bonds"],
        "trigger_label": "Japan 2Y yield flagged",
        "reason": "BoJ policy signal — check carry trade implications",
    },
    "us2y_jp2y_spread": {
        "commands": ["/bonds"],
        "trigger_label": "US-JP spread flagged",
        "reason": "Carry trade spread moving — check bond market stress",
    },
    "crude_oil": {
        "commands": ["/commodity crude_oil", "/oil"],
        "trigger_label": "Crude oil flagged",
        "reason": "Oil abnormality — check fundamentals, inventories, and XLE/XOP divergence",
    },
    "gold": {
        "commands": ["/commodity gold"],
        "trigger_label": "Gold flagged",
        "reason": "Gold move — check commodity outlook and safe-haven flows",
    },
    "silver": {
        "commands": ["/commodity silver"],
        "trigger_label": "Silver flagged",
        "reason": "Silver move — check commodity outlook and gold/silver ratio",
    },
    "copper": {
        "commands": ["/commodity copper", "/bbb"],
        "trigger_label": "Copper flagged",
        "reason": "Copper move — check commodity outlook and boom-bust barometer",
    },
    "cot_gold": {
        "commands": ["/commodity gold"],
        "trigger_label": "Gold positioning extreme",
        "reason": "COT gold at extreme — check for contrarian signal",
    },
    "cot_silver": {
        "commands": ["/commodity silver"],
        "trigger_label": "Silver positioning extreme",
        "reason": "COT silver at extreme — check for contrarian signal",
    },
    "es_futures": {
        "commands": ["/drivers SPX", "/stress", "/drawdown"],
        "trigger_label": "S&P 500 futures flagged",
        "reason": "S&P 500 move — check equity drivers, stress, and drawdown classification",
    },
    "rty_futures": {
        "commands": ["/drivers russell_2000"],
        "trigger_label": "Russell 2000 futures flagged",
        "reason": "Small-cap move — check equity index drivers for breadth signal",
    },
    "russell_2000": {
        "commands": ["/drivers russell_2000"],
        "trigger_label": "Russell 2000 flagged",
        "reason": "Small-cap index move — check breadth and rotation signals",
    },
    "sp500_ma200": {
        "commands": ["/drivers SPX", "/drawdown"],
        "trigger_label": "S&P 500 / 200MA flagged",
        "reason": "Price vs trend signal — check drawdown classification",
    },
    "shiller_cape": {
        "commands": ["/valuation"],
        "trigger_label": "Shiller CAPE flagged",
        "reason": "Valuation extreme — check Yardeni valuation frameworks",
    },
    "sp500_fundamentals": {
        "commands": ["/valuation"],
        "trigger_label": "S&P 500 P/E or P/B flagged",
        "reason": "Valuation shift — check Rule of 20/24 valuation",
    },
    "market_cap": {
        "commands": ["/valuation"],
        "trigger_label": "Total market cap flagged",
        "reason": "Market cap shift — check valuation frameworks",
    },
    "marketcap_to_gdp": {
        "commands": ["/valuation"],
        "trigger_label": "Buffett Indicator flagged",
        "reason": "Market cap to GDP ratio moved — check valuation",
    },
    "dxy": {
        "commands": ["/macro", "/drivers SPX"],
        "trigger_label": "DXY flagged",
        "reason": "Dollar move — check macro regime and equity impact",
    },
    "jpy": {
        "commands": ["/bonds", "/macro"],
        "trigger_label": "USD/JPY flagged",
        "reason": "Yen move — check carry trade and macro regime",
    },
    "ism_pmi": {
        "commands": ["/macro", "/latecycle", "/bbb"],
        "trigger_label": "ISM PMI flagged",
        "reason": "Manufacturing signal — check macro regime, late-cycle, and boom-bust barometer",
    },
    "us_gdp": {
        "commands": ["/macro", "/vigilantes"],
        "trigger_label": "GDP flagged",
        "reason": "GDP move — check macro regime and bond vigilantes model",
    },
    "tga_balance": {
        "commands": ["/macro"],
        "trigger_label": "TGA balance flagged",
        "reason": "Treasury account move — check liquidity regime",
    },
    "net_liquidity": {
        "commands": ["/macro"],
        "trigger_label": "Net liquidity flagged",
        "reason": "Fed liquidity change — check macro regime",
    },
}


def _generate_followup_suggestions(flagged_items: list[dict]) -> list[dict]:
    """Generate follow-up command suggestions based on flagged indicators.

    Iterates over flagged indicators, looks up the INDICATOR_FOLLOWUP_MAP,
    deduplicates commands, and returns a list of suggestion dicts.
    """
    suggestions = []
    seen_commands: set[str] = set()

    for item in flagged_items:
        key = item.get("key", "")
        mapping = INDICATOR_FOLLOWUP_MAP.get(key)
        if not mapping:
            continue

        # Deduplicate: skip if all commands already suggested
        new_commands = [c for c in mapping["commands"] if c not in seen_commands]
        if not new_commands:
            continue

        seen_commands.update(new_commands)
        suggestions.append({
            "trigger": mapping["trigger_label"],
            "commands": new_commands,
            "reason": mapping["reason"],
        })

    return suggestions


def get_followup_commands(indicator_keys: list[str]) -> list[dict]:
    """Public helper: get follow-up suggestions for a list of indicator keys.

    Used by telegram_bot.py which builds its own flagged list structure.
    """
    items = [{"key": k} for k in indicator_keys]
    return _generate_followup_suggestions(items)


def scan_all_indicators(mode: str = "short") -> str:
    """Scan ALL macro indicators for abnormalities using indicator-specific rules.

    Performs the full analysis on every indicator and returns:
    1. Flagged indicators with their specific alerts
    2. Cross-asset signals when multiple indicators align
    3. Follow-up suggestions for deeper analysis (both modes)
    4. A summary of all normal indicators (full mode only)

    This is the primary monitoring sweep tool.

    Args:
        mode: 'short' (default) — top flags per indicator + follow-up suggestions.
              'full' — complete detail for every indicator.
    """
    flagged = []
    summary = []
    all_data = {}  # Cache for cross-asset checks

    for key in MACRO_INDICATORS:
        raw = analyze_indicator_changes(key)
        data = json.loads(raw)
        if "error" in data:
            continue

        all_data[key] = data

        has_flags = False
        indicator_flags = []
        for metric_name, metric in data.get("metrics", {}).items():
            if metric.get("flags"):
                has_flags = True
                indicator_flags.extend(
                    [f"{metric_name}: {f}" for f in metric["flags"]]
                )

        summary_entry = {
            "indicator": data["indicator"],
            "key": key,
        }

        metrics = data.get("metrics", {})
        if metrics:
            first_metric = next(iter(metrics.values()))
            summary_entry["latest"] = first_metric["latest_value"]
            summary_entry["daily_change"] = first_metric.get("daily_change")
            summary_entry["daily_pct"] = first_metric["daily_change_pct"]
            summary_entry["wow_pct"] = first_metric["wow_change_pct"]
            summary_entry["mom_pct"] = first_metric["mom_change_pct"]

        if has_flags:
            summary_entry["flags"] = indicator_flags
            flagged.append(summary_entry)
        else:
            summary.append(summary_entry)

    # ── Cross-Asset Signal Detection ──
    cross_signals = _detect_cross_asset_signals(all_data)

    # ── Build output based on mode ──
    if mode == "full":
        suggestions = _generate_followup_suggestions(flagged)
        return json.dumps({
            "scan_time": datetime.now().isoformat(),
            "mode": "full",
            "total_indicators": len(MACRO_INDICATORS),
            "flagged_count": len(flagged),
            "flagged_indicators": flagged,
            "cross_asset_signals": cross_signals,
            "normal_indicators_summary": summary,
            "follow_up_suggestions": suggestions,
        }, indent=2, default=str)

    # Short mode: trim flags, add follow-up suggestions
    short_flagged = []
    for item in flagged:
        short_flagged.append({
            "indicator": item["indicator"],
            "key": item["key"],
            "latest": item.get("latest"),
            "daily_pct": item.get("daily_pct"),
            "top_flags": _get_top_flags(item.get("flags", []), max_flags=3),
        })

    suggestions = _generate_followup_suggestions(flagged)

    return json.dumps({
        "scan_time": datetime.now().isoformat(),
        "mode": "short",
        "total_indicators": len(MACRO_INDICATORS),
        "flagged_count": len(short_flagged),
        "flagged_indicators": short_flagged,
        "cross_asset_signals": cross_signals,
        "normal_count": len(summary),
        "follow_up_suggestions": suggestions,
    }, indent=2, default=str)


def _detect_cross_asset_signals(all_data: dict) -> list[dict]:
    """Check for cross-asset alignment signals."""
    signals = []

    def _get_latest(key, col):
        data = all_data.get(key, {})
        metrics = data.get("metrics", {})
        m = metrics.get(col, {})
        return m.get("latest_value")

    def _get_change(key, col, period="wow_change_pct"):
        data = all_data.get(key, {})
        metrics = data.get("metrics", {})
        m = metrics.get(col, {})
        return m.get(period)

    vix = _get_latest("vix_move", "vix")
    move = _get_latest("vix_move", "move")
    dxy_pct = _get_change("dxy", "dxy")
    spread_change = _get_change("us2y_jp2y_spread", "spread", "wow_change")
    copper_pct = _get_change("copper", "copper_price")
    oil_pct = _get_change("crude_oil", "crude_oil_price")
    pmi = _get_latest("ism_pmi", "ism_pmi")
    tga_change = _get_change("tga_balance", "tga_balance", "wow_change")
    netliq_change = _get_change("net_liquidity", "net_liquidity", "wow_change")
    gold = _get_latest("gold", "gold_price")
    silver = _get_latest("silver", "silver_price")
    rty_pct = _get_change("rty_futures", "rty_price")
    es_pct = _get_change("es_futures", "es_price")

    # Check 52w high proximity for ES
    es_data = all_data.get("es_futures", {}).get("metrics", {}).get("es_price", {})
    es_pct_from_high = es_data.get("pct_from_52w_high") if es_data else None

    # 1. VIX + MOVE dual spike
    if vix is not None and move is not None:
        if vix > 20 and move > 120:
            signals.append({
                "signal": "VIX_MOVE_DUAL_SPIKE",
                "severity": "HIGH",
                "detail": f"VIX={vix:.1f} (>20) and MOVE={move:.1f} (>120) — both elevated; high-stress regime",
            })

    # 2. Carry trade unwind risk
    if spread_change is not None and vix is not None:
        vix_wow = _get_change("vix_move", "vix")
        if spread_change < 0 and vix_wow is not None and vix_wow > 0:
            signals.append({
                "signal": "CARRY_TRADE_STRESS",
                "severity": "MEDIUM",
                "detail": f"US-JP spread narrowing ({spread_change:+.2f} WoW) while VIX rising — carry trade unwind risk",
            })

    # 3. Risk-off trifecta (gold/silver ratio rising + VIX rising + DXY rising)
    if gold is not None and silver is not None and silver > 0:
        gs_ratio = gold / silver
        vix_wow = _get_change("vix_move", "vix")
        if vix_wow is not None and vix_wow > 0 and dxy_pct is not None and dxy_pct > 0:
            if gs_ratio > 70:
                signals.append({
                    "signal": "RISK_OFF_TRIFECTA",
                    "severity": "HIGH",
                    "detail": f"Gold/Silver ratio={gs_ratio:.1f} (>70) + VIX rising + DXY rising — broad risk-off",
                })

    # 4. Liquidity drain
    if tga_change is not None and netliq_change is not None:
        if tga_change > 0 and netliq_change < 0:
            signals.append({
                "signal": "LIQUIDITY_DRAIN",
                "severity": "MEDIUM",
                "detail": f"TGA rising (${tga_change/1000:+.0f}B WoW) + net liquidity falling (${netliq_change/1000:+.0f}B WoW) — double squeeze",
            })

    # 5. Industrial slowdown
    if copper_pct is not None and oil_pct is not None and pmi is not None:
        if copper_pct < 0 and oil_pct < 0 and pmi < 50:
            signals.append({
                "signal": "INDUSTRIAL_SLOWDOWN",
                "severity": "HIGH",
                "detail": f"Copper ({copper_pct:+.1f}% WoW) + Oil ({oil_pct:+.1f}% WoW) falling; PMI={pmi:.1f} (<50) — industrial slowdown confirmed",
            })

    # 6. Narrow breadth warning
    if es_pct_from_high is not None and rty_pct is not None:
        if abs(es_pct_from_high) < 3 and rty_pct < -2:
            signals.append({
                "signal": "NARROW_BREADTH",
                "severity": "MEDIUM",
                "detail": f"ES near 52w high (within {abs(es_pct_from_high):.1f}%) while RTY falling ({rty_pct:+.1f}% WoW) — narrow rally, fragile",
            })

    # 7. Gold/Silver ratio extreme
    if gold is not None and silver is not None and silver > 0:
        gs_ratio = gold / silver
        if gs_ratio > 80:
            signals.append({
                "signal": "GOLD_SILVER_RATIO_HIGH",
                "severity": "MEDIUM",
                "detail": f"Gold/Silver ratio={gs_ratio:.1f} (>80) — silver undervalued vs gold; risk-off sentiment or silver accumulation opportunity",
            })
        elif gs_ratio < 50:
            signals.append({
                "signal": "GOLD_SILVER_RATIO_LOW",
                "severity": "LOW",
                "detail": f"Gold/Silver ratio={gs_ratio:.1f} (<50) — silver potentially overvalued vs gold",
            })

    return signals


def read_data_metadata() -> str:
    """Read the data extraction metadata (last extraction timestamps, row counts).

    Returns the data_metadata.json content from historical_data/.
    """
    path = os.path.join(HISTORICAL_DATA_DIR, "data_metadata.json")
    if not os.path.exists(path):
        return json.dumps({"error": "data_metadata.json not found"})
    with open(path) as f:
        return f.read()
