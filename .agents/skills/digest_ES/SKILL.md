---
name: digest_ES
description: Read ES-focused financial newsletters + general market emails, extract market regime context for ES trading
argument-hint: "[days=2] — optional lookback window in days (default: 2, max: 14)"
---

Read ES/S&P 500-focused financial newsletters and general market emails, then update `guides/market_context_ES.md` with qualitative market context for ES trading decisions. Arguments: $ARGUMENTS

## Step 1: Parse Arguments
- Default lookback: 2 days. If a number is provided in $ARGUMENTS, use that (max 14).
- Compute the Gmail `after:` date as today minus N days, formatted as `YYYY/MM/DD`.

## Step 2: Resolve Gmail Labels
Call `gmail_list_labels()` to find the exact label names/IDs for labels with special characters. Match these user labels:
- `W | BzWSJ` — Bloomberg/WSJ aggregation
- `W | BzWSJ/Markets` — Bloomberg/WSJ Markets
- `1 | invs-gen-ir-tasty | traderade | eliant` — Eliant Capital / traderade
- `1 | Invs-Gen-macro` — General macro investment newsletters

Store the resolved label names for use in search queries.

## Step 3: Search Emails (8 queries, max 5 results each)
Run these Gmail searches in parallel where possible. Use `gmail_search_messages` with `maxResults: 5` (9 queries):

**General Market (same as /digest):**
1. **The Daily Rip**: `from:newsletter@thedailyrip.stocktwits.com after:YYYY/MM/DD`
2. **WSJ Markets PM**: `from:access@interactive.wsj.com subject:"WSJ Markets P.M." after:YYYY/MM/DD`
3. **Bloomberg/WSJ**: `label:{resolved-W-BzWSJ} after:YYYY/MM/DD`
4. **Bloomberg/WSJ Markets**: `label:{resolved-W-BzWSJ-Markets} after:YYYY/MM/DD`
5. **Eliant Capital**: `from:eliantcap@substack.com after:YYYY/MM/DD`
6. **Macro Newsletters**: `label:{resolved-Invs-Gen-macro} after:YYYY/MM/DD`

**ES-Specific Sources:**
7. **Smashelito (ES/macro trader)**: `from:smashelito@substack.com after:YYYY/MM/DD`
8. **James Bulltard (rates/macro/ES)**: `from:jamesbulltard@substack.com after:YYYY/MM/DD`
9. **Geo Chen / Fidenza (macro/ES strategist)**: `from:fidenza@substack.com after:YYYY/MM/DD`

If a label cannot be resolved, skip that source and note it in the output.

## Step 4: Read Each Email
Call `gmail_read_message(messageId)` for each search result. Focus on the editorial text body — ignore:
- Email headers, footers, unsubscribe links
- Ads, promotional banners, subscription prompts
- HTML boilerplate, tracking pixels

## Step 5: Extract ES-Focused Themes (COPYRIGHT CRITICAL)
For each email, extract in YOUR OWN ANALYTICAL VOICE:

**General themes (all sources):**
- 3-5 key market themes or signals (what moved, why, what's expected next)
- Asset/sector callouts with direction
- Macro data points mentioned (ISM, CPI, jobs, GDP, central bank commentary)
- Sentiment tone: risk-on, risk-off, mixed, cautious, euphoric

**ES-specific extraction (prioritize for Smashelito, James Bulltard & Geo Chen/Fidenza):**
- S&P 500 / ES futures specific commentary and levels
- Key support/resistance levels mentioned
- VIX regime assessment
- Positioning signals (CTA flows, dealer gamma, vol-control)
- Rate/bond market impact on equities
- Sector rotation themes affecting S&P
- Risk events calendar (Fed meetings, CPI, NFP, earnings)
- Market regime assessment: trending vs ranging, bull vs bear

**CRITICAL: Do NOT reproduce newsletter text verbatim. Do NOT quote sentences or paragraphs. Summarize themes in your own words as a financial analyst would. This is for copyright compliance. Extract the SIGNAL, not the prose.**

## Step 6: Read Existing Context File
Read `guides/market_context_ES.md` if it exists. If it doesn't exist, start fresh.

## Step 7: Write Updated Context File
Write `guides/market_context_ES.md` with this structure:

```markdown
# ES Market Context — Newsletter Digest

> Last updated: YYYY-MM-DD HH:MM | Sources: Daily Rip, WSJ PM, Bloomberg/WSJ, Eliant, Macro, Smashelito, James Bulltard, Geo Chen/Fidenza | Rolling: 7 days

## ES Regime Assessment
- **Trend**: [Bullish / Bearish / Sideways / Transitioning]
- **VIX Regime**: [Tier 1-7 per VIX framework] — current VIX level and direction
- **Key Levels**: Support at [X], Resistance at [Y]
- **Positioning**: [CTA positioning, dealer gamma, vol-control signals]
- **Key Risks**: [Upcoming events that could move ES]

## Key Themes This Week
- [Aggregated cross-source theme 1 — ES-relevant]
- [Aggregated cross-source theme 2 — ES-relevant]
- ...up to 8 bullets synthesizing the most important ES-relevant signals

## YYYY-MM-DD (newest first)

### The Daily Rip
- Theme 1
- Theme 2
- Sentiment: [tone]

### WSJ Markets PM
- Theme 1
- Theme 2

### Bloomberg/WSJ
- Theme 1
- Theme 2

### Eliant Capital
- Theme 1
- Theme 2

### Macro Newsletters
- Theme 1
- Theme 2

### Smashelito
- ES-specific theme 1
- ES-specific theme 2
- Key levels / positioning signals

### James Bulltard
- Rates/macro theme 1
- ES impact assessment
- Key levels / regime call

### Geo Chen / Fidenza
- Macro/geopolitical regime theme 1
- ES/SPX positioning and flow signals
- Key levels / directional bias

## YYYY-MM-DD (previous day)
...
```

**Rolling window**: Prune entries older than 7 days from the file. Keep the "ES Regime Assessment" and "Key Themes This Week" sections as syntheses of all remaining entries.

## Step 8: Report Summary
Tell the user:
- How many emails were processed per source
- Any sources that had no new emails or failed label resolution
- Top 3 ES-specific themes extracted across all sources
- Current ES regime assessment based on all signals
