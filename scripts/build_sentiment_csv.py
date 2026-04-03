#!/usr/bin/env python3
"""
Build daily sentiment CSV from WSJ email subjects and DJ-N headlines.

Inputs:
  data/news/wsj_subjects.json   — [{date, subject}] from Gmail (WSJ Markets AM/PM)
  data/news/sample_headlines.json — IBKR DJ-N headlines [{headline, time, ...}]

Output:
  data/news/daily_sentiment.csv — date, wsj_sentiment, djn_sentiment,
                                  composite_sentiment, headline_count, wsj_count

Scoring uses keyword-based NLP with intensity weighting (no external models).

Usage:
  python scripts/build_sentiment_csv.py
  python scripts/build_sentiment_csv.py --wsj data/news/wsj_subjects.json
  python scripts/build_sentiment_csv.py --djn data/news/sample_headlines.json
  python scripts/build_sentiment_csv.py --output data/news/daily_sentiment.csv
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent

# ─── Keyword Dictionaries with Intensity Weights ───────────────────────
# Values represent intensity: higher = stronger signal
# Range: 0.3 (mild) to 1.0 (extreme)

BULLISH_KEYWORDS = {
    # Extreme bullish (0.8-1.0)
    "surge": 0.9,
    "surges": 0.9,
    "surging": 0.9,
    "soar": 0.9,
    "soars": 0.9,
    "soaring": 0.9,
    "skyrocket": 1.0,
    "record high": 1.0,
    "all-time high": 1.0,
    "boom": 0.8,
    "booming": 0.8,
    "explode": 0.9,
    "moonshot": 1.0,
    "blowout": 0.8,
    # Strong bullish (0.6-0.8)
    "rally": 0.7,
    "rallies": 0.7,
    "rallying": 0.7,
    "bull market": 0.8,
    "bull run": 0.8,
    "breakout": 0.7,
    "rebound": 0.7,
    "rebounds": 0.7,
    "recovery": 0.7,
    "recover": 0.6,
    "optimism": 0.6,
    "optimistic": 0.6,
    "beat": 0.6,
    "beats": 0.6,
    "beating": 0.6,
    "top estimates": 0.7,
    "strong earnings": 0.7,
    "record earnings": 0.8,
    "blowout earnings": 0.8,
    "advance": 0.6,
    "advances": 0.6,
    "advancing": 0.6,
    "jump": 0.7,
    "jumps": 0.7,
    "jumping": 0.7,
    "pop": 0.6,
    "pops": 0.6,
    # Moderate bullish (0.3-0.6)
    "gain": 0.5,
    "gains": 0.5,
    "rise": 0.5,
    "rises": 0.5,
    "rising": 0.5,
    "climb": 0.5,
    "climbs": 0.5,
    "climbing": 0.5,
    "higher": 0.4,
    "up": 0.3,
    "uptick": 0.4,
    "edge up": 0.3,
    "edges up": 0.3,
    "tick up": 0.3,
    "positive": 0.4,
    "upbeat": 0.5,
    "lift": 0.4,
    "lifts": 0.4,
    "ease": 0.4,
    "easing": 0.4,
    "rate cut": 0.6,
    "rate cuts": 0.6,
    "dovish": 0.6,
    "stimulus": 0.6,
    "soft landing": 0.6,
    "goldilocks": 0.7,
    "resilient": 0.5,
    "strong jobs": 0.5,
}

BEARISH_KEYWORDS = {
    # Extreme bearish (0.8-1.0)
    "crash": 0.95,
    "crashes": 0.95,
    "crashing": 0.95,
    "plunge": 0.9,
    "plunges": 0.9,
    "plunging": 0.9,
    "plummet": 0.9,
    "plummets": 0.9,
    "plummeting": 0.9,
    "collapse": 0.9,
    "collapses": 0.9,
    "capitulation": 0.9,
    "rout": 0.85,
    "meltdown": 0.9,
    "bloodbath": 0.95,
    "panic": 0.8,
    "freefall": 0.95,
    "free fall": 0.95,
    # Strong bearish (0.6-0.8)
    "tumble": 0.7,
    "tumbles": 0.7,
    "tumbling": 0.7,
    "tank": 0.75,
    "tanks": 0.75,
    "tanking": 0.75,
    "sell-off": 0.7,
    "selloff": 0.7,
    "selling": 0.5,
    "bear market": 0.8,
    "recession": 0.8,
    "crisis": 0.7,
    "fear": 0.6,
    "fears": 0.6,
    "slump": 0.65,
    "slumps": 0.65,
    "slumping": 0.65,
    "sink": 0.65,
    "sinks": 0.65,
    "sinking": 0.65,
    "dive": 0.7,
    "dives": 0.7,
    "diving": 0.7,
    "reel": 0.6,
    "reels": 0.6,
    "reeling": 0.6,
    "war": 0.6,
    "tariff": 0.5,
    "tariffs": 0.5,
    "trade war": 0.7,
    "inflation": 0.5,
    "hawkish": 0.6,
    # Moderate bearish (0.3-0.6)
    "fall": 0.5,
    "falls": 0.5,
    "falling": 0.5,
    "drop": 0.5,
    "drops": 0.5,
    "dropping": 0.5,
    "decline": 0.5,
    "declines": 0.5,
    "declining": 0.5,
    "slide": 0.5,
    "slides": 0.5,
    "sliding": 0.5,
    "slip": 0.4,
    "slips": 0.4,
    "slipping": 0.4,
    "lower": 0.4,
    "down": 0.3,
    "dip": 0.35,
    "dips": 0.35,
    "retreat": 0.45,
    "retreats": 0.45,
    "retreating": 0.45,
    "pullback": 0.4,
    "pull back": 0.4,
    "edge down": 0.3,
    "edges down": 0.3,
    "tick down": 0.3,
    "weak": 0.4,
    "weaken": 0.4,
    "weakens": 0.4,
    "wobble": 0.4,
    "wobbles": 0.4,
    "jitters": 0.4,
    "uncertainty": 0.4,
    "volatile": 0.4,
    "volatility": 0.35,
    "miss": 0.5,
    "misses": 0.5,
    "disappoints": 0.5,
    "disappointing": 0.5,
    "warning": 0.5,
    "warns": 0.5,
    "concern": 0.4,
    "concerns": 0.4,
    "worried": 0.4,
    "worry": 0.4,
    "headwind": 0.4,
    "headwinds": 0.4,
    "fizzle": 0.5,
    "fizzles": 0.5,
    "stall": 0.4,
    "stalls": 0.4,
    "stalling": 0.4,
}

NEUTRAL_KEYWORDS = {
    "mixed": 0.0,
    "flat": 0.0,
    "steady": 0.0,
    "unchanged": 0.0,
    "sideways": 0.0,
    "little changed": 0.0,
    "hold steady": 0.0,
    "holds steady": 0.0,
    "muted": 0.0,
    "range-bound": 0.0,
    "consolidat": 0.0,
    "pause": 0.0,
    "pauses": 0.0,
    "wait": 0.0,
    "tread water": 0.0,
    "treads water": 0.0,
}

# Context modifiers: these words before bullish/bearish keywords flip or dampen the signal
NEGATION_WORDS = {"not", "no", "n't", "never", "neither", "nor", "barely", "hardly"}
DAMPENING_WORDS = {"could", "might", "may", "possibly", "potentially", "if", "whether"}


def score_headline(text: str) -> float:
    """Score a single headline/subject line.

    Returns a value in [-1.0, +1.0]:
      positive = bullish
      negative = bearish
      zero = neutral

    Uses keyword matching with intensity weights and context modifiers.
    """
    if not text:
        return 0.0

    text_lower = text.lower().strip()
    words = text_lower.split()

    # Check for neutral keywords first — if found, dampen all signals
    is_neutral = any(kw in text_lower for kw in NEUTRAL_KEYWORDS)

    bullish_total = 0.0
    bearish_total = 0.0
    match_count = 0

    # Check for negation in the headline
    has_negation = bool(NEGATION_WORDS & set(words))
    has_dampening = bool(DAMPENING_WORDS & set(words))

    # Score bullish keywords
    for keyword, intensity in BULLISH_KEYWORDS.items():
        # Use word boundary matching for short words, substring for phrases
        if len(keyword.split()) > 1:
            # Multi-word phrase: substring match
            if keyword in text_lower:
                bullish_total += intensity
                match_count += 1
        else:
            # Single word: check word boundaries to avoid false matches
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text_lower):
                bullish_total += intensity
                match_count += 1

    # Score bearish keywords
    for keyword, intensity in BEARISH_KEYWORDS.items():
        if len(keyword.split()) > 1:
            if keyword in text_lower:
                bearish_total += intensity
                match_count += 1
        else:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text_lower):
                bearish_total += intensity
                match_count += 1

    if match_count == 0:
        return 0.0

    # Raw score: bullish - bearish
    raw_score = bullish_total - bearish_total

    # Apply negation: flip the signal
    if has_negation:
        raw_score *= -0.5  # Partial flip (negation is noisy)

    # Apply dampening for speculative language
    if has_dampening:
        raw_score *= 0.6

    # Dampen if neutral keywords present
    if is_neutral:
        raw_score *= 0.3

    # Normalize to [-1, +1] — use tanh-like scaling
    # A single strong keyword (~0.9) should give ~0.6 score
    # Multiple aligned keywords should push toward +/-1.0
    normalized = np.tanh(raw_score / 1.5)

    return float(np.clip(normalized, -1.0, 1.0))


def load_wsj_subjects(path: Path) -> list[dict]:
    """Load WSJ email subjects from JSON.

    Expected format: [{"date": "2025-02-01", "subject": "Markets A.M.: Stocks Fall..."}]
    """
    if not path.exists():
        print(f"WARNING: WSJ subjects file not found: {path}", file=sys.stderr)
        return []

    with open(path) as f:
        data = json.load(f)

    # Validate format
    subjects = []
    for item in data:
        if isinstance(item, dict) and "date" in item and "subject" in item:
            subjects.append(item)
        elif isinstance(item, dict) and "date" in item and "headline" in item:
            # Allow alternate key name
            subjects.append({"date": item["date"], "subject": item["headline"]})

    print(f"Loaded {len(subjects)} WSJ subjects from {path}", file=sys.stderr)
    return subjects


def load_djn_headlines(path: Path) -> list[dict]:
    """Load DJ-N / IBKR headlines from sample_headlines.json.

    Expected format: [{"headline": "...", "time": "2026-03-05 13:07:36", ...}]
    """
    if not path.exists():
        print(f"WARNING: DJ-N headlines file not found: {path}", file=sys.stderr)
        return []

    with open(path) as f:
        data = json.load(f)

    headlines = []
    for item in data:
        if isinstance(item, dict) and "headline" in item and "time" in item:
            headlines.append(item)

    print(f"Loaded {len(headlines)} DJ-N headlines from {path}", file=sys.stderr)
    return headlines


def build_daily_sentiment(
    wsj_subjects: list[dict],
    djn_headlines: list[dict],
    wsj_weight: float = 0.6,
    djn_weight: float = 0.4,
) -> pd.DataFrame:
    """Build daily sentiment scores from WSJ subjects and DJ-N headlines.

    Args:
        wsj_subjects: List of {date, subject} dicts
        djn_headlines: List of {headline, time, ...} dicts
        wsj_weight: Weight for WSJ sentiment in composite (default 0.6)
        djn_weight: Weight for DJ-N sentiment in composite (default 0.4)

    Returns:
        DataFrame with columns: date, wsj_sentiment, djn_sentiment,
                                composite_sentiment, headline_count, wsj_count
    """
    # Aggregate scores by date
    wsj_by_date = defaultdict(list)
    djn_by_date = defaultdict(list)

    # Process WSJ subjects
    for item in wsj_subjects:
        try:
            date_str = item["date"]
            # Handle various date formats
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
            else:
                date_key = date_str[:10]  # Take YYYY-MM-DD

            subject = item["subject"]
            score = score_headline(subject)
            wsj_by_date[date_key].append(score)
        except (ValueError, KeyError) as e:
            continue

    # Process DJ-N headlines
    for item in djn_headlines:
        try:
            time_str = item["time"]
            if "T" in time_str:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            date_key = dt.strftime("%Y-%m-%d")

            headline = item["headline"]
            score = score_headline(headline)
            djn_by_date[date_key].append(score)
        except (ValueError, KeyError):
            continue

    # Collect all dates
    all_dates = sorted(set(list(wsj_by_date.keys()) + list(djn_by_date.keys())))

    if not all_dates:
        print("WARNING: No dates found in input data", file=sys.stderr)
        return pd.DataFrame(columns=[
            "date", "wsj_sentiment", "djn_sentiment",
            "composite_sentiment", "headline_count", "wsj_count"
        ])

    rows = []
    for date_key in all_dates:
        wsj_scores = wsj_by_date.get(date_key, [])
        djn_scores = djn_by_date.get(date_key, [])

        # Compute daily averages
        wsj_sent = float(np.mean(wsj_scores)) if wsj_scores else 0.0
        djn_sent = float(np.mean(djn_scores)) if djn_scores else 0.0

        wsj_count = len(wsj_scores)
        djn_count = len(djn_scores)
        total_count = wsj_count + djn_count

        # Composite: weighted average, adjusting weights if one source is missing
        if wsj_count > 0 and djn_count > 0:
            composite = wsj_weight * wsj_sent + djn_weight * djn_sent
        elif wsj_count > 0:
            composite = wsj_sent
        elif djn_count > 0:
            composite = djn_sent
        else:
            composite = 0.0

        rows.append({
            "date": date_key,
            "wsj_sentiment": round(wsj_sent, 4),
            "djn_sentiment": round(djn_sent, 4),
            "composite_sentiment": round(composite, 4),
            "headline_count": total_count,
            "wsj_count": wsj_count,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Build daily sentiment CSV from WSJ subjects + DJ-N headlines"
    )
    parser.add_argument(
        "--wsj", type=str,
        default=str(PROJECT_ROOT / "data" / "news" / "wsj_subjects.json"),
        help="Path to WSJ subjects JSON"
    )
    parser.add_argument(
        "--djn", type=str,
        default=str(PROJECT_ROOT / "data" / "news" / "sample_headlines.json"),
        help="Path to DJ-N headlines JSON"
    )
    parser.add_argument(
        "--output", type=str,
        default=str(PROJECT_ROOT / "data" / "news" / "daily_sentiment.csv"),
        help="Output CSV path"
    )
    parser.add_argument(
        "--wsj-weight", type=float, default=0.6,
        help="Weight for WSJ sentiment in composite (default: 0.6)"
    )
    parser.add_argument(
        "--djn-weight", type=float, default=0.4,
        help="Weight for DJ-N sentiment in composite (default: 0.4)"
    )
    args = parser.parse_args()

    # Load data
    wsj_subjects = load_wsj_subjects(Path(args.wsj))
    djn_headlines = load_djn_headlines(Path(args.djn))

    if not wsj_subjects and not djn_headlines:
        print("ERROR: No input data found. Provide at least one of:", file=sys.stderr)
        print(f"  WSJ subjects: {args.wsj}", file=sys.stderr)
        print(f"  DJ-N headlines: {args.djn}", file=sys.stderr)
        sys.exit(1)

    # Build daily sentiment
    df = build_daily_sentiment(
        wsj_subjects, djn_headlines,
        wsj_weight=args.wsj_weight,
        djn_weight=args.djn_weight,
    )

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    # Summary stats
    print(f"\nDaily Sentiment CSV written to: {output_path}", file=sys.stderr)
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}", file=sys.stderr)
    print(f"  Total days: {len(df)}", file=sys.stderr)
    print(f"  Days with WSJ: {(df['wsj_count'] > 0).sum()}", file=sys.stderr)
    print(f"  Days with DJN: {(df['headline_count'] - df['wsj_count'] > 0).sum()}", file=sys.stderr)
    print(f"  Mean composite: {df['composite_sentiment'].mean():.4f}", file=sys.stderr)
    print(f"  Std composite:  {df['composite_sentiment'].std():.4f}", file=sys.stderr)
    print(f"  Min composite:  {df['composite_sentiment'].min():.4f}", file=sys.stderr)
    print(f"  Max composite:  {df['composite_sentiment'].max():.4f}", file=sys.stderr)

    # Print score distribution
    bullish_days = (df['composite_sentiment'] > 0.1).sum()
    bearish_days = (df['composite_sentiment'] < -0.1).sum()
    neutral_days = len(df) - bullish_days - bearish_days
    print(f"\n  Signal distribution:", file=sys.stderr)
    print(f"    Bullish days (>0.1):  {bullish_days} ({bullish_days/len(df)*100:.1f}%)", file=sys.stderr)
    print(f"    Neutral days:         {neutral_days} ({neutral_days/len(df)*100:.1f}%)", file=sys.stderr)
    print(f"    Bearish days (<-0.1): {bearish_days} ({bearish_days/len(df)*100:.1f}%)", file=sys.stderr)


if __name__ == "__main__":
    main()
