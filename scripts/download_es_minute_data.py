#!/usr/bin/env python3
"""
Download ES Minute-Level Data from IBKR

Downloads maximum available 1-minute or 5-minute ES data.
IBKR provides ~2 years of minute-level data.

Prerequisites:
- TWS or IB Gateway running
- API enabled (port 7497 for paper, 7496 for live)
- Market data subscription active

Usage:
    python scripts/download_es_minute_data.py
    python scripts/download_es_minute_data.py --bar-size 5min --years 2
    python scripts/download_es_minute_data.py --incremental --days 7
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.es_data import ESDataExtractor


def main():
    parser = argparse.ArgumentParser(
        description="Download ES minute-level data from IBKR"
    )
    parser.add_argument(
        "--bar-size",
        choices=["1min", "5min", "both"],
        default="5min",
        help="Bar size to download (default: 5min)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=2,
        help="Years of data to download (default: 2)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only download recent data (for updates)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days for incremental download (default: 30)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/es",
        help="Directory to store data",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("ES MINUTE-LEVEL DATA DOWNLOADER (IBKR)")
    print("=" * 60)
    print(f"\nBar size: {args.bar_size}")
    print(f"Data directory: {args.data_dir}")

    if args.incremental:
        print(f"Mode: Incremental ({args.days} days)")
    else:
        print(f"Mode: Full download ({args.years} years)")

    print("\nMake sure TWS/IB Gateway is running with API enabled!")
    print("-" * 60)

    extractor = ESDataExtractor(data_dir=args.data_dir)

    try:
        if args.incremental:
            # Incremental update
            if args.bar_size in ["1min", "both"]:
                print("\n--- Downloading 1-Minute Incremental Data ---")
                df = extractor.download_incremental(
                    bar_size="1 min",
                    days_back=args.days,
                )
                if not df.empty:
                    extractor.merge_with_existing(df, "ES_combined_1min.parquet")

            if args.bar_size in ["5min", "both"]:
                print("\n--- Downloading 5-Minute Incremental Data ---")
                df = extractor.download_incremental(
                    bar_size="5 mins",
                    days_back=args.days,
                )
                if not df.empty:
                    extractor.merge_with_existing(df, "ES_combined_5min.parquet")

        else:
            # Full download - convert years to days
            days_back = args.years * 365

            if args.bar_size in ["1min", "both"]:
                print("\n--- Downloading 1-Minute Data ---")
                print("This will take a while due to IBKR rate limits...")
                df = extractor.download_1min_data(days_back=days_back)
                if not df.empty:
                    print(f"Downloaded {len(df):,} 1-minute bars")

            if args.bar_size in ["5min", "both"]:
                print("\n--- Downloading 5-Minute Data ---")
                df = extractor.download_5min_data(days_back=days_back)
                if not df.empty:
                    print(f"Downloaded {len(df):,} 5-minute bars")

        # Show summary
        print("\n" + "=" * 60)
        print("DOWNLOAD SUMMARY")
        print("=" * 60)

        info = extractor.get_data_info()
        for filename, details in sorted(info.items()):
            print(f"\n{filename}:")
            print(f"  Rows: {details['rows']:,}")
            print(f"  Date range: {details['start']} to {details['end']}")
            print(f"  Size: {details['size_mb']:.2f} MB")

        # Estimate bars
        print("\n" + "-" * 60)
        print("EXPECTED DATA VOLUME:")
        print("  1-min bars per day: ~1,410 (23.5 hours × 60)")
        print("  5-min bars per day: ~282 (23.5 hours × 12)")
        print("  2 years of 1-min: ~730,000 bars")
        print("  2 years of 5-min: ~146,000 bars")

    except Exception as e:
        print(f"\nError: {e}")
        print("\nTroubleshooting:")
        print("  1. Is TWS/IB Gateway running?")
        print("  2. Is API enabled? (Configure → API → Settings)")
        print("  3. Is the port correct? (7497 paper, 7496 live)")
        print("  4. Do you have ES market data subscription?")
        raise

    finally:
        extractor.disconnect()


if __name__ == "__main__":
    main()
