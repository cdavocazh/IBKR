#!/usr/bin/env python3
"""Unified CLI entry point for Financial Analysis Agent tools.

Run any tool function directly from the command line.
Claude Code calls these functions; this script lets you test them standalone.

Usage:
    python tools/run.py scan                          # Quick macro scan
    python tools/run.py scan_full                     # Full macro scan
    python tools/run.py analyze NVDA                  # Equity analysis (auto-routes ETFs to etf_analysis)
    python tools/run.py etf EWY                       # ETF analysis (AUM, holdings, concentration, risk)
    python tools/run.py compare AAPL,MSFT,NVDA        # Cross-ticker comparison
    python tools/run.py peers NVDA                    # GICS peer comparison
    python tools/run.py commodity crude_oil            # Commodity analysis
    python tools/run.py oil                           # Oil fundamentals (FRED)
    python tools/run.py macro                         # Macro regime analysis
    python tools/run.py bonds                         # Bond market analysis
    python tools/run.py drivers SPX                   # Equity index drivers
    python tools/run.py stress                        # Financial stress score
    python tools/run.py latecycle                     # Late-cycle signals
    python tools/run.py consumer                      # Consumer health dashboard
    python tools/run.py housing                       # Housing market analysis
    python tools/run.py labor                         # Labor deep dive
    python tools/run.py btc                           # BTC full analysis
    python tools/run.py bbb                           # Yardeni Boom-Bust Barometer
    python tools/run.py fsmi                          # Yardeni FSMI
    python tools/run.py vigilantes                    # Bond Vigilantes Model
    python tools/run.py valuation                     # Yardeni valuation (Rule of 20/24)
    python tools/run.py drawdown                      # Market decline classification
    python tools/run.py graham AAPL                   # Graham value analysis
    python tools/run.py grahamscreen                  # Graham screen (top-20 by MoS)
    python tools/run.py ta AAPL                       # Murphy technical analysis
    python tools/run.py rsi AAPL                      # RSI calculator
    python tools/run.py sr es_futures                 # Support/resistance
    python tools/run.py breakout gold                 # Breakout analysis
    python tools/run.py quickta btc                   # Quick TA snapshot
    python tools/run.py synthesis NVDA                # Fundamental + TA synthesis
    python tools/run.py riskpremium                   # Risk premium analysis
    python tools/run.py crossasset                    # Cross-asset momentum
    python tools/run.py pmregime                      # Precious metals regime
    python tools/run.py usdregime                     # USD structural regime
    python tools/run.py sl gold 3348 long             # Stop-loss framework
    python tools/run.py synthesize                    # Full macro synthesis
    python tools/run.py search "Fed rate decision"    # Web search
    python tools/run.py indicator vix                 # Single indicator deep dive
    python tools/run.py list                          # List all available tools
"""

import sys
import os
import json

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pp(result):
    """Pretty-print a tool result (dict or string)."""
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, default=str))
    elif isinstance(result, list):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result)


def _show_help():
    print(__doc__)
    sys.exit(0)


def _list_tools():
    """List all available tool functions with brief descriptions."""
    tools = {
        "scan": "Quick macro sweep (top flags + follow-ups)",
        "scan_full": "Full macro sweep (all flags, all indicators)",
        "indicator <name>": "Deep dive on a single macro indicator",
        "analyze <TICKER>": "Investment-grade equity valuation",
        "compare <T1,T2,...>": "Cross-ticker metric comparison",
        "peers <TICKER>": "GICS sector peer comparison",
        "allocation <TICKER>": "Capital allocation analysis",
        "balance <TICKER>": "Balance sheet deep dive",
        "commodity <name>": "Commodity comprehensive analysis",
        "oil": "Oil fundamentals (WTI-Brent, inventories, COT)",
        "macro": "Macro regime classification (6 dimensions)",
        "bonds": "Bond market analysis (curve, credit, duration)",
        "drivers [INDEX]": "Equity index drivers (ERP, DXY, VIX)",
        "stress": "Financial stress score (8-component composite)",
        "latecycle": "Late-cycle signal detection (13 signals)",
        "termpremium": "Term premium dynamics",
        "vixanalysis": "VIX 7-tier opportunity framework",
        "consumer": "Consumer health dashboard",
        "housing": "Housing market analysis",
        "labor": "Labor deep dive (productivity, hiring)",
        "btc": "BTC full analysis (trend + positioning + trade)",
        "btctrend": "BTC trend only",
        "btcposition": "BTC positioning only",
        "bbb": "Yardeni Boom-Bust Barometer",
        "fsmi": "Yardeni FSMI",
        "vigilantes": "Bond Vigilantes Model",
        "valuation": "Yardeni valuation (Rule of 20/24)",
        "drawdown": "Market decline classification",
        "graham <TICKER>": "Graham value analysis",
        "grahamscreen": "Graham screen (top-20 by MoS)",
        "netnet": "Graham net-net WCAV screen",
        "ta <ASSET>": "Murphy 13-framework technical analysis",
        "rsi <ASSET> [period] [tf]": "RSI calculator",
        "sr <ASSET>": "Support/resistance levels",
        "breakout <ASSET>": "Breakout analysis",
        "quickta <ASSET>": "Quick TA snapshot (RSI+S/R+breakout)",
        "synthesis <TICKER>": "Fundamental + TA synthesis",
        "riskpremium": "Risk premium analysis (VIX, vanna/charm, CTA)",
        "crossasset": "Cross-asset momentum & divergences",
        "pmregime": "Precious metals regime classification",
        "usdregime": "USD structural regime & exodus basket",
        "sl <asset> <price> <dir>": "Stop-loss framework",
        "synthesize": "Full macro synthesis (contradictions, recommendations)",
        "search <query>": "Web search (Tavily + DuckDuckGo fallback)",
        "list": "Show this tool list",
    }
    print("Available tools:\n")
    for cmd, desc in tools.items():
        print(f"  {cmd:<30s} {desc}")
    sys.exit(0)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _show_help()

    cmd = sys.argv[1].lower().lstrip("/")
    args = sys.argv[2:]

    # ── Macro ────────────────────────────────────────────────────────
    if cmd == "scan":
        from tools.macro_data import scan_all_indicators
        _pp(scan_all_indicators("short"))

    elif cmd == "scan_full":
        from tools.macro_data import scan_all_indicators
        _pp(scan_all_indicators("full"))

    elif cmd == "indicator":
        from tools.macro_data import analyze_indicator_changes
        if not args:
            print("Usage: run.py indicator <name>")
            sys.exit(1)
        _pp(analyze_indicator_changes(args[0]))

    elif cmd == "macro":
        from tools.macro_market_analysis import analyze_macro_regime
        _pp(analyze_macro_regime())

    elif cmd == "bonds":
        from tools.macro_market_analysis import analyze_bond_market
        _pp(analyze_bond_market())

    elif cmd in ("drivers",):
        from tools.macro_market_analysis import analyze_equity_drivers
        index = args[0] if args else "SPX"
        _pp(analyze_equity_drivers(index))

    elif cmd == "stress":
        from tools.market_regime_enhanced import analyze_financial_stress
        _pp(analyze_financial_stress())

    elif cmd == "latecycle":
        from tools.market_regime_enhanced import detect_late_cycle_signals
        _pp(detect_late_cycle_signals())

    elif cmd == "termpremium":
        from tools.market_regime_enhanced import analyze_term_premium_dynamics
        _pp(analyze_term_premium_dynamics())

    elif cmd == "vixanalysis":
        from tools.market_regime_enhanced import get_enhanced_vix_analysis
        _pp(get_enhanced_vix_analysis())

    # ── Consumer / Housing / Labor ────────────────────────────────────
    elif cmd == "consumer":
        from tools.consumer_housing_analysis import analyze_consumer_health
        _pp(analyze_consumer_health())

    elif cmd == "housing":
        from tools.consumer_housing_analysis import analyze_housing_market
        _pp(analyze_housing_market())

    elif cmd == "labor":
        from tools.consumer_housing_analysis import analyze_labor_deep_dive
        _pp(analyze_labor_deep_dive())

    # ── Equity / ETF (auto-routed) ────────────────────────────────────
    elif cmd == "analyze":
        if not args:
            print("Usage: run.py analyze <TICKER>")
            sys.exit(1)
        ticker = args[0].upper()
        # Router: ETF → etf_analysis, equity → equity_analysis (with yfinance fallback)
        from tools.etf_analysis import is_etf, analyze_etf
        if is_etf(ticker):
            _pp(analyze_etf(ticker))
        else:
            from tools.equity_analysis import analyze_equity_valuation
            _pp(analyze_equity_valuation(ticker))

    elif cmd == "compare":
        from tools.equity_analysis import compare_equity_metrics
        if not args:
            print("Usage: run.py compare <TICKER1,TICKER2,...>")
            sys.exit(1)
        _pp(compare_equity_metrics(args[0].upper()))

    elif cmd == "peers":
        from tools.equity_analysis import get_peer_comparison
        if not args:
            print("Usage: run.py peers <TICKER>")
            sys.exit(1)
        _pp(get_peer_comparison(args[0].upper()))

    elif cmd == "allocation":
        from tools.equity_analysis import analyze_capital_allocation
        if not args:
            print("Usage: run.py allocation <TICKER>")
            sys.exit(1)
        _pp(analyze_capital_allocation(args[0].upper()))

    elif cmd == "balance":
        from tools.equity_analysis import analyze_balance_sheet_health
        if not args:
            print("Usage: run.py balance <TICKER>")
            sys.exit(1)
        _pp(analyze_balance_sheet_health(args[0].upper()))

    # ── Commodity ─────────────────────────────────────────────────────
    elif cmd == "commodity":
        from tools.commodity_analysis import analyze_commodity_outlook
        if not args:
            print("Usage: run.py commodity <name>")
            sys.exit(1)
        _pp(analyze_commodity_outlook(args[0]))

    elif cmd == "oil":
        from tools.fred_data import get_oil_fundamentals
        _pp(get_oil_fundamentals())

    # ── BTC ───────────────────────────────────────────────────────────
    elif cmd == "btc":
        from tools.btc_analysis import analyze_btc_market
        _pp(analyze_btc_market())

    elif cmd == "btctrend":
        from tools.btc_analysis import analyze_btc_trend
        _pp(analyze_btc_trend())

    elif cmd == "btcposition":
        from tools.btc_analysis import analyze_btc_positioning
        _pp(analyze_btc_positioning())

    # ── Yardeni ───────────────────────────────────────────────────────
    elif cmd == "bbb":
        from tools.yardeni_frameworks import get_boom_bust_barometer
        _pp(get_boom_bust_barometer())

    elif cmd == "fsmi":
        from tools.yardeni_frameworks import get_fsmi
        _pp(get_fsmi())

    elif cmd == "vigilantes":
        from tools.yardeni_frameworks import analyze_bond_vigilantes
        _pp(analyze_bond_vigilantes())

    elif cmd == "valuation":
        from tools.yardeni_frameworks import analyze_yardeni_valuation
        _pp(analyze_yardeni_valuation())

    elif cmd == "drawdown":
        from tools.yardeni_frameworks import classify_market_decline
        _pp(classify_market_decline())

    # ── Graham (auto-routed: ETF → ETF analysis, equity → Graham) ────
    elif cmd == "graham":
        if not args:
            print("Usage: run.py graham <TICKER>")
            sys.exit(1)
        ticker = args[0].upper()
        # ETFs don't have Graham numbers — serve full ETF analysis instead
        from tools.etf_analysis import is_etf, analyze_etf
        if is_etf(ticker):
            print(f"Note: '{ticker}' is an ETF — redirecting to ETF analysis (Graham N/A for funds).")
            _pp(analyze_etf(ticker))
        else:
            from tools.graham_analysis import graham_value_analysis
            _pp(graham_value_analysis(ticker))

    elif cmd == "etf":
        from tools.etf_analysis import analyze_etf
        if not args:
            print("Usage: run.py etf <TICKER>  (e.g. run.py etf EWY)")
            sys.exit(1)
        _pp(analyze_etf(args[0].upper()))

    elif cmd == "grahamscreen":
        from tools.graham_analysis import graham_screen
        _pp(graham_screen())

    elif cmd == "netnet":
        from tools.graham_analysis import graham_net_net_screen
        _pp(graham_net_net_screen())

    # ── Murphy TA ─────────────────────────────────────────────────────
    elif cmd == "ta":
        from tools.murphy_ta import murphy_technical_analysis
        if not args:
            print("Usage: run.py ta <ASSET>")
            sys.exit(1)
        _pp(murphy_technical_analysis(args[0]))

    elif cmd == "rsi":
        from tools.murphy_ta import calculate_rsi
        if not args:
            print("Usage: run.py rsi <ASSET> [period] [timeframe]")
            sys.exit(1)
        asset = args[0]
        period = int(args[1]) if len(args) > 1 else 14
        tf = args[2] if len(args) > 2 else "1D"
        _pp(calculate_rsi(asset, period, tf))

    elif cmd in ("sr", "support", "levels"):
        from tools.murphy_ta import find_support_resistance
        if not args:
            print("Usage: run.py sr <ASSET> [timeframe]")
            sys.exit(1)
        asset = args[0]
        tf = args[1] if len(args) > 1 else "1D"
        _pp(find_support_resistance(asset, tf))

    elif cmd == "breakout":
        from tools.murphy_ta import analyze_breakout
        if not args:
            print("Usage: run.py breakout <ASSET>")
            sys.exit(1)
        _pp(analyze_breakout(args[0]))

    elif cmd == "quickta":
        from tools.murphy_ta import quick_ta_snapshot
        if not args:
            print("Usage: run.py quickta <ASSET>")
            sys.exit(1)
        _pp(quick_ta_snapshot(args[0]))

    elif cmd == "synthesis":
        from tools.murphy_ta import fundamental_ta_synthesis
        if not args:
            print("Usage: run.py synthesis <TICKER>")
            sys.exit(1)
        _pp(fundamental_ta_synthesis(args[0].upper()))

    # ── Pro Trader ────────────────────────────────────────────────────
    elif cmd == "riskpremium":
        from tools.protrader_frameworks import protrader_risk_premium_analysis
        _pp(protrader_risk_premium_analysis())

    elif cmd == "crossasset":
        from tools.protrader_frameworks import protrader_cross_asset_momentum
        _pp(protrader_cross_asset_momentum())

    elif cmd == "pmregime":
        from tools.protrader_frameworks import protrader_precious_metals_regime
        _pp(protrader_precious_metals_regime())

    elif cmd == "usdregime":
        from tools.protrader_frameworks import protrader_usd_regime_analysis
        _pp(protrader_usd_regime_analysis())

    elif cmd == "sl":
        from tools.protrader_sl import protrader_stop_loss_framework
        if len(args) < 3:
            print("Usage: run.py sl <asset> <entry_price> <direction>")
            sys.exit(1)
        asset = args[0]
        price = float(args[1])
        direction = args[2]
        _pp(protrader_stop_loss_framework(asset, price, direction))

    # ── Macro Synthesis ───────────────────────────────────────────────
    elif cmd == "synthesize":
        from tools.macro_synthesis import synthesize_macro_view
        _pp(synthesize_macro_view())

    # ── Web Search ────────────────────────────────────────────────────
    elif cmd == "search":
        from tools.web_search import web_search
        if not args:
            print("Usage: run.py search <query>")
            sys.exit(1)
        _pp(web_search(" ".join(args)))

    elif cmd == "list":
        _list_tools()

    # ── News Streaming ─────────────────────────────────────────────
    elif cmd == "news":
        from tools.news_stream import get_news
        tickers = args[0].split(",") if args else None
        _pp(get_news(tickers=tickers, limit=20))

    elif cmd == "news_sentiment":
        from tools.news_stream import get_news_sentiment
        ticker = args[0] if args else "AAPL"
        _pp(get_news_sentiment(ticker))

    elif cmd == "news_search":
        from tools.news_stream import search_news
        query = " ".join(args) if args else "market"
        _pp(search_news(query, limit=20))

    elif cmd == "news_providers":
        from tools.news_stream import list_providers
        _pp(list_providers())

    elif cmd == "sentiment":
        from tools.news_sentiment_nlp import main as sentiment_main
        import sys as _sys
        _sys.argv = ["news_sentiment_nlp.py"] + args
        sentiment_main()

    elif cmd == "sentiment_live":
        from tools.news_sentiment_nlp import main as sentiment_main
        import sys as _sys
        _sys.argv = ["news_sentiment_nlp.py", "live"]
        sentiment_main()

    elif cmd == "regime":
        from tools.news_sentiment_nlp import analyze_headlines, get_regime_signal, enrich_with_market_context
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sample_path = os.path.join(_root, "data", "news", "sample_headlines.json")
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                headlines = json.load(f)
            analyzed = analyze_headlines(headlines)
            regime = get_regime_signal(analyzed, hours_back=168)
            regime = enrich_with_market_context(regime)
            _pp(regime)
        else:
            print("No sample data. Run 'sentiment_live' first.")

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'python tools/run.py list' for available tools")
        sys.exit(1)


if __name__ == "__main__":
    main()
