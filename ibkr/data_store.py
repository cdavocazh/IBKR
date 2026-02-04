"""
Data Storage and Management for Backtesting

Handles:
- Parquet storage for efficient data access
- Data validation and cleaning
- Resampling (1min -> 5min, 15min, 1hour, etc.)
- Gap detection and handling
"""

from datetime import datetime, time
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import numpy as np


class DataStore:
    """Manage historical market data for backtesting."""

    def __init__(self, data_dir: str = "data"):
        """
        Initialize data store.

        Args:
            data_dir: Root directory for all data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        format: str = "parquet",
    ) -> Path:
        """
        Save data to storage.

        Args:
            df: DataFrame with datetime index
            symbol: Instrument symbol
            timeframe: Timeframe string (e.g., "1min", "1hour", "daily")
            format: Storage format ("parquet" or "csv")

        Returns:
            Path to saved file
        """
        symbol_dir = self.data_dir / symbol.upper()
        symbol_dir.mkdir(exist_ok=True)

        filename = f"{symbol}_{timeframe}.{format}"
        filepath = symbol_dir / filename

        if format == "parquet":
            df.to_parquet(filepath)
        else:
            df.to_csv(filepath)

        return filepath

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[Union[str, datetime]] = None,
        end: Optional[Union[str, datetime]] = None,
        format: str = "parquet",
    ) -> pd.DataFrame:
        """
        Load data from storage.

        Args:
            symbol: Instrument symbol
            timeframe: Timeframe string
            start: Start date filter
            end: End date filter
            format: Storage format

        Returns:
            DataFrame with market data
        """
        filename = f"{symbol}_{timeframe}.{format}"
        filepath = self.data_dir / symbol.upper() / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found: {filepath}")

        if format == "parquet":
            df = pd.read_parquet(filepath)
        else:
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)

        # Apply date filters
        if start:
            start = pd.to_datetime(start)
            df = df[df.index >= start]

        if end:
            end = pd.to_datetime(end)
            df = df[df.index <= end]

        return df

    def list_available(self) -> dict:
        """List all available data files."""
        available = {}
        for symbol_dir in self.data_dir.iterdir():
            if symbol_dir.is_dir():
                symbol = symbol_dir.name
                available[symbol] = []
                for filepath in symbol_dir.glob("*"):
                    available[symbol].append(filepath.name)
        return available

    def resample(
        self,
        df: pd.DataFrame,
        target_timeframe: str,
    ) -> pd.DataFrame:
        """
        Resample OHLCV data to larger timeframe.

        Args:
            df: Source DataFrame with OHLCV columns
            target_timeframe: Target timeframe (e.g., "5min", "15min", "1H", "1D")

        Returns:
            Resampled DataFrame
        """
        # Map common names to pandas offset strings
        timeframe_map = {
            "1min": "1min",
            "5min": "5min",
            "15min": "15min",
            "30min": "30min",
            "1hour": "1H",
            "1h": "1H",
            "4hour": "4H",
            "4h": "4H",
            "daily": "1D",
            "1d": "1D",
            "weekly": "1W",
            "1w": "1W",
        }

        offset = timeframe_map.get(target_timeframe.lower(), target_timeframe)

        resampled = df.resample(offset).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        # Carry forward other columns if present
        if "average" in df.columns:
            resampled["average"] = df["average"].resample(offset).mean()

        if "bar_count" in df.columns:
            resampled["bar_count"] = df["bar_count"].resample(offset).sum()

        return resampled

    def clean_data(
        self,
        df: pd.DataFrame,
        remove_duplicates: bool = True,
        fill_gaps: bool = False,
        remove_outliers: bool = True,
        outlier_std: float = 5.0,
    ) -> pd.DataFrame:
        """
        Clean and validate market data.

        Args:
            df: Raw DataFrame
            remove_duplicates: Remove duplicate index entries
            fill_gaps: Forward-fill small gaps
            remove_outliers: Remove extreme price outliers
            outlier_std: Standard deviations for outlier detection

        Returns:
            Cleaned DataFrame
        """
        df = df.copy()

        # Remove duplicates
        if remove_duplicates:
            df = df[~df.index.duplicated(keep="first")]

        # Sort by index
        df.sort_index(inplace=True)

        # Remove rows with zero/negative prices
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if col in df.columns:
                df = df[df[col] > 0]

        # Validate OHLC relationship
        if all(col in df.columns for col in price_cols):
            # High should be >= Open, Close, Low
            # Low should be <= Open, Close, High
            valid_ohlc = (
                (df["high"] >= df["open"]) &
                (df["high"] >= df["close"]) &
                (df["high"] >= df["low"]) &
                (df["low"] <= df["open"]) &
                (df["low"] <= df["close"])
            )
            invalid_count = (~valid_ohlc).sum()
            if invalid_count > 0:
                print(f"Removing {invalid_count} rows with invalid OHLC")
                df = df[valid_ohlc]

        # Remove outliers based on returns
        if remove_outliers and "close" in df.columns:
            returns = df["close"].pct_change()
            mean_ret = returns.mean()
            std_ret = returns.std()

            outlier_mask = abs(returns - mean_ret) > (outlier_std * std_ret)
            outlier_count = outlier_mask.sum()
            if outlier_count > 0:
                print(f"Removing {outlier_count} outlier rows")
                df = df[~outlier_mask]

        # Fill small gaps (optional)
        if fill_gaps:
            df = df.ffill(limit=5)  # Forward fill up to 5 bars

        return df

    def detect_gaps(
        self,
        df: pd.DataFrame,
        expected_freq: str = "1min",
        trading_hours_only: bool = True,
    ) -> pd.DataFrame:
        """
        Detect gaps in time series data.

        Args:
            df: DataFrame with datetime index
            expected_freq: Expected data frequency
            trading_hours_only: Only flag gaps during trading hours

        Returns:
            DataFrame with gap information
        """
        freq_map = {
            "1min": pd.Timedelta(minutes=1),
            "5min": pd.Timedelta(minutes=5),
            "15min": pd.Timedelta(minutes=15),
            "1hour": pd.Timedelta(hours=1),
            "daily": pd.Timedelta(days=1),
        }

        expected_delta = freq_map.get(expected_freq, pd.Timedelta(expected_freq))

        # Calculate time differences
        time_diff = df.index.to_series().diff()

        # Find gaps (where diff > expected)
        gap_mask = time_diff > expected_delta * 1.5  # Allow some tolerance

        gaps = df[gap_mask].copy()
        gaps["gap_duration"] = time_diff[gap_mask]
        gaps["gap_start"] = gaps.index - gaps["gap_duration"]

        # Filter for trading hours if requested (ES trades nearly 24h)
        if trading_hours_only:
            # ES trades Sun 6pm - Fri 5pm ET with 1hr break
            # Simplified: flag gaps > 2 hours as significant
            gaps = gaps[gaps["gap_duration"] > pd.Timedelta(hours=2)]

        return gaps[["gap_start", "gap_duration"]]

    def get_stats(self, df: pd.DataFrame) -> dict:
        """
        Calculate data statistics.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary of statistics
        """
        stats = {
            "rows": len(df),
            "start_date": df.index.min(),
            "end_date": df.index.max(),
            "trading_days": df.index.normalize().nunique(),
        }

        if "close" in df.columns:
            stats.update({
                "min_price": df["close"].min(),
                "max_price": df["close"].max(),
                "mean_price": df["close"].mean(),
                "total_return": (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100,
            })

        if "volume" in df.columns:
            stats.update({
                "total_volume": df["volume"].sum(),
                "avg_volume": df["volume"].mean(),
            })

        return stats
