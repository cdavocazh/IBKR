"""Market data service for fetching prices from IBKR."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union

import pandas as pd
from ib_insync import IB, Contract, Ticker, BarDataList


@dataclass
class Quote:
    """Market quote data."""
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def mid(self) -> Optional[float]:
        """Calculate mid price."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        """Calculate bid-ask spread."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": self.mid,
            "spread": self.spread,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "timestamp": self.timestamp,
        }


class MarketDataService:
    """Service for fetching market data from IBKR."""

    def __init__(self, ib: IB):
        """
        Initialize market data service.

        Args:
            ib: Connected IB instance from ib_insync.
        """
        self.ib = ib

    def qualify_contract(self, contract: Contract) -> Contract:
        """
        Qualify a contract to get full contract details.

        This resolves ambiguous contract definitions.
        """
        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            return qualified[0]
        raise ValueError(f"Could not qualify contract: {contract}")

    def get_quote(self, contract: Contract, qualify: bool = True) -> Quote:
        """
        Get current market quote for a contract.

        Args:
            contract: The contract to get quote for.
            qualify: Whether to qualify the contract first.

        Returns:
            Quote object with current market data.
        """
        if qualify:
            contract = self.qualify_contract(contract)

        # Request market data
        ticker: Ticker = self.ib.reqMktData(contract, snapshot=True)

        # Wait for data (with timeout)
        self.ib.sleep(2)

        quote = Quote(
            symbol=contract.symbol,
            bid=ticker.bid if ticker.bid > 0 else None,
            ask=ticker.ask if ticker.ask > 0 else None,
            last=ticker.last if ticker.last > 0 else None,
            high=ticker.high if ticker.high > 0 else None,
            low=ticker.low if ticker.low > 0 else None,
            close=ticker.close if ticker.close > 0 else None,
            volume=int(ticker.volume) if ticker.volume > 0 else None,
            timestamp=datetime.now(),
        )

        # Cancel market data subscription
        self.ib.cancelMktData(contract)

        return quote

    def get_quotes(self, contracts: list[Contract], qualify: bool = True) -> list[Quote]:
        """
        Get market quotes for multiple contracts.

        Args:
            contracts: List of contracts to get quotes for.
            qualify: Whether to qualify contracts first.

        Returns:
            List of Quote objects.
        """
        if qualify:
            contracts = [self.qualify_contract(c) for c in contracts]

        # Request market data for all contracts
        tickers = []
        for contract in contracts:
            ticker = self.ib.reqMktData(contract, snapshot=True)
            tickers.append((contract, ticker))

        # Wait for data
        self.ib.sleep(2)

        quotes = []
        for contract, ticker in tickers:
            quote = Quote(
                symbol=contract.symbol,
                bid=ticker.bid if ticker.bid > 0 else None,
                ask=ticker.ask if ticker.ask > 0 else None,
                last=ticker.last if ticker.last > 0 else None,
                high=ticker.high if ticker.high > 0 else None,
                low=ticker.low if ticker.low > 0 else None,
                close=ticker.close if ticker.close > 0 else None,
                volume=int(ticker.volume) if ticker.volume > 0 else None,
                timestamp=datetime.now(),
            )
            quotes.append(quote)
            self.ib.cancelMktData(contract)

        return quotes

    def get_historical_bars(
        self,
        contract: Contract,
        duration: str = "1 D",
        bar_size: str = "1 hour",
        what_to_show: str = "TRADES",
        use_rth: bool = False,
        qualify: bool = True,
    ) -> pd.DataFrame:
        """
        Get historical bar data for a contract.

        Args:
            contract: The contract to get data for.
            duration: Time span (e.g., '1 D', '1 W', '1 M', '1 Y').
            bar_size: Bar size (e.g., '1 min', '5 mins', '1 hour', '1 day').
            what_to_show: Data type ('TRADES', 'MIDPOINT', 'BID', 'ASK').
            use_rth: Use regular trading hours only.
            qualify: Whether to qualify the contract first.

        Returns:
            DataFrame with OHLCV data.
        """
        if qualify:
            contract = self.qualify_contract(contract)

        bars: BarDataList = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
        )

        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "average": bar.average,
            "barCount": bar.barCount,
        } for bar in bars])

        df.set_index("date", inplace=True)
        return df

    def stream_quotes(
        self,
        contract: Contract,
        callback: callable,
        qualify: bool = True,
    ) -> Ticker:
        """
        Stream live quotes for a contract.

        Args:
            contract: The contract to stream.
            callback: Function called on each update. Receives (ticker, contract).
            qualify: Whether to qualify the contract first.

        Returns:
            Ticker object (can be used to cancel with cancelMktData).
        """
        if qualify:
            contract = self.qualify_contract(contract)

        ticker = self.ib.reqMktData(contract)

        def on_update(t):
            callback(t, contract)

        ticker.updateEvent += on_update
        return ticker

    def get_contract_details(self, contract: Contract) -> dict:
        """
        Get detailed contract information.

        Args:
            contract: The contract to get details for.

        Returns:
            Dictionary with contract details.
        """
        details = self.ib.reqContractDetails(contract)
        if not details:
            return {}

        d = details[0]
        return {
            "symbol": d.contract.symbol,
            "localSymbol": d.contract.localSymbol,
            "exchange": d.contract.exchange,
            "currency": d.contract.currency,
            "multiplier": d.contract.multiplier,
            "longName": d.longName,
            "category": d.category,
            "subcategory": d.subcategory,
            "minTick": d.minTick,
            "priceMagnifier": d.priceMagnifier,
            "tradingHours": d.tradingHours,
            "liquidHours": d.liquidHours,
        }

    def quotes_to_dataframe(self, quotes: list[Quote]) -> pd.DataFrame:
        """Convert list of quotes to a DataFrame."""
        return pd.DataFrame([q.to_dict() for q in quotes])
