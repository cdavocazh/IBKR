"""Contract definitions for various IBKR instruments."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ib_insync import Contract, Future, Stock, Forex, Index


@dataclass
class ContractInfo:
    """Information about a contract."""
    symbol: str
    name: str
    exchange: str
    currency: str
    contract_type: str
    multiplier: Optional[float] = None


class ContractFactory:
    """Factory for creating IBKR contracts."""

    # Common futures contract specifications
    FUTURES_SPECS = {
        # Precious Metals (COMEX)
        "GC": ContractInfo("GC", "Gold Futures", "COMEX", "USD", "FUT", 100),
        "SI": ContractInfo("SI", "Silver Futures", "COMEX", "USD", "FUT", 5000),
        "HG": ContractInfo("HG", "Copper Futures", "COMEX", "USD", "FUT", 25000),
        "PL": ContractInfo("PL", "Platinum Futures", "NYMEX", "USD", "FUT", 50),
        "PA": ContractInfo("PA", "Palladium Futures", "NYMEX", "USD", "FUT", 100),

        # Micro Precious Metals
        "MGC": ContractInfo("MGC", "Micro Gold Futures", "COMEX", "USD", "FUT", 10),
        "SIL": ContractInfo("SIL", "Micro Silver Futures", "COMEX", "USD", "FUT", 1000),

        # Treasury Futures (CBOT)
        "ZN": ContractInfo("ZN", "10-Year T-Note Futures", "CBOT", "USD", "FUT", 1000),
        "ZB": ContractInfo("ZB", "30-Year T-Bond Futures", "CBOT", "USD", "FUT", 1000),
        "ZF": ContractInfo("ZF", "5-Year T-Note Futures", "CBOT", "USD", "FUT", 1000),
        "ZT": ContractInfo("ZT", "2-Year T-Note Futures", "CBOT", "USD", "FUT", 2000),
        "UB": ContractInfo("UB", "Ultra T-Bond Futures", "CBOT", "USD", "FUT", 1000),

        # Micro Treasury Futures
        "10Y": ContractInfo("10Y", "Micro 10-Year Yield Futures", "CBOT", "USD", "FUT", 1000),
        "2YY": ContractInfo("2YY", "Micro 2-Year Yield Futures", "CBOT", "USD", "FUT", 1000),

        # Energy Futures (NYMEX)
        "CL": ContractInfo("CL", "Crude Oil Futures", "NYMEX", "USD", "FUT", 1000),
        "NG": ContractInfo("NG", "Natural Gas Futures", "NYMEX", "USD", "FUT", 10000),
        "RB": ContractInfo("RB", "RBOB Gasoline Futures", "NYMEX", "USD", "FUT", 42000),

        # Micro Energy
        "MCL": ContractInfo("MCL", "Micro Crude Oil Futures", "NYMEX", "USD", "FUT", 100),

        # Index Futures (CME)
        "ES": ContractInfo("ES", "E-mini S&P 500 Futures", "CME", "USD", "FUT", 50),
        "NQ": ContractInfo("NQ", "E-mini Nasdaq 100 Futures", "CME", "USD", "FUT", 20),
        "YM": ContractInfo("YM", "E-mini Dow Futures", "CBOT", "USD", "FUT", 5),
        "RTY": ContractInfo("RTY", "E-mini Russell 2000 Futures", "CME", "USD", "FUT", 50),

        # Micro Index Futures
        "MES": ContractInfo("MES", "Micro E-mini S&P 500 Futures", "CME", "USD", "FUT", 5),
        "MNQ": ContractInfo("MNQ", "Micro E-mini Nasdaq 100 Futures", "CME", "USD", "FUT", 2),
        "MYM": ContractInfo("MYM", "Micro E-mini Dow Futures", "CBOT", "USD", "FUT", 0.5),
        "M2K": ContractInfo("M2K", "Micro E-mini Russell 2000 Futures", "CME", "USD", "FUT", 5),

        # Currency Futures (CME)
        "6E": ContractInfo("6E", "Euro FX Futures", "CME", "USD", "FUT", 125000),
        "6J": ContractInfo("6J", "Japanese Yen Futures", "CME", "USD", "FUT", 12500000),
        "6B": ContractInfo("6B", "British Pound Futures", "CME", "USD", "FUT", 62500),

        # Agricultural Futures (CBOT)
        "ZC": ContractInfo("ZC", "Corn Futures", "CBOT", "USD", "FUT", 5000),
        "ZS": ContractInfo("ZS", "Soybean Futures", "CBOT", "USD", "FUT", 5000),
        "ZW": ContractInfo("ZW", "Wheat Futures", "CBOT", "USD", "FUT", 5000),
    }

    @staticmethod
    def get_front_month(year: Optional[int] = None, month: Optional[int] = None) -> str:
        """
        Get the front month contract expiry in YYYYMM format.

        Futures typically roll to the next contract month before expiry.
        Common contract months: H(Mar), M(Jun), U(Sep), Z(Dec) for financials.
        """
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        # Standard quarterly months for most futures
        quarterly_months = [3, 6, 9, 12]

        # Find next quarterly month
        for qm in quarterly_months:
            if month <= qm:
                return f"{year}{qm:02d}"

        # Roll to next year's first quarter
        return f"{year + 1}03"

    @staticmethod
    def get_monthly_expiry(year: Optional[int] = None, month: Optional[int] = None) -> str:
        """Get monthly contract expiry for metals (which have monthly contracts)."""
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        # If we're past the 20th, use next month
        if now.day > 20:
            month += 1
            if month > 12:
                month = 1
                year += 1

        return f"{year}{month:02d}"

    @classmethod
    def create_future(
        cls,
        symbol: str,
        expiry: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: str = "USD",
    ) -> Future:
        """
        Create a futures contract.

        Args:
            symbol: Futures symbol (e.g., 'GC' for Gold, 'ZN' for 10-Year)
            expiry: Contract expiry in YYYYMM format. Auto-calculated if not provided.
            exchange: Exchange override. Uses default if not provided.
            currency: Currency (default USD).

        Returns:
            ib_insync Future contract object.
        """
        spec = cls.FUTURES_SPECS.get(symbol.upper())

        if spec:
            exchange = exchange or spec.exchange
        else:
            exchange = exchange or "SMART"

        # Determine expiry based on contract type
        if not expiry:
            if symbol.upper() in ["GC", "SI", "HG", "CL", "NG"]:
                # Metals and energy have monthly contracts
                expiry = cls.get_monthly_expiry()
            else:
                # Most other futures are quarterly
                expiry = cls.get_front_month()

        return Future(
            symbol=symbol.upper(),
            lastTradeDateOrContractMonth=expiry,
            exchange=exchange,
            currency=currency,
        )

    @classmethod
    def create_stock(
        cls,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Stock:
        """Create a stock contract."""
        return Stock(symbol=symbol.upper(), exchange=exchange, currency=currency)

    @classmethod
    def create_forex(cls, pair: str) -> Forex:
        """
        Create a forex contract.

        Args:
            pair: Currency pair (e.g., 'EURUSD', 'GBPUSD')
        """
        pair = pair.upper()
        return Forex(pair=pair)

    @classmethod
    def create_index(
        cls,
        symbol: str,
        exchange: str = "CBOE",
        currency: str = "USD",
    ) -> Index:
        """Create an index contract."""
        return Index(symbol=symbol.upper(), exchange=exchange, currency=currency)

    @classmethod
    def gold_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a Gold futures contract (GC)."""
        return cls.create_future("GC", expiry=expiry)

    @classmethod
    def silver_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a Silver futures contract (SI)."""
        return cls.create_future("SI", expiry=expiry)

    @classmethod
    def micro_gold_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a Micro Gold futures contract (MGC)."""
        return cls.create_future("MGC", expiry=expiry)

    @classmethod
    def micro_silver_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a Micro Silver futures contract (SIL)."""
        return cls.create_future("SIL", expiry=expiry)

    @classmethod
    def ten_year_note_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a 10-Year Treasury Note futures contract (ZN)."""
        return cls.create_future("ZN", expiry=expiry)

    @classmethod
    def thirty_year_bond_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a 30-Year Treasury Bond futures contract (ZB)."""
        return cls.create_future("ZB", expiry=expiry)

    @classmethod
    def five_year_note_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a 5-Year Treasury Note futures contract (ZF)."""
        return cls.create_future("ZF", expiry=expiry)

    @classmethod
    def two_year_note_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a 2-Year Treasury Note futures contract (ZT)."""
        return cls.create_future("ZT", expiry=expiry)

    @classmethod
    def sp500_future(cls, expiry: Optional[str] = None) -> Future:
        """Create an E-mini S&P 500 futures contract (ES)."""
        return cls.create_future("ES", expiry=expiry)

    @classmethod
    def nasdaq_future(cls, expiry: Optional[str] = None) -> Future:
        """Create an E-mini Nasdaq 100 futures contract (NQ)."""
        return cls.create_future("NQ", expiry=expiry)

    @classmethod
    def crude_oil_future(cls, expiry: Optional[str] = None) -> Future:
        """Create a Crude Oil futures contract (CL)."""
        return cls.create_future("CL", expiry=expiry)

    @classmethod
    def list_available_contracts(cls) -> dict:
        """List all pre-defined contract specifications."""
        return {k: v for k, v in cls.FUTURES_SPECS.items()}
