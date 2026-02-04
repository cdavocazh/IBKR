#!/usr/bin/env python3
"""Example: Get Silver and Gold futures prices."""

import sys
sys.path.insert(0, "..")

from ibkr import IBKRConnection, ContractFactory, MarketDataService


def main():
    # Create connection
    conn = IBKRConnection()

    with conn.session() as ib:
        # Create market data service
        mds = MarketDataService(ib)

        # Create contracts for Gold and Silver
        gold = ContractFactory.gold_future()
        silver = ContractFactory.silver_future()

        # Also get micro contracts (smaller position sizes)
        micro_gold = ContractFactory.micro_gold_future()
        micro_silver = ContractFactory.micro_silver_future()

        print("\n" + "=" * 60)
        print("PRECIOUS METALS FUTURES PRICES")
        print("=" * 60)

        # Get quotes for all contracts
        contracts = [gold, silver, micro_gold, micro_silver]
        names = ["Gold (GC)", "Silver (SI)", "Micro Gold (MGC)", "Micro Silver (SIL)"]

        for contract, name in zip(contracts, names):
            try:
                quote = mds.get_quote(contract)
                print(f"\n{name}:")
                print(f"  Last:   ${quote.last:,.2f}" if quote.last else "  Last:   N/A")
                print(f"  Bid:    ${quote.bid:,.2f}" if quote.bid else "  Bid:    N/A")
                print(f"  Ask:    ${quote.ask:,.2f}" if quote.ask else "  Ask:    N/A")
                print(f"  High:   ${quote.high:,.2f}" if quote.high else "  High:   N/A")
                print(f"  Low:    ${quote.low:,.2f}" if quote.low else "  Low:    N/A")
                print(f"  Volume: {quote.volume:,}" if quote.volume else "  Volume: N/A")
            except Exception as e:
                print(f"\n{name}: Error - {e}")

        # Get contract details for standard Gold
        print("\n" + "-" * 60)
        print("Gold Futures Contract Details:")
        details = mds.get_contract_details(gold)
        if details:
            print(f"  Full Name:   {details.get('longName', 'N/A')}")
            print(f"  Multiplier:  {details.get('multiplier', 'N/A')}")
            print(f"  Min Tick:    {details.get('minTick', 'N/A')}")

        print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
