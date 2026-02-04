#!/usr/bin/env python3
"""Example: Get Treasury futures prices (10-Year, 30-Year, etc.)."""

import sys
sys.path.insert(0, "..")

from ibkr import IBKRConnection, ContractFactory, MarketDataService


def main():
    conn = IBKRConnection()

    with conn.session() as ib:
        mds = MarketDataService(ib)

        # Create Treasury futures contracts
        two_year = ContractFactory.two_year_note_future()
        five_year = ContractFactory.five_year_note_future()
        ten_year = ContractFactory.ten_year_note_future()
        thirty_year = ContractFactory.thirty_year_bond_future()

        print("\n" + "=" * 60)
        print("TREASURY FUTURES PRICES")
        print("=" * 60)

        contracts = [two_year, five_year, ten_year, thirty_year]
        names = [
            "2-Year T-Note (ZT)",
            "5-Year T-Note (ZF)",
            "10-Year T-Note (ZN)",
            "30-Year T-Bond (ZB)",
        ]

        for contract, name in zip(contracts, names):
            try:
                quote = mds.get_quote(contract)

                # Treasury prices are quoted in 32nds
                # A price of 110'16 means 110 + 16/32 = 110.50
                print(f"\n{name}:")
                if quote.last:
                    # Convert decimal to 32nds notation
                    whole = int(quote.last)
                    frac = (quote.last - whole) * 32
                    print(f"  Last:   {quote.last:.4f} ({whole}'{frac:.1f})")
                else:
                    print(f"  Last:   N/A")

                print(f"  Bid:    {quote.bid:.4f}" if quote.bid else "  Bid:    N/A")
                print(f"  Ask:    {quote.ask:.4f}" if quote.ask else "  Ask:    N/A")
                print(f"  High:   {quote.high:.4f}" if quote.high else "  High:   N/A")
                print(f"  Low:    {quote.low:.4f}" if quote.low else "  Low:    N/A")
                print(f"  Volume: {quote.volume:,}" if quote.volume else "  Volume: N/A")

            except Exception as e:
                print(f"\n{name}: Error - {e}")

        # Get contract details for 10-Year
        print("\n" + "-" * 60)
        print("10-Year T-Note Contract Details:")
        details = mds.get_contract_details(ten_year)
        if details:
            print(f"  Full Name:   {details.get('longName', 'N/A')}")
            print(f"  Multiplier:  {details.get('multiplier', 'N/A')}")
            print(f"  Min Tick:    {details.get('minTick', 'N/A')}")

        print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
