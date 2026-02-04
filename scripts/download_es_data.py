#!/usr/bin/env python3
"""
Download Maximum ES Futures Historical Data from IBKR

This script downloads the maximum available ES data:
- 1-minute data: ~2 years (IBKR limit)
- Hourly data: ~5 years
- Daily data: ~10 years

Usage:
    python scripts/download_es_data.py --timeframe all
    python scripts/download_es_data.py --timeframe 1min
    python scripts/download_es_data.py --timeframe hourly
    python scripts/download_es_data.py --timeframe daily
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.es_data import ESDataExtractor


def main():
    parser = argparse.ArgumentParser(
        description="Download ES futures historical data from IBKR"
    )
    parser.add_argument(
        "--timeframe",
        choices=["all", "1min", "hourly", "daily"],
        default="all",
        help="Timeframe to download",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=2,
        help="Years of 1-minute data to attempt (default: 2)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/es",
        help="Directory to store data",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("ES FUTURES DATA DOWNLOADER")
    print("=" * 60)
    print(f"\nTimeframe: {args.timeframe}")
    print(f"Data directory: {args.data_dir}")
    print()

    extractor = ESDataExtractor(data_dir=args.data_dir)

    try:
        if args.timeframe in ["all", "1min"]:
            print("\n--- Downloading 1-Minute Data ---")
            print("This may take a while due to IBKR rate limits...")
            print(f"Attempting to download {args.years} years of data")
            df = extractor.download_max_1min_data(years_back=args.years)
            if not df.empty:
                print(f"Downloaded {len(df):,} 1-minute bars")

        if args.timeframe in ["all", "hourly"]:
            print("\n--- Downloading Hourly Data ---")
            df = extractor.download_hourly_data(years_back=5)
            if not df.empty:
                print(f"Downloaded {len(df):,} hourly bars")

        if args.timeframe in ["all", "daily"]:
            print("\n--- Downloading Daily Data ---")
            df = extractor.download_daily_data(years_back=10)
            if not df.empty:
                print(f"Downloaded {len(df):,} daily bars")

        # Show summary
        print("\n" + "=" * 60)
        print("DOWNLOAD SUMMARY")
        print("=" * 60)
        info = extractor.get_data_info()
        for filename, details in info.items():
            print(f"\n{filename}:")
            print(f"  Rows: {details['rows']:,}")
            print(f"  Date range: {details['start']} to {details['end']}")
            print(f"  Size: {details['size_mb']:.2f} MB")

    finally:
        extractor.disconnect()


if __name__ == "__main__":
    main()
