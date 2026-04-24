"""ETF Analysis Tools.

Provides investment-grade analysis for ETFs using yfinance.
Covers AUM, expense ratio, NAV, top holdings, concentration risk,
sector/country exposure, and performance metrics.

Works for any US-listed ETF (EWY, EWT, REMX, LIT, SPY, QQQ, etc.).

All public functions return JSON strings (json.dumps with indent=2).

Usage:
    from tools.etf_analysis import is_etf, analyze_etf
    is_etf('EWY')           # True
    analyze_etf('EWY')      # Full JSON analysis
"""

import json
import logging
import concurrent.futures
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _yf_ticker(symbol: str):
    """Return a yfinance Ticker, suppressing noisy log warnings."""
    import yfinance as yf
    log = logging.getLogger("yfinance")
    prev = log.level
    log.setLevel(logging.CRITICAL)
    try:
        return yf.Ticker(symbol)
    finally:
        log.setLevel(prev)


def _fetch_info(ticker_obj) -> dict:
    """Fetch .info with 15-second hard timeout."""
    def _get():
        return ticker_obj.info or {}

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_get).result(timeout=15)
    except Exception:
        return {}


def _safe_round(val, digits=2):
    if val is None:
        return None
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return None
        return round(v, digits)
    except (TypeError, ValueError):
        return None


def _fmt_aum(aum_usd: float | None) -> str | None:
    """Format AUM as a human-readable string (e.g. '$15.7B')."""
    if aum_usd is None:
        return None
    try:
        v = float(aum_usd)
        if v >= 1e12:
            return f"${v/1e12:.1f}T"
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def is_etf(ticker: str) -> bool:
    """Return True if the ticker is an ETF, False otherwise.

    Uses yfinance quoteType field. Falls back to False on any error.

    Args:
        ticker: Any stock or ETF symbol (e.g. 'EWY', 'AAPL').
    """
    try:
        t = _yf_ticker(ticker.upper())
        info = _fetch_info(t)
        return info.get("quoteType", "").upper() in ("ETF", "MUTUALFUND")
    except Exception:
        return False


def analyze_etf(ticker: str) -> str:
    """Comprehensive ETF analysis.

    Returns a JSON string with:
    - fund_info: name, family, AUM, expense ratio, inception date, category
    - performance: YTD, 1Y, 3Y returns; beta, Sharpe proxy
    - valuation: P/E, P/B, dividend yield
    - concentration: top-10 holdings with weights; top-10 % of total
    - exposure: sector weights, country/region exposure where available
    - risk_flags: concentration alerts, China exposure, currency risk, etc.

    Args:
        ticker: ETF symbol (e.g. 'EWY', 'EWT', 'REMX', 'LIT', 'SPY').
    """
    ticker = ticker.strip().upper()
    t = _yf_ticker(ticker)
    info = _fetch_info(t)

    if not info:
        return json.dumps({"error": f"No data available for '{ticker}'"})

    quote_type = info.get("quoteType", "")
    if quote_type.upper() not in ("ETF", "MUTUALFUND"):
        return json.dumps({
            "error": f"'{ticker}' does not appear to be an ETF (quoteType='{quote_type}'). "
                     "Use analyze_equity_valuation() for individual stocks."
        })

    # ── Fund metadata ─────────────────────────────────────────────────
    total_assets = info.get("totalAssets")
    # Note: yfinance does not reliably expose expense ratios for ETFs.
    # expenseRatio returns None for most ETFs. The value is populated below
    # from funds_data.fund_overview if available; otherwise omitted from output.
    expense_ratio = info.get("expenseRatio") or info.get("annualReportExpenseRatio")
    nav = info.get("navPrice") or info.get("regularMarketPrice")

    fund_info = {
        "ticker":          ticker,
        "name":            info.get("shortName") or info.get("longName", ticker),
        "fund_family":     info.get("fundFamily"),
        "category":        info.get("category") or info.get("fundFamily"),
        "aum_usd":         total_assets,
        "aum_formatted":   _fmt_aum(total_assets),
        "nav":             _safe_round(nav),
        "inception_date":  info.get("fundInceptionDate"),
        "legal_type":      info.get("legalType"),
        "exchange":        info.get("exchange"),
    }
    # Only include expense ratio if actually available
    if expense_ratio is not None:
        fund_info["expense_ratio_pct"] = _safe_round(float(expense_ratio) * 100, 3)

    # ── Valuation ─────────────────────────────────────────────────────
    valuation = {}
    pe = info.get("trailingPE") or info.get("forwardPE")
    pb = info.get("priceToBook")
    div_yield = info.get("yield") or info.get("trailingAnnualDividendYield")
    if pe:   valuation["trailing_pe"]   = _safe_round(pe)
    if pb:   valuation["price_to_book"] = _safe_round(pb)
    if div_yield:
        valuation["dividend_yield_pct"] = _safe_round(float(div_yield) * 100, 2)
    beta = info.get("beta3Year") or info.get("beta")
    if beta: valuation["beta"] = _safe_round(beta)

    # ── Performance ───────────────────────────────────────────────────
    performance = {}
    try:
        hist = t.history(period="2y", progress=False)
        if hist is not None and not hist.empty:
            close = hist["Close"].dropna()
            if len(close) >= 2:
                curr = float(close.iloc[-1])
                # YTD
                ytd_start = close[close.index.year == datetime.now().year]
                if not ytd_start.empty:
                    first_ytd = float(ytd_start.iloc[0])
                    performance["ytd_pct"] = _safe_round(
                        (curr / first_ytd - 1) * 100
                    )
                # 1Y
                one_yr_ago = datetime.now() - timedelta(days=365)
                prior_1y = close[close.index.tz_localize(None) <= one_yr_ago]
                if not prior_1y.empty:
                    performance["return_1y_pct"] = _safe_round(
                        (curr / float(prior_1y.iloc[-1]) - 1) * 100
                    )
                # Daily returns for vol / Sharpe proxy
                daily_ret = close.pct_change().dropna()
                if len(daily_ret) > 20:
                    ann_vol = float(daily_ret.std() * np.sqrt(252) * 100)
                    performance["ann_volatility_pct"] = _safe_round(ann_vol)
                    ann_ret = float(daily_ret.mean() * 252 * 100)
                    if ann_vol > 0:
                        performance["sharpe_proxy"] = _safe_round(ann_ret / ann_vol)
    except Exception:
        pass

    # ── Holdings & concentration ──────────────────────────────────────
    holdings_data = []
    concentration = {}
    try:
        fd = t.funds_data
        if fd is not None:
            # ── Top holdings ──
            # yfinance funds_data: top_holdings has Symbol as index,
            # columns are 'Name' and 'Holding Percent'
            th = getattr(fd, "top_holdings", None)
            if th is not None and not th.empty:
                for sym, row in th.head(15).iterrows():
                    h = {"symbol": str(sym)}
                    # Find name column (any column with 'name' in it)
                    name_val = None
                    for col in th.columns:
                        if "name" in col.lower():
                            name_val = row[col]
                            break
                    if name_val is not None:
                        h["name"] = str(name_val)
                    # Find weight column (any column with 'percent' or 'weight')
                    wt_val = None
                    for col in th.columns:
                        if "percent" in col.lower() or "weight" in col.lower():
                            wt_val = row[col]
                            break
                    if wt_val is not None:
                        v = float(wt_val)
                        h["weight_pct"] = _safe_round(v * 100 if v <= 1 else v)
                    holdings_data.append(h)

            # ── Sector weights — dict or DataFrame ──
            sw = getattr(fd, "sector_weightings", None)
            if sw is not None:
                sector_exp = {}
                if isinstance(sw, dict):
                    # yfinance returns {sector: fraction} dict
                    for sec, wt in sw.items():
                        if wt is not None:
                            v = float(wt)
                            sector_exp[str(sec)] = _safe_round(v * 100 if v <= 1 else v)
                elif hasattr(sw, "iterrows"):
                    for _, row in sw.iterrows():
                        sec = row.get("sector")
                        wt  = row.get("weight") or row.get("percentage")
                        if sec and wt is not None:
                            v = float(wt)
                            sector_exp[str(sec)] = _safe_round(v * 100 if v <= 1 else v)
                if sector_exp:
                    concentration["sector_weights"] = sector_exp

            # ── Country / market allocation ──
            for attr in ("country_weightings", "market_allocation", "country_weights"):
                cw = getattr(fd, attr, None)
                if cw is None:
                    continue
                country_exp = {}
                if isinstance(cw, dict):
                    for ctry, wt in cw.items():
                        if wt is not None:
                            v = float(wt)
                            country_exp[str(ctry)] = _safe_round(v * 100 if v <= 1 else v)
                elif hasattr(cw, "iterrows"):
                    for _, row in cw.iterrows():
                        ctry = row.get("country") or row.get("region")
                        wt   = row.get("weight") or row.get("percentage")
                        if ctry and wt is not None:
                            v = float(wt)
                            country_exp[str(ctry)] = _safe_round(v * 100 if v <= 1 else v)
                if country_exp:
                    concentration["country_weights"] = country_exp
                    break  # found it, stop searching

            # ── Fund overview (expense ratio may be here) ──
            fo = getattr(fd, "fund_overview", None)
            if isinstance(fo, dict):
                er_fo = fo.get("expenseRatio") or fo.get("annual_expense_ratio")
                if er_fo is not None:
                    fund_info["expense_ratio_pct"] = _safe_round(float(er_fo) * 100, 3)

    except Exception:
        pass

    # Concentration metrics
    if holdings_data:
        weights = [h["weight_pct"] for h in holdings_data if h.get("weight_pct") is not None]
        if weights:
            top5_pct  = _safe_round(sum(weights[:5]))
            top10_pct = _safe_round(sum(weights[:10]))
            concentration["top_5_holdings_pct"]  = top5_pct
            concentration["top_10_holdings_pct"] = top10_pct
        concentration["holdings"] = holdings_data

    # ── Risk flags ────────────────────────────────────────────────────
    risk_flags = []

    # Concentration risk: top-10 > 50% is notable
    top10 = concentration.get("top_10_holdings_pct")
    if top10 and top10 > 50:
        risk_flags.append(
            f"HIGH CONCENTRATION: top-10 holdings = {top10:.1f}% of fund. "
            "Single-name risk is elevated."
        )

    # China A-share exposure
    country_wts = concentration.get("country_weights", {})
    china_exp = sum(
        v for k, v in country_wts.items()
        if isinstance(v, (int, float)) and "china" in k.lower()
    )
    if china_exp > 10:
        risk_flags.append(
            f"CHINA EXPOSURE: ~{china_exp:.0f}% of fund in Chinese securities. "
            "Subject to US-China trade/geopolitical risk and potential delisting."
        )

    # Single-name concentration (top holding > 20%)
    if holdings_data:
        top_holding = holdings_data[0]
        top_wt = top_holding.get("weight_pct", 0) or 0
        if top_wt > 20:
            name = top_holding.get("name") or top_holding.get("symbol", "?")
            risk_flags.append(
                f"TOP-HOLDING DOMINANCE: '{name}' = {top_wt:.1f}% of fund. "
                "This is effectively a concentrated single-name bet."
            )

    # AUM < $500M = liquidity/closure risk
    if total_assets and total_assets < 500_000_000:
        risk_flags.append(
            f"LOW AUM: {_fmt_aum(total_assets)} — small fund size increases "
            "closure risk and bid/ask spreads."
        )

    # Expense ratio > 0.75%
    er = fund_info.get("expense_ratio_pct") or 0
    if er and er > 0.75:
        risk_flags.append(
            f"HIGH EXPENSE RATIO: {er:.2f}% — above the 0.75% threshold for "
            "ETFs. Compounds to meaningful drag over multi-year holds."
        )

    # ── Assemble output ───────────────────────────────────────────────
    output = {
        "type":        "ETF",
        "fund_info":   {k: v for k, v in fund_info.items()  if v is not None},
        "valuation":   valuation,
        "performance": performance,
    }
    if concentration:
        output["concentration"] = concentration
    if risk_flags:
        output["risk_flags"] = risk_flags
    else:
        output["risk_flags"] = ["No major structural risk flags detected."]

    return json.dumps(output, indent=2, default=str)
