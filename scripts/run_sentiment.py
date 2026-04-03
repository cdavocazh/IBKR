#!/usr/bin/env python3
"""
Standalone ES Sentiment Pipeline

Fetches 1 week of IBKR news headlines from all providers, runs NLP sentiment
analysis, merges with newsletter context from /digest_ES, and saves results.

Usage:
    python scripts/run_sentiment.py          # Auto-detect IBKR port
    python scripts/run_sentiment.py --port 7496   # Specify port
    python scripts/run_sentiment.py --dry-run     # Skip IBKR, use cached headlines

Output:
    data/news/sentiment_analysis.json   — Full analysis + unified ES direction
    data/news/sentiment_timeseries.csv  — Appends one row per run
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def parse_headline(raw_headline: str) -> dict:
    """Parse IBKR headline metadata prefix."""
    metadata = {}
    headline = raw_headline
    if raw_headline.startswith("{"):
        if "}!" in raw_headline:
            meta_str, headline = raw_headline.split("}!", 1)
            meta_str = meta_str[1:]
            parts = meta_str.split(":")
            for i in range(0, len(parts) - 1, 2):
                key, val = parts[i], parts[i + 1]
                if key == "C":
                    try:
                        metadata["confidence"] = round(float(val), 2)
                    except ValueError:
                        pass
                elif key == "K":
                    metadata["keywords"] = val
        elif "}" in raw_headline:
            meta_str, headline = raw_headline.split("}", 1)
            meta_str = meta_str[1:]
            parts = meta_str.split(":")
            for i in range(0, len(parts) - 1, 2):
                key, val = parts[i], parts[i + 1]
                if key == "C":
                    try:
                        metadata["confidence"] = round(float(val), 2)
                    except ValueError:
                        pass
    return {"headline": headline.strip(), "metadata": metadata}


ALL_PROVIDERS = ["BRFG", "BRFUPDN", "DJ-N", "DJ-RT", "DJ-RTA", "DJ-RTE", "DJ-RTG"]
TICKERS = ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "SPY", "QQQ"]


def connect_ibkr(port=None, client_id=98):
    """Connect to IBKR, auto-detecting port if not specified."""
    from ib_async import IB

    ib = IB()
    ports = [port] if port else [7496, 7497, 4001, 4002]

    for p in ports:
        try:
            ib.connect("127.0.0.1", p, clientId=client_id, readonly=True)
            label = {7496: "TWS Live", 7497: "TWS Paper", 4001: "GW Live", 4002: "GW Paper"}.get(p, f"port {p}")
            print(f"[IBKR] Connected to {label} (port {p})")
            return ib
        except Exception:
            continue

    print(f"[IBKR] ERROR: Could not connect (tried ports {ports})")
    return None


def fetch_headlines(ib, days=7):
    """Fetch headlines from all providers for all tickers."""
    from ib_async import Stock

    ib.reqMarketDataType(4)
    ib.sleep(2)

    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.0")
    end = now.strftime("%Y-%m-%d %H:%M:%S.0")

    all_headlines = []
    seen = set()

    for ticker in TICKERS:
        try:
            c = Stock(ticker, "SMART", "USD")
            qual = ib.qualifyContracts(c)
            if not qual:
                continue
            con_id = qual[0].conId

            for provider in ALL_PROVIDERS:
                try:
                    headlines = ib.reqHistoricalNews(con_id, provider, start, end, 100)
                    if headlines:
                        for h in headlines:
                            if h.articleId in seen:
                                continue
                            seen.add(h.articleId)
                            parsed = parse_headline(h.headline)
                            all_headlines.append({
                                "headline": parsed["headline"],
                                "provider": h.providerCode,
                                "time": str(h.time),
                                "articleId": h.articleId,
                                "ticker": ticker,
                                "metadata": parsed["metadata"],
                            })
                except Exception:
                    pass
                time.sleep(0.3)
        except Exception:
            pass
        time.sleep(0.5)

    print(f"[IBKR] Fetched {len(all_headlines)} unique headlines ({len(seen)} deduplicated)")
    return all_headlines


def run_sentiment(headlines):
    """Run NLP sentiment analysis and return results."""
    from tools.news_sentiment_nlp import (
        analyze_headlines,
        get_regime_signal,
        enrich_with_market_context,
    )

    analyzed = analyze_headlines(headlines)

    regime_24h = get_regime_signal(analyzed, hours_back=24)
    regime_24h = enrich_with_market_context(regime_24h)

    regime_72h = get_regime_signal(analyzed, hours_back=72)
    regime_7d = get_regime_signal(analyzed, hours_back=168)

    unified_regime = regime_24h.get("unified_regime", regime_24h["regime"])
    unified_sentiment = regime_24h.get("unified_sentiment", regime_24h["net_sentiment"])
    newsletter_score = regime_24h.get("newsletter_sentiment_score", 0.0)

    result = {
        "timestamp": datetime.now().isoformat(),
        "headline_count": len(analyzed),
        "regime_24h": regime_24h,
        "regime_72h": regime_72h,
        "regime_7d": regime_7d,
        "es_trading_direction": {
            "signal": unified_regime,
            "signal_source": "unified (NLP 40% + newsletters 60%)",
            "confidence": regime_24h["confidence"],
            "unified_sentiment": unified_sentiment,
            "newsletter_sentiment": newsletter_score,
            "nlp_sentiment_24h": regime_24h["net_sentiment"],
            "net_sentiment_24h": regime_24h["net_sentiment"],
            "net_sentiment_72h": regime_72h["net_sentiment"],
            "net_sentiment_7d": regime_7d["net_sentiment"],
            "dominant_category": regime_24h["dominant_category"],
            "key_themes": regime_24h["key_themes"],
            "context_themes": regime_24h.get("context_themes", []),
            "context_trend": regime_24h.get("context_trend"),
            "context_levels": regime_24h.get("context_levels", {}),
            "context_positioning": regime_24h.get("context_positioning", {}),
            "context_key_risks": regime_24h.get("context_key_risks"),
            "context_vix_tier": regime_24h.get("context_vix_tier"),
            "cross_validated": regime_24h.get("cross_validated"),
            "actionable_insights": regime_24h["actionable_insights"],
        },
        "analyzed_headlines": [
            {k: v for k, v in h.items() if k != "raw"}
            for h in sorted(analyzed, key=lambda x: x.get("actionability", 0), reverse=True)[:100]
        ],
    }

    return result


def save_results(result):
    """Save to JSON and append to CSV timeseries."""
    # JSON
    json_path = PROJECT_ROOT / "data" / "news" / "sentiment_analysis.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # CSV
    csv_path = PROJECT_ROOT / "data" / "news" / "sentiment_timeseries.csv"
    direction = result["es_trading_direction"]
    r24 = result["regime_24h"]

    row = {
        "timestamp": result["timestamp"],
        "signal": direction["signal"],
        "confidence": direction["confidence"],
        "unified_sentiment": direction.get("unified_sentiment", 0),
        "newsletter_sentiment": direction.get("newsletter_sentiment", 0),
        "nlp_sentiment_24h": direction.get("nlp_sentiment_24h", 0),
        "net_sentiment_72h": direction.get("net_sentiment_72h", 0),
        "net_sentiment_7d": direction.get("net_sentiment_7d", 0),
        "headline_count": result["headline_count"],
        "bullish_count_24h": r24["bullish_count"],
        "bearish_count_24h": r24["bearish_count"],
        "neutral_count_24h": r24["neutral_count"],
        "upgrade_count_24h": r24["upgrade_count"],
        "downgrade_count_24h": r24["downgrade_count"],
        "dominant_category": direction["dominant_category"],
        "context_trend": direction.get("context_trend", ""),
        "cross_validated": direction.get("cross_validated", ""),
    }

    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"[Save] JSON: {json_path}")
    print(f"[Save] CSV:  {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="ES Sentiment Pipeline")
    parser.add_argument("--port", type=int, help="IBKR port (auto-detect if omitted)")
    parser.add_argument("--days", type=int, default=7, help="Headline lookback days (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Skip IBKR, use cached headlines")
    parser.add_argument("--client-id", type=int, default=98, help="IBKR client ID (default: 98)")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  ES Sentiment Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    headlines = []

    if args.dry_run:
        # Load from cached JSON
        cached = PROJECT_ROOT / "data" / "news" / "sentiment_analysis.json"
        if cached.exists():
            data = json.loads(cached.read_text())
            headlines = data.get("analyzed_headlines", [])
            print(f"[DryRun] Loaded {len(headlines)} cached headlines")
        else:
            print("[DryRun] No cached data found")
            return
    else:
        ib = connect_ibkr(port=args.port, client_id=args.client_id)
        if not ib:
            sys.exit(1)

        try:
            headlines = fetch_headlines(ib, days=args.days)
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

    if not headlines:
        print("[ERROR] No headlines to analyze")
        sys.exit(1)

    result = run_sentiment(headlines)
    save_results(result)

    # Print summary
    d = result["es_trading_direction"]
    print(f"\n{'='*60}")
    print(f"  ES TRADING DIRECTION: {d['signal']}")
    print(f"{'='*60}")
    print(f"  Unified sentiment:  {d.get('unified_sentiment', 0):+.3f}")
    print(f"  Newsletter:         {d.get('newsletter_sentiment', 0):+.3f}")
    print(f"  NLP (24h):          {d['net_sentiment_24h']:+.3f}")
    print(f"  NLP (7d):           {d['net_sentiment_7d']:+.3f}")
    print(f"  Confidence:         {d['confidence']:.0%}")
    print(f"  Headlines analyzed: {result['headline_count']}")
    if d.get("context_trend"):
        print(f"  Newsletter trend:   {d['context_trend']} (cross_validated={d.get('cross_validated')})")
    if d.get("context_levels"):
        levels = d["context_levels"]
        if "smashlevel_pivot" in levels:
            print(f"  Smashlevel pivot:   {levels['smashlevel_pivot']}")
        if "support" in levels:
            print(f"  Support:            {levels['support']}")
        if "resistance" in levels:
            print(f"  Resistance:         {levels['resistance']}")
    if d.get("context_vix_tier"):
        print(f"  VIX tier:           {d['context_vix_tier']}")
    print()


if __name__ == "__main__":
    main()
