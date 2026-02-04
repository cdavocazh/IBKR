"""
Yahoo Finance Data Extraction for ES Futures

Yahoo Finance provides ES data via the "ES=F" ticker (continuous front-month).
Available data:
- Daily: 10+ years
- Hourly: ~2 years (730 days)
- 1-minute: ~7 days

Note: Yahoo data is delayed and less reliable than IBKR,
but useful for longer historical backtests.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


class YahooESData:
    """Extract ES futures data from Yahoo Finance."""

    # Yahoo Finance ticker for ES continuous contract
    ES_TICKER = "ES=F"

    # Alternative tickers
    TICKERS = {
        "ES": "ES=F",      # E-mini S&P 500
        "NQ": "NQ=F",      # E-mini Nasdaq 100
        "YM": "YM=F",      # E-mini Dow
        "RTY": "RTY=F",    # E-mini Russell 2000
        "GC": "GC=F",      # Gold
        "SI": "SI=F",      # Silver
        "CL": "CL=F",      # Crude Oil
        "ZN": "ZN=F",      # 10-Year Treasury
        "ZB": "ZB=F",      # 30-Year Treasury
    }

    def __init__(self, data_dir: str = "data/yahoo"):
        """
        Initialize Yahoo data extractor.

        Args:
            data_dir: Directory to store downloaded data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_es_data(
        self,
        period: str = "5y",
        interval: str = "1d",
        save: bool = True,
    ) -> pd.DataFrame:
        """
        Download ES futures data from Yahoo Finance.

        Args:
            period: Data period. Valid values:
                    1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max
            interval: Data interval. Valid values:
                    1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

        Returns:
            DataFrame with OHLCV data
        """
        print(f"Downloading ES data from Yahoo Finance...")
        print(f"Period: {period}, Interval: {interval}")

        ticker = yf.Ticker(self.ES_TICKER)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            print("No data returned from Yahoo Finance")
            return pd.DataFrame()

        # Standardize column names
        df.columns = df.columns.str.lower()
        df = df.rename(columns={
            "stock splits": "splits",
        })

        # Keep only OHLCV columns
        cols_to_keep = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in cols_to_keep if c in df.columns]]

        # Remove timezone info for compatibility
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        print(f"Downloaded {len(df)} bars")
        print(f"Date range: {df.index.min()} to {df.index.max()}")

        if save:
            filename = f"ES_yahoo_{interval}_{period}.parquet"
            filepath = self.data_dir / filename
            df.to_parquet(filepath)
            print(f"Saved to {filepath}")

        return df

    def download_multi_timeframe(
        self,
        years: int = 5,
        save: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """
        Download multiple timeframes of ES data.

        Args:
            years: Years of daily data to download
            save: Whether to save to disk

        Returns:
            Dictionary of DataFrames by timeframe
        """
        data = {}

        # Daily data (max history)
        print("\n--- Downloading Daily Data ---")
        data["daily"] = self.download_es_data(
            period=f"{years}y",
            interval="1d",
            save=save,
        )

        # Hourly data (limited to ~2 years)
        print("\n--- Downloading Hourly Data ---")
        data["hourly"] = self.download_es_data(
            period="2y",
            interval="1h",
            save=save,
        )

        return data

    def load_data(
        self,
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load previously downloaded data.

        Args:
            interval: Data interval (1d, 1h, etc.)
            start: Start date filter
            end: End date filter

        Returns:
            DataFrame with data
        """
        # Find matching file
        pattern = f"ES_yahoo_{interval}_*.parquet"
        files = list(self.data_dir.glob(pattern))

        if not files:
            raise FileNotFoundError(
                f"No data file found matching {pattern}. "
                "Run download_es_data() first."
            )

        # Use most recent file
        filepath = sorted(files)[-1]
        df = pd.read_parquet(filepath)

        # Apply filters
        if start:
            df = df[df.index >= start]
        if end:
            df = df[df.index <= end]

        return df

    def get_data_info(self) -> dict:
        """Get information about downloaded data files."""
        info = {}
        for filepath in self.data_dir.glob("*.parquet"):
            df = pd.read_parquet(filepath)
            info[filepath.name] = {
                "rows": len(df),
                "start": df.index.min(),
                "end": df.index.max(),
                "size_mb": filepath.stat().st_size / (1024 * 1024),
            }
        return info
