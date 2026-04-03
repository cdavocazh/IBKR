#!/usr/bin/env python3
"""
Update ES data to most recent + probe earliest available data.

1. Connect to IBKR API
2. Download incremental 1-min data (from last available to now)
3. Merge with existing parquet files
4. Probe earliest available 1-min data
5. Update 5-min, hourly, daily, IV, HV data
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.connection import IBKRConnection
from ibkr.es_data import ESDataExtractor

DATA_DIR = Path(__file__).parent.parent / "data" / "es"


def get_last_timestamp(filename):
    """Get the last timestamp from an existing parquet file."""
    path = DATA_DIR / filename
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return df.index.max()


def merge_and_save(existing_file, new_df, label=""):
    """Merge new data with existing parquet, deduplicate, save."""
    path = DATA_DIR / existing_file
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        print(f"  {label}: {len(existing)} existing + {len(new_df)} new = {len(combined)} total")
    else:
        combined = new_df
        print(f"  {label}: {len(new_df)} bars (new file)")

    combined.to_parquet(path)
    print(f"  Saved: {path}")
    print(f"  Range: {combined.index.min()} to {combined.index.max()}")
    return combined


def download_chunked(ib, contract, bar_size, start_date, end_date=None, chunk_days=7):
    """Download data in chunks from start_date to end_date."""
    if end_date is None:
        end_date = datetime.now()

    all_data = []
    current_end = end_date

    while current_end > start_date:
        chunk_start = max(start_date, current_end - timedelta(days=chunk_days))
        days_in_chunk = (current_end - chunk_start).days
        if days_in_chunk < 1:
            break

        end_str = current_end.strftime("%Y%m%d %H:%M:%S")
        print(f"    Fetching {bar_size} ending {current_end.strftime('%Y-%m-%d')} ({days_in_chunk}D)...")

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f"{days_in_chunk} D",
                barSizeSetting=bar_size,
                whatToShow="TRADES",
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
                    "volume": bar.volume,
                    "average": bar.average,
                    "bar_count": bar.barCount,
                } for bar in bars])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df.set_index("datetime", inplace=True)
                all_data.append(df)
                print(f"      Got {len(df)} bars")
            else:
                print(f"      No data returned")

        except Exception as e:
            print(f"      Error: {e}")

        current_end = chunk_start
        time.sleep(11)  # Rate limit

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)
    return combined


def download_vol_data(ib, contract, what_to_show, duration="1 Y"):
    """Download implied or historical volatility daily data."""
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow=what_to_show,
            useRTH=True,
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
            return df
    except Exception as e:
        print(f"  Error downloading {what_to_show}: {e}")
    return pd.DataFrame()


def probe_earliest_available(ib, contract):
    """Probe backwards to find earliest available 1-min data."""
    print("\n=== Probing Earliest Available 1-Min Data ===")
    now = datetime.now()

    # Try progressively further back
    test_durations = [
        ("6 M", 180),
        ("1 Y", 365),
        ("18 M", 540),
        ("2 Y", 730),
    ]

    earliest = None
    for dur_str, approx_days in test_durations:
        end_date = now - timedelta(days=approx_days - 7)
        end_str = end_date.strftime("%Y%m%d %H:%M:%S")

        print(f"  Testing {dur_str} ago (ending {end_date.strftime('%Y-%m-%d')})...")
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr="7 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            if bars:
                first_bar = bars[0].date
                print(f"    Got data! Earliest bar: {first_bar}")
                earliest = first_bar
            else:
                print(f"    No data at this range")
                break
        except Exception as e:
            print(f"    Error (likely beyond limit): {e}")
            break

        time.sleep(11)

    # Also check daily data availability (goes much further back)
    print("\n  Checking daily data availability...")
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="20 Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if bars:
            print(f"  Daily data: {bars[0].date} to {bars[-1].date} ({len(bars)} bars)")
    except Exception as e:
        print(f"  Daily data error: {e}")

    return earliest


def main():
    print("=" * 60)
    print("ES DATA UPDATE")
    print("=" * 60)

    # Current data state
    last_1min = get_last_timestamp("ES_1min.parquet")
    last_5min = get_last_timestamp("ES_combined_5min.parquet")
    print(f"\nCurrent data:")
    print(f"  1-min last: {last_1min}")
    print(f"  5-min last: {last_5min}")
    print(f"  Gap to now: ~{(datetime.now(last_1min.tzinfo) - last_1min).days if last_1min else '?'} days")

    conn = IBKRConnection()
    with conn.session() as ib:
        # Get front month contract
        extractor = ESDataExtractor(ib=ib)
        contract = extractor.get_continuous_es_contract()
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            print("ERROR: Could not qualify ES contract")
            return
        contract = qualified[0]
        print(f"\nUsing contract: {contract.localSymbol}")

        # ── 1. Update 1-min data ──
        print("\n=== Updating 1-Min Data ===")
        if last_1min:
            start = last_1min.tz_localize(None) if last_1min.tzinfo else last_1min
            start = start + timedelta(minutes=1)
        else:
            start = datetime.now() - timedelta(days=365)

        days_gap = (datetime.now() - start).days
        if days_gap > 0:
            new_1min = download_chunked(ib, contract, "1 min", start, chunk_days=7)
            if not new_1min.empty:
                merge_and_save("ES_1min.parquet", new_1min, "1-min")
            else:
                print("  No new 1-min data available")
        else:
            print("  1-min data is up to date")

        time.sleep(11)

        # ── 2. Update 5-min data ──
        print("\n=== Updating 5-Min Data ===")
        if last_5min:
            start_5m = last_5min.tz_localize(None) if last_5min.tzinfo else last_5min
            start_5m = start_5m + timedelta(minutes=5)
        else:
            start_5m = datetime.now() - timedelta(days=365)

        days_gap_5m = (datetime.now() - start_5m).days
        if days_gap_5m > 0:
            new_5min = download_chunked(ib, contract, "5 mins", start_5m, chunk_days=30)
            if not new_5min.empty:
                merge_and_save("ES_combined_5min.parquet", new_5min, "5-min")
        else:
            print("  5-min data is up to date")

        time.sleep(11)

        # ── 3. Update hourly data ──
        print("\n=== Updating Hourly Data ===")
        for what_to_show, suffix in [("MIDPOINT", "midpoint"), ("BID", "bid"), ("ASK", "ask")]:
            filename = f"ES_{suffix}_hourly.parquet"
            print(f"  Downloading {what_to_show} hourly...")
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr="60 D",
                    barSizeSetting="1 hour",
                    whatToShow=what_to_show,
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = pd.DataFrame([{
                        "datetime": bar.date,
                        "open": bar.open, "high": bar.high, "low": bar.low,
                        "close": bar.close, "volume": bar.volume,
                        "average": bar.average, "bar_count": bar.barCount,
                    } for bar in bars])
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    df.set_index("datetime", inplace=True)
                    merge_and_save(filename, df, f"{suffix} hourly")
            except Exception as e:
                print(f"    Error: {e}")
            time.sleep(11)

        # ── 4. Update IV and HV daily ──
        print("\n=== Updating Volatility Data ===")
        for what_to_show, filename in [
            ("OPTION_IMPLIED_VOLATILITY", "ES_implied_volatility_daily.parquet"),
            ("HISTORICAL_VOLATILITY", "ES_historical_volatility_daily.parquet"),
        ]:
            print(f"  Downloading {what_to_show}...")
            df = download_vol_data(ib, contract, what_to_show, "1 Y")
            if not df.empty:
                merge_and_save(filename, df, what_to_show)
            time.sleep(11)

        # ── 5. Probe earliest available data ──
        earliest = probe_earliest_available(ib, contract)

        # ── 6. Summary ──
        print("\n" + "=" * 60)
        print("UPDATE COMPLETE")
        print("=" * 60)
        print("\nUpdated files:")
        for f in sorted(DATA_DIR.glob("*.parquet")):
            df = pd.read_parquet(f)
            print(f"  {f.name}: {len(df)} rows, {df.index.min()} to {df.index.max()}")

        if earliest:
            print(f"\nEarliest available 1-min data: {earliest}")
            if last_1min:
                current_start = pd.read_parquet(DATA_DIR / "ES_1min.parquet").index.min()
                print(f"Current local start: {current_start}")
                if hasattr(earliest, 'tzinfo') and earliest.tzinfo:
                    gap = (current_start.tz_localize(None) if current_start.tzinfo else current_start) - earliest.replace(tzinfo=None)
                else:
                    gap = (current_start.tz_localize(None) if current_start.tzinfo else current_start) - earliest
                print(f"Additional data available: ~{gap.days} days earlier")


if __name__ == "__main__":
    main()
