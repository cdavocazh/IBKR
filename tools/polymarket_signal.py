#!/usr/bin/env python3
"""
Polymarket Prediction-Market Signals for ES Trading (Phase 4 partial)

Reads Polymarket data extracted by ../market-tracker (independent repo) and
extracts probabilities relevant to ES futures direction:

  - Fed rate cut probability at next FOMC meeting → liquidity / risk-on bias
  - Recession probability (within 6/12 mo) → risk-off bias
  - CPI above-consensus probability → inflation surprise risk
  - Geopolitics escalation probabilities (Iran, Ukraine) → vol spike risk

The market-tracker repo's launchd job (`com.macro2.polymarket-extract.plist`)
refreshes data every 5 minutes into:
    ~/Github/market-tracker/data_cache/all_indicators.json
    (key: '86_polymarket')

This module is a READ-ONLY consumer of that cache. We never call Polymarket
API directly — that's market-tracker's job.

Usage:
    from tools.polymarket_signal import PolymarketSignals
    pm = PolymarketSignals()
    sigs = pm.snapshot()
    print(sigs)  # {'fed_cut_prob_next': 0.72, 'recession_prob_12m': 0.31, ...}

Or as CLI:
    python tools/polymarket_signal.py
    python tools/polymarket_signal.py --append-csv
    python tools/polymarket_signal.py --history
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = Path.home() / "Github" / "market-tracker" / "data_cache" / "all_indicators.json"
DEFAULT_CACHE_VPS = Path("/root/market-tracker/data_cache/all_indicators.json")
OUTPUT_CSV = PROJECT_ROOT / "data" / "es" / "polymarket_signals.csv"


# Pattern → label mapping. Each entry = (regex on event/market title, our normalized label, polarity for ES)
# Polarity: 'risk_on' (high prob → bullish ES), 'risk_off' (high prob → bearish ES)
TOPIC_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Fed rate path — cut probability is risk-on
    (re.compile(r"\bfed.*\b(rate cut|cut rates?)\b", re.I), "fed_cut_prob_next", "risk_on"),
    (re.compile(r"\b(fomc|fed).*\b(?:hold|no change|skip)\b", re.I), "fed_hold_prob_next", "neutral"),
    (re.compile(r"\b(fed|fomc).*\b(rate hike|hike rates?|raise rates?)\b", re.I), "fed_hike_prob_next", "risk_off"),
    # Recession risk
    (re.compile(r"\brecession\b.*(2026|next year|12 mo|6 mo)", re.I), "recession_prob_12m", "risk_off"),
    (re.compile(r"\brecession\b", re.I), "recession_prob", "risk_off"),
    # Inflation surprises
    (re.compile(r"\bcpi\b.*(above|hot|exceed|higher)", re.I), "cpi_above_consensus_prob", "risk_off"),
    (re.compile(r"\bcore (cpi|pce)\b.*(above|hot|exceed)", re.I), "core_inflation_above_prob", "risk_off"),
    # Geopolitics — escalations are risk-off
    (re.compile(r"\biran\b.*(strike|attack|war|escalat)", re.I), "iran_escalation_prob", "risk_off"),
    (re.compile(r"\bukraine\b.*(escalat|nuclear|invasion)", re.I), "ukraine_escalation_prob", "risk_off"),
    (re.compile(r"\b(taiwan|china).*invasion\b", re.I), "taiwan_invasion_prob", "risk_off"),
    # Tariff / trade policy
    (re.compile(r"\btariff\b.*(impose|raise|increase)", re.I), "tariff_increase_prob", "risk_off"),
    # Bitcoin (sometimes correlates with risk appetite)
    (re.compile(r"\bbitcoin\b.*(\$?100k|\$?150k|\$?200k|all.?time)", re.I), "bitcoin_milestone_prob", "risk_on"),
    # Politics / fiscal expansion — addresses user's explicit ES-driver list.
    # Stimulus / tax-cut / spending-bill probability is risk-on (more liquidity).
    # Government shutdown / debt-ceiling crisis is risk-off.
    (re.compile(r"\b(tax cut|stimulus|spending bill|infrastructure bill|fiscal expansion)\b", re.I),
     "fiscal_expansion_prob", "risk_on"),
    (re.compile(r"\b(government shutdown|debt ceiling|default)\b", re.I),
     "shutdown_default_prob", "risk_off"),
    (re.compile(r"\b(impeachment|election.*(?:contested|disputed))\b", re.I),
     "political_crisis_prob", "risk_off"),
]


class PolymarketSignals:
    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path or (DEFAULT_CACHE if DEFAULT_CACHE.exists() else DEFAULT_CACHE_VPS)

    def _load_polymarket_data(self) -> dict:
        """Load the 86_polymarket section of all_indicators.json."""
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open() as f:
                cache = json.load(f)
            data = cache.get("data", {})
            return data.get("86_polymarket", {}) or {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _flatten_events(self, pm_data: dict) -> list[dict]:
        """Walk the polymarket data structure and yield each event as a flat dict
        with at least: title, yes_price (probability), tag.
        """
        events = []
        # The polymarket extractor produces nested dicts keyed by tag/category.
        # Common keys: 'fed_rates', 'finance', 'geopolitics', 'inflation', 'crypto', 'tech',
        # 'part5_trending' (which is {tag_label: [events]})
        def walk(node: Any, tag_hint: str = ""):
            if isinstance(node, dict):
                # Direct event format
                if "outcomes" in node and isinstance(node.get("outcomes"), list):
                    for o in node["outcomes"]:
                        events.append({
                            "title": str(o.get("label", "") or node.get("title", "")),
                            "yes_price": float(o.get("yes_price", 0.0) or 0.0),
                            "tag": tag_hint or node.get("tag", ""),
                            "volume": node.get("volume", 0),
                        })
                elif "title" in node and "yes_price" in node:
                    events.append({
                        "title": str(node.get("title", "")),
                        "yes_price": float(node.get("yes_price", 0.0) or 0.0),
                        "tag": tag_hint,
                        "volume": node.get("volume", 0),
                    })
                else:
                    for k, v in node.items():
                        walk(v, tag_hint=tag_hint or k)
            elif isinstance(node, list):
                for item in node:
                    walk(item, tag_hint=tag_hint)
        walk(pm_data)
        return events

    def snapshot(self) -> dict:
        """Return a snapshot of all derived signals as a flat dict."""
        pm_data = self._load_polymarket_data()
        events = self._flatten_events(pm_data)

        result = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "cache_age_min": self._cache_age_minutes(),
            "event_count": len(events),
        }

        # For each topic pattern, take the MAX probability across matching events
        # (i.e. "is there strong consensus on this anywhere in the market?")
        for pattern, label, polarity in TOPIC_PATTERNS:
            matches = [e for e in events if pattern.search(e["title"])]
            if matches:
                # Volume-weighted average if volume present, else mean
                total_vol = sum(max(1.0, e.get("volume", 0) or 0) for e in matches)
                if total_vol > 0:
                    weighted = sum(e["yes_price"] * max(1.0, e.get("volume", 0) or 0) for e in matches) / total_vol
                else:
                    weighted = sum(e["yes_price"] for e in matches) / len(matches)
                result[label] = round(weighted, 4)
                result[f"{label}_n"] = len(matches)
                result[f"{label}_polarity"] = polarity
            else:
                result[label] = None
                result[f"{label}_n"] = 0
                result[f"{label}_polarity"] = polarity

        # Composite ES signal: risk-on minus risk-off
        risk_on = sum(v for k, v in result.items()
                      if isinstance(v, (int, float)) and result.get(f"{k}_polarity") == "risk_on")
        risk_off = sum(v for k, v in result.items()
                       if isinstance(v, (int, float)) and result.get(f"{k}_polarity") == "risk_off")
        n_risk_on = sum(1 for k in result if result.get(f"{k}_polarity") == "risk_on" and result.get(k) is not None)
        n_risk_off = sum(1 for k in result if result.get(f"{k}_polarity") == "risk_off" and result.get(k) is not None)
        avg_on = risk_on / n_risk_on if n_risk_on else 0.0
        avg_off = risk_off / n_risk_off if n_risk_off else 0.0
        result["composite_es_signal"] = round(avg_on - avg_off, 4)
        return result

    def _cache_age_minutes(self) -> Optional[float]:
        try:
            with self.cache_path.open() as f:
                cache = json.load(f)
            ts_str = cache.get("timestamp")
            if not ts_str:
                return None
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return round((datetime.now(timezone.utc) - ts).total_seconds() / 60, 1)
        except Exception:
            return None


# ─── CSV append (for time-series persistence) ───────────────

def append_csv(snapshot: dict, csv_path: Path = OUTPUT_CSV):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    columns = ["ts_utc", "cache_age_min", "event_count", "composite_es_signal"]
    for _, label, _ in TOPIC_PATTERNS:
        columns.append(label)
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerow(snapshot)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Polymarket signal reader for ES trading")
    parser.add_argument("--cache", default=None, help="Path to all_indicators.json")
    parser.add_argument("--append-csv", action="store_true", help="Append snapshot to data/es/polymarket_signals.csv")
    parser.add_argument("--history", action="store_true", help="Show recent CSV history")
    parser.add_argument("--n", type=int, default=10, help="Number of history rows")
    args = parser.parse_args()

    pm = PolymarketSignals(cache_path=Path(args.cache) if args.cache else None)
    print(f"Cache path: {pm.cache_path}")
    print(f"Cache exists: {pm.cache_path.exists()}")

    if args.history:
        if not OUTPUT_CSV.exists():
            print(f"No history yet at {OUTPUT_CSV}")
            return
        with OUTPUT_CSV.open() as f:
            lines = f.readlines()
        print("".join(lines[:1] + lines[-args.n:]))
        return

    snap = pm.snapshot()
    print(json.dumps(snap, indent=2))

    if args.append_csv:
        append_csv(snap)
        print(f"\n  → appended to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
