---
name: digest
description: Read financial newsletter emails, extract market context, save to guides/market_context.md
argument-hint: "[days=2] — optional lookback window in days (default: 2, max: 14)"
---

Read financial newsletter emails and update `guides/market_context.md` with qualitative market context. Arguments: $ARGUMENTS

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

## Step 3: Search Emails (6 queries, max 5 results each)
Run these Gmail searches in parallel where possible. Use `gmail_search_messages` with `maxResults: 5`:

1. **The Daily Rip**: `from:newsletter@thedailyrip.stocktwits.com after:YYYY/MM/DD`
2. **WSJ Markets PM**: `from:access@interactive.wsj.com subject:"WSJ Markets P.M." after:YYYY/MM/DD`
3. **Bloomberg/WSJ**: `label:{resolved-W-BzWSJ} after:YYYY/MM/DD`
4. **Bloomberg/WSJ Markets**: `label:{resolved-W-BzWSJ-Markets} after:YYYY/MM/DD`
5. **Eliant Capital**: `from:eliantcap@substack.com after:YYYY/MM/DD` (also try the resolved eliant label if sender search returns few results)
6. **Macro Newsletters**: `label:{resolved-Invs-Gen-macro} after:YYYY/MM/DD`

If a label cannot be resolved, skip that source and note it in the output.

## Step 4: Read Each Email
Call `gmail_read_message(messageId)` for each search result. Focus on the editorial text body — ignore:
- Email headers, footers, unsubscribe links
- Ads, promotional banners, subscription prompts
- HTML boilerplate, tracking pixels

## Step 5: Extract Themes (COPYRIGHT CRITICAL)
For each email, extract in YOUR OWN ANALYTICAL VOICE:
- **3-5 key market themes or signals** (what moved, why, what's expected next)
- **Asset/sector callouts** with direction (e.g., "tech rotation into defensives", "oil supply concerns")
- **Macro data points** mentioned (ISM, CPI, jobs, GDP, central bank commentary)
- **Sentiment tone**: risk-on, risk-off, mixed, cautious, euphoric

**CRITICAL: Do NOT reproduce newsletter text verbatim. Do NOT quote sentences or paragraphs. Summarize themes in your own words as a financial analyst would. This is for copyright compliance. Extract the SIGNAL, not the prose.**

## Step 6: Read Existing Context File
Read `guides/market_context.md` if it exists. If it doesn't exist, start fresh.

## Step 7: Write Updated Context File
Write `guides/market_context.md` with this structure:

```markdown
# Market Context — Newsletter Digest

> Last updated: YYYY-MM-DD HH:MM | Sources: Daily Rip, WSJ PM, Bloomberg/WSJ, Eliant, Macro | Rolling: 7 days

## Key Themes This Week
- [Aggregated cross-source theme 1]
- [Aggregated cross-source theme 2]
- ...up to 8 bullets synthesizing the most important signals

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

## YYYY-MM-DD (previous day)
...
```

**Rolling window**: Prune entries older than 7 days from the file. Keep the "Key Themes This Week" section as a synthesis of all remaining entries.

## Step 8: Report Summary
Tell the user:
- How many emails were processed per source
- Any sources that had no new emails or failed label resolution
- Top 3 themes extracted across all sources
