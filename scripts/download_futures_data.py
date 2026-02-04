#!/usr/bin/env python3
"""
Download Futures Data from IBKR

Supports multiple futures:
- ES (E-mini S&P 500)
- GC (Gold)
- SI (Silver)

Usage:
    python scripts/download_futures_data.py --symbol ES --bar-size 5min
    python scripts/download_futures_data.py --symbol GC --bar-size 1min --days 180
    python scripts/download_futures_data.py --symbol SI --bar-size 5min
    python scripts/download_futures_data.py --all --bar-size 5min
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.futures_data import FuturesDataExtractor, FUTURES_SPECS, download_all_futures


def main():
    parser = argparse.ArgumentParser(
        description="Download futures data from IBKR"
    )
    parser.add_argument(
        "--symbol",
        choices=list(FUTURES_SPECS.keys()),
        help="Futures symbol to download",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all supported futures (ES, GC, SI)",
    )
    parser.add_argument(
        "--bar-size",
        choices=["1min", "5min", "1hour", "1day"],
        default="5min",
        help="Bar size to download (default: 5min)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Days of data to download (default: 365)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Base directory to store data",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=2,
        help="IBKR client ID (use different IDs for concurrent connections)",
    )

    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Must specify --symbol or --all")

    # Convert bar size to IBKR format
    bar_size_map = {
        "1min": "1 min",
        "5min": "5 mins",
        "1hour": "1 hour",
        "1day": "1 day",
    }
    bar_size = bar_size_map[args.bar_size]

    print("=" * 60)
    print("FUTURES DATA DOWNLOADER (IBKR)")
    print("=" * 60)
    print(f"\nBar size: {args.bar_size}")
    print(f"Days: {args.days}")
    print(f"Data directory: {args.data_dir}")
    print("\nMake sure IB Gateway is running with API enabled!")
    print("-" * 60)

    if args.all:
        # Download all futures
        symbols = list(FUTURES_SPECS.keys())
        print(f"\nDownloading all futures: {', '.join(symbols)}")

        results = download_all_futures(
            symbols=symbols,
            bar_size=bar_size,
            days_back=args.days,
        )

        # Summary
        print("\n" + "=" * 60)
        print("DOWNLOAD SUMMARY")
        print("=" * 60)
        for symbol, df in results.items():
            if not df.empty:
                print(f"\n{symbol} ({FUTURES_SPECS[symbol]['name']}):")
                print(f"  Bars: {len(df):,}")
                print(f"  Range: {df.index.min()} to {df.index.max()}")
            else:
                print(f"\n{symbol}: No data downloaded")

    else:
        # Download single symbol
        symbol = args.symbol
        print(f"\nDownloading {symbol} ({FUTURES_SPECS[symbol]['name']})")

        extractor = FuturesDataExtractor(
            symbol=symbol,
            data_dir=args.data_dir,
            client_id=args.client_id,
        )

        try:
            df = extractor.download_data(
                bar_size=bar_size,
                days_back=args.days,
            )

            if not df.empty:
                print(f"\nDownloaded {len(df):,} bars")

            # Show all data files
            print("\n" + "=" * 60)
            print("DATA FILES")
            print("=" * 60)
            info = extractor.get_data_info()
            for filename, details in sorted(info.items()):
                print(f"\n{filename}:")
                print(f"  Rows: {details['rows']:,}")
                print(f"  Range: {details['start']} to {details['end']}")
                print(f"  Size: {details['size_mb']:.2f} MB")

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

        finally:
            extractor.disconnect()


if __name__ == "__main__":
    main()
