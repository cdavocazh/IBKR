#!/usr/bin/env python3
"""
IB News Streaming Harness (ib_async)

Real-time financial news streaming via IBKR Gateway API.
Supports contract-specific headlines, broadtape streaming,
historical headline fetch, and full article retrieval.

Usage:
    # List available news providers on your IB account
    python scripts/ib_news_stream.py providers

    # Fetch recent historical headlines for a ticker
    python scripts/ib_news_stream.py headlines AAPL
    python scripts/ib_news_stream.py headlines ES --count 50

    # Fetch full article body
    python scripts/ib_news_stream.py article BRFG BRFG\$04fb9da2

    # Stream real-time headlines for specific tickers
    python scripts/ib_news_stream.py stream AAPL,NVDA,ES
    python scripts/ib_news_stream.py stream AAPL --duration 300

    # Stream broadtape (all headlines from a provider)
    python scripts/ib_news_stream.py broadtape
    python scripts/ib_news_stream.py broadtape --providers BRFG,BRFUPDN --duration 600

    # IB system bulletins
    python scripts/ib_news_stream.py bulletins

    # Full verification (run all checks)
    python scripts/ib_news_stream.py verify
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Use ib_async (actively maintained fork of ib_insync)
try:
    from ib_async import IB, Stock, Future, Contract
    IB_LIB = "ib_async"
except ImportError:
    from ib_insync import IB, Stock, Future, Contract
    IB_LIB = "ib_insync"


# ─── Connection ──────────────────────────────────────────────

def connect(client_id=10):
    """Connect to IB Gateway for news streaming."""
    from dotenv import load_dotenv
    load_dotenv()

    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT", "4001"))
    cid = int(os.environ.get("IB_NEWS_CLIENT_ID", str(client_id)))

    ib = IB()
    ib.connect(host, port, clientId=cid, readonly=True)
    print(f"Connected via {IB_LIB} to {host}:{port} (clientId={cid})")
    return ib


# ─── Headline Parsing ────────────────────────────────────────

def parse_headline(raw_headline: str) -> dict:
    """Parse IB headline format into structured data.

    IB headlines often have a metadata prefix like:
    {A:conId:L:lang:K:keywords:C:confidence}!Actual headline text
    """
    metadata = {}
    headline = raw_headline

    if raw_headline.startswith("{") and "}!" in raw_headline:
        meta_str, headline = raw_headline.split("}!", 1)
        meta_str = meta_str[1:]  # Remove leading {
        parts = meta_str.split(":")
        for i in range(0, len(parts) - 1, 2):
            key = parts[i]
            val = parts[i + 1] if i + 1 < len(parts) else ""
            if key == "A":
                metadata["conId"] = val
            elif key == "L":
                metadata["language"] = val
            elif key == "K":
                metadata["keywords"] = val
            elif key == "C":
                try:
                    metadata["confidence"] = float(val)
                except ValueError:
                    metadata["confidence"] = val

    return {
        "headline": headline.strip(),
        "metadata": metadata,
        "raw": raw_headline,
    }


# ─── Commands ────────────────────────────────────────────────

def cmd_providers(ib):
    """List available news providers on this IB account."""
    providers = ib.reqNewsProviders()
    print(f"\n{'='*60}")
    print(f"  Available News Providers ({len(providers)})")
    print(f"{'='*60}")
    for p in providers:
        print(f"  {p.code:<12} {p.name}")
    print(f"{'='*60}")
    return providers


def _qualify_ticker(ib, ticker):
    """Qualify a ticker as stock or future (with front-month for futures)."""
    # Try as stock first
    contract = Stock(ticker, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if qualified:
        return qualified[0]

    # Try as future with front month
    from datetime import datetime
    now = datetime.now()
    expiry_months = [3, 6, 9, 12]
    for m in expiry_months:
        if now.month <= m:
            front = f"{now.year}{m:02d}"
            break
    else:
        front = f"{now.year + 1}03"

    contract = Future(ticker, lastTradeDateOrContractMonth=front, exchange="CME", currency="USD")
    qualified = ib.qualifyContracts(contract)
    if qualified:
        return qualified[0]

    return None


def cmd_headlines(ib, ticker, count=20, provider_codes="BRFG+BRFUPDN+DJNL"):
    """Fetch historical headlines for a ticker."""
    contract = _qualify_ticker(ib, ticker)
    if not contract:
        print(f"Could not qualify contract for {ticker}")
        return []

    print(f"Fetching headlines for {contract.localSymbol} (conId={contract.conId})...")
    print(f"Providers: {provider_codes}")

    headlines = ib.reqHistoricalNews(
        conId=contract.conId,
        providerCodes=provider_codes,
        startDateTime="",
        endDateTime="",
        totalResults=min(count, 300),
    )

    print(f"\n{'='*80}")
    print(f"  Headlines for {ticker} ({len(headlines)} results)")
    print(f"{'='*80}")
    for h in headlines:
        parsed = parse_headline(h.headline)
        conf = parsed["metadata"].get("confidence", "")
        conf_str = f" [conf={conf:.2f}]" if isinstance(conf, float) else ""
        print(f"  [{h.providerCode}] {h.time}")
        print(f"    {parsed['headline']}{conf_str}")
        print(f"    articleId: {h.articleId}")
        print()

    return headlines


def cmd_article(ib, provider_code, article_id):
    """Fetch full article body."""
    print(f"Fetching article: {provider_code} / {article_id}...")
    article = ib.reqNewsArticle(provider_code, article_id)

    if article:
        print(f"\n{'='*80}")
        print(f"  Article: {provider_code} / {article_id}")
        print(f"{'='*80}")
        # article.articleType is 0 for text, 1 for HTML
        content = article.articleText if hasattr(article, "articleText") else str(article)
        print(content[:2000])
        if len(content) > 2000:
            print(f"\n  ... ({len(content)} chars total, truncated)")
    else:
        print("No article returned")

    return article


def cmd_stream(ib, tickers, provider_codes="BRFG+BRFUPDN+DJNL", duration=120):
    """Stream real-time headlines for specific tickers."""
    contracts = []
    for ticker in tickers:
        c = _qualify_ticker(ib, ticker)
        if c:
            contracts.append(c)
            print(f"  Subscribed: {c.localSymbol}")
        else:
            print(f"  SKIP: Could not qualify {ticker}")

    if not contracts:
        print("No contracts qualified")
        return

    headline_count = [0]
    headlines_log = []

    def on_news_tick(ticker_obj):
        """Callback for incoming news ticks."""
        # ib_async/ib_insync delivers news via the Ticker object's ticks
        pass

    def on_pending_tickers(tickers_list):
        """Process pending ticker updates that may contain news."""
        for t in tickers_list:
            # Check for news ticks in the ticker
            if hasattr(t, "ticks"):
                for tick in t.ticks:
                    if hasattr(tick, "tickType") and tick.tickType == 48:  # NEWS_TICK
                        headline_count[0] += 1
                        now = datetime.now().strftime("%H:%M:%S")
                        print(f"  [{now}] NEWS: {tick}")

    # Subscribe to market data with news tick type
    for contract in contracts:
        generic_ticks = f"mdoff,292:{provider_codes}"
        ib.reqMktData(contract, genericTickList=generic_ticks)

    # Also attach to the newsTicks event if available
    def on_new_news_tick(news_tick):
        headline_count[0] += 1
        parsed = parse_headline(news_tick.headline if hasattr(news_tick, "headline") else str(news_tick))
        now = datetime.now().strftime("%H:%M:%S")
        provider = news_tick.providerCode if hasattr(news_tick, "providerCode") else "?"
        print(f"  [{now}] [{provider}] {parsed['headline']}")
        headlines_log.append({
            "time": now,
            "provider": provider,
            "headline": parsed["headline"],
            "articleId": news_tick.articleId if hasattr(news_tick, "articleId") else "",
        })

    # Try different event attachment methods for ib_async vs ib_insync
    if hasattr(ib, "newsTicks"):
        ib.newsTicks.updateEvent += on_new_news_tick
    if hasattr(ib, "pendingTickersEvent"):
        ib.pendingTickersEvent += on_pending_tickers

    tickers_str = ", ".join(t.localSymbol for t in contracts)
    print(f"\n{'='*60}")
    print(f"  Streaming news for: {tickers_str}")
    print(f"  Providers: {provider_codes}")
    print(f"  Duration: {duration}s | Press Ctrl+C to stop")
    print(f"{'='*60}")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    start = time.time()
    while running and (time.time() - start) < duration:
        ib.sleep(0.5)

    # Cleanup
    for contract in contracts:
        ib.cancelMktData(contract)

    print(f"\n  Stream ended. {headline_count[0]} headlines received in {time.time()-start:.0f}s")
    return headlines_log


def cmd_broadtape(ib, provider_codes=None, duration=120):
    """Stream broadtape — all headlines from specified providers."""
    if provider_codes is None:
        provider_codes = ["BRFG", "BRFUPDN"]

    subscribed = []
    for code in provider_codes:
        news_contract = Contract()
        news_contract.symbol = f"{code}:{code}_ALL"
        news_contract.secType = "NEWS"
        news_contract.exchange = code

        try:
            ib.reqMktData(news_contract, genericTickList="mdoff,292")
            subscribed.append(code)
            print(f"  Subscribed to broadtape: {code}")
        except Exception as e:
            print(f"  Failed to subscribe to {code}: {e}")

    if not subscribed:
        print("No broadtape subscriptions active")
        return

    headline_count = [0]

    def on_new_news_tick(news_tick):
        headline_count[0] += 1
        parsed = parse_headline(news_tick.headline if hasattr(news_tick, "headline") else str(news_tick))
        now = datetime.now().strftime("%H:%M:%S")
        provider = news_tick.providerCode if hasattr(news_tick, "providerCode") else "?"
        print(f"  [{now}] [{provider}] {parsed['headline']}")

    if hasattr(ib, "newsTicks"):
        ib.newsTicks.updateEvent += on_new_news_tick

    print(f"\n{'='*60}")
    print(f"  Broadtape streaming: {', '.join(subscribed)}")
    print(f"  Duration: {duration}s | Press Ctrl+C to stop")
    print(f"{'='*60}")

    running = True
    signal.signal(signal.SIGINT, lambda s, f: setattr(sys.modules[__name__], '_stop', True))

    start = time.time()
    while (time.time() - start) < duration:
        ib.sleep(0.5)
        if getattr(sys.modules[__name__], '_stop', False):
            break

    print(f"\n  Broadtape ended. {headline_count[0]} headlines received in {time.time()-start:.0f}s")


def cmd_bulletins(ib):
    """Fetch IB system bulletins."""
    ib.reqNewsBulletins(allMessages=True)
    ib.sleep(5)
    bulletins = ib.newsBulletins()

    print(f"\n{'='*60}")
    print(f"  IB Bulletins ({len(bulletins)})")
    print(f"{'='*60}")
    for b in bulletins:
        print(f"  [{b.msgType}] {b.message[:200]}")
    return bulletins


def cmd_verify(ib):
    """Run full verification of news API capabilities."""
    print(f"\n{'='*60}")
    print(f"  IB NEWS API VERIFICATION ({IB_LIB} v{getattr(sys.modules.get(IB_LIB), '__version__', '?')})")
    print(f"{'='*60}")

    # Step 1: Connection
    print(f"\n[1/5] Connection: {'OK' if ib.isConnected() else 'FAILED'}")

    # Step 2: List providers
    print("\n[2/5] News Providers:")
    providers = ib.reqNewsProviders()
    for p in providers:
        print(f"  {p.code:<12} {p.name}")
    print(f"  Total: {len(providers)} providers")

    # Step 3: Historical headlines
    print("\n[3/5] Historical Headlines (AAPL, last 10):")
    aapl = Stock("AAPL", "SMART", "USD")
    qualified = ib.qualifyContracts(aapl)
    if qualified:
        aapl = qualified[0]
        headlines = ib.reqHistoricalNews(aapl.conId, "BRFG+BRFUPDN+DJNL", "", "", 10)
        for h in headlines[:5]:
            parsed = parse_headline(h.headline)
            print(f"  [{h.providerCode}] {h.time}: {parsed['headline'][:70]}")
        print(f"  ... {len(headlines)} headlines total")
    else:
        print("  FAILED: Could not qualify AAPL")

    # Step 4: Article body
    print("\n[4/5] Article Body Fetch:")
    if qualified and headlines:
        h = headlines[0]
        article = ib.reqNewsArticle(h.providerCode, h.articleId)
        if article:
            content = article.articleText if hasattr(article, "articleText") else str(article)
            print(f"  OK: {len(content)} chars from {h.providerCode}/{h.articleId}")
        else:
            print(f"  No article body returned for {h.articleId}")
    else:
        print("  SKIPPED (no headlines to test)")

    # Step 5: ES futures headlines
    print("\n[5/5] ES Futures Headlines:")
    es = _qualify_ticker(ib, "ES")
    if es:
        es_headlines = ib.reqHistoricalNews(es.conId, "BRFG+BRFUPDN+DJNL", "", "", 5)
        for h in es_headlines:
            parsed = parse_headline(h.headline)
            print(f"  [{h.providerCode}] {h.time}: {parsed['headline'][:70]}")
        print(f"  ... {len(es_headlines)} headlines for ES")
    else:
        print("  FAILED: Could not qualify ES contract")

    print(f"\n{'='*60}")
    print(f"  VERIFICATION COMPLETE")
    print(f"{'='*60}")


# ─── Main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="IB News Streaming Harness (ib_async)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s providers                        List news providers
  %(prog)s headlines AAPL                   Recent AAPL headlines
  %(prog)s headlines ES --count 50          50 ES futures headlines
  %(prog)s stream AAPL,NVDA --duration 300  Stream for 5 minutes
  %(prog)s broadtape --duration 600         All headlines for 10 min
  %(prog)s verify                           Full API verification
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("providers", help="List available news providers")
    sub.add_parser("verify", help="Run full verification checks")
    sub.add_parser("bulletins", help="Fetch IB system bulletins")

    p_head = sub.add_parser("headlines", help="Fetch historical headlines")
    p_head.add_argument("ticker", help="Ticker symbol (e.g., AAPL, ES)")
    p_head.add_argument("--count", type=int, default=20, help="Number of headlines")
    p_head.add_argument("--providers", default="BRFG+BRFUPDN+DJNL", help="Provider codes")

    p_art = sub.add_parser("article", help="Fetch full article body")
    p_art.add_argument("provider_code", help="Provider code (e.g., BRFG)")
    p_art.add_argument("article_id", help="Article ID")

    p_stream = sub.add_parser("stream", help="Stream real-time headlines for tickers")
    p_stream.add_argument("tickers", help="Comma-separated tickers (e.g., AAPL,NVDA)")
    p_stream.add_argument("--duration", type=int, default=120, help="Duration in seconds")
    p_stream.add_argument("--providers", default="BRFG+BRFUPDN+DJNL", help="Provider codes")

    p_broad = sub.add_parser("broadtape", help="Stream all headlines from providers")
    p_broad.add_argument("--providers", default="BRFG,BRFUPDN", help="Comma-separated provider codes")
    p_broad.add_argument("--duration", type=int, default=120, help="Duration in seconds")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    ib = connect()

    try:
        if args.command == "providers":
            cmd_providers(ib)
        elif args.command == "verify":
            cmd_verify(ib)
        elif args.command == "bulletins":
            cmd_bulletins(ib)
        elif args.command == "headlines":
            cmd_headlines(ib, args.ticker, args.count, args.providers)
        elif args.command == "article":
            cmd_article(ib, args.provider_code, args.article_id)
        elif args.command == "stream":
            tickers = [t.strip() for t in args.tickers.split(",")]
            cmd_stream(ib, tickers, args.providers, args.duration)
        elif args.command == "broadtape":
            codes = [c.strip() for c in args.providers.split(",")]
            cmd_broadtape(ib, codes, args.duration)
    finally:
        ib.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
