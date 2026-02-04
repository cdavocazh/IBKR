#!/usr/bin/env python3
"""Example: Get historical price data for futures contracts."""

import sys
sys.path.insert(0, "..")

from ibkr import IBKRConnection, ContractFactory, MarketDataService


def main():
    conn = IBKRConnection()

    with conn.session() as ib:
        mds = MarketDataService(ib)

        # Get historical data for Gold futures
        gold = ContractFactory.gold_future()

        print("\n" + "=" * 60)
        print("GOLD FUTURES - HISTORICAL DATA")
        print("=" * 60)

        # Daily bars for the last month
        print("\n--- Daily Bars (Last 1 Month) ---")
        daily_df = mds.get_historical_bars(
            gold,
            duration="1 M",
            bar_size="1 day",
            what_to_show="TRADES",
        )

        if not daily_df.empty:
            print(daily_df.tail(10).to_string())
            print(f"\nTotal bars: {len(daily_df)}")

        # Hourly bars for the last week
        print("\n--- Hourly Bars (Last 1 Week) ---")
        hourly_df = mds.get_historical_bars(
            gold,
            duration="1 W",
            bar_size="1 hour",
            what_to_show="TRADES",
        )

        if not hourly_df.empty:
            print(hourly_df.tail(10).to_string())
            print(f"\nTotal bars: {len(hourly_df)}")

        # Same for 10-Year Treasury
        print("\n" + "=" * 60)
        print("10-YEAR T-NOTE FUTURES - HISTORICAL DATA")
        print("=" * 60)

        ten_year = ContractFactory.ten_year_note_future()

        print("\n--- Daily Bars (Last 1 Month) ---")
        tn_df = mds.get_historical_bars(
            ten_year,
            duration="1 M",
            bar_size="1 day",
            what_to_show="TRADES",
        )

        if not tn_df.empty:
            print(tn_df.tail(10).to_string())

        print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
