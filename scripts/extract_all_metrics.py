#!/usr/bin/env python3
"""
Extract all available IBKR metrics for ES, GC, SI futures.

Metrics extracted:
1. Historical Data Types:
   - TRADES (OHLCV) - already extracted as 1min data
   - MIDPOINT - bid/ask midpoint
   - BID - bid prices
   - ASK - ask prices
   - HISTORICAL_VOLATILITY - 30-day HV
   - OPTION_IMPLIED_VOLATILITY - IV from options

2. Real-Time Snapshot:
   - Open Interest
   - Historical Volatility (real-time)
   - Implied Volatility (real-time)
   - Bid/Ask spread
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
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

REQUEST_DELAY = 11


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


def download_historical_data_type(
    ib: IB,
    contract: Future,
    what_to_show: str,
    bar_size: str = "1 day",
    days_back: int = 365,
) -> pd.DataFrame:
    """Download historical data for a specific data type."""
    print(f"  Downloading {what_to_show} ({bar_size})...", end=" ")

    all_data = []

    # For daily data, we can fetch larger chunks
    if "day" in bar_size:
        chunk_days = 365
    elif "hour" in bar_size:
        chunk_days = 30
    else:
        chunk_days = 7

    now = datetime.now()

    for i in range(0, days_back, chunk_days):
        end_date = now - timedelta(days=i)
        end_str = end_date.strftime("%Y%m%d %H:%M:%S")

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f"{min(chunk_days, days_back - i)} D",
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=1,
            )

            if bars:
                df = pd.DataFrame([{
                    "datetime": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": getattr(bar, 'volume', 0),
                    "average": getattr(bar, 'average', 0),
                    "bar_count": getattr(bar, 'barCount', 0),
                } for bar in bars])

                df["datetime"] = pd.to_datetime(df["datetime"])
                df.set_index("datetime", inplace=True)
                all_data.append(df)

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(REQUEST_DELAY)

    if not all_data:
        print("No data")
        return pd.DataFrame()

    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)

    print(f"Got {len(combined)} bars")
    return combined


def get_realtime_snapshot(ib: IB, contract: Future) -> dict:
    """Get real-time snapshot including open interest, HV, IV."""
    print(f"  Getting real-time snapshot for {contract.localSymbol}...", end=" ")

    # Request market data with generic ticks for volatility and open interest
    # 100,101 = option volume, 104 = HV, 106 = IV, 162 = future premium
    # 165 = misc stats, 221 = mark price, 411 = RT HV
    generic_ticks = "104,106,162,165,221,411"

    ticker = ib.reqMktData(contract, genericTickList=generic_ticks, snapshot=False)
    ib.sleep(5)  # Wait for data to arrive

    data = {
        "symbol": contract.symbol,
        "localSymbol": contract.localSymbol,
        "timestamp": datetime.now().isoformat(),
        "bid": ticker.bid if ticker.bid > 0 else None,
        "bidSize": ticker.bidSize if ticker.bidSize > 0 else None,
        "ask": ticker.ask if ticker.ask > 0 else None,
        "askSize": ticker.askSize if ticker.askSize > 0 else None,
        "last": ticker.last if ticker.last > 0 else None,
        "lastSize": ticker.lastSize if ticker.lastSize > 0 else None,
        "volume": int(ticker.volume) if ticker.volume > 0 else None,
        "open": ticker.open if ticker.open > 0 else None,
        "high": ticker.high if ticker.high > 0 else None,
        "low": ticker.low if ticker.low > 0 else None,
        "close": ticker.close if ticker.close > 0 else None,
        "futuresOpenInterest": ticker.futuresOpenInterest if hasattr(ticker, 'futuresOpenInterest') and ticker.futuresOpenInterest else None,
        "histVolatility": ticker.histVolatility if hasattr(ticker, 'histVolatility') and ticker.histVolatility else None,
        "impliedVolatility": ticker.impliedVolatility if hasattr(ticker, 'impliedVolatility') and ticker.impliedVolatility else None,
    }

    # Calculate spread if bid/ask available
    if data["bid"] and data["ask"]:
        data["spread"] = data["ask"] - data["bid"]
        data["midpoint"] = (data["bid"] + data["ask"]) / 2

    ib.cancelMktData(contract)

    print("Done")
    return data


def extract_all_metrics(
    ib: IB,
    symbol: str,
    data_dir: Path,
    days_back: int = 365,
) -> dict:
    """Extract all available metrics for a symbol."""
    print(f"\n{'='*60}")
    print(f"Extracting all metrics for {symbol} ({FUTURES_SPECS[symbol]['name']})")
    print(f"{'='*60}")

    contract = get_front_month_contract(ib, symbol)
    print(f"Contract: {contract.localSymbol}")

    symbol_dir = data_dir / symbol.lower()
    symbol_dir.mkdir(parents=True, exist_ok=True)

    results = {"symbol": symbol, "contract": contract.localSymbol}

    # 1. Historical Volatility (daily)
    print("\n[1/6] Historical Volatility (daily)")
    hv_df = download_historical_data_type(
        ib, contract, "HISTORICAL_VOLATILITY", "1 day", days_back
    )
    if not hv_df.empty:
        filepath = symbol_dir / f"{symbol}_historical_volatility_daily.parquet"
        hv_df.to_parquet(filepath)
        results["historical_volatility"] = {
            "rows": len(hv_df),
            "file": str(filepath),
            "date_range": f"{hv_df.index.min()} to {hv_df.index.max()}",
        }
        print(f"    Saved: {filepath}")

    # 2. Option Implied Volatility (daily)
    print("\n[2/6] Option Implied Volatility (daily)")
    iv_df = download_historical_data_type(
        ib, contract, "OPTION_IMPLIED_VOLATILITY", "1 day", days_back
    )
    if not iv_df.empty:
        filepath = symbol_dir / f"{symbol}_implied_volatility_daily.parquet"
        iv_df.to_parquet(filepath)
        results["implied_volatility"] = {
            "rows": len(iv_df),
            "file": str(filepath),
            "date_range": f"{iv_df.index.min()} to {iv_df.index.max()}",
        }
        print(f"    Saved: {filepath}")

    # 3. Midpoint data (hourly for past 30 days)
    print("\n[3/6] Midpoint data (hourly, 30 days)")
    mid_df = download_historical_data_type(
        ib, contract, "MIDPOINT", "1 hour", 30
    )
    if not mid_df.empty:
        filepath = symbol_dir / f"{symbol}_midpoint_hourly.parquet"
        mid_df.to_parquet(filepath)
        results["midpoint"] = {
            "rows": len(mid_df),
            "file": str(filepath),
            "date_range": f"{mid_df.index.min()} to {mid_df.index.max()}",
        }
        print(f"    Saved: {filepath}")

    # 4. Bid data (hourly for past 30 days)
    print("\n[4/6] Bid data (hourly, 30 days)")
    bid_df = download_historical_data_type(
        ib, contract, "BID", "1 hour", 30
    )
    if not bid_df.empty:
        filepath = symbol_dir / f"{symbol}_bid_hourly.parquet"
        bid_df.to_parquet(filepath)
        results["bid"] = {
            "rows": len(bid_df),
            "file": str(filepath),
            "date_range": f"{bid_df.index.min()} to {bid_df.index.max()}",
        }
        print(f"    Saved: {filepath}")

    # 5. Ask data (hourly for past 30 days)
    print("\n[5/6] Ask data (hourly, 30 days)")
    ask_df = download_historical_data_type(
        ib, contract, "ASK", "1 hour", 30
    )
    if not ask_df.empty:
        filepath = symbol_dir / f"{symbol}_ask_hourly.parquet"
        ask_df.to_parquet(filepath)
        results["ask"] = {
            "rows": len(ask_df),
            "file": str(filepath),
            "date_range": f"{ask_df.index.min()} to {ask_df.index.max()}",
        }
        print(f"    Saved: {filepath}")

    # 6. Real-time snapshot (open interest, HV, IV)
    print("\n[6/6] Real-time snapshot")
    snapshot = get_realtime_snapshot(ib, contract)
    results["realtime_snapshot"] = snapshot

    # Save snapshot to JSON
    import json
    snapshot_file = symbol_dir / f"{symbol}_realtime_snapshot.json"
    with open(snapshot_file, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"    Saved: {snapshot_file}")

    return results


def generate_report(all_results: dict, data_dir: Path) -> str:
    """Generate updated extraction report."""
    report_lines = [
        "=" * 70,
        "FUTURES DATA EXTRACTION REPORT (ALL METRICS)",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        "",
    ]

    for symbol in ["ES", "GC", "SI"]:
        symbol_dir = data_dir / symbol.lower()
        report_lines.append(f"\n{symbol} ({FUTURES_SPECS[symbol]['name']})")
        report_lines.append("-" * 50)

        # List all parquet files
        parquet_files = list(symbol_dir.glob("*.parquet")) if symbol_dir.exists() else []

        if not parquet_files:
            report_lines.append("  No data files found")
            continue

        for filepath in sorted(parquet_files):
            df = pd.read_parquet(filepath)

            report_lines.append(f"\n  File: {filepath.name}")
            report_lines.append(f"  Size: {filepath.stat().st_size / (1024*1024):.2f} MB")
            report_lines.append(f"  Rows: {len(df):,}")
            report_lines.append(f"  Date range: {df.index.min()} to {df.index.max()}")

            # Determine data type from filename
            if "volatility" in filepath.name.lower():
                # For volatility data, 'close' contains the volatility value
                if "close" in df.columns:
                    vol = df["close"]
                    report_lines.append(f"  Volatility Statistics:")
                    report_lines.append(f"    Latest: {vol.iloc[-1]:.4f}")
                    report_lines.append(f"    Mean: {vol.mean():.4f}")
                    report_lines.append(f"    Max: {vol.max():.4f}")
                    report_lines.append(f"    Min: {vol.min():.4f}")
            elif "1min" in filepath.name or "5min" in filepath.name:
                # Volume statistics for OHLCV data
                if "volume" in df.columns:
                    vol = df["volume"]
                    report_lines.append(f"  Volume Statistics:")
                    report_lines.append(f"    Total: {vol.sum():,.0f}")
                    report_lines.append(f"    Mean per bar: {vol.mean():,.1f}")
                    report_lines.append(f"    Max: {vol.max():,.0f}")
                if "close" in df.columns:
                    close = df["close"]
                    report_lines.append(f"  Price Statistics (Close):")
                    report_lines.append(f"    Latest: {close.iloc[-1]:,.2f}")
                    report_lines.append(f"    Mean: {close.mean():,.2f}")
            else:
                # Bid/Ask/Midpoint data
                if "close" in df.columns:
                    close = df["close"]
                    report_lines.append(f"  Price Statistics:")
                    report_lines.append(f"    Latest: {close.iloc[-1]:,.2f}")
                    report_lines.append(f"    Mean: {close.mean():,.2f}")

        # Add real-time snapshot info
        snapshot_file = symbol_dir / f"{symbol}_realtime_snapshot.json"
        if snapshot_file.exists():
            import json
            with open(snapshot_file) as f:
                snapshot = json.load(f)
            report_lines.append(f"\n  Real-Time Snapshot ({snapshot.get('timestamp', 'N/A')}):")
            if snapshot.get("last"):
                report_lines.append(f"    Last Price: {snapshot['last']:,.2f}")
            if snapshot.get("bid") and snapshot.get("ask"):
                report_lines.append(f"    Bid/Ask: {snapshot['bid']:,.2f} / {snapshot['ask']:,.2f}")
                if snapshot.get("spread"):
                    report_lines.append(f"    Spread: {snapshot['spread']:,.2f}")
            if snapshot.get("futuresOpenInterest"):
                report_lines.append(f"    Open Interest: {snapshot['futuresOpenInterest']:,}")
            if snapshot.get("histVolatility"):
                report_lines.append(f"    Historical Volatility: {snapshot['histVolatility']:.4f}")
            if snapshot.get("impliedVolatility"):
                report_lines.append(f"    Implied Volatility: {snapshot['impliedVolatility']:.4f}")
            if snapshot.get("volume"):
                report_lines.append(f"    Daily Volume: {snapshot['volume']:,}")

    report_lines.append("\n" + "=" * 70)
    report_lines.append("\nDATA TYPES EXTRACTED:")
    report_lines.append("-" * 30)
    report_lines.append("1. TRADES (1-min OHLCV) - Price and volume data")
    report_lines.append("2. HISTORICAL_VOLATILITY (daily) - 30-day historical volatility")
    report_lines.append("3. OPTION_IMPLIED_VOLATILITY (daily) - IV from options market")
    report_lines.append("4. MIDPOINT (hourly) - Bid-ask midpoint")
    report_lines.append("5. BID (hourly) - Bid prices")
    report_lines.append("6. ASK (hourly) - Ask prices")
    report_lines.append("7. Real-time snapshot - Open Interest, HV, IV, Bid/Ask")
    report_lines.append("\n" + "=" * 70)

    return "\n".join(report_lines)


def main():
    """Main entry point."""
    data_dir = Path(__file__).parent.parent / "data"
    symbols = ["ES", "GC", "SI"]

    print("Connecting to IBKR...")
    conn = IBKRConnection()
    ib = conn.connect()

    all_results = {}

    try:
        for symbol in symbols:
            results = extract_all_metrics(ib, symbol, data_dir, days_back=365)
            all_results[symbol] = results

        # Generate and save report
        print("\n" + "=" * 70)
        print("GENERATING REPORT")
        print("=" * 70)

        report = generate_report(all_results, data_dir)
        print(report)

        report_path = data_dir / "extraction_report.txt"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR")


if __name__ == "__main__":
    main()
