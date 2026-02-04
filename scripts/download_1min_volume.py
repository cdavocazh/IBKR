#!/usr/bin/env python3
"""
Download 1-minute OHLCV data for ES, GC, SI futures.

Volume is included in the historical data request along with OHLC prices.
Uses front-month contracts for historical data (IBKR limitation: continuous
futures don't support endDateTime for historical requests).
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from ib_insync import IB, Future

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.connection import IBKRConnection


# Contract specifications with expiry month info
FUTURES_SPECS = {
    "ES": {
        "symbol": "ES",
        "exchange": "CME",
        "currency": "USD",
        "name": "E-mini S&P 500",
        "contract_months": ["H", "M", "U", "Z"],  # Mar, Jun, Sep, Dec
        "month_map": {"H": 3, "M": 6, "U": 9, "Z": 12},
    },
    "GC": {
        "symbol": "GC",
        "exchange": "COMEX",
        "currency": "USD",
        "name": "Gold",
        "contract_months": ["G", "J", "M", "Q", "V", "Z"],
        "month_map": {"G": 2, "J": 4, "M": 6, "Q": 8, "V": 10, "Z": 12},
    },
    "SI": {
        "symbol": "SI",
        "exchange": "COMEX",
        "currency": "USD",
        "name": "Silver",
        "contract_months": ["H", "K", "N", "U", "Z"],
        "month_map": {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12},
        "trading_class": "SI",
    },
}

REQUEST_DELAY = 11  # Seconds between requests to avoid rate limiting


def get_front_month_contract(ib: IB, symbol: str) -> Future:
    """Get the front month contract for a futures symbol."""
    spec = FUTURES_SPECS[symbol]
    now = datetime.now()
    year = now.year
    month = now.month

    # Find next expiry month
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


def download_1min_data(
    ib: IB,
    symbol: str,
    days_back: int = 365,
    data_dir: Path = Path("data"),
) -> pd.DataFrame:
    """
    Download 1-minute OHLCV data for a futures symbol.

    Args:
        ib: Connected IB instance
        symbol: Futures symbol (ES, GC, SI)
        days_back: Number of days of history to fetch
        data_dir: Directory to save data

    Returns:
        DataFrame with datetime index and OHLCV columns
    """
    print(f"\n{'='*60}")
    print(f"Downloading 1-minute data for {symbol} ({FUTURES_SPECS[symbol]['name']})")
    print(f"Days back: {days_back}")
    print(f"{'='*60}")

    contract = get_front_month_contract(ib, symbol)
    print(f"Using front-month contract: {contract.localSymbol}")

    all_data = []
    chunk_days = 7  # 1-min data limited to ~7 days per request
    now = datetime.now()

    for i in range(0, days_back, chunk_days):
        end_date = now - timedelta(days=i)
        end_str = end_date.strftime("%Y%m%d %H:%M:%S")

        print(f"  Fetching chunk ending {end_date.strftime('%Y-%m-%d')}...", end=" ")

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f"{chunk_days} D",
                barSizeSetting="1 min",
                whatToShow="TRADES",  # Includes volume
                useRTH=False,  # Include extended hours
                formatDate=1,
            )

            if bars:
                df = pd.DataFrame([{
                    "datetime": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "average": bar.average,
                    "bar_count": bar.barCount,
                } for bar in bars])

                df["datetime"] = pd.to_datetime(df["datetime"])
                df.set_index("datetime", inplace=True)
                all_data.append(df)
                print(f"Got {len(df)} bars")
            else:
                print("No data")

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(REQUEST_DELAY)

    if not all_data:
        print(f"No data retrieved for {symbol}")
        return pd.DataFrame()

    # Combine and deduplicate
    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)

    # Save to parquet
    symbol_dir = data_dir / symbol.lower()
    symbol_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{symbol}_1min.parquet"
    filepath = symbol_dir / filename
    combined.to_parquet(filepath)

    print(f"\nSaved: {filepath}")
    print(f"Total bars: {len(combined):,}")
    print(f"Date range: {combined.index.min()} to {combined.index.max()}")
    print(f"Volume range: {combined['volume'].min():,.0f} to {combined['volume'].max():,.0f}")
    print(f"Total volume: {combined['volume'].sum():,.0f}")

    return combined


def generate_report(data_dir: Path = Path("data")) -> str:
    """Generate a report on all extracted data."""
    report_lines = [
        "=" * 70,
        "FUTURES DATA EXTRACTION REPORT",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        "",
    ]

    for symbol in ["ES", "GC", "SI"]:
        symbol_dir = data_dir / symbol.lower()
        report_lines.append(f"\n{symbol} ({FUTURES_SPECS[symbol]['name']})")
        report_lines.append("-" * 40)

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

            # Calculate days of data
            days = (df.index.max() - df.index.min()).days
            report_lines.append(f"  Days covered: {days}")

            # Column info
            report_lines.append(f"  Columns: {list(df.columns)}")

            # Volume statistics
            if "volume" in df.columns:
                vol = df["volume"]
                report_lines.append(f"\n  Volume Statistics:")
                report_lines.append(f"    Total: {vol.sum():,.0f}")
                report_lines.append(f"    Mean per bar: {vol.mean():,.1f}")
                report_lines.append(f"    Max: {vol.max():,.0f}")
                report_lines.append(f"    Min: {vol.min():,.0f}")
                report_lines.append(f"    Std Dev: {vol.std():,.1f}")

                # Percentage of zero-volume bars
                zero_pct = (vol == 0).sum() / len(vol) * 100
                report_lines.append(f"    Zero-volume bars: {zero_pct:.1f}%")

            # Price statistics
            if "close" in df.columns:
                close = df["close"]
                report_lines.append(f"\n  Price Statistics (Close):")
                report_lines.append(f"    Latest: {close.iloc[-1]:,.2f}")
                report_lines.append(f"    Mean: {close.mean():,.2f}")
                report_lines.append(f"    Max: {close.max():,.2f}")
                report_lines.append(f"    Min: {close.min():,.2f}")

    report_lines.append("\n" + "=" * 70)

    return "\n".join(report_lines)


def main():
    """Main entry point."""
    data_dir = Path(__file__).parent.parent / "data"
    symbols = ["ES", "GC", "SI"]
    days_back = 365  # Max ~1-2 years for 1-min data

    print("Connecting to IBKR...")
    conn = IBKRConnection()
    ib = conn.connect()

    try:
        results = {}
        for symbol in symbols:
            df = download_1min_data(ib, symbol, days_back=days_back, data_dir=data_dir)
            results[symbol] = df

        # Generate and save report
        print("\n" + "=" * 70)
        print("GENERATING REPORT")
        print("=" * 70)

        report = generate_report(data_dir)
        print(report)

        # Save report to file
        report_path = data_dir / "extraction_report.txt"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR")


if __name__ == "__main__":
    main()
