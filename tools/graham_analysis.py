"""Benjamin Graham value investing analysis tools.

Implements Graham's core frameworks from *The Intelligent Investor* and
*Security Analysis*, applied to ~500 S&P 500 companies using the existing
53-column equity financial data.

Frameworks:
  1. Graham Number — sqrt(22.5 × EPS × BVPS) intrinsic value estimate
  2. Defensive Investor Criteria — 7-test quality/value filter
  3. Margin of Safety — current price vs intrinsic value gap
  4. Net-Net Working Capital (NCAV) — deep value screen
  5. Earnings Power Value (Greenwald extension)
  6. Debt Safety — current ratio, debt/equity thresholds
  7. Book Value Analysis — tangible book, growth trend

Data sources:
  - /macro_2/historical_data/equity_financials/ (53-column SEC EDGAR + Yahoo Finance)
  - yfinance — current stock price (lightweight, for P/E and margin of safety)

All public functions return JSON strings (json.dumps with indent=2).
"""

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd

from tools.equity_analysis import (
    _load_equity_csv,
    _safe_div,
    _safe_round,
    _growth_pct,
    _trend_direction,
)
from tools.config import discover_all_tickers


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _get_current_price(ticker: str) -> float | None:
    """Fetch the latest stock price via yfinance with hard 8-second timeout."""
    import concurrent.futures

    def _fetch():
        import yfinance as yf
        data = yf.download(ticker, period="5d", progress=False, timeout=8)
        if data is not None and not data.empty:
            closes = data["Close"].dropna()
            if len(closes) > 0:
                val = closes.iloc[-1]
                # Handle both scalar and single-element Series
                if isinstance(val, pd.Series):
                    val = val.iloc[0]
                return float(val)
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            return future.result(timeout=8)
    except (concurrent.futures.TimeoutError, Exception):
        return None


def _get_batch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current prices for multiple tickers via batch yfinance download.

    Returns a dict of {ticker: price} for tickers where data was available.
    Uses hard 15-second timeout to prevent hangs.
    """
    if not tickers:
        return {}
    import concurrent.futures

    def _fetch():
        import yfinance as yf
        # Join tickers for batch download
        ticker_str = " ".join(tickers[:100])  # limit to 100 at a time
        data = yf.download(ticker_str, period="5d", progress=False, timeout=12)
        if data is None or data.empty:
            return {}

        prices: dict[str, float] = {}
        closes = data["Close"]
        if isinstance(closes, pd.Series):
            # Single ticker case
            if len(tickers) == 1 and not closes.empty:
                prices[tickers[0]] = float(closes.dropna().iloc[-1])
        else:
            for t in tickers:
                if t in closes.columns:
                    series = closes[t].dropna()
                    if len(series) > 0:
                        prices[t] = float(series.iloc[-1])
        return prices

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            return future.result(timeout=15)
    except (concurrent.futures.TimeoutError, Exception):
        return {}


def _compute_graham_number(eps: float, bvps: float) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × BVPS).

    Only valid when both EPS and BVPS are positive.
    """
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    try:
        return round(math.sqrt(22.5 * eps * bvps), 2)
    except (ValueError, OverflowError):
        return None


def _extract_fundamentals(df: pd.DataFrame) -> dict:
    """Extract key Graham-relevant metrics from an equity DataFrame.

    Args:
        df: Equity quarterly data sorted newest-first.

    Returns:
        Dict with eps, bvps, current_ratio, debt_to_equity, etc.
    """
    if df is None or df.empty:
        return {}

    latest = df.iloc[0]
    result: dict = {}

    # EPS (trailing twelve months — sum of last 4 quarters)
    eps_col = "diluted_eps" if "diluted_eps" in df.columns else "basic_eps"
    if eps_col in df.columns:
        eps_vals = df[eps_col].dropna().head(4)
        if len(eps_vals) >= 4:
            result["eps_ttm"] = round(float(eps_vals.sum()), 4)
        elif len(eps_vals) > 0:
            # Annualize available quarters
            result["eps_ttm"] = round(float(eps_vals.mean() * 4), 4)

    # Shares outstanding
    shares_col = "diluted_shares" if "diluted_shares" in df.columns else "basic_shares"
    shares = latest.get(shares_col)
    if shares is not None and not pd.isna(shares) and shares > 0:
        result["shares"] = float(shares)

    # Book Value Per Share
    equity = latest.get("stockholders_equity")
    if equity is not None and not pd.isna(equity) and result.get("shares"):
        result["bvps"] = round(equity / result["shares"], 4)
        result["stockholders_equity"] = float(equity)

    # Tangible Book Value Per Share (exclude goodwill + intangibles)
    goodwill = latest.get("goodwill", 0)
    if goodwill is None or pd.isna(goodwill):
        goodwill = 0
    if equity is not None and not pd.isna(equity) and result.get("shares"):
        tangible_equity = equity - goodwill
        result["tangible_bvps"] = round(tangible_equity / result["shares"], 4)

    # Current ratio
    cr = latest.get("current_ratio")
    if cr is not None and not pd.isna(cr):
        result["current_ratio"] = round(float(cr), 4)

    # Current assets / liabilities for NCAV
    ca = latest.get("current_assets")
    cl = latest.get("current_liabilities")
    tl = latest.get("total_liabilities")
    if ca is not None and not pd.isna(ca):
        result["current_assets"] = float(ca)
    if cl is not None and not pd.isna(cl):
        result["current_liabilities"] = float(cl)
    if tl is not None and not pd.isna(tl):
        result["total_liabilities"] = float(tl)

    # Debt metrics
    dte = latest.get("debt_to_equity")
    if dte is not None and not pd.isna(dte):
        result["debt_to_equity"] = round(float(dte), 4)
    td = latest.get("total_debt")
    if td is not None and not pd.isna(td):
        result["total_debt"] = float(td)
    ltd = latest.get("long_term_debt")
    if ltd is not None and not pd.isna(ltd):
        result["long_term_debt"] = float(ltd)

    # Revenue (annualized from latest 4 quarters)
    if "total_revenue" in df.columns:
        rev_vals = df["total_revenue"].dropna().head(4)
        if len(rev_vals) >= 4:
            result["revenue_ttm"] = float(rev_vals.sum())
        elif len(rev_vals) > 0:
            result["revenue_ttm"] = float(rev_vals.mean() * 4)

    # Net Income TTM
    if "net_income" in df.columns:
        ni_vals = df["net_income"].dropna().head(4)
        if len(ni_vals) >= 4:
            result["net_income_ttm"] = float(ni_vals.sum())
        elif len(ni_vals) > 0:
            result["net_income_ttm"] = float(ni_vals.mean() * 4)

    # Dividends (TTM, negative means paid)
    if "dividends_paid" in df.columns:
        div_vals = df["dividends_paid"].dropna().head(4)
        if len(div_vals) > 0:
            result["dividends_ttm"] = float(div_vals.sum())

    # Operating income for EPV
    if "operating_income" in df.columns:
        oi_vals = df["operating_income"].dropna().head(4)
        if len(oi_vals) >= 4:
            result["operating_income_ttm"] = float(oi_vals.sum())

    # Earnings stability — count of positive-EPS quarters
    if eps_col in df.columns:
        all_eps = df[eps_col].dropna()
        result["total_quarters"] = len(all_eps)
        result["positive_eps_quarters"] = int((all_eps > 0).sum())

    # EPS growth: compare oldest 4Q to newest 4Q
    if eps_col in df.columns and len(df) >= 8:
        newest_4q = df[eps_col].dropna().head(4)
        oldest_4q = df[eps_col].dropna().tail(4)
        if len(newest_4q) == 4 and len(oldest_4q) == 4:
            new_eps = newest_4q.sum()
            old_eps = oldest_4q.sum()
            result["eps_growth_pct"] = _growth_pct(new_eps, old_eps)

    # Book value trend (newest vs oldest available)
    if "stockholders_equity" in df.columns and result.get("shares"):
        eq_series = df["stockholders_equity"].dropna()
        shares_series = df.get(shares_col)
        if shares_series is not None:
            shares_series = shares_series.dropna()
            if len(eq_series) >= 4 and len(shares_series) >= 4:
                bvps_vals = []
                for i in range(min(len(eq_series), len(shares_series))):
                    s = shares_series.iloc[i]
                    e = eq_series.iloc[i]
                    if s > 0 and not pd.isna(e):
                        bvps_vals.append(e / s)
                if len(bvps_vals) >= 3:
                    result["bvps_trend"] = _trend_direction(list(reversed(bvps_vals)))

    # Quarter label
    result["latest_quarter"] = str(latest.get("quarter", latest.get("timestamp", "N/A")))

    return result


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC TOOL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def graham_value_analysis(ticker: str) -> str:
    """Complete Benjamin Graham value investing analysis for a single company.

    Applies Graham's frameworks from The Intelligent Investor:
    - Graham Number (intrinsic value estimate)
    - Margin of Safety vs current market price
    - 7 Defensive Investor Criteria (pass/fail)
    - Net-Net Working Capital Value (NCAV)
    - Debt Safety assessment
    - Earnings Power Value (Greenwald extension)
    - Book Value analysis and trend

    Args:
        ticker: Stock ticker (e.g. 'AAPL', 'BRK-B').

    Returns:
        JSON string with complete Graham analysis.
    """
    ticker = ticker.upper().strip()
    result: dict = {
        "ticker": ticker,
        "analysis": "benjamin_graham_value",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d"),
    }

    # Load financial data
    df = _load_equity_csv(ticker)
    if df is None:
        result["error"] = f"No financial data found for {ticker}"
        return json.dumps(result, indent=2)

    fundamentals = _extract_fundamentals(df)
    if not fundamentals:
        result["error"] = f"Could not extract fundamentals for {ticker}"
        return json.dumps(result, indent=2)

    result["company"] = str(df.iloc[0].get("company_name", ticker))
    result["latest_quarter"] = fundamentals.get("latest_quarter")

    # ── Data staleness warning ────────────────────────────────────────
    lq = fundamentals.get("latest_quarter", "")
    try:
        lq_date = pd.to_datetime(str(lq), errors="coerce")
        if lq_date is not None and not pd.isna(lq_date):
            staleness_days = (pd.Timestamp.utcnow() - lq_date).days
            if staleness_days > 730:  # > 2 years
                result["data_warning"] = (
                    f"Financial data is from {lq} ({staleness_days // 365}+ years old). "
                    f"Graham analysis may be unreliable — consider updating the data pipeline."
                )
            elif staleness_days > 365:
                result["data_warning"] = (
                    f"Financial data is from {lq} ({staleness_days // 30} months old). "
                    f"Earnings and book value may have changed significantly."
                )
    except Exception:
        pass

    # ── Current price (via yfinance) ─────────────────────────────────
    price = _get_current_price(ticker)
    result["current_price"] = price

    eps_ttm = fundamentals.get("eps_ttm")
    bvps = fundamentals.get("bvps")
    shares = fundamentals.get("shares")

    # ── 1. Graham Number ─────────────────────────────────────────────
    graham_num = _compute_graham_number(eps_ttm, bvps)
    result["graham_number"] = {
        "value": graham_num,
        "formula": "sqrt(22.5 × EPS_TTM × BVPS)",
        "eps_ttm": eps_ttm,
        "bvps": bvps,
    }

    # ── 2. Margin of Safety ──────────────────────────────────────────
    if graham_num and price and price > 0:
        margin = round((graham_num - price) / price * 100, 2)
        result["margin_of_safety"] = {
            "pct": margin,
            "assessment": (
                "Significant margin of safety (>30%)" if margin > 30
                else "Moderate margin (10-30%)" if margin > 10
                else "Slim margin (0-10%)" if margin > 0
                else "Overvalued vs Graham Number (negative margin)"
            ),
        }
    else:
        result["margin_of_safety"] = {"pct": None, "assessment": "Cannot compute (missing price or Graham Number)"}

    # ── 3. Defensive Investor Criteria (7 tests) ─────────────────────
    criteria: list[dict] = []
    score = 0
    total_tests = 7

    # Test 1: Adequate size (revenue > $100M annualized)
    rev_ttm = fundamentals.get("revenue_ttm")
    t1_pass = bool(rev_ttm is not None and rev_ttm > 100_000_000)
    criteria.append({
        "test": "1. Adequate size",
        "threshold": "Annual revenue > $100M",
        "value": f"${rev_ttm / 1e9:.2f}B" if rev_ttm else "N/A",
        "pass": t1_pass,
    })
    if t1_pass:
        score += 1

    # Test 2: Strong financial condition (current ratio ≥ 2.0)
    cr = fundamentals.get("current_ratio")
    t2_pass = bool(cr is not None and cr >= 2.0)
    criteria.append({
        "test": "2. Strong financial condition",
        "threshold": "Current ratio ≥ 2.0",
        "value": cr,
        "pass": t2_pass,
    })
    if t2_pass:
        score += 1

    # Test 3: Earnings stability (positive EPS in all available quarters)
    total_q = fundamentals.get("total_quarters", 0)
    pos_q = fundamentals.get("positive_eps_quarters", 0)
    t3_pass = bool(total_q >= 4 and pos_q == total_q)
    criteria.append({
        "test": "3. Earnings stability",
        "threshold": "Positive EPS in all quarters",
        "value": f"{pos_q}/{total_q} quarters positive",
        "pass": t3_pass,
    })
    if t3_pass:
        score += 1

    # Test 4: Dividend record (paying dividends)
    div_ttm = fundamentals.get("dividends_ttm")
    # dividends_paid is negative when dividends are actually paid
    t4_pass = bool(div_ttm is not None and div_ttm < 0)
    criteria.append({
        "test": "4. Dividend record",
        "threshold": "Paying dividends",
        "value": f"${abs(div_ttm) / 1e9:.2f}B TTM" if div_ttm and div_ttm < 0 else "No dividends",
        "pass": t4_pass,
    })
    if t4_pass:
        score += 1

    # Test 5: Earnings growth
    eps_growth = fundamentals.get("eps_growth_pct")
    t5_pass = bool(eps_growth is not None and eps_growth > 0)
    criteria.append({
        "test": "5. Earnings growth",
        "threshold": "EPS growth (newest 4Q vs oldest 4Q)",
        "value": f"{eps_growth}%" if eps_growth is not None else "N/A",
        "pass": t5_pass,
    })
    if t5_pass:
        score += 1

    # Test 6: Moderate P/E (< 15)
    pe = None
    if eps_ttm and eps_ttm > 0 and price and price > 0:
        pe = round(price / eps_ttm, 2)
    t6_pass = bool(pe is not None and pe < 15)
    criteria.append({
        "test": "6. Moderate P/E ratio",
        "threshold": "P/E < 15",
        "value": pe,
        "pass": t6_pass,
    })
    if t6_pass:
        score += 1

    # Test 7: Moderate P/E × P/B (< 22.5)
    pb = None
    if bvps and bvps > 0 and price and price > 0:
        pb = round(price / bvps, 2)
    pe_pb_product = round(pe * pb, 2) if pe and pb else None
    t7_pass = bool(pe_pb_product is not None and pe_pb_product < 22.5)
    criteria.append({
        "test": "7. Moderate P/E × P/B",
        "threshold": "P/E × P/B < 22.5",
        "value": pe_pb_product,
        "pass": t7_pass,
    })
    if t7_pass:
        score += 1

    result["defensive_criteria"] = {
        "score": f"{score}/{total_tests}",
        "tests": criteria,
        "assessment": (
            "Passes all Graham defensive criteria" if score == 7
            else "Strong Graham candidate (5-6/7)" if score >= 5
            else "Partial Graham fit (3-4/7)" if score >= 3
            else "Does not meet Graham defensive standards (<3/7)"
        ),
    }

    # ── 4. Net-Net Working Capital (NCAV) ────────────────────────────
    ca = fundamentals.get("current_assets")
    tl = fundamentals.get("total_liabilities")
    if ca is not None and tl is not None and shares:
        ncav = (ca - tl) / shares
        ncav_rounded = round(ncav, 2)
        result["net_net_wcav"] = {
            "ncav_per_share": ncav_rounded,
            "current_assets": ca,
            "total_liabilities": tl,
            "formula": "(Current Assets - Total Liabilities) / Shares",
        }
        if price and price > 0:
            ncav_ratio = round(price / ncav, 2) if ncav > 0 else None
            result["net_net_wcav"]["price_to_ncav"] = ncav_ratio
            if ncav > 0 and price < ncav * 0.67:
                result["net_net_wcav"]["signal"] = "DEEP_VALUE — trading below 2/3 of NCAV (Graham net-net)"
            elif ncav > 0 and price < ncav:
                result["net_net_wcav"]["signal"] = "VALUE — trading below NCAV"
            elif ncav <= 0:
                result["net_net_wcav"]["signal"] = "Negative NCAV — liabilities exceed current assets"
            else:
                result["net_net_wcav"]["signal"] = "Trading above NCAV"
    else:
        result["net_net_wcav"] = {"ncav_per_share": None, "note": "Insufficient data"}

    # ── 5. Debt Safety ───────────────────────────────────────────────
    dte = fundamentals.get("debt_to_equity")
    ltd = fundamentals.get("long_term_debt")
    result["debt_safety"] = {
        "current_ratio": cr,
        "debt_to_equity": dte,
        "long_term_debt": ltd,
        "assessment": [],
    }
    debt_flags = result["debt_safety"]["assessment"]
    if cr is not None:
        if cr >= 2.0:
            debt_flags.append("PASS: Current ratio ≥ 2.0 (Graham threshold)")
        elif cr >= 1.5:
            debt_flags.append("MARGINAL: Current ratio 1.5-2.0")
        else:
            debt_flags.append("FAIL: Current ratio < 1.5")
    if dte is not None:
        if dte < 1.0:
            debt_flags.append("PASS: Debt/equity < 1.0 (Graham preferred)")
        elif dte < 2.0:
            debt_flags.append("MARGINAL: Debt/equity 1.0-2.0")
        else:
            debt_flags.append("FAIL: Debt/equity ≥ 2.0 (high leverage)")
    # Graham: long-term debt should not exceed net current assets
    nca = None
    if ca is not None and fundamentals.get("current_liabilities"):
        nca = ca - fundamentals["current_liabilities"]
        if ltd is not None and nca > 0:
            if ltd <= nca:
                debt_flags.append("PASS: Long-term debt ≤ net current assets")
            else:
                debt_flags.append(f"FAIL: Long-term debt ${ltd/1e9:.1f}B > net current assets ${nca/1e9:.1f}B")

    # ── 6. Earnings Power Value (Greenwald) ──────────────────────────
    oi_ttm = fundamentals.get("operating_income_ttm")
    cost_of_capital = 0.10  # 10% (standard assumption)
    if oi_ttm and oi_ttm > 0:
        # Adjust for taxes (assume 21% corporate rate)
        after_tax_earnings = oi_ttm * (1 - 0.21)
        epv = after_tax_earnings / cost_of_capital
        epv_per_share = round(epv / shares, 2) if shares else None
        result["earnings_power_value"] = {
            "epv_total": round(epv / 1e9, 2),
            "epv_per_share": epv_per_share,
            "operating_income_ttm": round(oi_ttm / 1e9, 2),
            "assumed_cost_of_capital": "10%",
            "assumed_tax_rate": "21%",
            "formula": "After-tax Operating Income / Cost of Capital",
        }
        if epv_per_share and price and price > 0:
            epv_margin = round((epv_per_share - price) / epv_per_share * 100, 2)
            result["earnings_power_value"]["margin_vs_price"] = f"{epv_margin}%"
    else:
        result["earnings_power_value"] = {"epv_per_share": None, "note": "Negative or missing operating income"}

    # ── 7. Book Value Analysis ───────────────────────────────────────
    result["book_value"] = {
        "bvps": bvps,
        "tangible_bvps": fundamentals.get("tangible_bvps"),
        "pb_ratio": pb,
        "bvps_trend": fundamentals.get("bvps_trend", "insufficient_data"),
    }

    # ── 8. Valuation Metrics ─────────────────────────────────────────
    result["valuation_metrics"] = {
        "trailing_pe": pe,
        "price_to_book": pb,
        "pe_x_pb": pe_pb_product,
        "earnings_yield": round(1 / pe * 100, 2) if pe and pe > 0 else None,
    }

    # ── Overall Assessment ───────────────────────────────────────────
    signals = []
    if score >= 5:
        signals.append(f"Strong Graham candidate ({score}/7 defensive criteria)")
    elif score >= 3:
        signals.append(f"Partial Graham fit ({score}/7)")
    else:
        signals.append(f"Does not meet Graham standards ({score}/7)")

    mos_pct = result.get("margin_of_safety", {}).get("pct")
    if mos_pct is not None:
        if mos_pct > 30:
            signals.append("Significant margin of safety — potential value opportunity")
        elif mos_pct > 0:
            signals.append("Positive but slim margin of safety")
        else:
            signals.append("No margin of safety — trading above Graham Number")

    result["overall_assessment"] = signals

    return json.dumps(result, indent=2)


def graham_screen(tickers: str = "", top_n: int = 20) -> str:
    """Screen companies against Benjamin Graham's defensive investor criteria.

    Ranks companies by margin of safety (Graham Number vs current price).
    Uses batch yfinance download for efficiency.

    Args:
        tickers: Comma-separated ticker list. Empty = all ~500 S&P 500.
        top_n: Maximum results to return (default 20).

    Returns:
        JSON string with ranked screening results.
    """
    result: dict = {
        "screen": "graham_defensive_investor",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d"),
    }

    # Determine ticker universe
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = discover_all_tickers()

    result["universe_size"] = len(ticker_list)

    # Extract fundamentals for all tickers
    candidates: list[dict] = []
    tickers_needing_prices: list[str] = []
    ticker_fundamentals: dict[str, dict] = {}

    for t in ticker_list:
        df = _load_equity_csv(t)
        if df is None:
            continue
        f = _extract_fundamentals(df)
        if not f or not f.get("eps_ttm") or not f.get("bvps"):
            continue
        ticker_fundamentals[t] = f
        tickers_needing_prices.append(t)

    # Batch fetch current prices
    prices = _get_batch_prices(tickers_needing_prices)

    # Score each ticker
    for t, f in ticker_fundamentals.items():
        price = prices.get(t)
        if not price or price <= 0:
            continue

        eps_ttm = f.get("eps_ttm")
        bvps = f.get("bvps")
        graham_num = _compute_graham_number(eps_ttm, bvps)
        if not graham_num:
            continue

        margin = round((graham_num - price) / price * 100, 2)

        # Quick criteria count
        criteria_passed = 0
        rev = f.get("revenue_ttm")
        if rev and rev > 100_000_000:
            criteria_passed += 1
        cr = f.get("current_ratio")
        if cr and cr >= 2.0:
            criteria_passed += 1
        tq = f.get("total_quarters", 0)
        pq = f.get("positive_eps_quarters", 0)
        if tq >= 4 and pq == tq:
            criteria_passed += 1
        div = f.get("dividends_ttm")
        if div and div < 0:
            criteria_passed += 1
        eg = f.get("eps_growth_pct")
        if eg and eg > 0:
            criteria_passed += 1
        pe = round(price / eps_ttm, 2) if eps_ttm > 0 else None
        if pe and pe < 15:
            criteria_passed += 1
        pb = round(price / bvps, 2) if bvps > 0 else None
        pe_pb = round(pe * pb, 2) if pe and pb else None
        if pe_pb and pe_pb < 22.5:
            criteria_passed += 1

        candidates.append({
            "ticker": t,
            "price": round(price, 2),
            "graham_number": graham_num,
            "margin_of_safety_pct": margin,
            "pe": pe,
            "pb": pb,
            "pe_x_pb": pe_pb,
            "current_ratio": cr,
            "criteria_passed": f"{criteria_passed}/7",
            "debt_to_equity": f.get("debt_to_equity"),
        })

    # Sort by margin of safety (highest first)
    candidates.sort(key=lambda x: x["margin_of_safety_pct"], reverse=True)
    candidates = candidates[:top_n]

    result["results_count"] = len(candidates)
    result["screened"] = len(ticker_fundamentals)
    result["top_value_candidates"] = candidates

    # Summary stats
    if candidates:
        avg_margin = round(sum(c["margin_of_safety_pct"] for c in candidates) / len(candidates), 2)
        result["summary"] = {
            "avg_margin_of_safety": avg_margin,
            "companies_with_positive_margin": sum(1 for c in candidates if c["margin_of_safety_pct"] > 0),
            "companies_passing_5plus_criteria": sum(1 for c in candidates if int(c["criteria_passed"].split("/")[0]) >= 5),
        }

    return json.dumps(result, indent=2)


def graham_net_net_screen(top_n: int = 20) -> str:
    """Screen for Graham net-net opportunities (deep value).

    Finds companies trading below their Net Current Asset Value (NCAV):
    NCAV = (Current Assets - Total Liabilities) / Shares Outstanding.

    Graham's criteria: buy at < 2/3 of NCAV for maximum safety.
    Note: Very few S&P 500 companies trade at net-net — this is more
    common in small/micro-caps, but the screen is valuable for context.

    Args:
        top_n: Maximum results to return (default 20).

    Returns:
        JSON string with net-net screening results.
    """
    result: dict = {
        "screen": "graham_net_net_working_capital",
        "as_of": datetime.utcnow().strftime("%Y-%m-%d"),
        "formula": "NCAV = (Current Assets - Total Liabilities) / Shares",
        "graham_rule": "Buy at < 2/3 of NCAV for deep value",
    }

    ticker_list = discover_all_tickers()
    result["universe_size"] = len(ticker_list)

    # First pass: find tickers with positive NCAV
    ncav_candidates: list[dict] = []
    tickers_for_price: list[str] = []

    for t in ticker_list:
        df = _load_equity_csv(t)
        if df is None:
            continue
        latest = df.iloc[0]

        ca = latest.get("current_assets")
        tl = latest.get("total_liabilities")
        shares_col = "diluted_shares" if "diluted_shares" in df.columns else "basic_shares"
        shares = latest.get(shares_col)

        if (ca is None or tl is None or shares is None
                or pd.isna(ca) or pd.isna(tl) or pd.isna(shares) or shares <= 0):
            continue

        ncav = (ca - tl) / shares
        if ncav <= 0:
            continue  # Skip negative NCAV

        ncav_candidates.append({
            "ticker": t,
            "ncav_per_share": round(ncav, 2),
            "current_assets": float(ca),
            "total_liabilities": float(tl),
        })
        tickers_for_price.append(t)

    # Batch fetch prices
    prices = _get_batch_prices(tickers_for_price)

    # Score by price/NCAV ratio
    scored: list[dict] = []
    for c in ncav_candidates:
        t = c["ticker"]
        price = prices.get(t)
        if not price or price <= 0:
            continue
        ncav = c["ncav_per_share"]
        ratio = round(price / ncav, 2)
        c["current_price"] = round(price, 2)
        c["price_to_ncav"] = ratio
        c["discount_pct"] = round((ncav - price) / ncav * 100, 2) if ncav > 0 else 0
        if ratio < 0.67:
            c["signal"] = "DEEP_VALUE — below 2/3 NCAV (Graham buy zone)"
        elif ratio < 1.0:
            c["signal"] = "VALUE — below NCAV"
        else:
            c["signal"] = "Above NCAV"
        scored.append(c)

    # Sort by price/NCAV ratio (lowest = cheapest)
    scored.sort(key=lambda x: x["price_to_ncav"])
    scored = scored[:top_n]

    result["positive_ncav_count"] = len(ncav_candidates)
    result["results_count"] = len(scored)
    result["net_net_candidates"] = scored

    deep_value = [s for s in scored if s.get("price_to_ncav", 999) < 0.67]
    below_ncav = [s for s in scored if s.get("price_to_ncav", 999) < 1.0]
    result["summary"] = {
        "deep_value_count": len(deep_value),
        "below_ncav_count": len(below_ncav),
        "note": (
            "Few S&P 500 companies trade at net-net. "
            "This screen is more relevant for small/micro-caps."
        ) if not deep_value else f"Found {len(deep_value)} deep value net-net opportunities!",
    }

    return json.dumps(result, indent=2)
