#!/usr/bin/env python3
"""
FinBERT / DistilRoBERTa Financial Sentiment Wrapper (Phase 3)

Drop-in transformer-based sentiment scorer for financial headlines.
Wraps HuggingFace's `pipeline("sentiment-analysis", model=...)` with:
  - Lazy model loading (avoid 440MB-load on import)
  - Batched inference (32 headlines/call)
  - Graceful fallback if `transformers`/`torch` not installed
  - LRU cache on a per-process basis (same headline scored once)

Default model: `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`
- ~85% accuracy on financial sentiment, faster (150 hl/sec on CPU) and smaller (330MB)
  than the heavier ProsusAI/finbert (89% / 50 hl/sec / 440MB).

Usage:
    from tools.sentiment_finbert import FinBERTScorer
    scorer = FinBERTScorer()             # lazy-loads model on first call
    if scorer.is_available():
        result = scorer.score("Apple beats earnings, raises guidance")
        # → {"label": "positive", "confidence": 0.97, "raw_label": "positive"}

    # Batch
    results = scorer.score_batch(["headline 1", "headline 2", ...])

Or as CLI:
    python tools/sentiment_finbert.py "Fed signals more rate cuts ahead"
    python tools/sentiment_finbert.py --bench   # Benchmark vs regex on a sample
"""
from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Default model — DistilRoBERTa is the best speed/accuracy trade-off for streaming.
# Swap in "ProsusAI/finbert" for highest accuracy at 3x latency.
DEFAULT_MODEL = "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
DEFAULT_BATCH_SIZE = 32

# Map FinBERT-family labels to our 3-class scheme used elsewhere
LABEL_MAP = {
    "positive": "bullish",
    "POSITIVE": "bullish",
    "LABEL_2":  "bullish",  # ProsusAI uses LABEL_2 for positive
    "negative": "bearish",
    "NEGATIVE": "bearish",
    "LABEL_0":  "bearish",
    "neutral":  "neutral",
    "NEUTRAL":  "neutral",
    "LABEL_1":  "neutral",
}


class FinBERTScorer:
    def __init__(self, model_name: str = DEFAULT_MODEL,
                 batch_size: int = DEFAULT_BATCH_SIZE,
                 device: str = "cpu"):
        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device
        self._pipe = None
        self._import_error: Optional[str] = None
        self._cache = {}

    def _ensure_loaded(self) -> bool:
        """Lazy-load the HuggingFace pipeline. Returns True on success."""
        if self._pipe is not None:
            return True
        if self._import_error is not None:
            return False
        try:
            from transformers import pipeline  # type: ignore
        except ImportError as e:
            self._import_error = (
                f"transformers not installed ({e}). "
                "Install with: pip install transformers torch --extra-index-url "
                "https://download.pytorch.org/whl/cpu"
            )
            print(f"[FinBERTScorer] {self._import_error}", file=sys.stderr)
            return False

        try:
            # device=-1 means CPU; positive int = GPU index
            device_id = -1 if self.device == "cpu" else int(self.device.split(":")[-1])
            self._pipe = pipeline(
                "sentiment-analysis",
                model=self.model_name,
                tokenizer=self.model_name,
                device=device_id,
                top_k=None,  # return all class probs
                truncation=True,
                max_length=256,
            )
            return True
        except Exception as e:
            self._import_error = f"failed to load model {self.model_name}: {e}"
            print(f"[FinBERTScorer] {self._import_error}", file=sys.stderr)
            return False

    def is_available(self) -> bool:
        """Check if model is usable (loads if not yet loaded)."""
        return self._ensure_loaded()

    def score(self, headline: str) -> Optional[dict]:
        """Score a single headline. Returns dict with normalized label/confidence
        or None if scorer unavailable.
        """
        if not headline or not headline.strip():
            return None
        if headline in self._cache:
            return self._cache[headline]
        if not self._ensure_loaded():
            return None
        result = self.score_batch([headline])
        return result[0] if result else None

    def score_batch(self, headlines: list[str]) -> list[Optional[dict]]:
        """Batch-score a list of headlines. Returns list aligned with input
        (None for any headline that couldn't be scored)."""
        if not headlines:
            return []
        if not self._ensure_loaded():
            return [None] * len(headlines)

        # Cache lookup
        results: list[Optional[dict]] = [None] * len(headlines)
        to_score: list[tuple[int, str]] = []
        for i, h in enumerate(headlines):
            if not h or not h.strip():
                continue
            if h in self._cache:
                results[i] = self._cache[h]
            else:
                to_score.append((i, h))

        if not to_score:
            return results

        # Batched inference
        try:
            batch_inputs = [h for _, h in to_score]
            raw_outputs = self._pipe(batch_inputs, batch_size=self.batch_size)
            # raw_outputs is list-of-lists when top_k=None: [[{label, score}, ...], ...]
            for (idx, hl), out in zip(to_score, raw_outputs):
                # out = list of {label, score} for each class
                if isinstance(out, list):
                    # Pick max-confidence class
                    top = max(out, key=lambda x: x["score"])
                else:
                    top = out
                normalized = {
                    "label": LABEL_MAP.get(top["label"], "neutral"),
                    "raw_label": top["label"],
                    "confidence": float(top["score"]),
                    # Also include all class probs for downstream use
                    "probs": {LABEL_MAP.get(o["label"], o["label"]): float(o["score"])
                              for o in (out if isinstance(out, list) else [out])},
                }
                results[idx] = normalized
                self._cache[hl] = normalized
        except Exception as e:
            print(f"[FinBERTScorer] inference error: {e}", file=sys.stderr)
        return results


# Singleton accessor — most callers want one shared scorer per process
@functools.lru_cache(maxsize=1)
def get_scorer(model_name: str = DEFAULT_MODEL) -> FinBERTScorer:
    return FinBERTScorer(model_name=model_name)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FinBERT/DistilRoBERTa headline scorer")
    parser.add_argument("text", nargs="?", default=None, help="Headline to score")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace model name")
    parser.add_argument("--batch", action="store_true", help="Read headlines from stdin (1/line)")
    parser.add_argument("--bench", action="store_true",
                        help="Benchmark vs regex on a fixed sample of 20 headlines")
    args = parser.parse_args()

    scorer = FinBERTScorer(model_name=args.model)

    if args.bench:
        sample = [
            "Fed signals more rate cuts ahead amid easing inflation",
            "Apple beats earnings, raises Q4 guidance to $1.50 EPS",
            "Powell hints at hawkish stance, markets sell off",
            "Oil prices surge on Iran tensions; equities decline",
            "Goldman Sachs upgrades NVDA to Buy on AI demand",
            "Recession concerns mount as yield curve inverts further",
            "Bitcoin breaks $100k as institutional flow accelerates",
            "Tariff escalation looms, China retaliates",
            "JPMorgan sees soft landing; raises 2026 SPX target to 7200",
            "Inflation surprise to the upside, Fed rate cuts off the table",
            "Tesla margins crater on price cuts, stock plunges 12%",
            "META earnings beat across the board, ad revenue +27% YoY",
            "Microsoft Azure growth slows for third straight quarter",
            "Government shutdown averted in last-minute Senate deal",
            "Treasury yields hit 6-month highs on hot CPI print",
            "Geopolitical tensions ease as ceasefire holds",
            "ECB cuts rates 25bps as expected; euro weakens",
            "ISM PMI contracts for fourth straight month",
            "Consumer confidence at 18-month low",
            "S&P 500 hits all-time high amid tech earnings bonanza",
        ]
        results = scorer.score_batch(sample)
        print(f"\nFinBERT model: {args.model}\n")
        print(f"{'Headline':<70} {'Label':<10} {'Conf'}")
        print("-" * 100)
        for hl, r in zip(sample, results):
            if r is None:
                print(f"{hl[:70]:<70} {'N/A':<10} -")
            else:
                print(f"{hl[:70]:<70} {r['label']:<10} {r['confidence']:.3f}")
        return

    if args.batch:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            r = scorer.score(text)
            if r is None:
                print(f"NULL\t{text}")
            else:
                print(f"{r['label']}\t{r['confidence']:.3f}\t{text}")
        return

    if not args.text:
        parser.print_help()
        return

    r = scorer.score(args.text)
    if r is None:
        print("Scorer unavailable (transformers not installed?)")
        sys.exit(2)
    import json
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
