#!/usr/bin/env python3
"""
NLP Sentiment Engine for ES/S&P 500 News Analysis

Parses financial news headlines to extract:
1. Sentiment polarity (bullish/bearish/neutral) with confidence
2. Analyst action signals (upgrades, downgrades, initiations, target changes)
3. Macro regime signals (rate moves, inflation, geopolitical risk, positioning)
4. ES-specific actionable insights (key levels, VIX signals, flow data)
5. Market regime classification from aggregated sentiment

Integrates with:
- VIX 7-tier framework (guides/interpretation.md)
- Macro regime classification (guides/macro_framework.md)
- Financial stress score components (guides/thresholds.md)
- Fidenza stop-loss framework (tools/protrader_sl.py)
- Market context from /digest_ES (guides/market_context_ES.md)

Usage:
    from tools.news_sentiment_nlp import analyze_headlines, get_regime_signal

    # Analyze a batch of headlines
    results = analyze_headlines(headlines)

    # Get aggregated regime signal for ES
    regime = get_regime_signal(results)
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─── Analyst Action Patterns ─────────────────────────────────

# Upgrades / positive actions
UPGRADE_PATTERNS = [
    r'\bupgraded?\b.*\b(buy|outperform|overweight|strong buy|positive|accumulate)\b',
    r'\binitiated?\b.*\b(buy|outperform|overweight|strong buy|positive)\b',
    r'\bresumed?\b.*\b(buy|outperform|overweight|strong buy)\b',
    r'\braised?\b.*\btarget\b',
    r'\bincreased?\b.*\btarget\b',
    r'\btarget\b.*\braised?\b',
    r'\bprice target\b.*\b(raised|increased|lifted|hiked|upped)\b',
]

# Downgrades / negative actions
DOWNGRADE_PATTERNS = [
    r'\bdowngraded?\b.*\b(sell|underperform|underweight|neutral|hold|equal weight|market perform)\b',
    r'\binitiated?\b.*\b(sell|underperform|underweight|reduce)\b',
    r'\bresumed?\b.*\b(sell|underperform|underweight|neutral)\b',
    r'\blowered?\b.*\btarget\b',
    r'\breduced?\b.*\btarget\b',
    r'\bcut\b.*\btarget\b',
    r'\btarget\b.*\b(lowered|reduced|cut|slashed|trimmed)\b',
]

# Neutral analyst actions
NEUTRAL_PATTERNS = [
    r'\breiterated?\b.*\b(neutral|hold|equal weight|market perform|in.line|sector perform)\b',
    r'\bmaintained?\b.*\b(neutral|hold|equal weight)\b',
]

# Positive reiteration
POSITIVE_REIT_PATTERNS = [
    r'\breiterated?\b.*\b(buy|outperform|overweight|strong buy|positive)\b',
    r'\bmaintained?\b.*\b(buy|outperform|overweight)\b',
]

# ─── Macro / Geopolitical Keywords ───────────────────────────

BEARISH_MACRO_KEYWORDS = {
    # Rate / monetary
    'hawkish': 0.7, 'rate hike': 0.8, 'rates higher': 0.6, 'tightening': 0.6,
    'inflation higher': 0.7, 'inflation accelerat': 0.6, 'stagflation': 0.9,
    'no rate cut': 0.7, 'rate cuts delayed': 0.6,
    # Geopolitical
    'war': 0.5, 'escalat': 0.6, 'sanctions': 0.4, 'missile': 0.5,
    'strait of hormuz': 0.7, 'no ceasefire': 0.8, 'military strike': 0.5,
    # Economic weakness
    'recession': 0.8, 'contraction': 0.7, 'layoffs': 0.5, 'job losses': 0.6,
    'gdp decline': 0.7, 'earnings miss': 0.6, 'revenue miss': 0.6,
    'guidance lower': 0.7, 'guidance cut': 0.7, 'profit warning': 0.8,
    # Market structure
    'correction': 0.6, 'bear market': 0.8, 'sell-off': 0.5, 'selloff': 0.5,
    'crash': 0.7, 'capitulation': 0.6, 'margin call': 0.7,
    'below 200': 0.6, 'death cross': 0.7, 'breakdown': 0.5,
    'record outflow': 0.6, 'net selling': 0.5,
    # Credit / stress
    'credit spread': 0.4, 'default': 0.6, 'downgrade': 0.5,
    'yield curve invert': 0.6, 'financial stress': 0.5,
}

BULLISH_MACRO_KEYWORDS = {
    # Rate / monetary
    'dovish': 0.7, 'rate cut': 0.7, 'easing': 0.6, 'stimulus': 0.7,
    'inflation cool': 0.6, 'inflation slow': 0.5, 'disinflation': 0.6,
    # Positive economic
    'recovery': 0.5, 'expansion': 0.5, 'job growth': 0.5, 'hiring': 0.4,
    'gdp growth': 0.5, 'earnings beat': 0.6, 'revenue beat': 0.6,
    'guidance raise': 0.7, 'guidance higher': 0.7, 'record revenue': 0.6,
    'blowout earnings': 0.8, 'record quarter': 0.7,
    # Market structure
    'all-time high': 0.6, 'breakout': 0.5, 'golden cross': 0.6,
    'bull market': 0.6, 'rally': 0.4, 'buying': 0.3,
    'record inflow': 0.6, 'net buying': 0.5,
    # Geopolitical resolution
    'ceasefire': 0.7, 'peace deal': 0.8, 'de-escalation': 0.6,
    'trade deal': 0.6, 'tariff remove': 0.5, 'tariff revers': 0.5,
}

# ─── ES-Specific Level Extraction ────────────────────────────

ES_LEVEL_PATTERN = re.compile(
    r'(?:ES|SPX|S&P)\s*(?:at|near|above|below|target|support|resistance|level)?\s*'
    r'(\d{4}(?:\.\d{1,2})?)',
    re.IGNORECASE
)

TARGET_PRICE_PATTERN = re.compile(
    r'target\s*\$?(\d+(?:\.\d{1,2})?)',
    re.IGNORECASE
)

# ─── VIX Signal Extraction ───────────────────────────────────

VIX_PATTERN = re.compile(
    r'VIX\s*(?:at|near|above|below|hit|spike|jump|surge|fell|drop)?\s*(\d+(?:\.\d{1,2})?)',
    re.IGNORECASE
)

# ─── Core Analysis Functions ─────────────────────────────────

def _match_any(text: str, patterns: list) -> bool:
    text_lower = text.lower()
    for p in patterns:
        if re.search(p, text_lower):
            return True
    return False


def _keyword_score(text: str, keyword_dict: dict) -> tuple:
    """Score text against keyword dict. Returns (total_score, matched_keywords)."""
    text_lower = text.lower()
    total = 0.0
    matched = []
    for keyword, weight in keyword_dict.items():
        if keyword in text_lower:
            total += weight
            matched.append(keyword)
    return total, matched


def classify_analyst_action(headline: str) -> dict:
    """Classify analyst action from headline.

    Returns:
        {
            "action": "upgrade" | "downgrade" | "neutral_reit" | "positive_reit" | "none",
            "firm": str or None,
            "rating": str or None,
            "target": float or None,
            "signal": float (-1 to +1),
        }
    """
    result = {"action": "none", "firm": None, "rating": None, "target": None, "signal": 0.0}

    # Extract target price
    target_match = TARGET_PRICE_PATTERN.search(headline)
    if target_match:
        try:
            result["target"] = float(target_match.group(1))
        except ValueError:
            pass

    # Extract firm name (typically first word(s) before "upgraded/downgraded/reiterated")
    firm_match = re.match(r'^([A-Z][A-Za-z\s&.]+?)(?:\s+(?:upgraded|downgraded|initiated|reiterated|resumed|maintained|raised|lowered|cut))', headline)
    if firm_match:
        result["firm"] = firm_match.group(1).strip()

    # Classify action
    if _match_any(headline, UPGRADE_PATTERNS):
        result["action"] = "upgrade"
        result["signal"] = 0.7
    elif _match_any(headline, DOWNGRADE_PATTERNS):
        result["action"] = "downgrade"
        result["signal"] = -0.7
    elif _match_any(headline, POSITIVE_REIT_PATTERNS):
        result["action"] = "positive_reit"
        result["signal"] = 0.3
    elif _match_any(headline, NEUTRAL_PATTERNS):
        result["action"] = "neutral_reit"
        result["signal"] = 0.0

    return result


def classify_macro_sentiment(headline: str) -> dict:
    """Classify macro/geopolitical sentiment from headline.

    Returns:
        {
            "bearish_score": float (0-5),
            "bullish_score": float (0-5),
            "net_signal": float (-1 to +1),
            "bearish_keywords": list,
            "bullish_keywords": list,
            "category": "macro" | "geopolitical" | "earnings" | "market_structure" | "none",
        }
    """
    bear_score, bear_kw = _keyword_score(headline, BEARISH_MACRO_KEYWORDS)
    bull_score, bull_kw = _keyword_score(headline, BULLISH_MACRO_KEYWORDS)

    total = bear_score + bull_score
    if total > 0:
        net = (bull_score - bear_score) / max(total, 1)
    else:
        net = 0.0

    # Categorize
    category = "none"
    text_lower = headline.lower()
    if any(k in text_lower for k in ['rate', 'fed', 'inflation', 'gdp', 'jobs', 'employment', 'cpi', 'pce', 'ism']):
        category = "macro"
    elif any(k in text_lower for k in ['war', 'iran', 'missile', 'sanctions', 'hormuz', 'geopolit', 'military', 'ceasefire']):
        category = "geopolitical"
    elif any(k in text_lower for k in ['earnings', 'revenue', 'guidance', 'quarter', 'profit', 'eps']):
        category = "earnings"
    elif any(k in text_lower for k in ['correction', 'bear', 'bull', 'rally', 'selloff', 'breakout', 'support', 'resistance', 'vix']):
        category = "market_structure"

    return {
        "bearish_score": round(bear_score, 2),
        "bullish_score": round(bull_score, 2),
        "net_signal": round(net, 3),
        "bearish_keywords": bear_kw,
        "bullish_keywords": bull_kw,
        "category": category,
    }


def extract_es_levels(headline: str) -> list:
    """Extract ES/SPX price levels mentioned in headline."""
    levels = []
    for match in ES_LEVEL_PATTERN.finditer(headline):
        try:
            level = float(match.group(1))
            if 3000 < level < 10000:  # Reasonable ES range
                levels.append(level)
        except ValueError:
            pass
    return levels


def extract_vix_level(headline: str) -> Optional[float]:
    """Extract VIX level if mentioned."""
    match = VIX_PATTERN.search(headline)
    if match:
        try:
            vix = float(match.group(1))
            if 5 < vix < 100:  # Reasonable VIX range
                return vix
        except ValueError:
            pass
    return None


# ─── Main Analysis Function ──────────────────────────────────

def analyze_headline(headline_dict: dict) -> dict:
    """Analyze a single headline dict and produce structured sentiment.

    Args:
        headline_dict: {headline, provider, time, ticker, articleId, metadata}

    Returns:
        Enriched dict with sentiment analysis fields.
    """
    headline = headline_dict.get("headline", "")
    provider = headline_dict.get("provider", "")

    # Analyst action analysis
    analyst = classify_analyst_action(headline)

    # Macro sentiment analysis
    macro = classify_macro_sentiment(headline)

    # ES-specific extraction
    es_levels = extract_es_levels(headline)
    vix_level = extract_vix_level(headline)

    # Composite sentiment (-1 to +1)
    signals = []
    if analyst["action"] != "none":
        signals.append(analyst["signal"])
    if macro["bearish_score"] > 0 or macro["bullish_score"] > 0:
        signals.append(macro["net_signal"])

    # Provider confidence as weight
    confidence = headline_dict.get("metadata", {}).get("confidence", 0.5)

    if signals:
        composite = sum(signals) / len(signals)
    else:
        composite = 0.0

    # Determine label
    if composite > 0.2:
        label = "bullish"
    elif composite < -0.2:
        label = "bearish"
    else:
        label = "neutral"

    # Actionability score (0-1): how useful is this for trading decisions?
    actionability = 0.0
    if analyst["action"] in ("upgrade", "downgrade"):
        actionability += 0.4
    if macro["category"] in ("macro", "geopolitical"):
        actionability += 0.3
    if es_levels:
        actionability += 0.2
    if vix_level:
        actionability += 0.1
    if abs(macro["net_signal"]) > 0.5:
        actionability += 0.2
    actionability = min(1.0, actionability)

    return {
        **headline_dict,
        "sentiment": {
            "label": label,
            "score": round(composite, 3),
            "confidence": round(confidence if isinstance(confidence, (int, float)) else 0.5, 2),
        },
        "analyst_action": analyst,
        "macro_signal": macro,
        "es_levels": es_levels,
        "vix_level": vix_level,
        "actionability": round(actionability, 2),
    }


def analyze_headlines(headlines: list) -> list:
    """Analyze a batch of headlines."""
    return [analyze_headline(h) for h in headlines]


# ─── Regime Signal Aggregation ───────────────────────────────

def get_regime_signal(analyzed: list, hours_back: int = 24) -> dict:
    """Aggregate analyzed headlines into an ES regime signal.

    Integrates with:
    - VIX 7-tier framework
    - Macro regime classification
    - Market positioning signals

    Returns:
        {
            "regime": "BULLISH" | "BEARISH" | "SIDEWAYS",
            "confidence": float (0-1),
            "net_sentiment": float (-1 to +1),
            "headline_count": int,
            "bullish_count": int,
            "bearish_count": int,
            "neutral_count": int,
            "upgrade_count": int,
            "downgrade_count": int,
            "dominant_category": str,
            "key_themes": list,
            "es_levels_mentioned": list,
            "vix_signals": list,
            "actionable_insights": list,
        }
    """
    if not analyzed:
        return {
            "regime": "SIDEWAYS", "confidence": 0.0, "net_sentiment": 0.0,
            "headline_count": 0, "bullish_count": 0, "bearish_count": 0,
            "neutral_count": 0, "upgrade_count": 0, "downgrade_count": 0,
            "dominant_category": "none", "key_themes": [],
            "es_levels_mentioned": [], "vix_signals": [],
            "actionable_insights": [],
        }

    # Filter by time window
    now = datetime.now()
    cutoff = now - timedelta(hours=hours_back)
    recent = []
    for h in analyzed:
        try:
            t = datetime.fromisoformat(str(h.get("time", "")).replace(" ", "T")[:19])
            if t > cutoff:
                recent.append(h)
        except (ValueError, TypeError):
            recent.append(h)  # Include if we can't parse time

    if not recent:
        recent = analyzed[-50:]  # Fall back to latest 50

    # Count sentiments
    sentiments = Counter(h["sentiment"]["label"] for h in recent)
    bull_count = sentiments.get("bullish", 0)
    bear_count = sentiments.get("bearish", 0)
    neutral_count = sentiments.get("neutral", 0)

    # Analyst actions
    upgrade_count = sum(1 for h in recent if h["analyst_action"]["action"] in ("upgrade", "positive_reit"))
    downgrade_count = sum(1 for h in recent if h["analyst_action"]["action"] in ("downgrade",))

    # Net sentiment (weighted by actionability)
    weighted_scores = []
    for h in recent:
        weight = max(0.1, h.get("actionability", 0.5))
        weighted_scores.append(h["sentiment"]["score"] * weight)
    net_sentiment = sum(weighted_scores) / max(len(weighted_scores), 1)

    # Dominant category
    categories = Counter(h["macro_signal"]["category"] for h in recent if h["macro_signal"]["category"] != "none")
    dominant_category = categories.most_common(1)[0][0] if categories else "none"

    # ES levels mentioned
    all_levels = []
    for h in recent:
        all_levels.extend(h.get("es_levels", []))
    es_levels = sorted(set(all_levels))

    # VIX signals
    vix_signals = [h["vix_level"] for h in recent if h.get("vix_level") is not None]

    # Key themes (most common bearish/bullish keywords)
    all_bear_kw = []
    all_bull_kw = []
    for h in recent:
        all_bear_kw.extend(h["macro_signal"].get("bearish_keywords", []))
        all_bull_kw.extend(h["macro_signal"].get("bullish_keywords", []))

    key_themes = []
    for kw, count in Counter(all_bear_kw).most_common(5):
        key_themes.append(f"BEARISH: {kw} ({count}x)")
    for kw, count in Counter(all_bull_kw).most_common(5):
        key_themes.append(f"BULLISH: {kw} ({count}x)")

    # Actionable insights (high-actionability headlines)
    actionable = sorted(recent, key=lambda h: h.get("actionability", 0), reverse=True)
    actionable_insights = []
    for h in actionable[:10]:
        if h.get("actionability", 0) >= 0.3:
            actionable_insights.append({
                "headline": h["headline"][:120],
                "sentiment": h["sentiment"]["label"],
                "score": h["sentiment"]["score"],
                "category": h["macro_signal"]["category"],
                "actionability": h["actionability"],
            })

    # Regime classification
    # Uses net sentiment + upgrade/downgrade ratio + category dominance
    regime_score = net_sentiment
    if upgrade_count + downgrade_count > 0:
        analyst_ratio = (upgrade_count - downgrade_count) / (upgrade_count + downgrade_count)
        regime_score = regime_score * 0.6 + analyst_ratio * 0.4

    if regime_score > 0.15:
        regime = "BULLISH"
    elif regime_score < -0.15:
        regime = "BEARISH"
    else:
        regime = "SIDEWAYS"

    # Confidence based on sample size and agreement
    total = bull_count + bear_count + neutral_count
    if total > 0:
        max_count = max(bull_count, bear_count, neutral_count)
        agreement = max_count / total
        confidence = min(1.0, agreement * min(1.0, total / 20))
    else:
        confidence = 0.0

    return {
        "regime": regime,
        "confidence": round(confidence, 2),
        "net_sentiment": round(net_sentiment, 3),
        "headline_count": len(recent),
        "bullish_count": bull_count,
        "bearish_count": bear_count,
        "neutral_count": neutral_count,
        "upgrade_count": upgrade_count,
        "downgrade_count": downgrade_count,
        "dominant_category": dominant_category,
        "key_themes": key_themes,
        "es_levels_mentioned": es_levels,
        "vix_signals": vix_signals,
        "actionable_insights": actionable_insights,
    }


# ─── Market Context Integration ──────────────────────────────

def enrich_with_market_context(regime_signal: dict) -> dict:
    """Enrich regime signal with market context from /digest_ES output.

    Deeply parses guides/market_context_ES.md to extract:
    - Trend direction and cross-validate with NLP regime
    - VIX tier and specific levels
    - Key support/resistance levels (Smashlevel, VPOC, MA200, etc.)
    - Positioning signals (Goldman, JPM, NAAIM, CTA)
    - Key risks and themes
    - Per-source sentiment tones
    - Newsletter-derived sentiment score

    The newsletter context is weighted heavily (0.6) vs NLP headlines (0.4)
    when producing the unified ES trading direction.
    """
    context_path = Path(__file__).parent.parent / "guides" / "market_context_ES.md"
    if not context_path.exists():
        regime_signal["market_context_available"] = False
        return regime_signal

    content = context_path.read_text()
    regime_signal["market_context_available"] = True

    # Extract last updated timestamp
    updated_match = re.search(r'Last updated:\s*(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})', content)
    if updated_match:
        regime_signal["context_last_updated"] = updated_match.group(1)

    # ── Trend ──
    trend_match = re.search(r'\*\*Trend\*\*:\s*(\w+)', content)
    if trend_match:
        context_trend = trend_match.group(1).upper()
        regime_signal["context_trend"] = context_trend

        if context_trend == regime_signal["regime"]:
            regime_signal["confidence"] = min(1.0, regime_signal["confidence"] + 0.15)
            regime_signal["cross_validated"] = True
        else:
            regime_signal["cross_validated"] = False
            regime_signal["divergence_note"] = (
                f"NLP says {regime_signal['regime']} but newsletter context says {context_trend}"
            )

    # ── VIX regime ──
    vix_match = re.search(r'\*\*VIX Regime\*\*:\s*Tier\s*(\d)(?:-(\d))?', content)
    if vix_match:
        regime_signal["context_vix_tier"] = int(vix_match.group(1))
        if vix_match.group(2):
            regime_signal["context_vix_tier_high"] = int(vix_match.group(2))

    # Extract specific VIX levels
    vix_levels = re.findall(r'VIX\s*(?:at|near|levels?|watch)?:?\s*(\d+\.?\d*)', content, re.IGNORECASE)
    if vix_levels:
        regime_signal["context_vix_levels"] = sorted(set(float(v) for v in vix_levels if 5 < float(v) < 100))

    # ── Key levels (comprehensive) ──
    levels = {}

    # Smashlevel pivot
    smash_match = re.search(r'Smashlevel\s*\(?pivot\)?:\s*\*?\*?(\d{4}(?:\.\d+)?)', content)
    if smash_match:
        levels["smashlevel_pivot"] = float(smash_match.group(1))

    # VPOC levels
    for vpoc_match in re.finditer(r'(\d+D)\s*VPOC\s*(?:at)?\s*(\d{4}(?:\.\d+)?)', content):
        levels[f"vpoc_{vpoc_match.group(1).lower()}"] = float(vpoc_match.group(2))

    # Support/resistance from bullet points
    support_levels = re.findall(r'(?:support|downside\s*target|spike\s*base|extreme\s*low)[^:]*?(\d{4}(?:\.\d+)?)', content, re.IGNORECASE)
    resist_levels = re.findall(r'(?:resistance|upside\s*target|extreme\s*high)[^:]*?(\d{4}(?:\.\d+)?)', content, re.IGNORECASE)

    if support_levels:
        levels["support"] = sorted(set(float(s) for s in support_levels if 3000 < float(s) < 10000))
    if resist_levels:
        levels["resistance"] = sorted(set(float(r) for r in resist_levels if 3000 < float(r) < 10000))

    # MA levels
    ma200_match = re.search(r'(?:MA|SMA|EMA)\s*200[^:]*?(\d{4}(?:\.\d+)?)', content)
    if ma200_match:
        levels["ma200"] = float(ma200_match.group(1))

    # Correction level
    correction_match = re.search(r'(?:correction|10%)\s*level[^:]*?(\d{4}(?:\.\d+)?)', content)
    if correction_match:
        levels["correction_level"] = float(correction_match.group(1))

    if levels:
        regime_signal["context_levels"] = levels

    # ── Positioning signals ──
    positioning = {}
    content_lower = content.lower()

    # Goldman
    if 'goldman' in content_lower:
        goldman_match = re.search(r'Goldman[^.]*?(\$[\d.]+\s*b(?:n|illion)?)[^.]*?(selling|buying|net\s+\w+)', content, re.IGNORECASE)
        if goldman_match:
            positioning["goldman"] = goldman_match.group(0)[:120]

    # JPM
    if 'jpm' in content_lower or 'jp morgan' in content_lower:
        jpm_match = re.search(r'JPM[^.]*?(-?\d+\.?\d*z)', content, re.IGNORECASE)
        if jpm_match:
            positioning["jpm_z_score"] = float(jpm_match.group(1).replace('z', ''))

    # NAAIM
    if 'naaim' in content_lower:
        naaim_match = re.search(r'NAAIM[^.]*?(low|high|extreme|record|bearish|bullish)', content, re.IGNORECASE)
        if naaim_match:
            positioning["naaim"] = naaim_match.group(0)[:100]

    # Breadth
    breadth_match = re.search(r'(\d+)%\s*(?:of\s*stocks?\s*)?above\s*(\d+)D', content)
    if breadth_match:
        positioning[f"pct_above_{breadth_match.group(2)}d"] = int(breadth_match.group(1))

    if positioning:
        regime_signal["context_positioning"] = positioning

    # ── Key risks ──
    risks_match = re.search(r'\*\*Key Risks\*\*:\s*(.+?)(?:\n\n|\n##)', content, re.DOTALL)
    if risks_match:
        regime_signal["context_key_risks"] = risks_match.group(1).strip()[:300]

    # ── Key themes ──
    themes_section = re.search(r'## Key Themes This Week\n((?:- .+\n?)+)', content)
    if themes_section:
        themes = [line.strip('- \n') for line in themes_section.group(1).strip().split('\n') if line.strip().startswith('-')]
        regime_signal["context_themes"] = themes[:8]

    # ── Per-source sentiment tones ──
    sentiment_tones = re.findall(r'Sentiment:\s*(.+?)$', content, re.MULTILINE)
    if sentiment_tones:
        regime_signal["context_sentiment_tones"] = sentiment_tones

    # ── Derive newsletter sentiment score ──
    newsletter_score = _compute_newsletter_sentiment_score(content, sentiment_tones)
    regime_signal["newsletter_sentiment_score"] = newsletter_score

    # ── Unified signal: blend NLP (0.4) + newsletter (0.6) ──
    nlp_score = regime_signal.get("net_sentiment", 0.0)
    blended = nlp_score * 0.4 + newsletter_score * 0.6
    regime_signal["unified_sentiment"] = round(blended, 3)

    if blended > 0.15:
        regime_signal["unified_regime"] = "BULLISH"
    elif blended < -0.15:
        regime_signal["unified_regime"] = "BEARISH"
    else:
        regime_signal["unified_regime"] = "SIDEWAYS"

    return regime_signal


def _compute_newsletter_sentiment_score(content: str, sentiment_tones: list) -> float:
    """Derive a -1 to +1 sentiment score from newsletter context.

    Uses:
    - Explicit sentiment tones (risk-off, bearish, etc.)
    - Trend direction from regime assessment
    - Positioning signals (extreme bearish = contrarian bullish potential)
    - Keyword density in themes
    """
    score = 0.0
    signals = 0

    # Sentiment tones
    tone_scores = {
        'risk-off': -0.6, 'deeply risk-off': -0.9, 'bearish': -0.7,
        'cautious': -0.3, 'mixed': 0.0, 'neutral': 0.0,
        'risk-on': 0.6, 'bullish': 0.7, 'euphoric': 0.8,
    }
    for tone in sentiment_tones:
        tone_lower = tone.lower().strip()
        for key, val in tone_scores.items():
            if key in tone_lower:
                score += val
                signals += 1
                break

    # Trend direction
    trend_match = re.search(r'\*\*Trend\*\*:\s*(\w+)', content)
    if trend_match:
        trend = trend_match.group(1).upper()
        if trend == "BEARISH":
            score -= 0.5
        elif trend == "BULLISH":
            score += 0.5
        elif trend == "TRANSITIONING":
            score -= 0.1
        signals += 1

    # Bearish/bullish keyword density in themes section
    themes_section = re.search(r'## Key Themes This Week\n((?:- .+\n?)+)', content)
    if themes_section:
        themes_text = themes_section.group(1).lower()
        bear_kw = sum(1 for kw in ['selloff', 'sell-off', 'correction', 'war', 'risk-off',
                                     'below 200', 'recession', 'crash', 'hawkish', 'washout',
                                     'decline', 'weakness', 'losses'] if kw in themes_text)
        bull_kw = sum(1 for kw in ['rally', 'breakout', 'recovery', 'dovish', 'rate cut',
                                    'all-time high', 'bullish', 'strength', 'beat'] if kw in themes_text)
        if bear_kw + bull_kw > 0:
            kw_signal = (bull_kw - bear_kw) / (bear_kw + bull_kw)
            score += kw_signal * 0.4
            signals += 1

    if signals > 0:
        return round(max(-1.0, min(1.0, score / max(signals, 1))), 3)
    return 0.0


# ─── CLI ─────────────────────────────────────────────────────

def main():
    """CLI for testing the NLP sentiment engine."""
    import sys

    # Load sample data
    sample_path = Path(__file__).parent.parent / "data" / "news" / "sample_headlines.json"

    if len(sys.argv) > 1 and sys.argv[1] == "live":
        # Fetch live headlines
        print("Fetching live headlines from IBKR...")
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.ib_news_stream import connect, _qualify_ticker, parse_headline
        ib = connect(client_id=26)
        headlines = []
        for ticker in ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN"]:
            c = _qualify_ticker(ib, ticker)
            if c:
                try:
                    result = ib.reqHistoricalNews(c.conId, "BRFG+BRFUPDN+DJNL", "", "", 20)
                    if result:
                        for h in result:
                            parsed = parse_headline(h.headline)
                            headlines.append({
                                "headline": parsed["headline"],
                                "provider": h.providerCode,
                                "time": str(h.time),
                                "articleId": h.articleId,
                                "ticker": ticker,
                                "metadata": parsed["metadata"],
                            })
                except Exception as e:
                    print(f"  Skip {ticker}: {e}")
                import time; time.sleep(2)
        ib.disconnect()
    elif sample_path.exists():
        with open(sample_path) as f:
            headlines = json.load(f)
        print(f"Loaded {len(headlines)} headlines from {sample_path}")
    else:
        print("No data available. Run with 'live' argument or fetch sample data first.")
        return

    # Analyze
    analyzed = analyze_headlines(headlines)

    # Print individual results
    print(f"\n{'='*80}")
    print(f"  HEADLINE SENTIMENT ANALYSIS ({len(analyzed)} headlines)")
    print(f"{'='*80}")

    for h in sorted(analyzed, key=lambda x: x.get("actionability", 0), reverse=True)[:20]:
        sent = h["sentiment"]
        color = {"bullish": "+", "bearish": "-", "neutral": "~"}[sent["label"]]
        action = h["analyst_action"]["action"]
        action_str = f" [{action}]" if action != "none" else ""
        cat = h["macro_signal"]["category"]
        cat_str = f" ({cat})" if cat != "none" else ""

        print(f"  [{color}] {sent['label']:>7s} ({sent['score']:+.2f}) "
              f"act={h['actionability']:.1f}{action_str}{cat_str}")
        print(f"      {h['headline'][:90]}")
        if h.get("es_levels"):
            print(f"      ES levels: {h['es_levels']}")
        print()

    # Regime signal
    regime = get_regime_signal(analyzed, hours_back=168)  # Last week
    regime = enrich_with_market_context(regime)

    print(f"{'='*80}")
    print(f"  ES REGIME SIGNAL")
    print(f"{'='*80}")
    print(f"  Regime:       {regime['regime']} (confidence: {regime['confidence']:.0%})")
    print(f"  Net Sentiment: {regime['net_sentiment']:+.3f}")
    print(f"  Headlines:    {regime['headline_count']} "
          f"(bull={regime['bullish_count']}, bear={regime['bearish_count']}, neutral={regime['neutral_count']})")
    print(f"  Analyst:      {regime['upgrade_count']} upgrades, {regime['downgrade_count']} downgrades")
    print(f"  Category:     {regime['dominant_category']}")

    if regime.get("cross_validated"):
        print(f"  Cross-Valid:  CONFIRMED (newsletter context agrees)")
    elif regime.get("divergence_note"):
        print(f"  Divergence:   {regime['divergence_note']}")

    if regime.get("context_vix_tier"):
        print(f"  VIX Tier:     {regime['context_vix_tier']}")

    if regime["key_themes"]:
        print(f"\n  Key Themes:")
        for t in regime["key_themes"]:
            print(f"    - {t}")

    if regime["actionable_insights"]:
        print(f"\n  Actionable Insights:")
        for ins in regime["actionable_insights"][:5]:
            print(f"    [{ins['sentiment']:>7s}] (act={ins['actionability']:.1f}) {ins['headline']}")

    # Save results
    output_path = Path(__file__).parent.parent / "data" / "news" / "sentiment_analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "regime_signal": regime,
            "analyzed_count": len(analyzed),
            "sample_analyzed": [
                {k: v for k, v in h.items() if k != "raw"}
                for h in sorted(analyzed, key=lambda x: x.get("actionability", 0), reverse=True)[:50]
            ],
        }, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()
