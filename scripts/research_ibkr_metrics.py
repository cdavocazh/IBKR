#!/usr/bin/env python3
"""
Research available IBKR API metrics for futures contracts.

This script explores what data types and metrics are available from IBKR
for futures contracts like ES, GC, and SI.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ib_insync import IB, ContFuture, Future
from ibkr.connection import IBKRConnection


# All available whatToShow options in IBKR API
WHAT_TO_SHOW_OPTIONS = [
    "TRADES",              # Trade data (OHLCV)
    "MIDPOINT",            # Midpoint between bid and ask
    "BID",                 # Bid prices
    "ASK",                 # Ask prices
    "BID_ASK",             # Time-averaged bid-ask
    "ADJUSTED_LAST",       # Adjusted for dividends/splits (equities)
    "HISTORICAL_VOLATILITY",  # Historical volatility
    "OPTION_IMPLIED_VOLATILITY",  # IV from options
    "REBATE_RATE",         # Short stock rebate rate
    "FEE_RATE",            # Short stock fee rate
    "YIELD_BID",           # Bond yield bid
    "YIELD_ASK",           # Bond yield ask
    "YIELD_BID_ASK",       # Bond yield bid-ask
    "YIELD_LAST",          # Bond yield last
    "SCHEDULE",            # Trading schedule
]

# Available bar sizes
BAR_SIZES = [
    "1 secs", "5 secs", "10 secs", "15 secs", "30 secs",
    "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins",
    "1 hour", "2 hours", "3 hours", "4 hours", "8 hours",
    "1 day", "1 week", "1 month",
]

# Real-time tick types available
TICK_TYPES = {
    # Generic tick types that can be requested
    "100": "Option Volume (Calls)",
    "101": "Option Volume (Puts)",
    "104": "Historical Volatility",
    "105": "Average Option Volume",
    "106": "Option Implied Volatility",
    "162": "Index Future Premium",
    "165": "Misc Stats",
    "221": "Mark Price",
    "225": "Auction Info",
    "232": "Last Yield",
    "233": "Earnings",
    "236": "Shortable Shares",
    "256": "Inventory",
    "258": "Fundamental Ratios",
    "291": "Close Implied Volatility",
    "293": "Index Future Premium (Real)",
    "294": "Bond Analytic Data",
    "295": "Queue Size",
    "411": "Real-time Historical Volatility",
    "456": "Dividends",
    "460": "Reuters Fundamentals",
    "513": "IB Dividends",
    "588": "Short-term Volume",
    "595": "EMA",
    "608": "Creditman Mark Price",
    "619": "Creditman Slow Mark Price",
}


def get_contract_details(ib: IB, symbol: str, exchange: str) -> dict:
    """Get detailed contract information."""
    contract = ContFuture(symbol=symbol, exchange=exchange, currency="USD")
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        return {}

    contract = qualified[0]
    details_list = ib.reqContractDetails(contract)

    if not details_list:
        return {}

    d = details_list[0]
    return {
        "symbol": d.contract.symbol,
        "localSymbol": d.contract.localSymbol,
        "exchange": d.contract.exchange,
        "primaryExchange": d.contract.primaryExchange,
        "currency": d.contract.currency,
        "multiplier": d.contract.multiplier,
        "longName": d.longName,
        "category": d.category,
        "subcategory": d.subcategory,
        "minTick": d.minTick,
        "priceMagnifier": d.priceMagnifier,
        "tradingHours": d.tradingHours,
        "liquidHours": d.liquidHours,
        "timeZoneId": d.timeZoneId,
        "underSymbol": d.underSymbol,
        "underSecType": d.underSecType,
        "marketRuleIds": d.marketRuleIds,
    }


def test_data_type(ib: IB, contract, what_to_show: str) -> dict:
    """Test if a data type is available for a contract."""
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 hour",
            whatToShow=what_to_show,
            useRTH=False,
            formatDate=1,
            timeout=10,
        )

        if bars:
            return {
                "available": True,
                "sample_count": len(bars),
                "sample_fields": list(vars(bars[0]).keys()) if bars else [],
            }
        else:
            return {"available": False, "reason": "No data returned"}

    except Exception as e:
        return {"available": False, "reason": str(e)}


def get_real_time_data_sample(ib: IB, contract) -> dict:
    """Get a sample of real-time tick data."""
    # Request market data with generic ticks
    generic_ticks = "100,101,104,105,106,165,221,225,233,236"

    ticker = ib.reqMktData(contract, genericTickList=generic_ticks)
    ib.sleep(3)  # Wait for data

    data = {
        "bid": ticker.bid,
        "bidSize": ticker.bidSize,
        "ask": ticker.ask,
        "askSize": ticker.askSize,
        "last": ticker.last,
        "lastSize": ticker.lastSize,
        "volume": ticker.volume,
        "high": ticker.high,
        "low": ticker.low,
        "close": ticker.close,
        "open": ticker.open,
        "halted": ticker.halted,
        "histVol": ticker.histVolatility,
        "impliedVol": ticker.impliedVolatility,
        "avOptionVolume": ticker.avOptionVolume,
        "callOpenInterest": ticker.callOpenInterest,
        "putOpenInterest": ticker.putOpenInterest,
        "futuresOpenInterest": ticker.futuresOpenInterest,
    }

    ib.cancelMktData(contract)

    # Filter out None values for cleaner output
    return {k: v for k, v in data.items() if v is not None and v != float("nan")}


def main():
    """Research available IBKR metrics for futures."""
    print("=" * 70)
    print("IBKR API METRICS RESEARCH FOR FUTURES")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    contracts_to_test = [
        ("ES", "CME"),
        ("GC", "COMEX"),
        ("SI", "COMEX"),
    ]

    print("\nConnecting to IBKR...")
    conn = IBKRConnection()
    ib = conn.connect()

    results = {}

    try:
        for symbol, exchange in contracts_to_test:
            print(f"\n{'='*60}")
            print(f"Testing {symbol} on {exchange}")
            print("=" * 60)

            # Get contract
            contract = ContFuture(symbol=symbol, exchange=exchange, currency="USD")
            qualified = ib.qualifyContracts(contract)

            if not qualified:
                print(f"  Could not qualify contract for {symbol}")
                continue

            contract = qualified[0]
            print(f"  Contract: {contract.localSymbol}")

            # Get contract details
            print("\n  CONTRACT DETAILS:")
            details = get_contract_details(ib, symbol, exchange)
            for key, value in details.items():
                if value and key not in ["tradingHours", "liquidHours", "marketRuleIds"]:
                    print(f"    {key}: {value}")

            # Test historical data types
            print("\n  HISTORICAL DATA TYPES AVAILABLE:")
            data_types_available = []
            for what_to_show in ["TRADES", "MIDPOINT", "BID", "ASK", "BID_ASK",
                                  "HISTORICAL_VOLATILITY", "OPTION_IMPLIED_VOLATILITY"]:
                result = test_data_type(ib, contract, what_to_show)
                status = "✓" if result["available"] else "✗"
                print(f"    {status} {what_to_show}", end="")
                if result["available"]:
                    print(f" ({result['sample_count']} bars)")
                    data_types_available.append(what_to_show)
                else:
                    reason = result.get("reason", "Unknown")
                    if len(reason) > 50:
                        reason = reason[:50] + "..."
                    print(f" - {reason}")

            # Get real-time data sample
            print("\n  REAL-TIME DATA AVAILABLE:")
            rt_data = get_real_time_data_sample(ib, contract)
            for key, value in rt_data.items():
                print(f"    {key}: {value}")

            results[symbol] = {
                "details": details,
                "historical_types": data_types_available,
                "realtime_sample": rt_data,
            }

        # Print summary
        print("\n" + "=" * 70)
        print("SUMMARY: AVAILABLE IBKR METRICS FOR FUTURES")
        print("=" * 70)

        print("""
HISTORICAL DATA TYPES (reqHistoricalData):
------------------------------------------
1. TRADES       - OHLCV trade data (most common)
2. MIDPOINT     - Midpoint between bid/ask
3. BID          - Bid prices
4. ASK          - Ask prices
5. BID_ASK      - Time-averaged bid-ask
6. HISTORICAL_VOLATILITY - 30-day historical vol
7. OPTION_IMPLIED_VOLATILITY - IV from options market

BAR SIZES AVAILABLE:
--------------------
- Seconds: 1, 5, 10, 15, 30 secs
- Minutes: 1, 2, 3, 5, 10, 15, 20, 30 mins
- Hours: 1, 2, 3, 4, 8 hours
- Days+: 1 day, 1 week, 1 month

Note: Smaller bar sizes have shorter history limits:
- 1 sec: ~2000 bars max
- 1 min: ~1-2 years
- 5 min+: 2+ years

REAL-TIME TICK DATA (reqMktData):
---------------------------------
- Bid/Ask (price and size)
- Last trade (price and size)
- OHLC for the day
- Daily volume
- Historical volatility
- Implied volatility
- Open interest (futures and options)
- Option volume (calls/puts)

ADDITIONAL DATA ENDPOINTS:
--------------------------
1. reqFundamentalData()   - Company fundamentals (stocks only)
2. reqContractDetails()   - Contract specifications
3. reqHistoricalTicks()   - Tick-by-tick data
4. reqRealTimeBars()      - 5-second real-time bars
5. reqTickByTickData()    - Live tick-by-tick trades
6. reqMktDepth()          - Level 2 order book (DOM)
7. reqHistoricalNews()    - News headlines
8. reqHeadTimeStamp()     - Earliest available data date
9. reqHistogramData()     - Price histogram
10. reqSecDefOptParams()  - Option chain parameters
""")

        # Save results
        report_path = Path(__file__).parent.parent / "data" / "ibkr_metrics_research.txt"
        with open(report_path, "w") as f:
            f.write("IBKR API METRICS RESEARCH FOR FUTURES\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")

            for symbol, data in results.items():
                f.write(f"\n{symbol}\n")
                f.write("-" * 40 + "\n")
                f.write(f"Historical data types: {data['historical_types']}\n")
                f.write(f"Real-time data: {data['realtime_sample']}\n")

        print(f"\nResults saved to: {report_path}")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR")


if __name__ == "__main__":
    main()
