#!/usr/bin/env python3
"""Example: Get prices for multiple instrument types at once."""

import sys
sys.path.insert(0, "..")

from ibkr import IBKRConnection, ContractFactory, MarketDataService


def main():
    conn = IBKRConnection()

    with conn.session() as ib:
        mds = MarketDataService(ib)

        # Create a diverse portfolio of contracts
        contracts_info = [
            # Precious Metals
            (ContractFactory.gold_future(), "Gold (GC)", "Precious Metals"),
            (ContractFactory.silver_future(), "Silver (SI)", "Precious Metals"),

            # Treasury Futures
            (ContractFactory.ten_year_note_future(), "10-Year Note (ZN)", "Treasuries"),
            (ContractFactory.thirty_year_bond_future(), "30-Year Bond (ZB)", "Treasuries"),

            # Energy
            (ContractFactory.crude_oil_future(), "Crude Oil (CL)", "Energy"),

            # Equity Index Futures
            (ContractFactory.sp500_future(), "E-mini S&P 500 (ES)", "Indices"),
            (ContractFactory.nasdaq_future(), "E-mini Nasdaq (NQ)", "Indices"),
        ]

        print("\n" + "=" * 70)
        print("MULTI-INSTRUMENT MARKET DATA")
        print("=" * 70)

        current_category = None
        for contract, name, category in contracts_info:
            try:
                # Print category header
                if category != current_category:
                    print(f"\n--- {category} ---")
                    current_category = category

                quote = mds.get_quote(contract)

                # Format based on instrument type
                if quote.last:
                    if category == "Treasuries":
                        # Treasury format (decimal)
                        print(f"  {name:30} Last: {quote.last:>10.4f}")
                    else:
                        # Standard format
                        print(f"  {name:30} Last: ${quote.last:>10,.2f}")
                else:
                    print(f"  {name:30} Last: {'N/A':>10}")

            except Exception as e:
                print(f"  {name:30} Error: {e}")

        # Export all quotes to DataFrame
        print("\n" + "-" * 70)
        print("Getting all quotes as DataFrame...")

        contracts = [c for c, _, _ in contracts_info]
        quotes = mds.get_quotes(contracts)
        df = mds.quotes_to_dataframe(quotes)

        print(df.to_string())

        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
