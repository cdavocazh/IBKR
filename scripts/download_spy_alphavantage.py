#!/usr/bin/env python3
"""
Download SPY 1-minute intraday data from Alpha Vantage to fill ES data gaps.

Alpha Vantage free tier: 25 requests/day, ~5/minute.
Each request fetches one month of 1-min OHLCV data.

Usage:
    python scripts/download_spy_alphavantage.py --api-key YOUR_KEY
    python scripts/download_spy_alphavantage.py --api-key YOUR_KEY --months 2024-01,2024-02
"""

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent.parent


def fetch_month(api_key: str, symbol: str, month: str, interval: str = "1min") -> pd.DataFrame:
    """Fetch one month of intraday data from Alpha Vantage.

    Args:
        api_key: Alpha Vantage API key
        symbol: Ticker symbol (e.g., "SPY")
        month: YYYY-MM format (e.g., "2024-06")
        interval: Bar size (1min, 5min, 15min, 30min, 60min)

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "month": month,
        "outputsize": "full",
        "extended_hours": "true",
        "apikey": api_key,
        "datatype": "csv",
    }

    print(f"  Fetching {symbol} {interval} for {month}...", end=" ", flush=True)
    resp = requests.get(url, params=params, timeout=30)

    if resp.status_code != 200:
        print(f"HTTP {resp.status_code}")
        return pd.DataFrame()

    # Check for API error messages
    text = resp.text.strip()
    if text.startswith("{"):
        import json
        error = json.loads(text)
        if "Note" in error:
            print(f"RATE LIMITED: {error['Note'][:80]}")
            return pd.DataFrame()
        if "Error Message" in error:
            print(f"ERROR: {error['Error Message'][:80]}")
            return pd.DataFrame()
        if "Information" in error:
            print(f"INFO: {error['Information'][:80]}")
            return pd.DataFrame()

    # Parse CSV
    from io import StringIO
    df = pd.read_csv(StringIO(text))

    if df.empty or "timestamp" not in df.columns:
        print(f"EMPTY (columns: {list(df.columns)[:5]})")
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()

    print(f"{len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
    return df


def main():
    parser = argparse.ArgumentParser(description="Download SPY data from Alpha Vantage")
    parser.add_argument("--api-key", required=True, help="Alpha Vantage API key")
    parser.add_argument("--symbol", default="SPY", help="Ticker symbol (default: SPY)")
    parser.add_argument("--months", type=str, default=None,
                        help="Comma-separated months (YYYY-MM). Default: auto-detect gaps")
    parser.add_argument("--delay", type=int, default=15,
                        help="Seconds between requests (default: 15 for free tier)")
    args = parser.parse_args()

    # Determine which months to download
    if args.months:
        months = args.months.split(",")
    else:
        # Auto-detect: download 2024 full year + 2023 H2 to fill ES gap
        # ES data starts Jan 2025, so we need 2023-07 through 2024-12
        months = []
        for year in [2023, 2024]:
            start_month = 7 if year == 2023 else 1
            end_month = 12
            for m in range(start_month, end_month + 1):
                months.append(f"{year}-{m:02d}")
        # Also Jan 2025 to overlap with ES data for calibration
        months.append("2025-01")

    print(f"Downloading {args.symbol} 1-min data for {len(months)} months")
    print(f"Rate limit delay: {args.delay}s between requests")
    print(f"Estimated time: {len(months) * args.delay // 60} minutes")
    print(f"Free tier budget: {len(months)}/25 daily requests")
    print()

    if len(months) > 25:
        print("WARNING: More than 25 months requested. Free tier allows 25 requests/day.")
        print("Will download first 25 months. Run again tomorrow for the rest.")
        months = months[:25]

    all_data = []
    requests_made = 0

    for i, month in enumerate(months):
        if requests_made > 0:
            print(f"  Waiting {args.delay}s (rate limit)...")
            time.sleep(args.delay)

        df = fetch_month(args.api_key, args.symbol, month)
        requests_made += 1

        if not df.empty:
            all_data.append(df)
        else:
            print(f"  WARNING: No data for {month}")

        # Extra safety: longer pause every 5 requests
        if requests_made % 5 == 0 and i < len(months) - 1:
            print(f"  Extra pause (60s) after {requests_made} requests...")
            time.sleep(60)

    if not all_data:
        print("\nERROR: No data downloaded")
        sys.exit(1)

    # Combine all months
    combined = pd.concat(all_data).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]

    print(f"\nCombined: {len(combined)} bars")
    print(f"Date range: {combined.index[0]} to {combined.index[-1]}")
    print(f"Trading days: {combined.index.normalize().nunique()}")

    # Save as parquet
    out_path = PROJECT_ROOT / "data" / "es" / f"{args.symbol}_1min_alphavantage.parquet"
    combined.to_parquet(out_path)
    print(f"Saved to {out_path}")

    # Also create a 5-min resampled version
    df_5m = combined.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    out_5m = PROJECT_ROOT / "data" / "es" / f"{args.symbol}_5min_alphavantage.parquet"
    df_5m.to_parquet(out_5m)
    print(f"Saved 5-min: {len(df_5m)} bars to {out_5m}")

    # Summary stats
    print(f"\nMonthly bar counts:")
    monthly = combined.groupby(combined.index.to_period("M")).size()
    for period, count in monthly.items():
        print(f"  {period}: {count:,} bars")


if __name__ == "__main__":
    main()
