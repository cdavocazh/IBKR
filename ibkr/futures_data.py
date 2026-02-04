"""
Futures Data Extraction Module

Supports multiple futures contracts:
- ES (E-mini S&P 500) - CME
- GC (Gold) - COMEX
- SI (Silver) - COMEX

IBKR Historical Data Limits:
- 1 min bars: Max 1-2 years
- 5 min bars: Max 2+ years
- Request pacing: 60 requests per 10 minutes
"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from ib_insync import IB, Future

from .connection import IBKRConnection


# Futures contract specifications
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
        # Gold has more contract months: G, J, M, Q, V, Z (Feb, Apr, Jun, Aug, Oct, Dec)
        # But most liquid are the even months
        "contract_months": ["G", "J", "M", "Q", "V", "Z"],
        "month_map": {"G": 2, "J": 4, "M": 6, "Q": 8, "V": 10, "Z": 12},
    },
    "SI": {
        "symbol": "SI",
        "exchange": "COMEX",
        "currency": "USD",
        "name": "Silver",
        # Silver: H, K, N, U, Z (Mar, May, Jul, Sep, Dec)
        "contract_months": ["H", "K", "N", "U", "Z"],
        "month_map": {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12},
        "trading_class": "SI",  # Standard 5000 oz contract (not SIL mini)
    },
}


class FuturesDataExtractor:
    """Extract historical futures data from IBKR for multiple symbols."""

    REQUEST_DELAY_SECONDS = 11  # Stay under rate limit

    def __init__(
        self,
        symbol: str = "ES",
        ib: Optional[IB] = None,
        data_dir: str = "data",
        client_id: Optional[int] = None,
    ):
        """
        Initialize futures data extractor.

        Args:
            symbol: Futures symbol (ES, GC, SI)
            ib: Connected IB instance. If None, will create connection.
            data_dir: Base directory to store downloaded data.
            client_id: IBKR client ID (use different IDs for concurrent connections)
        """
        if symbol not in FUTURES_SPECS:
            raise ValueError(f"Unknown symbol: {symbol}. Supported: {list(FUTURES_SPECS.keys())}")

        self.symbol = symbol
        self.spec = FUTURES_SPECS[symbol]
        self.ib = ib
        self.owns_connection = ib is None
        self.client_id = client_id
        self.data_dir = Path(data_dir) / symbol.lower()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> IB:
        """Connect to IBKR if not already connected."""
        if self.ib is None or not self.ib.isConnected():
            conn = IBKRConnection(client_id=self.client_id)
            self.ib = conn.connect()
            self.owns_connection = True
        return self.ib

    def disconnect(self):
        """Disconnect if we own the connection."""
        if self.owns_connection and self.ib and self.ib.isConnected():
            self.ib.disconnect()

    def get_front_month_contract(self) -> Future:
        """Get the front month contract for this futures symbol."""
        now = datetime.now()
        year = now.year
        month = now.month

        # Find next expiry month
        month_map = self.spec["month_map"]
        expiry_months = sorted(month_map.values())

        for exp_month in expiry_months:
            if month <= exp_month:
                front_month = exp_month
                front_year = year
                break
        else:
            front_month = expiry_months[0]  # First month of next year
            front_year = year + 1

        # Build contract with optional trading class for disambiguation
        contract_params = {
            "symbol": self.spec["symbol"],
            "lastTradeDateOrContractMonth": f"{front_year}{front_month:02d}",
            "exchange": self.spec["exchange"],
            "currency": self.spec["currency"],
        }

        # Add trading class if specified (needed for SI to distinguish from SIL mini)
        if "trading_class" in self.spec:
            contract_params["tradingClass"] = self.spec["trading_class"]

        return Future(**contract_params)

    def download_data(
        self,
        bar_size: str = "5 mins",
        days_back: int = 365,
    ) -> pd.DataFrame:
        """
        Download historical data for this futures contract.

        Args:
            bar_size: Bar size ("1 min", "5 mins", "1 hour", "1 day")
            days_back: Days of data to fetch

        Returns:
            DataFrame with OHLCV data
        """
        self.connect()

        contract = self.get_front_month_contract()

        # Qualify the contract
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            print(f"Could not qualify {self.symbol} contract")
            return pd.DataFrame()

        contract = qualified[0]
        print(f"Downloading {bar_size} data for {contract.localSymbol}...")

        all_data = []

        # Determine chunk size based on bar size
        if "min" in bar_size:
            chunk_days = 7 if bar_size == "1 min" else 30
        else:
            chunk_days = 365  # For hourly/daily

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
                    print(f"    Got {len(df)} bars")

            except Exception as e:
                print(f"    Error: {e}")

            time.sleep(self.REQUEST_DELAY_SECONDS)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined.sort_index(inplace=True)

        # Save data
        bar_label = bar_size.replace(" ", "")
        filename = f"{self.symbol}_combined_{bar_label}.parquet"
        filepath = self.data_dir / filename
        combined.to_parquet(filepath)

        print(f"\nSaved: {filepath}")
        print(f"Total bars: {len(combined)}")
        print(f"Date range: {combined.index.min()} to {combined.index.max()}")

        return combined

    def download_1min_data(self, days_back: int = 365) -> pd.DataFrame:
        """Download 1-minute data."""
        return self.download_data(bar_size="1 min", days_back=days_back)

    def download_5min_data(self, days_back: int = 365) -> pd.DataFrame:
        """Download 5-minute data."""
        return self.download_data(bar_size="5 mins", days_back=days_back)

    def download_hourly_data(self, days_back: int = 730) -> pd.DataFrame:
        """Download hourly data."""
        return self.download_data(bar_size="1 hour", days_back=days_back)

    def download_daily_data(self, days_back: int = 3650) -> pd.DataFrame:
        """Download daily data."""
        return self.download_data(bar_size="1 day", days_back=days_back)

    def load_data(self, bar_size: str = "5mins") -> pd.DataFrame:
        """Load previously downloaded data."""
        filename = f"{self.symbol}_combined_{bar_size}.parquet"
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


def download_all_futures(
    symbols: list[str] = ["ES", "GC", "SI"],
    bar_size: str = "5 mins",
    days_back: int = 365,
) -> dict[str, pd.DataFrame]:
    """
    Download data for multiple futures symbols.

    Args:
        symbols: List of symbols to download
        bar_size: Bar size
        days_back: Days of history

    Returns:
        Dict mapping symbol to DataFrame
    """
    results = {}

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"Downloading {symbol} ({FUTURES_SPECS[symbol]['name']})")
        print(f"{'='*60}")

        extractor = FuturesDataExtractor(symbol=symbol)
        try:
            df = extractor.download_data(bar_size=bar_size, days_back=days_back)
            results[symbol] = df
        except Exception as e:
            print(f"Error downloading {symbol}: {e}")
            results[symbol] = pd.DataFrame()
        finally:
            extractor.disconnect()

    return results
