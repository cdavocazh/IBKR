#!/usr/bin/env python3
"""Example: Stream live prices for futures contracts."""

import sys
import signal
sys.path.insert(0, "..")

from datetime import datetime
from ibkr import IBKRConnection, ContractFactory, MarketDataService


def main():
    conn = IBKRConnection()

    # Flag for graceful shutdown
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n\nShutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    with conn.session() as ib:
        mds = MarketDataService(ib)

        # Create contracts to stream
        gold = ContractFactory.gold_future()
        silver = ContractFactory.silver_future()
        ten_year = ContractFactory.ten_year_note_future()

        # Qualify contracts
        gold = mds.qualify_contract(gold)
        silver = mds.qualify_contract(silver)
        ten_year = mds.qualify_contract(ten_year)

        print("\n" + "=" * 60)
        print("LIVE PRICE STREAMING")
        print("Press Ctrl+C to stop")
        print("=" * 60 + "\n")

        # Callback for price updates
        def on_price_update(ticker, contract):
            now = datetime.now().strftime("%H:%M:%S")
            symbol = contract.symbol

            if ticker.last and ticker.last > 0:
                if symbol in ["ZN", "ZB", "ZF", "ZT"]:
                    # Treasury format
                    print(f"[{now}] {symbol:5} Last: {ticker.last:>10.4f}  "
                          f"Bid: {ticker.bid:>10.4f}  Ask: {ticker.ask:>10.4f}")
                else:
                    # Standard format
                    print(f"[{now}] {symbol:5} Last: ${ticker.last:>10,.2f}  "
                          f"Bid: ${ticker.bid:>10,.2f}  Ask: ${ticker.ask:>10,.2f}")

        # Start streaming
        tickers = []
        for contract in [gold, silver, ten_year]:
            ticker = mds.stream_quotes(contract, on_price_update, qualify=False)
            tickers.append((contract, ticker))

        print("Streaming started. Waiting for updates...\n")

        # Keep running until interrupted
        while running:
            ib.sleep(0.1)

        # Cancel all market data subscriptions
        for contract, ticker in tickers:
            ib.cancelMktData(contract)

        print("Streaming stopped.")


if __name__ == "__main__":
    main()
