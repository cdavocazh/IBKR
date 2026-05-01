#!/usr/bin/env python3
"""
Hybrid Sentiment Scorer (Phase 3)

Combines two scoring layers per headline:
  1. Regex-based analyst-action detection (high precision: upgrades/downgrades, etc.)
     — already in `tools/news_sentiment_nlp.py::classify_analyst_action`.
  2. FinBERT/DistilRoBERTa transformer scorer (better recall on macro nuance)
     — in `tools/sentiment_finbert.py::FinBERTScorer`.

Decision policy:
  - If regex matches a clear analyst action with confidence >= REGEX_CONFIDENCE_FLOOR,
    USE REGEX (fast + precise).
  - Otherwise, fall back to FinBERT for macro/general sentiment.
  - If FinBERT is unavailable (no `transformers` installed), gracefully fall back to
    the original keyword-based macro sentiment scorer.

This is a drop-in replacement for the per-headline scorer in
`tools/news_sentiment_nlp.py::analyze_headline`. The regime aggregation
(`get_regime_signal`) and the `sentiment_intraday.py` aggregator continue to work
unchanged — they only consume the standardized output dict.

Usage:
    from tools.sentiment_hybrid import HybridScorer
    h = HybridScorer()
    out = h.score_headline("Apple beats earnings, raises guidance to $1.50 EPS")
    # → dict with sentiment, analyst_action, macro_signal — same shape as analyze_headline

Env:
    HYBRID_DISABLE_FINBERT=1   # force regex-only mode (useful for tests / cold VPS)

CLI:
    python tools/sentiment_hybrid.py "Fed signals more rate cuts ahead"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.news_sentiment_nlp import (  # noqa: E402
    classify_analyst_action,
    classify_macro_sentiment,
    extract_es_levels,
    extract_vix_level,
)

# Lazy import so missing torch/transformers doesn't break import of this module
_FINBERT_AVAILABLE: Optional[bool] = None
_FINBERT_SCORER = None

REGEX_CONFIDENCE_FLOOR = 0.7  # Regex hits below this fall through to FinBERT


def _get_finbert():
    """Lazy-load FinBERT, returning scorer or None."""
    global _FINBERT_AVAILABLE, _FINBERT_SCORER
    if _FINBERT_AVAILABLE is False:
        return None
    if _FINBERT_SCORER is not None:
        return _FINBERT_SCORER
    if os.environ.get("HYBRID_DISABLE_FINBERT", "").strip() in ("1", "true", "yes"):
        _FINBERT_AVAILABLE = False
        return None
    try:
        from tools.sentiment_finbert import get_scorer
        scorer = get_scorer()
        if scorer.is_available():
            _FINBERT_AVAILABLE = True
            _FINBERT_SCORER = scorer
            return scorer
    except Exception as e:
        print(f"[HybridScorer] FinBERT load failed: {e}", file=sys.stderr)
    _FINBERT_AVAILABLE = False
    return None


class HybridScorer:
    def __init__(self, regex_floor: float = REGEX_CONFIDENCE_FLOOR):
        self.regex_floor = regex_floor

    def score_headline(self, headline_dict_or_str) -> dict:
        """Per-headline hybrid sentiment.

        Returns a dict with the same shape as
        `tools/news_sentiment_nlp.py::analyze_headline`.
        """
        # Accept both dict (legacy run_sentiment.py format) and raw string
        if isinstance(headline_dict_or_str, dict):
            headline_text = headline_dict_or_str.get("headline", "")
            base = dict(headline_dict_or_str)
        else:
            headline_text = str(headline_dict_or_str)
            base = {"headline": headline_text}

        # 1. Always run regex layers (fast, precise)
        analyst = classify_analyst_action(headline_text)
        macro = classify_macro_sentiment(headline_text)
        es_levels = extract_es_levels(headline_text)
        vix_level = extract_vix_level(headline_text)

        # 2. Decide whose label/score to use as the canonical "sentiment"
        # Priority: high-confidence analyst action > FinBERT > regex macro fallback
        sentiment = None
        sentiment_source = None

        analyst_action = analyst.get("action") or "none"
        # Schema: classify_analyst_action returns `signal` in [-1, +1], not `confidence`.
        # Use |signal| as confidence proxy.
        analyst_signal = float(analyst.get("signal", 0) or 0)
        analyst_conf = abs(analyst_signal)
        if analyst_action != "none" and analyst_conf >= self.regex_floor:
            # Map analyst action → sentiment label
            if analyst_action in ("upgrade", "positive_reit"):
                sentiment = {
                    "label": "bullish", "score": analyst_signal,
                    "confidence": analyst_conf,
                }
            elif analyst_action == "downgrade":
                sentiment = {
                    "label": "bearish", "score": analyst_signal,
                    "confidence": analyst_conf,
                }
            if sentiment is not None:
                sentiment_source = "regex_analyst"

        if sentiment is None:
            scorer = _get_finbert()
            if scorer is not None:
                fb = scorer.score(headline_text)
                if fb is not None:
                    label = fb["label"]
                    conf = fb["confidence"]
                    score_val = 0.0
                    if label == "bullish":
                        score_val = +conf
                    elif label == "bearish":
                        score_val = -conf
                    sentiment = {
                        "label": label,
                        "score": score_val,
                        "confidence": conf,
                    }
                    sentiment_source = "finbert"

        # 3. Fall back to regex macro sentiment if FinBERT unavailable.
        # classify_macro_sentiment returns net_signal in [-1, +1], not a sentiment dict.
        if sentiment is None:
            net = float(macro.get("net_signal", 0) or 0)
            label = "bullish" if net > 0.15 else ("bearish" if net < -0.15 else "neutral")
            sentiment = {
                "label": label,
                "score": net,
                "confidence": min(1.0, abs(net) + 0.3),  # baseline confidence floor
            }
            sentiment_source = "regex_macro"

        # 4. Compute actionability — analyst signal is most actionable
        actionability = 0.3
        if analyst_action != "none":
            actionability += 0.4
        if macro.get("category") and macro["category"] != "none":
            actionability += 0.2
        if es_levels:
            actionability += 0.1
        if vix_level is not None:
            actionability += 0.1
        actionability = min(1.0, actionability)

        return {
            **base,
            "sentiment": sentiment,
            "sentiment_source": sentiment_source,
            "analyst_action": analyst,
            "macro_signal": macro,
            "es_levels": es_levels,
            "vix_level": vix_level,
            "actionability": actionability,
        }


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hybrid sentiment scorer (regex + FinBERT)")
    parser.add_argument("text", nargs="?", default=None)
    parser.add_argument("--bench", action="store_true",
                        help="Run benchmark sample showing regex vs FinBERT splits")
    args = parser.parse_args()

    h = HybridScorer()

    if args.bench:
        sample = [
            ("Goldman upgrades NVDA to Buy, raises target to $200", "should be regex_analyst → bullish"),
            ("JPMorgan downgrades TSLA to Underweight on margin concerns", "regex_analyst → bearish"),
            ("Fed signals more rate cuts as inflation eases further", "finbert → likely bullish"),
            ("Recession risks mount; yield curve inverts deeper", "finbert → likely bearish"),
            ("Markets close mixed amid earnings deluge", "neutral"),
            ("Bitcoin surges past $120k all-time high", "finbert → bullish"),
            ("Tariff escalation rattles equities; SPX drops 2%", "finbert → bearish"),
            ("Apple beats Q4 estimates, raises full-year guidance", "regex/finbert → bullish"),
        ]
        for hl, expected in sample:
            r = h.score_headline(hl)
            print(f"\n{hl}")
            print(f"  expected:   {expected}")
            print(f"  source:     {r['sentiment_source']}")
            print(f"  label:      {r['sentiment']['label']:8}  score={r['sentiment']['score']:+.3f}  conf={r['sentiment']['confidence']:.3f}")
            print(f"  actionable: {r['actionability']:.2f}")
        return

    if not args.text:
        parser.print_help()
        return

    import json
    print(json.dumps(h.score_headline(args.text), indent=2, default=str))


if __name__ == "__main__":
    main()
