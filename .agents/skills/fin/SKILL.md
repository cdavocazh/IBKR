---
name: fin
description: Financial analysis — pass a subcommand (scan, analyze, macro, ta, stress, btc, etc.)
argument-hint: "<command> [args] — e.g., 'analyze NVDA', 'macro', 'ta gold', 'stress'"
---

Run the financial analysis subcommand: $ARGUMENTS

Available subcommands and how to execute them:

**Macro & Regime:**
- scan [full]          → python tools/run.py scan [--mode full]
- macro                → python tools/run.py macro
- bonds                → python tools/run.py bonds
- drivers [INDEX]      → python tools/run.py drivers [INDEX]
- stress               → python tools/run.py stress
- latecycle            → python tools/run.py latecycle
- termpremium          → python tools/run.py termpremium
- vixanalysis          → python tools/run.py vixanalysis
- consumer             → python tools/run.py consumer
- housing              → python tools/run.py housing
- labor                → python tools/run.py labor
- synthesize           → python tools/run.py synthesize

**Equity:**
- analyze TICKER       → python tools/run.py analyze TICKER
- compare T1,T2,...    → python tools/run.py compare T1,T2,...
- peers TICKER         → python tools/run.py peers TICKER
- allocation TICKER    → python tools/run.py allocation TICKER
- balance TICKER       → python tools/run.py balance TICKER

**Commodity:**
- commodity ASSET      → python tools/run.py commodity ASSET
- oil                  → python tools/run.py oil

**Technical Analysis:**
- ta ASSET             → python tools/run.py ta ASSET
- rsi ASSET [P] [TF]   → python tools/run.py rsi ASSET [--period P] [--timeframe TF]
- sr ASSET             → python tools/run.py sr ASSET
- breakout ASSET       → python tools/run.py breakout ASSET
- quickta ASSET        → python tools/run.py quickta ASSET
- synthesis TICKER     → python tools/run.py synthesis TICKER

**BTC:**
- btc                  → python tools/run.py btc
- btc trend            → python tools/run.py btc --trend
- btc position         → python tools/run.py btc --position

**Graham Value:**
- graham TICKER        → python tools/run.py graham TICKER
- grahamscreen         → python tools/run.py grahamscreen
- netnet               → python tools/run.py netnet

**Yardeni:**
- bbb                  → python tools/run.py bbb
- fsmi                 → python tools/run.py fsmi
- vigilantes           → python tools/run.py vigilantes
- valuation            → python tools/run.py valuation
- drawdown             → python tools/run.py drawdown

**Pro Trader:**
- riskpremium          → python tools/run.py riskpremium
- crossasset           → python tools/run.py crossasset
- pmregime             → python tools/run.py pmregime
- usdregime            → python tools/run.py usdregime
- sl ASSET PRICE DIR   → python tools/run.py sl ASSET PRICE DIR

**Multi-Step:**
- full_report          → Run the 8-analysis chain: scan → macro → stress → bonds → drivers → latecycle → consumer → synthesize. Execute each sequentially, then provide a unified briefing.
- search QUERY         → python tools/run.py search QUERY
- digest [DAYS]        → Read financial newsletter emails, extract market context to guides/market_context.md (default: last 2 days). Invoke the /digest skill.

Run the tool, then interpret results following guides/interpretation.md.
Write like a morning briefing for a portfolio manager: concise, data-driven, cite specific values/z-scores, highlight cross-asset signals.
