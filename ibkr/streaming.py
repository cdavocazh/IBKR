"""
Real-Time Streaming Module for IBKR Futures

Provides continuous market data streaming and portfolio monitoring:
- StreamingQuote: Enhanced real-time quote with session tracking
- PortfolioPosition: Live position tracking with P&L
- PortfolioSummary: Aggregate portfolio statistics
- MarketStreamer: Main streaming engine

Usage:
    from ibkr import IBKRConnection, MarketStreamer

    conn = IBKRConnection()
    with conn.session() as ib:
        streamer = MarketStreamer(ib, symbols=["ES", "GC", "SI"])
        streamer.on_quote_update(my_callback)
        streamer.start()

        while streamer.is_running:
            streamer.tick()
            ib.sleep(0.1)

        streamer.stop()
"""

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from ib_insync import IB, Contract, Ticker

from .contracts import ContractFactory
from .market_data import MarketDataService

logger = logging.getLogger(__name__)


def _valid_float(value) -> Optional[float]:
    """Validate a ticker float field (handles None, NaN, and non-positive)."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or f <= 0:
            return None
        return f
    except (ValueError, TypeError):
        return None


def _valid_int(value) -> Optional[int]:
    """Validate a ticker integer field."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return int(f)
    except (ValueError, TypeError):
        return None


def _optional_float(value) -> Optional[float]:
    """Extract an optional float that may be NaN (allows zero/negative)."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


@dataclass
class StreamingQuote:
    """Enhanced real-time quote with session tracking.

    Updated continuously by the MarketStreamer as ticks arrive.
    """
    symbol: str

    # Core price fields
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None

    # Session tracking
    open: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    prev_close: Optional[float] = None

    # Derived fields (computed on each update)
    change: Optional[float] = None
    change_pct: Optional[float] = None
    vwap: Optional[float] = None

    # Volatility / open interest (from generic tick types 106, 411, 588)
    implied_volatility: Optional[float] = None
    hist_volatility: Optional[float] = None
    futures_open_interest: Optional[int] = None

    # Metadata
    tick_count: int = 0
    last_update: Optional[datetime] = None

    @property
    def mid(self) -> Optional[float]:
        """Mid price."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def session_range(self) -> Optional[float]:
        """Session high minus session low."""
        if self.session_high is not None and self.session_low is not None:
            return self.session_high - self.session_low
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for display/export."""
        return {
            "symbol": self.symbol,
            "last": self.last,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread": self.spread,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "session_high": self.session_high,
            "session_low": self.session_low,
            "session_range": self.session_range,
            "prev_close": self.prev_close,
            "volume": self.volume,
            "vwap": self.vwap,
            "implied_volatility": self.implied_volatility,
            "hist_volatility": self.hist_volatility,
            "futures_open_interest": self.futures_open_interest,
            "tick_count": self.tick_count,
            "last_update": self.last_update,
        }


@dataclass
class PortfolioPosition:
    """Live position tracking with P&L metrics."""
    symbol: str
    local_symbol: str = ""
    sec_type: str = "FUT"
    exchange: str = ""
    currency: str = "USD"

    # Position data
    position_size: float = 0
    avg_cost: float = 0
    multiplier: float = 1.0

    # Market data
    market_price: Optional[float] = None
    market_value: Optional[float] = None

    # P&L
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    # Metadata
    account: str = ""
    last_update: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "local_symbol": self.local_symbol,
            "sec_type": self.sec_type,
            "position_size": self.position_size,
            "avg_cost": self.avg_cost,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "pnl_pct": self.pnl_pct,
            "account": self.account,
            "last_update": self.last_update,
        }


@dataclass
class PortfolioSummary:
    """Aggregate portfolio statistics."""
    total_market_value: float = 0
    total_unrealized_pnl: float = 0
    total_realized_pnl: float = 0
    total_pnl_pct: Optional[float] = None
    position_count: int = 0
    net_liquidation: Optional[float] = None
    available_funds: Optional[float] = None
    last_update: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_market_value": self.total_market_value,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_realized_pnl": self.total_realized_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "position_count": self.position_count,
            "net_liquidation": self.net_liquidation,
            "available_funds": self.available_funds,
            "last_update": self.last_update,
        }


class MarketStreamer:
    """
    Main real-time streaming engine for futures market data and portfolio.

    Manages market data subscriptions and portfolio monitoring.
    Uses ContractFactory for symbol-to-contract resolution and
    ib.reqMktData() with generic tick types for IV/HV/OI.

    Usage:
        streamer = MarketStreamer(ib, symbols=["ES", "GC", "SI"])
        streamer.on_quote_update(my_callback)
        streamer.start()

        while streamer.is_running:
            streamer.tick()
            ib.sleep(0.1)

        streamer.stop()
    """

    # Generic tick types: 106=IV, 411=HV, 588=Futures Open Interest
    GENERIC_TICK_LIST = "106,411,588"

    def __init__(
        self,
        ib: IB,
        symbols: Optional[list] = None,
        include_portfolio: bool = True,
        portfolio_refresh_interval: float = 30,
    ):
        """
        Initialize the streaming engine.

        Args:
            ib: Connected IB instance.
            symbols: Futures symbols to stream (default: ["ES", "GC", "SI"]).
            include_portfolio: Whether to monitor portfolio positions.
            portfolio_refresh_interval: Seconds between portfolio refreshes.
        """
        self.ib = ib
        self.mds = MarketDataService(ib)
        self.include_portfolio = include_portfolio
        self.portfolio_refresh_interval = portfolio_refresh_interval

        # State
        self._running = False
        self._quotes: dict = {}          # symbol -> StreamingQuote
        self._contracts: dict = {}       # symbol -> qualified Contract
        self._tickers: dict = {}         # symbol -> Ticker
        self._positions: list = []
        self._portfolio_summary = PortfolioSummary()
        self._last_portfolio_refresh: Optional[datetime] = None

        # Callbacks
        self._quote_callbacks: list = []
        self._portfolio_callbacks: list = []

        # Initialize symbols
        if symbols is None:
            symbols = ["ES", "GC", "SI"]
        for symbol in symbols:
            self._init_symbol(symbol)

    def _init_symbol(self, symbol: str) -> None:
        """Initialize tracking for a symbol without starting the stream."""
        symbol = symbol.upper()
        if symbol not in self._quotes:
            self._quotes[symbol] = StreamingQuote(symbol=symbol)
            logger.info(f"Initialized tracking for {symbol}")

    def _resolve_contract(self, symbol: str) -> Contract:
        """Resolve a symbol string to a qualified IBKR Contract."""
        symbol = symbol.upper()
        if symbol in self._contracts:
            return self._contracts[symbol]

        contract = ContractFactory.create_future(symbol)
        qualified = self.mds.qualify_contract(contract)
        self._contracts[symbol] = qualified
        logger.info(f"Resolved {symbol} -> {qualified.localSymbol}")
        return qualified

    def _on_ticker_update(self, ticker: Ticker, contract: Contract) -> None:
        """Internal callback for ticker updates.

        Extracts validated fields from the Ticker, updates the StreamingQuote
        with session tracking and derived metrics, then fires user callbacks.
        """
        symbol = contract.symbol
        quote = self._quotes.get(symbol)
        if quote is None:
            return

        # Core price fields
        bid = _valid_float(ticker.bid)
        ask = _valid_float(ticker.ask)
        last = _valid_float(ticker.last)
        volume = _valid_int(ticker.volume)

        # Session fields from exchange
        open_price = _valid_float(ticker.open)
        high = _valid_float(ticker.high)
        low = _valid_float(ticker.low)
        close = _valid_float(ticker.close)  # previous session close in IBKR

        # Update core fields
        if bid is not None:
            quote.bid = bid
        if ask is not None:
            quote.ask = ask
        if last is not None:
            quote.last = last
        if volume is not None:
            quote.volume = volume

        # Session tracking
        if open_price is not None:
            quote.open = open_price
        if close is not None:
            quote.prev_close = close

        # Session high/low from exchange
        if high is not None:
            quote.session_high = high
        if low is not None:
            quote.session_low = low

        # Track our own session high/low from last price
        if last is not None:
            if quote.session_high is None or last > quote.session_high:
                quote.session_high = last
            if quote.session_low is None or last < quote.session_low:
                quote.session_low = last

        # Change from previous close
        if quote.last is not None and quote.prev_close is not None and quote.prev_close > 0:
            quote.change = quote.last - quote.prev_close
            quote.change_pct = (quote.change / quote.prev_close) * 100

        # VWAP
        vwap = _valid_float(getattr(ticker, "vwap", None))
        if vwap is not None:
            quote.vwap = vwap

        # Generic tick fields: IV, HV, OI
        iv = _optional_float(getattr(ticker, "impliedVolatility", None))
        if iv is not None:
            quote.implied_volatility = iv

        hv = _optional_float(getattr(ticker, "histVolatility", None))
        if hv is not None:
            quote.hist_volatility = hv

        oi = _valid_int(getattr(ticker, "futuresOpenInterest", None))
        if oi is not None:
            quote.futures_open_interest = oi

        # Metadata
        quote.tick_count += 1
        quote.last_update = datetime.now()

        # Fire user callbacks
        for cb in self._quote_callbacks:
            try:
                cb(quote)
            except Exception as e:
                logger.error(f"Error in quote callback: {e}")

    def _refresh_portfolio(self) -> None:
        """Refresh portfolio positions from IBKR.

        Uses ib.portfolio() for positions and ib.accountSummary() for
        account-level metrics. Called periodically based on the refresh interval.
        """
        now = datetime.now()
        if (self._last_portfolio_refresh is not None and
                (now - self._last_portfolio_refresh).total_seconds() < self.portfolio_refresh_interval):
            return

        try:
            portfolio_items = self.ib.portfolio()
        except Exception as e:
            logger.error(f"Error fetching portfolio: {e}")
            return

        positions = []
        total_value = 0.0
        total_unrealized = 0.0
        total_realized = 0.0
        total_cost_basis = 0.0

        for item in portfolio_items:
            contract = item.contract
            multiplier = float(contract.multiplier) if contract.multiplier else 1.0

            # P&L percentage
            pnl_pct = None
            cost_basis = item.averageCost * abs(item.position)
            if cost_basis != 0 and item.unrealizedPNL is not None:
                pnl_pct = (item.unrealizedPNL / cost_basis) * 100

            pos = PortfolioPosition(
                symbol=contract.symbol,
                local_symbol=contract.localSymbol or contract.symbol,
                sec_type=contract.secType,
                exchange=contract.exchange or contract.primaryExchange or "",
                currency=contract.currency,
                position_size=item.position,
                avg_cost=item.averageCost,
                multiplier=multiplier,
                market_price=item.marketPrice,
                market_value=item.marketValue,
                unrealized_pnl=item.unrealizedPNL,
                realized_pnl=item.realizedPNL,
                pnl_pct=pnl_pct,
                account=item.account,
                last_update=now,
            )
            positions.append(pos)

            if item.marketValue is not None:
                total_value += item.marketValue
            if item.unrealizedPNL is not None:
                total_unrealized += item.unrealizedPNL
            if item.realizedPNL is not None:
                total_realized += item.realizedPNL
            total_cost_basis += cost_basis

        self._positions = positions

        # Total P&L percentage
        total_pnl_pct = None
        if total_cost_basis > 0:
            total_pnl_pct = (total_unrealized / total_cost_basis) * 100

        # Account-level data (non-critical)
        net_liq = None
        avail_funds = None
        try:
            account_values = self.ib.accountSummary()
            for av in account_values:
                if av.tag == "NetLiquidation":
                    net_liq = float(av.value)
                elif av.tag == "AvailableFunds":
                    avail_funds = float(av.value)
        except Exception:
            pass

        self._portfolio_summary = PortfolioSummary(
            total_market_value=total_value,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            total_pnl_pct=total_pnl_pct,
            position_count=len(positions),
            net_liquidation=net_liq,
            available_funds=avail_funds,
            last_update=now,
        )

        self._last_portfolio_refresh = now

        # Fire portfolio callbacks
        for cb in self._portfolio_callbacks:
            try:
                cb(self._portfolio_summary, self._positions)
            except Exception as e:
                logger.error(f"Error in portfolio callback: {e}")

    # --- Stream management ---

    def _start_symbol_stream(self, symbol: str) -> None:
        """Start streaming for a single symbol."""
        if symbol in self._tickers:
            return

        try:
            contract = self._resolve_contract(symbol)

            # Use reqMktData directly to pass genericTickList for IV/HV/OI
            ticker = self.ib.reqMktData(
                contract,
                genericTickList=self.GENERIC_TICK_LIST,
            )

            def on_update(t, c=contract):
                self._on_ticker_update(t, c)

            ticker.updateEvent += on_update
            self._tickers[symbol] = ticker

            logger.info(f"Started streaming {symbol} ({contract.localSymbol})")
        except Exception as e:
            logger.error(f"Failed to start stream for {symbol}: {e}")

    def _stop_symbol_stream(self, symbol: str) -> None:
        """Stop streaming for a single symbol."""
        symbol = symbol.upper()
        if symbol in self._tickers and symbol in self._contracts:
            try:
                self.ib.cancelMktData(self._contracts[symbol])
            except Exception as e:
                logger.error(f"Error cancelling market data for {symbol}: {e}")
            self._tickers.pop(symbol, None)
            logger.info(f"Stopped streaming {symbol}")

    # --- Public API ---

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to stream. Can be called before or after start()."""
        symbol = symbol.upper()
        self._init_symbol(symbol)
        if self._running:
            self._start_symbol_stream(symbol)

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from streaming."""
        symbol = symbol.upper()
        self._stop_symbol_stream(symbol)
        self._quotes.pop(symbol, None)
        self._contracts.pop(symbol, None)

    def start(self) -> None:
        """Begin streaming all subscribed instruments and portfolio.

        After calling start(), the caller must run the ib_insync event loop:
            while streamer.is_running:
                streamer.tick()
                ib.sleep(0.1)
        """
        if self._running:
            logger.warning("Streamer is already running")
            return

        self._running = True

        for symbol in list(self._quotes.keys()):
            self._start_symbol_stream(symbol)

        if self.include_portfolio:
            self._refresh_portfolio()

        logger.info(f"Streaming started for {list(self._quotes.keys())}")

    def stop(self) -> None:
        """Clean shutdown of all streams."""
        if not self._running:
            return

        self._running = False

        for symbol in list(self._tickers.keys()):
            self._stop_symbol_stream(symbol)

        logger.info("Streaming stopped")

    def tick(self) -> None:
        """Called periodically from the main loop.

        Performs housekeeping such as refreshing portfolio data when
        the configured interval has elapsed.
        """
        if self.include_portfolio and self._running:
            self._refresh_portfolio()

    def on_quote_update(self, callback: Callable) -> None:
        """Register a callback for quote updates.

        Args:
            callback: Function called with (StreamingQuote) on each tick.
        """
        self._quote_callbacks.append(callback)

    def on_portfolio_update(self, callback: Callable) -> None:
        """Register a callback for portfolio updates.

        Args:
            callback: Function called with (PortfolioSummary, list[PortfolioPosition]).
        """
        self._portfolio_callbacks.append(callback)

    def get_quotes(self) -> dict:
        """Get current quotes for all tracked symbols."""
        return dict(self._quotes)

    def get_quote(self, symbol: str) -> Optional[StreamingQuote]:
        """Get current quote for a specific symbol."""
        return self._quotes.get(symbol.upper())

    def get_portfolio(self) -> tuple:
        """Get current portfolio state.

        Returns:
            Tuple of (PortfolioSummary, list of PortfolioPosition).
        """
        return self._portfolio_summary, list(self._positions)

    @property
    def is_running(self) -> bool:
        """Whether the streamer is actively streaming."""
        return self._running

    @property
    def symbols(self) -> list:
        """List of currently tracked symbols."""
        return list(self._quotes.keys())
