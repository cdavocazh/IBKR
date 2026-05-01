# News Streaming Skill — Architecture & Provider Requirements

**This file has moved.** The canonical version is now at
[`guides/news_streaming_requirements.md`](guides/news_streaming_requirements.md).

Reason: the original lived at the repo root, but `guides/` is where all
interpretation/framework docs are organized. We keep this stub so any old
links don't 404.

For the current sentiment + news architecture (post-May 2026 deployment), see:
- [`CLAUDE.md`](CLAUDE.md) — overview, clientId map, all sentiment scripts/services
- [`STATUS.md`](STATUS.md) — current VPS deployment state
- [`VPS_Hostinger_setup.md`](VPS_Hostinger_setup.md) — deployment commands
- [`tools/news_stream_continuous.py`](tools/news_stream_continuous.py) — running daemon (clientId 27)
- [`tools/sentiment_intraday.py`](tools/sentiment_intraday.py) — 15-min rolling aggregator
