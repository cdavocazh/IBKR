"""
ES Futures Data Extraction Module

IBKR Historical Data Limits:
- 1 min bars: Max 1-2 years (depending on contract)
- Request pacing: 60 requests per 10 minutes for historical data
- Each request can fetch up to ~1 year of 1-min data
- Must request by contract expiry (ES is quarterly: H, M, U, Z)

Strategy:
- Download data for each quarterly contract
- Stitch together continuous contract data
- Handle contract rolls (typically 1 week before expiry)
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from ib_insync import IB, Future, Contract

from .connection import IBKRConnection


class ESDataExtractor:
    """Extract maximum historical ES futures data from IBKR."""

    # ES contract months: H(Mar), M(Jun), U(Sep), Z(Dec)
    CONTRACT_MONTHS = ["H", "M", "U", "Z"]
    MONTH_MAP = {"H": 3, "M": 6, "U": 9, "Z": 12}

    # IBKR limits
    MAX_REQUESTS_PER_10_MIN = 60
    REQUEST_DELAY_SECONDS = 11  # Stay under rate limit

    def __init__(
        self,
        ib: Optional[IB] = None,
        data_dir: str = "data/es",
    ):
        """
        Initialize ES data extractor.

        Args:
            ib: Connected IB instance. If None, will create connection.
            data_dir: Directory to store downloaded data.
        """
        self.ib = ib
        self.owns_connection = ib is None
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> IB:
        """Connect to IBKR if not already connected."""
        if self.ib is None or not self.ib.isConnected():
            conn = IBKRConnection()
            self.ib = conn.connect()
            self.owns_connection = True
        return self.ib

    def disconnect(self):
        """Disconnect if we own the connection."""
        if self.owns_connection and self.ib and self.ib.isConnected():
            self.ib.disconnect()

    def get_es_contract(self, year: int, month_code: str) -> Future:
        """
        Create ES futures contract for specific expiry.

        Args:
            year: Contract year (e.g., 2024)
            month_code: Contract month code (H, M, U, Z)

        Returns:
            Future contract object
        """
        month = self.MONTH_MAP[month_code]
        expiry = f"{year}{month:02d}"

        return Future(
            symbol="ES",
            lastTradeDateOrContractMonth=expiry,
            exchange="CME",
            currency="USD",
        )

    def get_continuous_es_contract(self) -> Future:
        """Get continuous ES contract (front month)."""
        # For ES, need to specify the front month explicitly
        # Calculate current front month
        now = datetime.now()
        year = now.year
        month = now.month

        # Find next expiry month (H=3, M=6, U=9, Z=12)
        expiry_months = [3, 6, 9, 12]
        for exp_month in expiry_months:
            if month <= exp_month:
                front_month = exp_month
                front_year = year
                break
        else:
            front_month = 3  # Next year March
            front_year = year + 1

        return Future(
            symbol="ES",
            lastTradeDateOrContractMonth=f"{front_year}{front_month:02d}",
            exchange="CME",
            currency="USD",
        )

    def _get_contract_expiries(
        self,
        start_year: int,
        end_year: int,
    ) -> list[tuple[int, str]]:
        """Generate list of contract expiries between years."""
        expiries = []
        for year in range(start_year, end_year + 1):
            for month in self.CONTRACT_MONTHS:
                expiries.append((year, month))
        return expiries

    def download_contract_data(
        self,
        contract: Contract,
        end_date: str = "",
        duration: str = "1 Y",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        use_rth: bool = False,
    ) -> pd.DataFrame:
        """
        Download historical data for a single contract.

        Args:
            contract: The futures contract
            end_date: End date (empty string = now)
            duration: Duration string (e.g., "1 Y", "6 M", "30 D")
            bar_size: Bar size ("1 min", "5 mins", "1 hour", "1 day")
            what_to_show: Data type ("TRADES", "MIDPOINT", "BID", "ASK")
            use_rth: Regular trading hours only

        Returns:
            DataFrame with OHLCV data
        """
        self.connect()

        # Qualify the contract
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            print(f"Could not qualify contract: {contract}")
            return pd.DataFrame()

        contract = qualified[0]
        print(f"Downloading {contract.localSymbol}...")

        try:
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime=end_date,
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
            )

            if not bars:
                print(f"No data returned for {contract.localSymbol}")
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
            df["contract"] = contract.localSymbol

            print(f"Downloaded {len(df)} bars for {contract.localSymbol}")
            return df

        except Exception as e:
            print(f"Error downloading {contract.localSymbol}: {e}")
            return pd.DataFrame()

    def download_max_1min_data(
        self,
        years_back: int = 2,
        save_individual: bool = True,
    ) -> pd.DataFrame:
        """
        Download maximum available 1-minute ES data.

        IBKR allows ~1-2 years of 1-min data per contract.
        This method downloads all available quarterly contracts
        and stitches them together.

        Args:
            years_back: How many years back to attempt (default 2)
            save_individual: Save individual contract files

        Returns:
            Combined DataFrame with all data
        """
        self.connect()

        now = datetime.now()
        start_year = now.year - years_back
        end_year = now.year + 1  # Include next year's contracts

        expiries = self._get_contract_expiries(start_year, end_year)
        all_data = []
        request_count = 0

        for year, month_code in expiries:
            # Skip future contracts that haven't started trading
            contract_month = self.MONTH_MAP[month_code]
            contract_date = datetime(year, contract_month, 1)

            # Don't request data for contracts more than 3 months in future
            if contract_date > now + timedelta(days=90):
                continue

            contract = self.get_es_contract(year, month_code)

            # Rate limiting
            if request_count > 0 and request_count % 5 == 0:
                print(f"Rate limiting: waiting {self.REQUEST_DELAY_SECONDS}s...")
                time.sleep(self.REQUEST_DELAY_SECONDS)

            df = self.download_contract_data(
                contract,
                duration="1 Y",
                bar_size="1 min",
            )

            if not df.empty:
                all_data.append(df)

                if save_individual:
                    filename = f"ES_{year}{month_code}_1min.parquet"
                    filepath = self.data_dir / filename
                    df.to_parquet(filepath)
                    print(f"Saved {filepath}")

            request_count += 1

        if not all_data:
            return pd.DataFrame()

        # Combine all data
        combined = pd.concat(all_data)
        combined.sort_index(inplace=True)

        # Save combined data
        combined_path = self.data_dir / "ES_combined_1min.parquet"
        combined.to_parquet(combined_path)
        print(f"\nSaved combined data: {combined_path}")
        print(f"Total bars: {len(combined)}")
        print(f"Date range: {combined.index.min()} to {combined.index.max()}")

        return combined

    def download_daily_data(
        self,
        years_back: int = 10,
    ) -> pd.DataFrame:
        """
        Download daily ES data (can go back further than 1-min).

        Args:
            years_back: Years of daily data to fetch

        Returns:
            DataFrame with daily OHLCV
        """
        self.connect()

        # Use continuous contract for daily data
        contract = self.get_continuous_es_contract()

        df = self.download_contract_data(
            contract,
            duration=f"{years_back} Y",
            bar_size="1 day",
        )

        if not df.empty:
            filepath = self.data_dir / "ES_daily.parquet"
            df.to_parquet(filepath)
            print(f"Saved daily data: {filepath}")

        return df

    def download_hourly_data(
        self,
        years_back: int = 5,
    ) -> pd.DataFrame:
        """
        Download hourly ES data.

        Args:
            years_back: Years of hourly data to fetch

        Returns:
            DataFrame with hourly OHLCV
        """
        self.connect()

        contract = self.get_continuous_es_contract()

        df = self.download_contract_data(
            contract,
            duration=f"{years_back} Y",
            bar_size="1 hour",
        )

        if not df.empty:
            filepath = self.data_dir / "ES_hourly.parquet"
            df.to_parquet(filepath)
            print(f"Saved hourly data: {filepath}")

        return df

    def create_continuous_contract(
        self,
        df: pd.DataFrame,
        roll_days_before_expiry: int = 7,
    ) -> pd.DataFrame:
        """
        Create continuous contract from individual contract data.

        Uses front-month contract and rolls to next contract
        N days before expiry.

        Args:
            df: DataFrame with 'contract' column identifying each contract
            roll_days_before_expiry: Days before expiry to roll

        Returns:
            DataFrame with continuous front-month prices
        """
        if "contract" not in df.columns:
            return df

        # Parse contract expiry from localSymbol (e.g., "ESH4" -> March 2024)
        def get_expiry_date(symbol: str) -> datetime:
            month_code = symbol[2]
            year_digit = int(symbol[3])
            month = self.MONTH_MAP.get(month_code, 3)

            # Determine full year (assume 2020s)
            year = 2020 + year_digit
            if year < 2020:
                year += 10

            # Third Friday of expiry month (approximate)
            return datetime(year, month, 15)

        df = df.copy()
        df["expiry"] = df["contract"].apply(get_expiry_date)
        df["days_to_expiry"] = (df["expiry"] - df.index).dt.days

        # Keep only front month (roll when days_to_expiry <= roll_days_before_expiry)
        # This is simplified - production would need more sophisticated logic
        continuous = df[df["days_to_expiry"] > roll_days_before_expiry].copy()

        # Remove duplicate timestamps (keep front month)
        continuous = continuous[~continuous.index.duplicated(keep="first")]

        return continuous

    def load_data(self, filename: str = "ES_combined_1min.parquet") -> pd.DataFrame:
        """Load previously downloaded data."""
        filepath = self.data_dir / filename
        if filepath.exists():
            return pd.read_parquet(filepath)
        raise FileNotFoundError(f"Data file not found: {filepath}")

    def get_data_info(self) -> dict:
        """Get information about downloaded data files."""
        info = {}
        for filepath in self.data_dir.glob("*.parquet"):
            df = pd.read_parquet(filepath)
            info[filepath.name] = {
                "rows": len(df),
                "start": df.index.min(),
                "end": df.index.max(),
                "columns": list(df.columns),
                "size_mb": filepath.stat().st_size / (1024 * 1024),
            }
        return info

    def download_5min_data(
        self,
        days_back: int = 365,
    ) -> pd.DataFrame:
        """
        Download 5-minute ES data using continuous contract.

        Uses chunked requests to get maximum historical data.
        IBKR limits: ~2 years for 5-min data.

        Args:
            days_back: Days of data to fetch (max ~730)

        Returns:
            DataFrame with 5-min OHLCV data
        """
        self.connect()

        contract = self.get_continuous_es_contract()

        # Qualify the contract first
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            print("Could not qualify continuous ES contract")
            return pd.DataFrame()

        contract = qualified[0]
        print(f"Downloading 5-min data for {contract.localSymbol}...")

        all_data = []
        chunk_days = 30  # Download in 30-day chunks
        now = datetime.now()

        for i in range(0, days_back, chunk_days):
            end_date = now - timedelta(days=i)
            end_str = end_date.strftime("%Y%m%d %H:%M:%S")

            print(f"  Fetching chunk ending {end_date.strftime('%Y-%m-%d')}...")

            try:
                bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime=end_str,
                    durationStr=f"{chunk_days} D",
                    barSizeSetting="5 mins",
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
                    print(f"    Got {len(df)} bars")

            except Exception as e:
                print(f"    Error: {e}")

            # Rate limiting
            time.sleep(self.REQUEST_DELAY_SECONDS)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined.sort_index(inplace=True)

        combined_path = self.data_dir / "ES_combined_5min.parquet"
        combined.to_parquet(combined_path)
        print(f"\nSaved: {combined_path}")
        print(f"Total bars: {len(combined)}")
        print(f"Date range: {combined.index.min()} to {combined.index.max()}")

        return combined

    def download_1min_data(
        self,
        days_back: int = 365,
    ) -> pd.DataFrame:
        """
        Download 1-minute ES data using continuous contract.

        Uses chunked requests. IBKR limits: ~1-2 years for 1-min data.

        Args:
            days_back: Days of data to fetch (max ~365-730)

        Returns:
            DataFrame with 1-min OHLCV data
        """
        self.connect()

        contract = self.get_continuous_es_contract()

        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            print("Could not qualify continuous ES contract")
            return pd.DataFrame()

        contract = qualified[0]
        print(f"Downloading 1-min data for {contract.localSymbol}...")

        all_data = []
        chunk_days = 7  # 1-min data: smaller chunks
        now = datetime.now()

        for i in range(0, days_back, chunk_days):
            end_date = now - timedelta(days=i)
            end_str = end_date.strftime("%Y%m%d %H:%M:%S")

            print(f"  Fetching chunk ending {end_date.strftime('%Y-%m-%d')}...")

            try:
                bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime=end_str,
                    durationStr=f"{chunk_days} D",
                    barSizeSetting="1 min",
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
                    print(f"    Got {len(df)} bars")

            except Exception as e:
                print(f"    Error: {e}")

            time.sleep(self.REQUEST_DELAY_SECONDS)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined.sort_index(inplace=True)

        combined_path = self.data_dir / "ES_combined_1min.parquet"
        combined.to_parquet(combined_path)
        print(f"\nSaved: {combined_path}")
        print(f"Total bars: {len(combined)}")
        print(f"Date range: {combined.index.min()} to {combined.index.max()}")

        return combined

    def download_incremental(
        self,
        bar_size: str = "1 min",
        days_back: int = 30,
    ) -> pd.DataFrame:
        """
        Download incremental data to update existing dataset.

        Useful for daily updates without re-downloading everything.

        Args:
            bar_size: Bar size ("1 min", "5 mins")
            days_back: Days of data to fetch

        Returns:
            DataFrame with new data
        """
        self.connect()

        contract = self.get_continuous_es_contract()

        df = self.download_contract_data(
            contract,
            duration=f"{days_back} D",
            bar_size=bar_size,
        )

        if not df.empty:
            bar_label = bar_size.replace(" ", "")
            filepath = self.data_dir / f"ES_incremental_{bar_label}.parquet"
            df.to_parquet(filepath)
            print(f"Saved incremental data: {filepath}")

        return df

    def merge_with_existing(
        self,
        new_data: pd.DataFrame,
        existing_file: str = "ES_combined_1min.parquet",
    ) -> pd.DataFrame:
        """
        Merge new data with existing dataset.

        Args:
            new_data: New DataFrame to merge
            existing_file: Existing data file name

        Returns:
            Merged DataFrame
        """
        filepath = self.data_dir / existing_file

        if filepath.exists():
            existing = pd.read_parquet(filepath)
            combined = pd.concat([existing, new_data])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
        else:
            combined = new_data

        combined.to_parquet(filepath)
        print(f"Merged data saved: {filepath}")
        print(f"Total bars: {len(combined)}")

        return combined
