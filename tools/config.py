"""
Shared configuration for Financial Analysis Tools.

Slim config: data paths + API keys only.
No LLM provider config — Claude Code is the agent.

Environment variables:
  FRED_API_KEY       — required for FRED data (tools/fred_data.py)
  TAVILY_API_KEY     — required for Tavily web search (tools/web_search.py)
  TWITTERAPI_IO_KEY  — required for Twitter tools (tools/twitter_tools.py)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = str(_PROJECT_ROOT)
MACRO2_ROOT = str(_PROJECT_ROOT.parent / "macro_2")
TWITTER_ROOT = str(_PROJECT_ROOT.parent / "Twitter_new")
HISTORICAL_DATA_DIR = os.path.join(MACRO2_ROOT, "historical_data")
EQUITY_FINANCIALS_DIR = os.path.join(HISTORICAL_DATA_DIR, "equity_financials")
BTC_DATA_DIR = str(
    _PROJECT_ROOT.parent
    / "btc-enhanced-streak-mitigation"
    / "binance-futures-data"
    / "data"
)
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

# ── API Keys ─────────────────────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
TWITTERAPI_IO_KEY = os.environ.get("TWITTERAPI_IO_KEY", "")

# ── Equity data paths ────────────────────────────────────────────────
EQUITY_SEC_EDGAR_DIR = os.path.join(EQUITY_FINANCIALS_DIR, "sec_edgar")
EQUITY_YAHOO_DIR = os.path.join(EQUITY_FINANCIALS_DIR, "yahoo_finance")

# ── Curated watchlist (original top-20 mega caps) ────────────────────
TOP_20_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "BRK-B", "TSM", "LLY", "AVGO",
    "JPM", "V", "WMT", "MA", "XOM",
    "UNH", "COST", "HD", "PG", "JNJ",
]


def discover_all_tickers() -> list[str]:
    """Discover all available equity tickers from sec_edgar and yahoo_finance dirs.

    Returns a sorted list of unique ticker symbols. Includes the top-20 legacy
    tickers and all ~500 S&P 500 tickers from the expanded data sources.
    """
    tickers = set(TOP_20_TICKERS)
    for directory in [EQUITY_SEC_EDGAR_DIR, EQUITY_YAHOO_DIR]:
        if os.path.isdir(directory):
            for fname in os.listdir(directory):
                if fname.endswith("_quarterly.csv") and not fname.startswith("_"):
                    ticker = fname.replace("_quarterly.csv", "")
                    tickers.add(ticker)
    return sorted(tickers)


# ── Macro indicator CSV files ────────────────────────────────────────
MACRO_INDICATORS = {
    "vix_move": "VIX / MOVE Index",
    "dxy": "US Dollar Index (DXY)",
    "10y_treasury_yield": "10-Year Treasury Yield",
    "us_2y_yield": "US 2-Year Treasury Yield",
    "gold": "Gold Futures",
    "silver": "Silver Futures",
    "crude_oil": "Crude Oil Futures",
    "copper": "Copper Futures",
    "es_futures": "ES Futures (S&P 500)",
    "rty_futures": "RTY Futures (Russell 2000)",
    "jpy": "USD/JPY Exchange Rate",
    "russell_2000": "Russell 2000 Index",
    "sp500_ma200": "S&P 500 / 200-day MA",
    "shiller_cape": "Shiller CAPE Ratio",
    "sp500_fundamentals": "S&P 500 P/E & P/B",
    "cboe_skew": "CBOE SKEW Index",
    "us_gdp": "US GDP",
    "ism_pmi": "ISM Manufacturing PMI",
    "tga_balance": "Treasury General Account Balance",
    "net_liquidity": "Fed Net Liquidity",
    "sofr": "SOFR Rate",
    "cot_gold": "COT Gold Positioning",
    "cot_silver": "COT Silver Positioning",
    "japan_2y_yield": "Japan 2Y Government Bond Yield",
    "us2y_jp2y_spread": "US 2Y - Japan 2Y Spread",
    "market_cap": "Total Market Cap",
    "marketcap_to_gdp": "Market Cap / GDP (Buffett Indicator)",
}
