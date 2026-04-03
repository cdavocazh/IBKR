"""Twitter tools — wraps the Twitter_new project's API tools for use by the agent.

Imports directly from /Twitter_new/tools/twitter.py. All Twitter API calls
require human-in-the-loop confirmation before execution.
"""

import sys
import os
import json
import importlib.util

from tools.config import TWITTER_ROOT

# Load Twitter tools directly by file path to avoid namespace collision
# with the local Financial_Agent/tools/ package.
_twitter_module_path = os.path.join(TWITTER_ROOT, "tools", "twitter.py")

if os.path.exists(_twitter_module_path):
    _spec = importlib.util.spec_from_file_location("twitter_api_tools", _twitter_module_path)
    _twitter_mod = importlib.util.module_from_spec(_spec)
    # Ensure the Twitter_new project root is on sys.path so *its* internal
    # imports (e.g., config, lists.json lookups) resolve correctly.
    if TWITTER_ROOT not in sys.path:
        sys.path.insert(0, TWITTER_ROOT)
    _spec.loader.exec_module(_twitter_mod)

    _search_tweets = _twitter_mod.search_tweets
    _get_tweets = _twitter_mod.get_tweets
    _get_profile = _twitter_mod.get_profile
    _get_tweet_by_id = _twitter_mod.get_tweet_by_id
    _check_watchlist = _twitter_mod.check_watchlist
    _summarize_list = _twitter_mod.summarize_list
    _get_list_tweets = _twitter_mod.get_list_tweets
    _get_list_members = _twitter_mod.get_list_members
    _show_configured_lists = _twitter_mod.show_configured_lists
    _get_credit_balance = _twitter_mod.get_credit_balance
    _refresh_list_members = _twitter_mod.refresh_list_members
    reset_api_call_count = _twitter_mod.reset_api_call_count
    get_api_call_count = _twitter_mod.get_api_call_count
    get_tweets_fetched = _twitter_mod.get_tweets_fetched
    get_profiles_fetched = _twitter_mod.get_profiles_fetched
else:
    # Twitter_new project not available — provide stubs so the agent can load
    # without crashing; Twitter tools will return errors when called.
    def _stub(*a, **kw):
        return json.dumps({"error": f"Twitter module not found at {_twitter_module_path}"})
    _search_tweets = _get_tweets = _get_profile = _get_tweet_by_id = _stub
    _check_watchlist = _summarize_list = _get_list_tweets = _stub
    _get_list_members = _show_configured_lists = _get_credit_balance = _stub
    _refresh_list_members = _stub
    reset_api_call_count = lambda: None
    get_api_call_count = lambda: 0
    get_tweets_fetched = lambda: 0
    get_profiles_fetched = lambda: 0


# ── Wrapped functions (these get registered as agent tools) ──────────

def search_tweets(query: str, count: int = 20, hours: int = 72) -> str:
    """Search Twitter/X for tweets matching a query within a time window.

    Use this for finding sentiment, analysis, signals, or opinions about
    a topic, ticker, or event. Default time window is 3 days.

    Args:
        query: Search query (e.g. '$AAPL earnings', 'Fed rate cut', 'copper sentiment').
        count: Number of results (max 40).
        hours: Time window in hours (default 72 = 3 days).
    """
    return _search_tweets(query, count, hours)


def get_tweets(username: str, count: int = 20, hours: int = 72) -> str:
    """Get the latest tweets from a specific Twitter/X user.

    Args:
        username: Twitter handle without @ symbol.
        count: Number of tweets to fetch (max 40).
        hours: Time window in hours (default 72 = 3 days).
    """
    return _get_tweets(username, count, hours)


def get_profile(username: str) -> str:
    """Get a Twitter/X user's profile info (bio, followers, etc).

    Args:
        username: Twitter handle without @ symbol.
    """
    return _get_profile(username)


def get_tweet_by_id(tweet_ids: str) -> str:
    """Fetch one or more specific tweets by their ID or URL.

    Auto-fetches X Article content if the tweet links to a long-form post.

    Args:
        tweet_ids: Comma-separated tweet IDs or full tweet URLs.
    """
    return _get_tweet_by_id(tweet_ids)


def check_watchlist(usernames: str, count: int = 5) -> str:
    """Check latest tweets from multiple users at once.

    Args:
        usernames: Comma-separated Twitter handles (without @).
        count: Tweets per user (default 5).
    """
    user_list = [u.strip() for u in usernames.split(",") if u.strip()]
    return _check_watchlist(user_list, count)


def summarize_list(list_name: str = "", list_id: str = "", hours: int = 10) -> str:
    """Fetch tweets from a Twitter/X list and group by author for summarization.

    This is the PRIMARY tool for monitoring curated Twitter lists.

    Args:
        list_name: Friendly name from lists.json (e.g. 'Fin-L1').
        list_id: Numeric Twitter list ID (overrides list_name).
        hours: Only tweets from the last N hours (default 10).
    """
    return _summarize_list(list_name, list_id, hours)


def get_list_tweets(list_id: str, hours: int = 10) -> str:
    """Get recent tweets from a Twitter/X list by its numeric ID.

    Args:
        list_id: Numeric Twitter list ID.
        hours: Only tweets from the last N hours (default 10).
    """
    return _get_list_tweets(list_id, hours)


def get_list_members(list_id: str) -> str:
    """Get all members of a Twitter/X list.

    Args:
        list_id: Numeric Twitter list ID.
    """
    return _get_list_members(list_id)


def show_configured_lists() -> str:
    """Show all Twitter lists configured in lists.json."""
    return _show_configured_lists()


def refresh_list_members(list_name: str = "", list_id: str = "") -> str:
    """Discover and cache members of a Twitter/X list.

    Finds list members via tweet search and caches them to lists.json.
    If no list specified, refreshes all configured lists.

    Args:
        list_name: Friendly name from lists.json (e.g. 'Fin-L1').
        list_id: Numeric Twitter list ID (overrides list_name).
    """
    return _refresh_list_members(list_name, list_id)


def get_twitter_credit_balance() -> str:
    """Check remaining TwitterAPI.io credits and usage stats.

    Returns credit balance and current turn API call count.
    """
    try:
        balance = _get_credit_balance()
        return json.dumps({
            "credits_remaining": balance,
            "turn_api_calls": get_api_call_count(),
            "turn_tweets_fetched": get_tweets_fetched(),
            "turn_profiles_fetched": get_profiles_fetched(),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
