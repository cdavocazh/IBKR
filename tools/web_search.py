"""Web search tool — Tavily (primary) with DuckDuckGo fallback.

Provides the agent with the ability to search the internet to verify
insights, find supporting data, or look up recent events.

Tavily is an AI-agent-optimized search API that returns structured results
with relevance scoring. Falls back to DuckDuckGo when Tavily is unavailable
or TAVILY_API_KEY is not set.

v2.7 — 2026-03-11: Added Tavily as primary search engine.
"""

import json
import os

# ── Tavily (primary — AI-agent-optimized search) ──
try:
    from tavily import TavilyClient
    _HAS_TAVILY = True
except ImportError:
    _HAS_TAVILY = False

# ── DuckDuckGo (fallback — no API key needed) ──
try:
    from duckduckgo_search import DDGS
    _HAS_DDG = True
except ImportError:
    _HAS_DDG = False


_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


def _search_tavily(query: str, max_results: int = 5, search_depth: str = "basic") -> dict | None:
    """Search using Tavily API. Returns structured results or None on failure."""
    if not _HAS_TAVILY or not _TAVILY_API_KEY:
        return None
    try:
        client = TavilyClient(api_key=_TAVILY_API_KEY)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=True,
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "relevance_score": r.get("score", 0),
            })
        return {
            "query": query,
            "engine": "tavily",
            "answer": response.get("answer", ""),
            "results_count": len(results),
            "results": results,
        }
    except Exception:
        return None


def _search_ddg(query: str, max_results: int = 5) -> dict | None:
    """Search using DuckDuckGo. Returns structured results or None on failure."""
    if not _HAS_DDG:
        return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        return {
            "query": query,
            "engine": "duckduckgo",
            "results_count": len(formatted),
            "results": formatted,
        }
    except Exception:
        return None


def _search_ddg_news(query: str, max_results: int = 5) -> dict | None:
    """Search DuckDuckGo news. Returns structured results or None on failure."""
    if not _HAS_DDG:
        return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("body", ""),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
            })
        return {
            "query": query,
            "engine": "duckduckgo_news",
            "results_count": len(formatted),
            "results": formatted,
        }
    except Exception:
        return None


def web_search(query: str, max_results: int = 5) -> str:
    """Search the internet using Tavily (primary) or DuckDuckGo (fallback).

    Tavily provides AI-optimized search with relevance scoring and direct
    answers. Falls back to DuckDuckGo when Tavily is unavailable.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default 5).
    """
    # Try Tavily first
    result = _search_tavily(query, max_results=max_results)
    if result:
        return json.dumps(result, indent=2)

    # Fallback to DuckDuckGo
    result = _search_ddg(query, max_results=max_results)
    if result:
        return json.dumps(result, indent=2)

    return json.dumps({
        "error": "No search engine available. Install tavily-python (pip install tavily-python) "
                 "or duckduckgo-search (pip install duckduckgo-search).",
        "query": query,
    })


def web_search_news(query: str, max_results: int = 5) -> str:
    """Search for recent news articles.

    Uses Tavily with news focus if available, otherwise DuckDuckGo News.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default 5).
    """
    # Try Tavily first (with advanced depth for news)
    result = _search_tavily(query, max_results=max_results, search_depth="advanced")
    if result:
        return json.dumps(result, indent=2)

    # Fallback to DuckDuckGo News
    result = _search_ddg_news(query, max_results=max_results)
    if result:
        return json.dumps(result, indent=2)

    return json.dumps({
        "error": "No search engine available. Install tavily-python or duckduckgo-search.",
        "query": query,
    })


def web_search_deep(query: str, max_results: int = 5) -> str:
    """Deep web search — uses Tavily advanced mode for comprehensive results.

    Best for complex financial research queries that need thorough coverage.
    Falls back to standard search if Tavily advanced is unavailable.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default 5).
    """
    # Try Tavily advanced
    result = _search_tavily(query, max_results=max_results, search_depth="advanced")
    if result:
        return json.dumps(result, indent=2)

    # Fallback to standard search
    return web_search(query, max_results=max_results)
