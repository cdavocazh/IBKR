#!/usr/bin/env python3
"""
Get real-time snapshot data for ES, GC, SI futures.

This script fetches:
- Futures Open Interest (tick 588)
- Historical Volatility (tick 411)
- Implied Volatility (tick 106)
- Bid/Ask prices and sizes
- Last trade price
- Daily volume
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from ib_insync import IB, Future

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.connection import IBKRConnection


FUTURES_SPECS = {
    "ES": {
        "symbol": "ES",
        "exchange": "CME",
        "currency": "USD",
        "name": "E-mini S&P 500",
        "month_map": {"H": 3, "M": 6, "U": 9, "Z": 12},
    },
    "GC": {
        "symbol": "GC",
        "exchange": "COMEX",
        "currency": "USD",
        "name": "Gold",
        "month_map": {"G": 2, "J": 4, "M": 6, "Q": 8, "V": 10, "Z": 12},
    },
    "SI": {
        "symbol": "SI",
        "exchange": "COMEX",
        "currency": "USD",
        "name": "Silver",
        "month_map": {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12},
        "trading_class": "SI",
    },
}


def get_front_month_contract(ib: IB, symbol: str) -> Future:
    """Get the front month contract for a futures symbol."""
    spec = FUTURES_SPECS[symbol]
    now = datetime.now()
    year = now.year
    month = now.month

    month_map = spec["month_map"]
    expiry_months = sorted(month_map.values())

    for exp_month in expiry_months:
        if month <= exp_month:
            front_month = exp_month
            front_year = year
            break
    else:
        front_month = expiry_months[0]
        front_year = year + 1

    contract_params = {
        "symbol": spec["symbol"],
        "lastTradeDateOrContractMonth": f"{front_year}{front_month:02d}",
        "exchange": spec["exchange"],
        "currency": spec["currency"],
    }

    if "trading_class" in spec:
        contract_params["tradingClass"] = spec["trading_class"]

    contract = Future(**contract_params)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        raise ValueError(f"Could not qualify contract for {symbol}")

    return qualified[0]


def get_realtime_snapshot(ib: IB, contract: Future) -> dict:
    """
    Get real-time snapshot including open interest, HV, IV.

    Legal tick types for FUT:
    - 106 = Implied Volatility
    - 165 = Misc Stats
    - 411 = Real-time Historical Volatility
    - 588 = Futures Open Interest
    """
    print(f"  Getting real-time snapshot for {contract.localSymbol}...", end=" ")

    # Use only legal tick types for futures
    # 106=IV, 411=RT HV, 588=Futures Open Interest
    generic_ticks = "106,411,588"

    ticker = ib.reqMktData(contract, genericTickList=generic_ticks, snapshot=False)
    ib.sleep(5)  # Wait for data to arrive

    data = {
        "symbol": contract.symbol,
        "localSymbol": contract.localSymbol,
        "timestamp": datetime.now().isoformat(),
        "bid": ticker.bid if ticker.bid and ticker.bid > 0 else None,
        "bidSize": ticker.bidSize if ticker.bidSize and ticker.bidSize > 0 else None,
        "ask": ticker.ask if ticker.ask and ticker.ask > 0 else None,
        "askSize": ticker.askSize if ticker.askSize and ticker.askSize > 0 else None,
        "last": ticker.last if ticker.last and ticker.last > 0 else None,
        "lastSize": ticker.lastSize if ticker.lastSize and ticker.lastSize > 0 else None,
        "volume": int(ticker.volume) if ticker.volume and ticker.volume > 0 else None,
        "open": ticker.open if ticker.open and ticker.open > 0 else None,
        "high": ticker.high if ticker.high and ticker.high > 0 else None,
        "low": ticker.low if ticker.low and ticker.low > 0 else None,
        "close": ticker.close if ticker.close and ticker.close > 0 else None,
    }

    # Get futures-specific fields
    # futuresOpenInterest comes from tick 588
    oi = getattr(ticker, 'futuresOpenInterest', None)
    if oi and str(oi) not in ['nan', 'None', '']:
        try:
            data["futuresOpenInterest"] = int(float(oi))
        except (ValueError, TypeError):
            data["futuresOpenInterest"] = None
    else:
        data["futuresOpenInterest"] = None

    # Historical volatility from tick 411
    hv = getattr(ticker, 'histVolatility', None)
    if hv and str(hv) not in ['nan', 'None', '']:
        try:
            data["histVolatility"] = float(hv)
        except (ValueError, TypeError):
            data["histVolatility"] = None
    else:
        data["histVolatility"] = None

    # Implied volatility from tick 106
    iv = getattr(ticker, 'impliedVolatility', None)
    if iv and str(iv) not in ['nan', 'None', '']:
        try:
            data["impliedVolatility"] = float(iv)
        except (ValueError, TypeError):
            data["impliedVolatility"] = None
    else:
        data["impliedVolatility"] = None

    # Calculate spread if bid/ask available
    if data["bid"] and data["ask"]:
        data["spread"] = round(data["ask"] - data["bid"], 4)
        data["midpoint"] = round((data["bid"] + data["ask"]) / 2, 4)

    ib.cancelMktData(contract)

    print("Done")
    return data


def main():
    """Main entry point."""
    data_dir = Path(__file__).parent.parent / "data"
    symbols = ["ES", "GC", "SI"]

    print("Connecting to IBKR...")
    conn = IBKRConnection()
    ib = conn.connect()

    all_snapshots = {}

    try:
        for symbol in symbols:
            print(f"\n{'='*50}")
            print(f"{symbol} ({FUTURES_SPECS[symbol]['name']})")
            print("=" * 50)

            contract = get_front_month_contract(ib, symbol)
            print(f"Contract: {contract.localSymbol}")

            snapshot = get_realtime_snapshot(ib, contract)
            all_snapshots[symbol] = snapshot

            # Save individual snapshot
            symbol_dir = data_dir / symbol.lower()
            symbol_dir.mkdir(parents=True, exist_ok=True)

            snapshot_file = symbol_dir / f"{symbol}_realtime_snapshot.json"
            with open(snapshot_file, "w") as f:
                json.dump(snapshot, f, indent=2, default=str)
            print(f"  Saved: {snapshot_file}")

            # Print summary
            print(f"\n  Summary:")
            if snapshot.get("last"):
                print(f"    Last Price: {snapshot['last']:,.2f}")
            if snapshot.get("bid") and snapshot.get("ask"):
                print(f"    Bid/Ask: {snapshot['bid']:,.2f} / {snapshot['ask']:,.2f}")
                if snapshot.get("spread"):
                    print(f"    Spread: {snapshot['spread']}")
            if snapshot.get("volume"):
                print(f"    Daily Volume: {snapshot['volume']:,}")
            if snapshot.get("futuresOpenInterest"):
                print(f"    Open Interest: {snapshot['futuresOpenInterest']:,}")
            if snapshot.get("histVolatility"):
                print(f"    Historical Volatility: {snapshot['histVolatility']:.4f}")
            if snapshot.get("impliedVolatility"):
                print(f"    Implied Volatility: {snapshot['impliedVolatility']:.4f}")

        # Save combined snapshot
        combined_file = data_dir / "all_realtime_snapshots.json"
        with open(combined_file, "w") as f:
            json.dump(all_snapshots, f, indent=2, default=str)
        print(f"\nCombined snapshots saved to: {combined_file}")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR")


if __name__ == "__main__":
    main()
