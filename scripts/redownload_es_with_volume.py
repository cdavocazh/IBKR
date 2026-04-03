#!/usr/bin/env python3
"""
Re-download ES data with proper TRADES volume.

Problem: The existing ES data was downloaded using a continuous contract,
which returns zero volume for expired contract periods. This script downloads
data per-contract (quarterly) and stitches them together, preserving volume.

Downloads:
  1. 5-min data per contract (Jan 2025 - now) → ES_combined_5min.parquet
  2. 1-min data per contract (Jan 2025 - now) → ES_1min.parquet
  3. Daily data (Aug 2023 - now) → ES_daily.parquet

Usage:
    python scripts/redownload_es_with_volume.py
    python scripts/redownload_es_with_volume.py --5min-only
    python scripts/redownload_es_with_volume.py --daily-only
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

try:
    from ib_async import IB, Future
except ImportError:
    from ib_insync import IB, Future

from dotenv import load_dotenv
import os

load_dotenv()

# ── Config ──
DATA_DIR = Path(__file__).parent.parent / "data" / "es"
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "4001"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "10"))
REQUEST_DELAY = 11  # seconds between requests (IBKR rate limit)

# ES quarterly months: H=Mar, M=Jun, U=Sep, Z=Dec
QUARTER_MONTHS = {"H": 3, "M": 6, "U": 9, "Z": 12}


def get_es_contracts(start_year, end_year):
    """Generate all ES quarterly contracts between start and end year."""
    contracts = []
    now = datetime.now()
    for year in range(start_year, end_year + 1):
        for code, month in QUARTER_MONTHS.items():
            expiry = f"{year}{month:02d}"
            contract_date = datetime(year, month, 1)
            # Skip contracts more than 3 months in the future
            if contract_date > now + timedelta(days=90):
                continue
            c = Future("ES", expiry, "CME", multiplier=50)
            c.includeExpired = True  # Need this for historical contracts
            contracts.append((c, f"ES{year}{code}"))
    return contracts


def download_bars(ib, contract, bar_size, days_back, chunk_days):
    """Download historical bars in chunks for a single contract."""
    all_data = []
    now = datetime.now()
    request_count = 0

    for i in range(0, days_back, chunk_days):
        end_date = now - timedelta(days=i)
        end_str = end_date.strftime("%Y%m%d %H:%M:%S")

        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_str,
                durationStr=f"{chunk_days} D",
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

            request_count += 1

        except Exception as e:
            print(f"    Error at chunk ending {end_date.strftime('%Y-%m-%d')}: {e}")

        time.sleep(REQUEST_DELAY)

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)
    return combined


def download_5min_per_contract(ib, days_back=450):
    """Download 5-min data per quarterly contract to preserve volume."""
    print("\n" + "=" * 60)
    print("DOWNLOADING 5-MIN DATA PER CONTRACT (WITH VOLUME)")
    print("=" * 60)

    now = datetime.now()
    start_year = now.year - 1  # Go back ~1.5 years
    contracts = get_es_contracts(start_year, now.year + 1)

    all_data = []
    for contract, label in contracts:
        try:
            qualified = ib.qualifyContracts(contract)
        except Exception as e:
            print(f"  {label}: Qualify error: {e}, skipping")
            continue

        if not qualified:
            print(f"  {label}: Could not qualify, skipping")
            continue

        contract = qualified[0]
        print(f"\n  Downloading {label} ({contract.localSymbol})...")

        df = download_bars(ib, contract, "5 mins", days_back=days_back, chunk_days=30)

        if not df.empty:
            vol_zero = (df["volume"] == 0).sum()
            vol_good = (df["volume"] > 0).sum()
            print(f"    Got {len(df)} bars, {vol_good} with volume ({100*vol_good/len(df):.0f}%)")

            # Save individual contract
            individual_path = DATA_DIR / f"{label}_5min.parquet"
            df.to_parquet(individual_path)
            print(f"    Saved: {individual_path}")

            all_data.append(df)
        else:
            print(f"    No data returned")

    if not all_data:
        print("No data downloaded!")
        return pd.DataFrame()

    # Combine: for overlapping periods, prefer the contract with more volume
    combined = pd.concat(all_data)

    # For duplicate timestamps, keep the row with higher volume
    combined = combined.sort_values("volume", ascending=False)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)

    # Backup old file
    old_path = DATA_DIR / "ES_combined_5min.parquet"
    if old_path.exists():
        backup = DATA_DIR / "ES_combined_5min_backup_novol.parquet"
        old_path.rename(backup)
        print(f"\n  Backed up old file to {backup}")

    combined.to_parquet(old_path)

    vol_zero = (combined["volume"] == 0).sum()
    vol_good = (combined["volume"] > 0).sum()
    print(f"\n  COMBINED 5-MIN DATA:")
    print(f"    Total bars: {len(combined)}")
    print(f"    Date range: {combined.index.min()} to {combined.index.max()}")
    print(f"    Volume > 0: {vol_good} ({100*vol_good/len(combined):.1f}%)")
    print(f"    Volume = 0: {vol_zero} ({100*vol_zero/len(combined):.1f}%)")
    print(f"    Saved: {old_path}")

    return combined


def download_1min_per_contract(ib, days_back=420):
    """Download 1-min data per quarterly contract to preserve volume."""
    print("\n" + "=" * 60)
    print("DOWNLOADING 1-MIN DATA PER CONTRACT (WITH VOLUME)")
    print("=" * 60)

    now = datetime.now()
    start_year = now.year - 1
    contracts = get_es_contracts(start_year, now.year + 1)

    all_data = []
    for contract, label in contracts:
        try:
            qualified = ib.qualifyContracts(contract)
        except Exception as e:
            print(f"  {label}: Qualify error: {e}, skipping")
            continue

        if not qualified:
            print(f"  {label}: Could not qualify, skipping")
            continue

        contract = qualified[0]
        print(f"\n  Downloading {label} ({contract.localSymbol})...")

        df = download_bars(ib, contract, "1 min", days_back=days_back, chunk_days=7)

        if not df.empty:
            vol_good = (df["volume"] > 0).sum()
            print(f"    Got {len(df)} bars, {vol_good} with volume ({100*vol_good/len(df):.0f}%)")

            individual_path = DATA_DIR / f"{label}_1min.parquet"
            df.to_parquet(individual_path)
            print(f"    Saved: {individual_path}")

            all_data.append(df)
        else:
            print(f"    No data returned")

    if not all_data:
        print("No data downloaded!")
        return pd.DataFrame()

    combined = pd.concat(all_data)
    combined = combined.sort_values("volume", ascending=False)
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.sort_index(inplace=True)

    old_path = DATA_DIR / "ES_1min.parquet"
    if old_path.exists():
        backup = DATA_DIR / "ES_1min_backup_novol.parquet"
        old_path.rename(backup)
        print(f"\n  Backed up old file to {backup}")

    combined.to_parquet(old_path)

    vol_good = (combined["volume"] > 0).sum()
    vol_zero = (combined["volume"] == 0).sum()
    print(f"\n  COMBINED 1-MIN DATA:")
    print(f"    Total bars: {len(combined)}")
    print(f"    Date range: {combined.index.min()} to {combined.index.max()}")
    print(f"    Volume > 0: {vol_good} ({100*vol_good/len(combined):.1f}%)")
    print(f"    Volume = 0: {vol_zero} ({100*vol_zero/len(combined):.1f}%)")
    print(f"    Saved: {old_path}")

    return combined


def download_daily(ib, years_back=3):
    """Download daily ES data using continuous contract (volume works for daily)."""
    print("\n" + "=" * 60)
    print("DOWNLOADING DAILY DATA")
    print("=" * 60)

    contract = Future("ES", "", "CME", multiplier=50)
    contract.includeExpired = False
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        print("Could not qualify continuous ES contract")
        return pd.DataFrame()

    contract = qualified[0]
    print(f"  Contract: {contract.localSymbol}")

    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=f"{years_back} Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )
    except Exception as e:
        print(f"  Error: {e}")
        return pd.DataFrame()

    if not bars:
        print("  No bars returned")
        return pd.DataFrame()

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

    old_path = DATA_DIR / "ES_daily.parquet"
    if old_path.exists():
        backup = DATA_DIR / "ES_daily_backup.parquet"
        old_path.rename(backup)
        print(f"  Backed up old file to {backup}")

    df.to_parquet(old_path)

    vol_good = (df["volume"] > 0).sum()
    print(f"\n  DAILY DATA:")
    print(f"    Total bars: {len(df)}")
    print(f"    Date range: {df.index.min()} to {df.index.max()}")
    print(f"    Volume > 0: {vol_good} ({100*vol_good/len(df):.1f}%)")
    print(f"    Saved: {old_path}")

    return df


def main():
    parser = argparse.ArgumentParser(description="Re-download ES data with TRADES volume")
    parser.add_argument("--5min-only", action="store_true", help="Only download 5-min data")
    parser.add_argument("--1min-only", action="store_true", help="Only download 1-min data")
    parser.add_argument("--daily-only", action="store_true", help="Only download daily data")
    args = parser.parse_args()

    do_all = not (args.__dict__.get("5min_only") or args.__dict__.get("1min_only") or args.daily_only)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Connecting to IBKR Gateway...")
    print(f"  Host: {IBKR_HOST}:{IBKR_PORT}, ClientID: {IBKR_CLIENT_ID}")

    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, readonly=True)
    print(f"  Connected: {ib.isConnected()}")

    try:
        if do_all or args.__dict__.get("5min_only"):
            download_5min_per_contract(ib, days_back=450)

        if do_all or args.__dict__.get("1min_only"):
            download_1min_per_contract(ib, days_back=420)

        if do_all or args.daily_only:
            download_daily(ib, years_back=3)

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR.")

    # Print final summary
    print("\n" + "=" * 60)
    print("DOWNLOAD COMPLETE — SUMMARY")
    print("=" * 60)
    for f in sorted(DATA_DIR.glob("ES_*.parquet")):
        if "backup" in f.name:
            continue
        df = pd.read_parquet(f)
        vol_good = (df["volume"] > 0).sum() if "volume" in df.columns else "N/A"
        print(f"  {f.name}: {len(df)} bars, {vol_good} with volume, {df.index.min()} to {df.index.max()}")


if __name__ == "__main__":
    main()
