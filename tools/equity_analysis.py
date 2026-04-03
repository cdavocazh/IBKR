"""Equity financial analysis tools.

Reads quarterly financial data from /macro_2/historical_data/equity_financials/
and computes valuation metrics, growth rates, and investment-grade analysis.

Data sources (all checked, best selected by freshness + quality):
  1. sec_edgar/   — ~503 S&P 500 tickers, 53 columns (SEC EDGAR filings)
  2. yahoo_finance/ — ~504 S&P 500 tickers, 53 columns (Yahoo Finance)
  3. Root dir     — 20 legacy tickers, 11 columns (original dataset)
  Source selection: freshest latest-quarter wins; ties broken by data quality
  (negative shares penalized, more columns preferred).

The 53-column schema adds: gross_profit, EBITDA, EPS, share counts, current
ratio, free cash flow, capex, debt breakdown, R&D, SGA, SBC, and more.

Enhanced metrics (v1.3):
  - Return on capital: ROE, ROIC, ROA (quarterly + annualized)
  - Margin trends: multi-quarter direction detection
  - Net cash position: cash vs debt breakdown
  - Capital allocation: buybacks, dividends, SBC dilution
  - Balance sheet efficiency: DSO, DPO, inventory turnover, cash conversion cycle
  - Peer comparison: GICS sector/industry peer matching
"""

import os
import json
import pandas as pd
import numpy as np

from tools.config import (
    EQUITY_FINANCIALS_DIR,
    EQUITY_SEC_EDGAR_DIR,
    EQUITY_YAHOO_DIR,
    HISTORICAL_DATA_DIR,
    TOP_20_TICKERS,
    discover_all_tickers,
)


def _quarter_to_date(q: str) -> pd.Timestamp | None:
    """Convert a quarter string like '2026-Q1' to an approximate date.

    Returns the quarter *end* date so that later quarters always sort after
    earlier ones: Q1→Mar-31, Q2→Jun-30, Q3→Sep-30, Q4→Dec-31.
    """
    try:
        parts = str(q).split("-")
        year = int(parts[0])
        qnum = int(parts[1].upper().replace("Q", ""))
        month = {1: 3, 2: 6, 3: 9, 4: 12}.get(qnum, 12)
        day = 30 if month in (6, 9) else 31
        return pd.Timestamp(year=year, month=month, day=day)
    except (ValueError, IndexError, KeyError):
        return None


def _load_equity_csv(ticker: str) -> pd.DataFrame | None:
    """Load quarterly financial CSV for a ticker.

    Compares all available sources (sec_edgar, yahoo_finance, legacy) and
    picks the best one using freshness + quality scoring:
      1. Freshest **quarter** date wins (uses the ``quarter`` column, NOT
         the scrape ``timestamp``).  This prevents a recently-scraped but
         financially-stale source from beating one with newer financial data.
      2. Ties broken by data quality (no negative shares, more columns).
    """
    source_paths = [
        ("sec_edgar", os.path.join(EQUITY_SEC_EDGAR_DIR, f"{ticker}_quarterly.csv")),
        ("yahoo_finance", os.path.join(EQUITY_YAHOO_DIR, f"{ticker}_quarterly.csv")),
        ("legacy", os.path.join(EQUITY_FINANCIALS_DIR, f"{ticker}_quarterly.csv")),
    ]

    # Each candidate: (label, DataFrame, latest_quarter_date, quality_score)
    candidates: list[tuple[str, pd.DataFrame, pd.Timestamp, int]] = []
    for label, path in source_paths:
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
            if len(df) == 0:
                continue
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

            # --- Determine freshness from the *quarter* column, not the
            # scrape timestamp.  The scrape timestamp only tells us when the
            # pipeline ran, which can be recent even if the underlying
            # financial data is years old (e.g., SEC EDGAR stuck at 2020-Q2
            # while pipeline re-scraped in 2026). ---
            if "quarter" in df.columns:
                df["_quarter_date"] = df["quarter"].apply(_quarter_to_date)
                df = df.sort_values("_quarter_date", ascending=False).reset_index(drop=True)
                latest_qd = df["_quarter_date"].iloc[0]
            else:
                # Fallback to scrape timestamp if no quarter column
                df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
                latest_qd = df["timestamp"].iloc[0]

            if pd.isna(latest_qd):
                continue

            # Quality score: penalise negative diluted_shares in newest row
            quality = len(df.columns)  # more columns = richer schema
            newest = df.iloc[0]
            ds = newest.get("diluted_shares")
            if ds is not None and not pd.isna(ds) and ds < 0:
                quality -= 20  # heavy penalty for corrupt share data
            candidates.append((label, df, latest_qd, quality))
        except Exception:
            continue

    if not candidates:
        return None

    # Sort: freshest quarter first, then highest quality score
    candidates.sort(key=lambda c: (c[2], c[3]), reverse=True)
    best_label, best_df, best_ts, best_q = candidates[0]

    return best_df


def _safe_div(a, b) -> float | None:
    """Safe division returning None on error."""
    try:
        if b is None or b == 0 or pd.isna(b):
            return None
        if a is None or pd.isna(a):
            return None
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def _safe_round(val, digits=2) -> float | None:
    """Round a value, returning None if not a number."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return round(val, digits)


def _pct(a, b) -> float | None:
    """Compute percentage: (a/b)*100, safe."""
    r = _safe_div(a, b)
    return _safe_round(r * 100) if r is not None else None


def _growth_pct(new, old) -> float | None:
    """Compute growth percentage: ((new-old)/|old|)*100, safe."""
    if old is None or new is None:
        return None
    try:
        if pd.isna(old) or pd.isna(new) or old == 0:
            return None
        return _safe_round(((new - old) / abs(old)) * 100)
    except (TypeError, ZeroDivisionError):
        return None


def _trend_direction(values: list) -> str:
    """Detect trend direction from a sequence of values (oldest to newest).

    Returns: "improving", "declining", "stable", "volatile", or "insufficient_data".
    """
    clean = [v for v in values if v is not None and not (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))]
    if len(clean) < 3:
        return "insufficient_data"
    diffs = [clean[i + 1] - clean[i] for i in range(len(clean) - 1)]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    if pos >= len(diffs) * 0.7:
        return "improving"
    elif neg >= len(diffs) * 0.7:
        return "declining"
    elif all(abs(d) / max(abs(clean[-1]), 1e-9) < 0.02 for d in diffs):
        return "stable"
    else:
        return "volatile"


def _compute_margin_trends(df: pd.DataFrame) -> dict:
    """Compute multi-quarter margin trends from a DataFrame sorted newest-first."""
    rev = df.iloc[::-1]  # oldest first for trend detection
    result = {}
    margin_calcs = {
        "gross_margin": ("gross_profit", "total_revenue"),
        "operating_margin": ("operating_income", "total_revenue"),
        "net_margin": ("net_income", "total_revenue"),
        "ebitda_margin": ("ebitda", "total_revenue"),
    }
    for margin_name, (numerator, denominator) in margin_calcs.items():
        if numerator in rev.columns and denominator in rev.columns:
            values = []
            for _, row in rev.iterrows():
                pct = _safe_div(row.get(numerator), row.get(denominator))
                values.append(pct * 100 if pct is not None else None)
            result[margin_name] = {
                "values_pct": [_safe_round(v) for v in values],
                "trend": _trend_direction(values),
            }
    return result


def _compute_efficiency_metrics(row: pd.Series) -> dict:
    """Compute balance sheet efficiency metrics from a single quarter's data."""
    metrics = {}
    rev = row.get("total_revenue")
    cogs = row.get("cost_of_revenue")
    ar = row.get("accounts_receivable")
    ap = row.get("accounts_payable")
    inv = row.get("inventory")
    ca = row.get("current_assets")
    cl = row.get("current_liabilities")

    # Days Sales Outstanding = (AR / Revenue) * 90 days (quarterly)
    dso = _safe_div(ar, rev)
    if dso is not None:
        metrics["days_sales_outstanding"] = _safe_round(dso * 90)

    # Days Payable Outstanding = (AP / COGS) * 90 days (quarterly)
    dpo = _safe_div(ap, cogs)
    if dpo is not None:
        metrics["days_payable_outstanding"] = _safe_round(dpo * 90)

    # Inventory Turnover (quarterly) = COGS / Inventory
    inv_turn = _safe_div(cogs, inv)
    if inv_turn is not None:
        metrics["inventory_turnover"] = _safe_round(inv_turn)
        if inv_turn > 0:
            metrics["days_inventory_outstanding"] = _safe_round(90 / inv_turn)

    # Cash Conversion Cycle = DSO + DIO - DPO
    if all(k in metrics for k in ["days_sales_outstanding", "days_inventory_outstanding", "days_payable_outstanding"]):
        metrics["cash_conversion_cycle"] = _safe_round(
            metrics["days_sales_outstanding"]
            + metrics["days_inventory_outstanding"]
            - metrics["days_payable_outstanding"]
        )

    # Working Capital = Current Assets - Current Liabilities
    if ca is not None and cl is not None:
        try:
            if not pd.isna(ca) and not pd.isna(cl):
                wc = ca - cl
                metrics["working_capital"] = wc
                metrics["working_capital_to_revenue_pct"] = _pct(wc, rev)
        except (TypeError, ValueError):
            pass

    return metrics


# ═════════════════════════════════════════════════════════════════════
# PUBLIC TOOL FUNCTIONS
# ═════════════════════════════════════════════════════════════════════

def list_available_equities() -> str:
    """List all equity tickers with data available for analysis.

    Discovers tickers from sec_edgar/, yahoo_finance/, and root directories.
    Returns ticker count, source breakdown, and sample of tickers.
    For the top-20 watchlist, includes latest quarter and row count.
    """
    all_tickers = discover_all_tickers()

    # Count by source
    sec_count = 0
    yahoo_count = 0
    root_count = 0
    if os.path.isdir(EQUITY_SEC_EDGAR_DIR):
        sec_count = len([f for f in os.listdir(EQUITY_SEC_EDGAR_DIR)
                         if f.endswith("_quarterly.csv")])
    if os.path.isdir(EQUITY_YAHOO_DIR):
        yahoo_count = len([f for f in os.listdir(EQUITY_YAHOO_DIR)
                           if f.endswith("_quarterly.csv")])
    root_count = len([f for f in os.listdir(EQUITY_FINANCIALS_DIR)
                      if f.endswith("_quarterly.csv") and not f.startswith("_")])

    # Detailed info for top-20 watchlist
    watchlist = []
    for ticker in TOP_20_TICKERS:
        df = _load_equity_csv(ticker)
        if df is None:
            watchlist.append({"ticker": ticker, "status": "not_found"})
            continue
        watchlist.append({
            "ticker": ticker,
            "company": df["company_name"].iloc[0] if "company_name" in df.columns else "?",
            "latest_quarter": df["quarter"].iloc[0] if "quarter" in df.columns else "?",
            "rows": len(df),
            "columns": len(df.columns),
        })

    snap_path = os.path.join(EQUITY_FINANCIALS_DIR, "_valuation_snapshot.csv")

    return json.dumps({
        "total_tickers": len(all_tickers),
        "sources": {
            "sec_edgar": sec_count,
            "yahoo_finance": yahoo_count,
            "root_legacy": root_count,
        },
        "all_tickers": all_tickers,
        "top_20_watchlist": watchlist,
        "valuation_snapshot_available": os.path.exists(snap_path),
    }, indent=2)


def search_equities(query: str) -> str:
    """Search for equity tickers by company name or ticker symbol.

    Useful when you know a company name but not the ticker, or want to
    find all tickers matching a pattern. Searches across all ~500 S&P 500
    companies.

    Args:
        query: Search string — matches against ticker and company_name.
               Case-insensitive. Examples: 'nvidia', 'bank', 'energy', 'TSLA'.
    """
    query_lower = query.lower().strip()
    all_tickers = discover_all_tickers()
    matches = []

    for ticker in all_tickers:
        # Quick ticker match
        if query_lower in ticker.lower():
            df = _load_equity_csv(ticker)
            company = "?"
            if df is not None and "company_name" in df.columns:
                company = df["company_name"].iloc[0]
            matches.append({"ticker": ticker, "company": company, "match": "ticker"})
            continue

        # Company name match (requires loading the CSV)
        df = _load_equity_csv(ticker)
        if df is not None and "company_name" in df.columns:
            company = str(df["company_name"].iloc[0])
            if query_lower in company.lower():
                matches.append({"ticker": ticker, "company": company, "match": "name"})

        # Cap at 30 results to avoid huge outputs
        if len(matches) >= 30:
            break

    return json.dumps({
        "query": query,
        "matches": len(matches),
        "results": matches,
        "total_searchable": len(all_tickers),
    }, indent=2)


def get_equity_financials(ticker: str) -> str:
    """Get quarterly financial data for a specific company.

    Returns income statement, balance sheet, and cash flow metrics
    for all available quarters. Works for any of the ~500 S&P 500 companies.

    Args:
        ticker: Stock ticker (e.g. 'AAPL', 'NVDA', 'TSLA', 'AMD').
    """
    ticker = ticker.strip().upper()
    df = _load_equity_csv(ticker)
    if df is None:
        return json.dumps({"error": f"No data for ticker '{ticker}'. Use search_equities() to find valid tickers."})

    records = df.to_dict(orient="records")

    # Compute growth rates between quarters
    growth_metrics = ["total_revenue", "net_income", "operating_income",
                      "operating_cash_flow", "free_cash_flow", "ebitda"]
    if len(records) >= 2:
        for i in range(len(records) - 1):
            curr = records[i]
            prev = records[i + 1]
            for metric in growth_metrics:
                g = _growth_pct(curr.get(metric), prev.get(metric))
                if g is not None:
                    curr[f"{metric}_qoq_growth_pct"] = g

    source = records[0].get("source", "legacy") if records else "unknown"

    return json.dumps({
        "ticker": ticker,
        "company": records[0].get("company_name", "?") if records else "?",
        "data_source": source,
        "quarters_available": len(records),
        "columns": len(df.columns),
        "data": records,
    }, indent=2, default=str)


def analyze_equity_valuation(ticker: str) -> str:
    """Perform investment-grade valuation analysis for a company.

    Works for any of the ~500 S&P 500 companies. Uses the richest data
    source available (53-column SEC EDGAR / Yahoo Finance when available).

    Computes:
    - Revenue and earnings growth (QoQ, YoY)
    - Margin analysis (gross, operating, net, EBITDA)
    - Cash flow quality (OCF/NI, FCF yield)
    - Balance sheet health (leverage, current ratio, debt structure)
    - Per-share metrics (EPS, diluted shares)
    - R&D and SBC intensity
    - Trend analysis across quarters

    Args:
        ticker: Stock ticker (e.g. 'AAPL', 'NVDA', 'TSLA', 'AMD').
    """
    ticker = ticker.strip().upper()
    df = _load_equity_csv(ticker)
    if df is None:
        return json.dumps({"error": f"No data for ticker '{ticker}'. Use search_equities() to find valid tickers."})

    if len(df) == 0:
        return json.dumps({"error": "Empty dataset"})

    latest = df.iloc[0]
    source = latest.get("source", "legacy")
    is_rich = "gross_profit" in df.columns  # 53-column schema

    latest_qtr = latest.get("quarter", "?")
    analysis = {
        "ticker": ticker,
        "company": latest.get("company_name", "?"),
        "data_source": source,
        "schema": "expanded_53col" if is_rich else "legacy_11col",
        "quarters_analyzed": len(df),
        "latest_quarter": latest_qtr,
    }
    # Staleness warning: flag if data is more than 2 quarters old
    try:
        q_year = int(str(latest_qtr).split("-")[0])
        from datetime import datetime as _dt
        current_year = _dt.now().year
        if q_year < current_year - 1:
            analysis["data_warning"] = (
                f"STALE DATA — latest quarter is {latest_qtr}, "
                f"over {current_year - q_year} years old. "
                "Valuation and financial analysis may be unreliable."
            )
    except (ValueError, IndexError):
        pass

    # ── Core metrics ─────────────────────────────────────────────
    rev = latest.get("total_revenue")
    cogs = latest.get("cost_of_revenue")
    gp = latest.get("gross_profit")
    oi = latest.get("operating_income")
    ni = latest.get("net_income")
    ebitda = latest.get("ebitda")
    ta = latest.get("total_assets")
    tl = latest.get("total_liabilities")
    ocf = latest.get("operating_cash_flow")
    fcf = latest.get("free_cash_flow")
    capex = latest.get("capital_expenditure")

    metrics = {
        "revenue": rev,
        "cost_of_revenue": cogs,
        "gross_profit": gp,
        "operating_income": oi,
        "net_income": ni,
        "ebitda": ebitda,
        "total_assets": ta,
        "total_liabilities": tl,
        "operating_cash_flow": ocf,
        "free_cash_flow": fcf,
        "capital_expenditure": capex,
        "debt_ratio": latest.get("debt_ratio"),
    }

    # Per-share metrics (rich schema only)
    if is_rich:
        metrics["diluted_eps"] = latest.get("diluted_eps")
        metrics["diluted_shares"] = latest.get("diluted_shares")
        metrics["stock_based_compensation"] = latest.get("stock_based_compensation")
        metrics["research_development"] = latest.get("research_development")

    analysis["latest_metrics"] = {k: v for k, v in metrics.items() if v is not None and not (isinstance(v, float) and pd.isna(v))}

    # ── Margins ──────────────────────────────────────────────────
    margins = {}
    margins["gross_margin_pct"] = _pct(gp, rev)
    margins["operating_margin_pct"] = _pct(oi, rev)
    margins["net_margin_pct"] = _pct(ni, rev)
    margins["ebitda_margin_pct"] = _pct(ebitda, rev)
    if is_rich:
        margins["rd_to_revenue_pct"] = _pct(latest.get("research_development"), rev)
        margins["sbc_to_revenue_pct"] = _pct(latest.get("stock_based_compensation"), rev)
    analysis["margins"] = {k: v for k, v in margins.items() if v is not None}

    # ── Cash flow quality ────────────────────────────────────────
    cfq = {}
    ocf_ni = _safe_div(ocf, ni)
    if ocf_ni is not None:
        cfq["ocf_to_net_income"] = _safe_round(ocf_ni)
        cfq["interpretation"] = (
            "Strong — cash flow well supports earnings" if ocf_ni >= 0.8
            else "Adequate — moderate cash conversion" if ocf_ni >= 0.5
            else "Weak — earnings may not be backed by cash"
        )
    if fcf is not None and rev:
        cfq["fcf_margin_pct"] = _pct(fcf, rev)
    if capex is not None and ocf:
        cfq["capex_to_ocf_pct"] = _pct(abs(capex) if capex else None, ocf)
    if cfq:
        analysis["cash_flow_quality"] = cfq

    # ── Balance sheet ────────────────────────────────────────────
    bs = {}
    if ta and tl:
        equity = ta - tl
        se = latest.get("stockholders_equity")
        if se is not None and not pd.isna(se):
            equity = se
        bs["total_equity"] = equity
        bs["equity_ratio"] = _safe_round(_safe_div(equity, ta), 4)
        bs["leverage_ratio"] = _safe_round(_safe_div(tl, equity))
    if is_rich:
        cr = latest.get("current_ratio")
        if cr is not None and not pd.isna(cr):
            bs["current_ratio"] = _safe_round(cr)
        dte = latest.get("debt_to_equity")
        if dte is not None and not pd.isna(dte):
            bs["debt_to_equity"] = _safe_round(dte)
        td = latest.get("total_debt")
        if td is not None and not pd.isna(td):
            bs["total_debt"] = td
        nd = latest.get("net_debt")
        if nd is not None and not pd.isna(nd):
            bs["net_debt"] = nd
    if bs:
        analysis["balance_sheet"] = bs

    # ── Growth trends (QoQ) ──────────────────────────────────────
    growth_metrics = ["total_revenue", "net_income", "operating_cash_flow"]
    if is_rich:
        growth_metrics.extend(["free_cash_flow", "ebitda", "gross_profit"])

    growth_trend = []
    for i in range(min(len(df) - 1, 4)):
        curr_q = df.iloc[i]
        prev_q = df.iloc[i + 1]
        entry = {"from": prev_q.get("quarter", "?"), "to": curr_q.get("quarter", "?")}
        for metric in growth_metrics:
            g = _growth_pct(curr_q.get(metric), prev_q.get(metric))
            if g is not None:
                entry[f"{metric}_growth_pct"] = g
        growth_trend.append(entry)
    analysis["growth_trend"] = growth_trend

    # ── YoY comparison ───────────────────────────────────────────
    if len(df) >= 5:
        curr = df.iloc[0]
        yoy = df.iloc[4]
        yoy_metrics = {}
        for metric in growth_metrics + ["operating_income"]:
            g = _growth_pct(curr.get(metric), yoy.get(metric))
            if g is not None:
                yoy_metrics[f"{metric}_yoy_growth_pct"] = g
        if yoy_metrics:
            analysis["year_over_year"] = {
                "current_quarter": curr.get("quarter", "?"),
                "year_ago_quarter": yoy.get("quarter", "?"),
                **yoy_metrics,
            }

    # ── Return on Capital (v1.3) ─────────────────────────────────
    roc = {}
    se = latest.get("stockholders_equity")
    ic = latest.get("invested_capital")

    # ROE = Net Income / Stockholders' Equity (annualized: * 4 for quarterly)
    roe = _safe_div(ni, se)
    if roe is not None:
        roc["roe_quarterly_pct"] = _safe_round(roe * 100)
        roc["roe_annualized_pct"] = _safe_round(roe * 4 * 100)

    # ROIC = NOPAT / Invested Capital (NOPAT = OI * (1 - effective tax rate))
    tax = latest.get("tax_provision")
    pretax = latest.get("pretax_income")
    eff_tax_rate = _safe_div(tax, pretax)
    if eff_tax_rate is not None and oi is not None and ic is not None:
        try:
            if not pd.isna(oi) and not pd.isna(ic) and ic != 0:
                nopat = oi * (1 - eff_tax_rate)
                roic = _safe_div(nopat, ic)
                if roic is not None:
                    roc["roic_quarterly_pct"] = _safe_round(roic * 100)
                    roc["roic_annualized_pct"] = _safe_round(roic * 4 * 100)
                    roc["effective_tax_rate_pct"] = _safe_round(eff_tax_rate * 100)
        except (TypeError, ValueError):
            pass

    # ROA = Net Income / Total Assets
    roa = _safe_div(ni, ta)
    if roa is not None:
        roc["roa_quarterly_pct"] = _safe_round(roa * 100)
        roc["roa_annualized_pct"] = _safe_round(roa * 4 * 100)

    if roc:
        analysis["return_on_capital"] = roc

    # ── Margin Trends (v1.3) ──────────────────────────────────
    if is_rich and len(df) >= 3:
        mt = _compute_margin_trends(df)
        if mt:
            analysis["margin_trends"] = mt

    # ── Net Cash Position (v1.3) ──────────────────────────────
    cash_pos = {}
    cash = latest.get("cash_and_equivalents")
    csti = latest.get("cash_and_short_term_investments")
    td = latest.get("total_debt") if is_rich else None
    nd = latest.get("net_debt") if is_rich else None

    if cash is not None and not (isinstance(cash, float) and pd.isna(cash)):
        cash_pos["cash_and_equivalents"] = cash
    if csti is not None and not (isinstance(csti, float) and pd.isna(csti)):
        cash_pos["cash_and_short_term_investments"] = csti
    if td is not None and not (isinstance(td, float) and pd.isna(td)):
        cash_pos["total_debt"] = td
    if nd is not None and not (isinstance(nd, float) and pd.isna(nd)):
        cash_pos["net_debt"] = nd
        cash_pos["net_cash_position"] = -nd  # positive = net cash
        cash_pos["position"] = "net_cash" if nd < 0 else "net_debt"

    if cash_pos:
        analysis["net_cash_position"] = cash_pos

    # ── Capital Allocation (v1.3) ─────────────────────────────
    cap_alloc = {}
    buybacks = latest.get("share_repurchases")
    dividends = latest.get("dividends_paid")
    sbc = latest.get("stock_based_compensation")

    def _valid(v):
        return v is not None and not (isinstance(v, float) and pd.isna(v))

    if _valid(buybacks):
        cap_alloc["share_repurchases"] = buybacks
        cap_alloc["buyback_to_revenue_pct"] = _pct(abs(buybacks), rev)
        if fcf:
            cap_alloc["buyback_to_fcf_pct"] = _pct(abs(buybacks), fcf)

    if _valid(dividends):
        cap_alloc["dividends_paid"] = dividends
        cap_alloc["dividend_to_revenue_pct"] = _pct(abs(dividends), rev)

    # Total shareholder return (buybacks + dividends) as % of FCF
    if _valid(buybacks) and _valid(dividends):
        total_return = abs(buybacks or 0) + abs(dividends or 0)
        cap_alloc["total_shareholder_return"] = total_return
        if fcf:
            cap_alloc["total_return_to_fcf_pct"] = _pct(total_return, fcf)

    # SBC dilution analysis
    if _valid(sbc):
        cap_alloc["sbc"] = sbc
        if _valid(buybacks):
            cap_alloc["net_buyback_vs_sbc"] = abs(buybacks) - sbc
            cap_alloc["net_dilution"] = "dilutive" if sbc > abs(buybacks or 0) else "accretive"

    if cap_alloc:
        analysis["capital_allocation"] = {k: v for k, v in cap_alloc.items() if v is not None}

    # ── Balance Sheet Efficiency (v1.3) ───────────────────────
    if is_rich:
        eff = _compute_efficiency_metrics(latest)
        if eff:
            analysis["balance_sheet_efficiency"] = eff

    # ── Enhanced Cash Flow Quality (v1.3 additions) ───────────
    cfq_adds = {}
    if _valid(sbc) and rev:
        cfq_adds["sbc_to_revenue_pct"] = _pct(sbc, rev)
    if fcf is not None and ni is not None:
        cfq_adds["fcf_to_net_income"] = _safe_round(_safe_div(fcf, ni))
    if ocf is not None and rev:
        cfq_adds["ocf_to_revenue_pct"] = _pct(ocf, rev)
    if cfq_adds:
        if "cash_flow_quality" not in analysis:
            analysis["cash_flow_quality"] = {}
        analysis["cash_flow_quality"].update(cfq_adds)

    # ── Sector Classification (v1.3) ─────────────────────────
    try:
        from tools.sector_mapping import get_sector, get_industry_group
        sector = get_sector(ticker)
        industry = get_industry_group(ticker)
        if sector:
            analysis["sector_classification"] = {
                "gics_sector": sector,
                "gics_industry_group": industry,
            }
    except ImportError:
        pass  # sector_mapping not yet available

    # ── Flags ────────────────────────────────────────────────────
    flags = []
    om = analysis.get("margins", {}).get("operating_margin_pct")
    if om is not None:
        if om > 30:
            flags.append(f"HIGH_MARGIN: Operating margin {om}% — premium business")
        elif om < 5:
            flags.append(f"LOW_MARGIN: Operating margin {om}% — thin margins")
        if om < 0:
            flags.append(f"OPERATING_LOSS: Operating margin {om}% — burning cash")

    gm = analysis.get("margins", {}).get("gross_margin_pct")
    if gm is not None and gm > 60:
        flags.append(f"HIGH_GROSS_MARGIN: {gm}% — strong pricing power")

    cq = analysis.get("cash_flow_quality", {}).get("ocf_to_net_income")
    if cq is not None and cq < 0.5:
        flags.append(f"CASH_FLOW_WARNING: OCF/NI ratio {cq} — earnings quality concern")

    lr = analysis.get("balance_sheet", {}).get("leverage_ratio")
    if lr is not None and lr > 5:
        flags.append(f"HIGH_LEVERAGE: Leverage ratio {lr}")

    cr = analysis.get("balance_sheet", {}).get("current_ratio")
    if cr is not None and cr < 1.0:
        flags.append(f"LOW_CURRENT_RATIO: {cr} — potential liquidity risk")

    rd_pct = analysis.get("margins", {}).get("rd_to_revenue_pct")
    if rd_pct is not None and rd_pct > 20:
        flags.append(f"HIGH_RD_SPEND: R&D at {rd_pct}% of revenue — heavy investment phase")

    # Revenue decline detection
    if analysis.get("year_over_year", {}).get("total_revenue_yoy_growth_pct") is not None:
        yoy_rev = analysis["year_over_year"]["total_revenue_yoy_growth_pct"]
        if yoy_rev < -5:
            flags.append(f"REVENUE_DECLINE: YoY revenue down {yoy_rev}%")

    # v1.3 flags — Return on capital
    roe_ann = analysis.get("return_on_capital", {}).get("roe_annualized_pct")
    if roe_ann is not None:
        if roe_ann > 30:
            flags.append(f"HIGH_ROE: {roe_ann}% annualized — exceptional capital efficiency")
        elif 0 < roe_ann < 5:
            flags.append(f"LOW_ROE: {roe_ann}% annualized — weak capital returns")
    roic_ann = analysis.get("return_on_capital", {}).get("roic_annualized_pct")
    if roic_ann is not None and roic_ann > 25:
        flags.append(f"HIGH_ROIC: {roic_ann}% annualized — strong value creation")

    # Negative equity
    se_val = latest.get("stockholders_equity") if is_rich else None
    if se_val is not None and not (isinstance(se_val, float) and pd.isna(se_val)) and se_val < 0:
        flags.append("NEGATIVE_EQUITY: Stockholders' equity is negative — ROE undefined")

    # Net cash flag
    net_cash_val = analysis.get("net_cash_position", {}).get("net_cash_position")
    if net_cash_val is not None and net_cash_val > 0 and rev:
        cash_to_rev = net_cash_val / rev
        if cash_to_rev > 0.5:
            flags.append(f"LARGE_NET_CASH: Net cash is {_safe_round(cash_to_rev * 100)}% of quarterly revenue")

    # SBC dilution flag
    net_dilution = analysis.get("capital_allocation", {}).get("net_dilution")
    if net_dilution == "dilutive":
        flags.append("SBC_DILUTION: Stock-based compensation exceeds share buybacks — net dilutive")

    # Margin trend flags
    for margin_name, trend_data in analysis.get("margin_trends", {}).items():
        trend = trend_data.get("trend")
        if trend == "declining":
            flags.append(f"MARGIN_DECLINING: {margin_name} trending down across recent quarters")
        elif trend == "improving":
            flags.append(f"MARGIN_IMPROVING: {margin_name} trending up across recent quarters")

    # Cash conversion cycle flag
    ccc = analysis.get("balance_sheet_efficiency", {}).get("cash_conversion_cycle")
    if ccc is not None and ccc > 120:
        flags.append(f"SLOW_CASH_CYCLE: Cash conversion cycle {ccc} days — capital tied up")

    analysis["flags"] = flags

    # ── Valuation summary (from financial data) ───────────────────
    valuation = {}
    eps_val = latest.get("diluted_eps") if is_rich else None
    if eps_val is not None and not (isinstance(eps_val, float) and pd.isna(eps_val)):
        valuation["diluted_eps"] = _safe_round(eps_val)
        # Annualized EPS (quarterly * 4) for trailing PE context
        valuation["annualized_eps"] = _safe_round(eps_val * 4)
    # Book value per share
    shares = latest.get("diluted_shares")
    se_val = latest.get("stockholders_equity")
    if se_val is not None and shares is not None and shares > 0:
        if not (isinstance(se_val, float) and pd.isna(se_val)):
            valuation["book_value_per_share"] = _safe_round(se_val / shares)
    valuation["note"] = "For market P/E, use graham_analysis(ticker) or get_valuation_snapshot()"
    analysis["valuation"] = valuation

    return json.dumps(analysis, indent=2, default=str)


def get_valuation_snapshot() -> str:
    """Get the latest valuation snapshot for tracked companies.

    Returns the _valuation_snapshot.csv which includes current
    market cap, P/E, P/B, margins, and other valuation multiples.
    """
    path = os.path.join(EQUITY_FINANCIALS_DIR, "_valuation_snapshot.csv")
    if not os.path.exists(path):
        return json.dumps({"error": "Valuation snapshot not available"})
    try:
        df = pd.read_csv(path)
        return json.dumps({
            "companies": len(df),
            "columns": list(df.columns),
            "data": df.to_dict(orient="records"),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def compare_equity_metrics(tickers: str) -> str:
    """Compare financial metrics across multiple companies side by side.

    Works for any of the ~500 S&P 500 companies. When comparing more than
    20 tickers, output is condensed to key metrics only.

    Args:
        tickers: Comma-separated ticker list (e.g. 'AAPL,MSFT,NVDA').
                 Leave empty for top-20 watchlist.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else TOP_20_TICKERS

    comparison = []
    for ticker in ticker_list:
        df = _load_equity_csv(ticker)
        if df is None or len(df) == 0:
            comparison.append({"ticker": ticker, "status": "no_data"})
            continue

        latest = df.iloc[0]
        rev = latest.get("total_revenue")
        ni = latest.get("net_income")
        oi = latest.get("operating_income")
        gp = latest.get("gross_profit")
        ocf = latest.get("operating_cash_flow")
        fcf = latest.get("free_cash_flow")

        entry = {
            "ticker": ticker,
            "company": latest.get("company_name", "?"),
            "quarter": latest.get("quarter", "?"),
            "revenue": rev,
            "net_income": ni,
            "gross_margin_pct": _pct(gp, rev),
            "operating_margin_pct": _pct(oi, rev),
            "net_margin_pct": _pct(ni, rev),
            "debt_ratio": latest.get("debt_ratio"),
            "ocf_to_ni": _safe_round(_safe_div(ocf, ni)),
        }

        # Rich-schema extras
        if "free_cash_flow" in df.columns:
            entry["fcf"] = fcf
            entry["fcf_margin_pct"] = _pct(fcf, rev)
        if "diluted_eps" in df.columns:
            eps = latest.get("diluted_eps")
            if eps is not None and not (isinstance(eps, float) and pd.isna(eps)):
                entry["diluted_eps"] = _safe_round(eps)
        if "current_ratio" in df.columns:
            cr = latest.get("current_ratio")
            if cr is not None and not (isinstance(cr, float) and pd.isna(cr)):
                entry["current_ratio"] = _safe_round(cr)

        # YoY revenue growth
        if len(df) >= 5:
            g = _growth_pct(rev, df.iloc[4].get("total_revenue"))
            if g is not None:
                entry["revenue_yoy_growth_pct"] = g

        # v1.3 additions — ROE, net cash, sector
        se = latest.get("stockholders_equity")
        if se is not None and ni is not None:
            entry["roe_quarterly_pct"] = _pct(ni, se)
        nd = latest.get("net_debt")
        if nd is not None and not (isinstance(nd, float) and pd.isna(nd)):
            entry["net_cash_position"] = -nd
        try:
            from tools.sector_mapping import get_sector
            s = get_sector(ticker)
            if s:
                entry["sector"] = s
        except ImportError:
            pass

        comparison.append(entry)

    return json.dumps({
        "companies_compared": len(comparison),
        "comparison": comparison,
    }, indent=2, default=str)


def analyze_capital_allocation(ticker: str) -> str:
    """Analyze capital allocation strategy across available quarters.

    Tracks share repurchases, dividends, stock-based compensation, and
    net dilution/accretion trends. Shows how a company returns capital
    to shareholders and whether SBC offsets buybacks.

    Args:
        ticker: Stock ticker (e.g. 'AAPL', 'NVDA', 'BRK-B').
    """
    ticker = ticker.strip().upper()
    df = _load_equity_csv(ticker)
    if df is None:
        return json.dumps({"error": f"No data for ticker '{ticker}'. Use search_equities() to find valid tickers."})

    result = {
        "ticker": ticker,
        "company": df.iloc[0].get("company_name", "?"),
        "quarters_analyzed": len(df),
    }

    quarterly = []
    for _, row in df.iterrows():
        # Validate diluted_shares — must be positive (negative is data error)
        ds = row.get("diluted_shares")
        if ds is not None and not pd.isna(ds) and ds < 0:
            ds = None  # Discard impossible negative share count
        q = {
            "quarter": row.get("quarter", "?"),
            "share_repurchases": row.get("share_repurchases"),
            "dividends_paid": row.get("dividends_paid"),
            "stock_based_compensation": row.get("stock_based_compensation"),
            "free_cash_flow": row.get("free_cash_flow"),
            "diluted_shares": ds,
        }
        fcf_val = row.get("free_cash_flow")
        bb = row.get("share_repurchases")
        sbc_val = row.get("stock_based_compensation")
        q["buyback_to_fcf_pct"] = _pct(abs(bb) if bb else None, fcf_val)
        q["sbc_to_fcf_pct"] = _pct(sbc_val, fcf_val)
        if bb is not None and sbc_val is not None:
            try:
                if not pd.isna(bb) and not pd.isna(sbc_val):
                    q["net_buyback_less_sbc"] = abs(bb) - sbc_val
            except (TypeError, ValueError):
                pass
        quarterly.append({k: v for k, v in q.items() if v is not None and not (isinstance(v, float) and pd.isna(v))})

    result["quarterly_data"] = quarterly

    # Share count trend (dilution check) — oldest to newest
    shares = [row.get("diluted_shares") for _, row in df.iloc[::-1].iterrows()]
    result["share_count_trend"] = _trend_direction(shares)

    # Latest quarter summary
    latest = quarterly[0] if quarterly else {}
    total_return = abs(latest.get("share_repurchases", 0) or 0) + abs(latest.get("dividends_paid", 0) or 0)
    result["latest_quarter_summary"] = {
        "total_shareholder_return": total_return,
        "buyback_strategy": "active" if (latest.get("share_repurchases") or 0) != 0 else "inactive",
        "dividend_strategy": "active" if (latest.get("dividends_paid") or 0) != 0 else "inactive",
    }

    return json.dumps(result, indent=2, default=str)


def get_peer_comparison(ticker: str, top_n: int = 8) -> str:
    """Compare a company against its sector peers (GICS classification).

    Finds companies in the same GICS industry group and compares key metrics:
    margins, growth, ROE, cash flow quality, and balance sheet health.
    Includes peer medians for context.

    Args:
        ticker: Reference ticker to find peers for (e.g. 'NVDA').
        top_n: Max number of peers to include (default 8, max 20).
    """
    try:
        from tools.sector_mapping import get_sector, get_industry_group, get_sector_peers
    except ImportError:
        return json.dumps({
            "error": "Sector mapping not available. Use compare_equity_metrics() with manual ticker list.",
        })

    ticker = ticker.strip().upper()
    sector = get_sector(ticker)
    industry = get_industry_group(ticker)

    if not sector:
        return json.dumps({
            "error": f"No GICS classification for '{ticker}'.",
            "suggestion": "Use compare_equity_metrics() with manually specified peer tickers.",
        })

    # Try industry group first (tight peers), fall back to sector
    peers = get_sector_peers(ticker, same_industry_group=True)
    peer_level = "industry_group"
    if len(peers) < 3:
        peers = get_sector_peers(ticker, same_industry_group=False)
        peer_level = "sector"

    top_n = min(top_n, 20)
    all_tickers = [ticker] + peers[:top_n]

    comparison = []
    for t in all_tickers:
        df = _load_equity_csv(t)
        if df is None or len(df) == 0:
            continue

        latest = df.iloc[0]
        rev = latest.get("total_revenue")
        ni = latest.get("net_income")
        gp = latest.get("gross_profit")
        oi = latest.get("operating_income")
        se = latest.get("stockholders_equity")
        ocf_val = latest.get("operating_cash_flow")
        fcf_val = latest.get("free_cash_flow")

        entry = {
            "ticker": t,
            "is_reference": t == ticker,
            "company": latest.get("company_name", "?"),
            "quarter": latest.get("quarter", "?"),
            "revenue": rev,
            "net_income": ni,
            "gross_margin_pct": _pct(gp, rev),
            "operating_margin_pct": _pct(oi, rev),
            "net_margin_pct": _pct(ni, rev),
            "roe_quarterly_pct": _pct(ni, se),
            "ocf_to_ni": _safe_round(_safe_div(ocf_val, ni)),
            "fcf_margin_pct": _pct(fcf_val, rev),
            "debt_to_equity": _safe_round(latest.get("debt_to_equity")),
            "current_ratio": _safe_round(latest.get("current_ratio")),
        }

        # YoY revenue growth
        if len(df) >= 5:
            g = _growth_pct(rev, df.iloc[4].get("total_revenue"))
            if g is not None:
                entry["revenue_yoy_growth_pct"] = g

        comparison.append(entry)

    # Compute peer median for context
    peer_only = [c for c in comparison if not c.get("is_reference")]
    medians = {}
    for key in ["gross_margin_pct", "operating_margin_pct", "net_margin_pct",
                 "roe_quarterly_pct", "fcf_margin_pct", "revenue_yoy_growth_pct"]:
        vals = [c[key] for c in peer_only if c.get(key) is not None]
        if vals:
            medians[key] = _safe_round(float(np.median(vals)))

    return json.dumps({
        "reference_ticker": ticker,
        "sector": sector,
        "industry_group": industry,
        "peer_level": peer_level,
        "peers_found": len(peers),
        "peers_shown": len(comparison) - 1,
        "peer_medians": medians,
        "comparison": comparison,
    }, indent=2, default=str)


def analyze_balance_sheet_health(ticker: str) -> str:
    """Deep-dive balance sheet analysis with efficiency metrics.

    Computes: DSO, DPO, inventory turnover, cash conversion cycle,
    working capital efficiency, net cash position, and debt structure.
    Tracks trends across available quarters.

    Args:
        ticker: Stock ticker (e.g. 'AAPL', 'NVDA', 'JPM').
    """
    ticker = ticker.strip().upper()
    df = _load_equity_csv(ticker)
    if df is None:
        return json.dumps({"error": f"No data for ticker '{ticker}'. Use search_equities() to find valid tickers."})

    result = {
        "ticker": ticker,
        "company": df.iloc[0].get("company_name", "?"),
        "quarters_analyzed": len(df),
    }

    quarterly_data = []
    for _, row in df.iterrows():
        eff = _compute_efficiency_metrics(row)
        eff["quarter"] = row.get("quarter", "?")

        # Net cash position
        nd = row.get("net_debt")
        if nd is not None and not (isinstance(nd, float) and pd.isna(nd)):
            eff["net_debt"] = nd
            eff["net_cash_position"] = -nd

        # Debt structure
        ltd = row.get("long_term_debt")
        cd = row.get("current_debt")
        td = row.get("total_debt")
        if td is not None and not (isinstance(td, float) and pd.isna(td)) and td != 0:
            if ltd is not None and not (isinstance(ltd, float) and pd.isna(ltd)):
                eff["long_term_debt_pct"] = _pct(ltd, td)
            if cd is not None and not (isinstance(cd, float) and pd.isna(cd)):
                eff["current_debt_pct"] = _pct(cd, td)

        quarterly_data.append(eff)

    result["quarterly_data"] = quarterly_data

    # Trend analysis on key metrics
    if len(quarterly_data) >= 3:
        rev_data = list(reversed(quarterly_data))
        for metric in ["days_sales_outstanding", "inventory_turnover", "cash_conversion_cycle", "working_capital"]:
            vals = [q.get(metric) for q in rev_data]
            result[f"{metric}_trend"] = _trend_direction(vals)

    # Latest snapshot summary
    if quarterly_data:
        result["latest_summary"] = quarterly_data[0]

    return json.dumps(result, indent=2, default=str)
